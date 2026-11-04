import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from finboard.db.models import Category
from finboard.db.uow import UnitOfWork
from finboard.domain.enums import CategoryType
from finboard.domain.errors import Conflict, NotFound, ValidationFailed

_UPDATABLE = frozenset({"name", "type", "parent_id", "colour", "sort_order", "archived"})


class CategoryService:
    """Categories form at most two levels: top-level categories and their children."""

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list(self) -> Sequence[Category]:
        return await self.uow.categories.list()

    async def get(self, category_id: uuid.UUID) -> Category:
        category = await self.uow.categories.get(category_id)
        if category is None:
            raise NotFound("Category not found")
        return category

    async def create(
        self,
        *,
        name: str,
        type: CategoryType,
        parent_id: uuid.UUID | None = None,
        colour: str | None = None,
    ) -> Category:
        if parent_id is not None:
            await self._check_parent(parent_id, child=None)
        await self._ensure_name_free(name, parent_id)
        category = await self.uow.categories.add(
            Category(name=name, type=type, parent_id=parent_id, colour=colour)
        )
        await self.uow.commit()
        return category

    async def update(self, category_id: uuid.UUID, changes: Mapping[str, Any]) -> Category:
        category = await self.get(category_id)
        unknown = set(changes) - _UPDATABLE
        if unknown:
            raise ValueError(f"not updatable: {sorted(unknown)}")

        if category.is_system and "type" in changes and changes["type"] != category.type:
            raise Conflict("The type of a system category can't be changed")
        new_parent = changes.get("parent_id", category.parent_id)
        if new_parent is not None and new_parent != category.parent_id:
            await self._check_parent(new_parent, child=category)
        name = changes.get("name", category.name)
        parent_id = changes.get("parent_id", category.parent_id)
        if name.lower() != category.name.lower() or parent_id != category.parent_id:
            await self._ensure_name_free(name, parent_id, exclude_id=category.id)

        type_changed = "type" in changes and changes["type"] != category.type
        for field, value in changes.items():
            setattr(category, field, value)
        if type_changed:
            # txn.type is denormalised from the category: keep the two in step (§9).
            await self.uow.txns.set_type_for_category(category.id, category.type)
        await self.uow.users.bump_data_version(self.uow.user_id)  # names show on the dashboard
        await self.uow.session.flush()
        await self.uow.commit()
        return category

    async def delete(self, category_id: uuid.UUID) -> None:
        category = await self.get(category_id)
        if category.is_system:
            raise Conflict("System categories can't be deleted")
        if await self.uow.categories.has_children(category.id):
            raise Conflict("Delete or move this category's sub-categories first")
        if await self.uow.categories.in_use(category.id):
            # Merging into another category arrives in M5.
            raise Conflict("Transactions use this category, so it can't be deleted; archive it")
        if await self.uow.categories.used_by_rules(category.id):
            raise Conflict("Rules use this category; change or delete those rules first")
        await self.uow.categories.delete(category)
        await self.uow.commit()

    async def merge(
        self, source_id: uuid.UUID, into_id: uuid.UUID
    ) -> tuple[Category, dict[str, int]]:
        """Move the source's transactions, rules and budgets to `into`, then delete the source
        (ARCHITECTURE §10). Merging into a category of another type changes those transactions'
        type too."""
        if source_id == into_id:
            raise ValidationFailed("Choose a different category to merge into")
        source = await self.get(source_id)
        target = await self.uow.categories.get(into_id)
        if target is None:
            raise ValidationFailed("The category to merge into doesn't exist")
        if source.is_system:
            raise Conflict("System categories can't be merged away; merge others into them")
        if await self.uow.categories.has_children(source.id):
            raise Conflict("Move or merge this category's sub-categories first")
        moved = await self.uow.categories.merge_into(source.id, target)
        await self.uow.categories.delete(source)
        await self.uow.users.bump_data_version(self.uow.user_id)
        await self.uow.commit()
        return target, moved

    async def _check_parent(self, parent_id: uuid.UUID, *, child: Category | None) -> None:
        parent = await self.uow.categories.get(parent_id)
        if parent is None:
            raise ValidationFailed("Parent category not found")
        if parent.parent_id is not None:
            raise ValidationFailed("Sub-categories can't have sub-categories of their own")
        if child is not None:
            if child.id == parent.id:
                raise ValidationFailed("A category can't be its own parent")
            if await self.uow.categories.has_children(child.id):
                raise ValidationFailed("A category with sub-categories can't become one")

    async def _ensure_name_free(
        self, name: str, parent_id: uuid.UUID | None, *, exclude_id: uuid.UUID | None = None
    ) -> None:
        if await self.uow.categories.name_taken(name, parent_id, exclude_id=exclude_id):
            raise Conflict(f"A category called '{name}' already exists here")
