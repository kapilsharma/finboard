from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.db.models import AppUser, Category, Rule
from finboard.db.uow import UnitOfWork, unit_of_work
from finboard.seed.categories import DEFAULT_CATEGORIES
from finboard.seed.rules import STARTER_RULES

LOCAL_USERNAME = "local"


def principal_for(user: AppUser) -> Principal:
    return Principal(user_id=user.id, username=user.username, display_name=user.display_name)


async def provision_user(uow: UnitOfWork, *, username: str, display_name: str) -> AppUser:
    """Create a user with the default categories and the starter rule pack. The caller
    commits."""
    user = await uow.users.add(AppUser(username=username, display_name=display_name))
    await uow.bind_user(user.id)
    await seed_defaults(uow)
    return user


async def seed_defaults(uow: UnitOfWork) -> None:
    """The default categories and the starter rule pack for the unit of work's user (a new
    user, or one whose data was just deleted). The caller commits."""
    categories = [
        Category(
            name=seed.name,
            type=seed.type,
            colour=seed.colour,
            is_system=seed.system_key is not None,
            system_key=seed.system_key,
            sort_order=index,
        )
        for index, seed in enumerate(DEFAULT_CATEGORIES)
    ]
    await uow.categories.add_all(categories)
    by_name = {c.name: c for c in categories}
    await uow.rules.add_all(
        [
            Rule(
                priority=index,
                match_kind=seed.match_kind,
                pattern=seed.pattern,
                category_id=by_name[seed.category].id,
                direction=seed.direction,
            )
            for index, seed in enumerate(STARTER_RULES)
        ]
    )


async def ensure_local_user(sessionmaker: async_sessionmaker[AsyncSession]) -> Principal:
    """Return the single local user (FINBOARD_MODE=local), creating it on first start."""
    async with unit_of_work(sessionmaker) as uow:
        user = await uow.users.get_by_username(LOCAL_USERNAME)
        if user is not None:
            return principal_for(user)
        try:
            user = await provision_user(uow, username=LOCAL_USERNAME, display_name="Me")
            await uow.commit()
            return principal_for(user)
        except IntegrityError:
            await uow.rollback()  # another instance created it at the same moment

    async with unit_of_work(sessionmaker) as uow:
        user = await uow.users.get_by_username(LOCAL_USERNAME)
        assert user is not None
        return principal_for(user)
