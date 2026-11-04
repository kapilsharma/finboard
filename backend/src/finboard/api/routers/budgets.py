import uuid
from datetime import date

from fastapi import APIRouter

from finboard.api.deps import BudgetServiceDep
from finboard.api.routers.dashboard import Month
from finboard.api.schemas import BudgetList, BudgetOut, BudgetPut
from finboard.services.dashboard import parse_month

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("")
async def list_budgets(service: BudgetServiceDep, month: Month = None) -> BudgetList:
    """The limit in force for each category in the month (default: this month)."""
    selected = parse_month(month) if month else date.today().replace(day=1)
    rows = await service.for_month(selected)
    return BudgetList(month=f"{selected:%Y-%m}", items=[BudgetOut.model_validate(b) for b in rows])


@router.put("/{category_id}")
async def put_budget(
    category_id: uuid.UUID, body: BudgetPut, service: BudgetServiceDep
) -> BudgetOut:
    """Set (or with null, remove) a category's limit from a month on."""
    budget = await service.put(
        category_id,
        effective_from=parse_month(body.effective_from),
        monthly_limit=body.monthly_limit,
    )
    return BudgetOut.model_validate(budget)
