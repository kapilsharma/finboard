"""Create N users for the server-mode load test (ROADMAP M8), each with the synthetic demo data.

    cd backend && uv run python tests/load/seed_users.py 300

Users are `load-0001` … `load-NNNN`, all with the password in LOAD_PASSWORD (default below).
It refuses any database whose name doesn't end in `_test`: point FINBOARD_DATABASE_URL at the
same test database the stack under load uses (e2e/stack.py does this itself).
"""

import asyncio
import os
import sys

from sqlalchemy.exc import IntegrityError

from finboard.auth import passwords
from finboard.core.config import get_settings
from finboard.db.engine import create_engine, create_sessionmaker
from finboard.db.uow import unit_of_work
from finboard.services.demo import load_demo
from finboard.services.users import provision_user

PASSWORD = os.environ.get("LOAD_PASSWORD", "load test passphrase")


async def main(count: int) -> None:
    settings = get_settings()
    if not settings.database_url.rsplit("/", 1)[-1].endswith("_test"):
        sys.exit("Refusing: FINBOARD_DATABASE_URL must name a database ending in '_test'.")
    password_hash = passwords.hash_password(PASSWORD)  # one hash for all: seeding stays fast
    engine = create_engine(settings)
    sessionmaker = create_sessionmaker(engine)
    created = 0
    try:
        for n in range(1, count + 1):
            async with unit_of_work(sessionmaker) as uow:
                try:
                    user = await provision_user(
                        uow, username=f"load-{n:04d}", display_name=f"Load {n}"
                    )
                except IntegrityError:
                    await uow.rollback()
                    continue  # seeded by an earlier run
                user.password_hash = password_hash
                await load_demo(uow)  # commits
                created += 1
    finally:
        await engine.dispose()
    print(f"{created} users created ({count - created} already there).")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300))
