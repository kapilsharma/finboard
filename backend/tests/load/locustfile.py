"""Load test (ARCHITECTURE §14): a dashboard / transactions / categorise mix. Run by hand, not
in CI. Budget: p95 < 300 ms on the reference machine.

Local mode (ROADMAP M4, 200 virtual users; every one is the single local user):

    cd e2e && E2E_PORT=8799 python3 stack.py            # app + worker on finboard_test, demo data
    cd backend && uv run --group load locust -f tests/load/locustfile.py \\
        --host http://127.0.0.1:8799 --users 200 --spawn-rate 20 --run-time 2m --headless

Server mode (ROADMAP M8, 300 signed-in users, each with their own data and session):

    cd e2e && E2E_PORT=8797 E2E_API_WORKERS=3 FINBOARD_MODE=server \\
        FINBOARD_PUBLIC_URL=http://127.0.0.1:8797 python3 stack.py
    cd backend && uv run python tests/load/seed_users.py 300
    cd backend && LOAD_SERVER_USERS=300 uv run --group load locust -f tests/load/locustfile.py \\
        --host http://127.0.0.1:8797 --users 300 --spawn-rate 10 --run-time 2m --headless

Writes only recategorise demo rows by hand.
"""

import itertools
import os
import random

from locust import HttpUser, between, task

API = "/api/v1"
MONTHS = ["2026-07", "2026-08", "2026-09"]
# Server mode: how many seeded `load-NNNN` users to sign in as (0 = local mode, no sign-in).
SERVER_USERS = int(os.environ.get("LOAD_SERVER_USERS", "0"))
PASSWORD = os.environ.get("LOAD_PASSWORD", "load test passphrase")
_numbers = itertools.count(1)


class FinboardUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.write = {"X-Finboard-Client": "1"}
        if SERVER_USERS:
            number = (next(_numbers) - 1) % SERVER_USERS + 1
            response = self.client.post(
                f"{API}/auth/login",
                json={"username": f"load-{number:04d}", "password": PASSWORD},
                headers=self.write,
                name="/auth/login",
            )
            response.raise_for_status()  # the session cookie stays in this user's client
            self.write["X-CSRF-Token"] = response.json()["csrf_token"]
        self.categories = [
            c["id"]
            for c in self.client.get(f"{API}/categories").json()["items"]
            if c["type"] == "expense"
        ]
        self.etags: dict[str, str] = {}

    @task(5)
    def dashboard(self) -> None:
        month = random.choice(MONTHS)  # noqa: S311
        headers = {"If-None-Match": self.etags[month]} if month in self.etags else {}
        with self.client.get(
            f"{API}/dashboard?month={month}",
            headers=headers,
            name="/dashboard",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 304):
                self.etags[month] = response.headers.get("etag", "")
                response.success()

    @task(3)
    def transactions(self) -> None:
        month = random.choice(MONTHS)  # noqa: S311
        sort = random.choice(["date", "amount", "category"])  # noqa: S311
        self.client.get(
            f"{API}/transactions?month={month}&sort={sort}&limit=100", name="/transactions"
        )

    @task(1)
    def search(self) -> None:
        self.client.get(f"{API}/transactions?q=swiggy&limit=50", name="/transactions?q")

    @task(1)
    def categorise(self) -> None:
        page = self.client.get(f"{API}/transactions?limit=50", name="/transactions").json()
        rows = [t for t in page["items"] if t["type"] == "expense"]
        if rows and self.categories:
            row = random.choice(rows)  # noqa: S311
            self.client.patch(
                f"{API}/transactions/{row['id']}",
                json={"category_id": random.choice(self.categories)},  # noqa: S311
                headers=self.write,
                name="/transactions/{id}",
            )
