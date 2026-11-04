"""Load test (ARCHITECTURE §14, ROADMAP M4): a dashboard / transactions / categorise mix.
Budget: 200 virtual users, p95 < 300 ms on the reference machine. Run by hand, not in CI:

    cd e2e && E2E_PORT=8799 python3 stack.py            # app + worker on finboard_test, demo data
    cd backend && uv run --group load locust -f tests/load/locustfile.py \\
        --host http://127.0.0.1:8799 --users 200 --spawn-rate 20 --run-time 2m --headless

Local mode has one user, so every virtual user is the local user: this measures the API and
the database under concurrency, not tenancy. Writes only recategorise demo rows by hand.
"""

import random

from locust import HttpUser, between, task

API = "/api/v1"
WRITE = {"X-Finboard-Client": "1"}
MONTHS = ["2026-07", "2026-08", "2026-09"]


class FinboardUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
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
                headers=WRITE,
                name="/transactions/{id}",
            )
