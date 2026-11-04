import uuid

from fastapi import APIRouter, status

from finboard.api.deps import CategoryServiceDep
from finboard.api.schemas import (
    CategoryCreate,
    CategoryList,
    CategoryMergeIn,
    CategoryMergeOut,
    CategoryOut,
    CategoryUpdate,
)

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("")
async def list_categories(service: CategoryServiceDep) -> CategoryList:
    return CategoryList(items=[CategoryOut.model_validate(c) for c in await service.list()])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_category(body: CategoryCreate, service: CategoryServiceDep) -> CategoryOut:
    return CategoryOut.model_validate(await service.create(**body.model_dump()))


@router.patch("/{category_id}")
async def update_category(
    category_id: uuid.UUID, body: CategoryUpdate, service: CategoryServiceDep
) -> CategoryOut:
    return CategoryOut.model_validate(await service.update(category_id, body.changes()))


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: uuid.UUID, service: CategoryServiceDep) -> None:
    await service.delete(category_id)


@router.post("/{category_id}/merge")
async def merge_category(
    category_id: uuid.UUID, body: CategoryMergeIn, service: CategoryServiceDep
) -> CategoryMergeOut:
    """Move this category's transactions, rules and budgets into another, then delete it."""
    target, moved = await service.merge(category_id, body.into_id)
    return CategoryMergeOut(into=CategoryOut.model_validate(target), **moved)
