import hashlib
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status

from finboard.api.deps import DashboardServiceDep, PrincipalDep
from finboard.api.schemas import (
    AccountRef,
    AccountTotalsOut,
    BiggestSpend,
    CashflowMonthOut,
    CategoriesOut,
    CategoryLimitOut,
    CategoryRef,
    DashboardMonths,
    DashboardOut,
    Headline,
    IncomeSourceOut,
    InvestedHeadline,
    LimitsSummaryOut,
    MoneyWithChange,
    NetSavingHeadline,
    RateHeadline,
)
from finboard.db.models import Account, Category
from finboard.services.dashboard import DashboardView, parse_month

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

Month = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2026-09"])]


def _month(value: object) -> str:
    return f"{value:%Y-%m}"


def _pct(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _category(c: Category) -> CategoryRef:
    return CategoryRef(id=c.id, name=c.name, type=c.type, colour=c.colour)


def _account(a: Account) -> AccountRef:
    return AccountRef(id=a.id, name=a.name, type=a.type, masked_number=a.masked_number)


def to_out(view: DashboardView) -> DashboardOut:
    h = view.headline
    return DashboardOut(
        month=_month(view.month),
        prev_month=_month(view.prev_month) if view.prev_month else None,
        headline=Headline(
            income=MoneyWithChange(
                value=h.income, prev=h.prev_income, delta_pct=_pct(h.income_delta_pct)
            ),
            spending=MoneyWithChange(
                value=h.spending, prev=h.prev_spending, delta_pct=_pct(h.spending_delta_pct)
            ),
            net_saving=NetSavingHeadline(
                value=h.net_saving, prev=h.prev_net_saving, delta=h.net_saving_delta
            ),
            savings_rate=RateHeadline(
                value=_pct(h.savings_rate),
                prev=_pct(h.prev_savings_rate),
                delta_pts=_pct(h.savings_rate_delta_pts),
            ),
            invested=InvestedHeadline(
                value=h.invested, pct_of_net_saving=_pct(h.invested_pct_of_net_saving)
            ),
        ),
        biggest_spend=(
            BiggestSpend(category=_category(view.biggest_spend[0]), amount=view.biggest_spend[1])
            if view.biggest_spend
            else None
        ),
        review_count=view.review_count,
        cashflow=[
            CashflowMonthOut(
                month=_month(m.month),
                income=m.totals.income,
                spending=m.totals.spending,
                net_saving=m.totals.net_saving,
                invested=m.totals.invested,
            )
            for m in view.cashflow
        ],
        categories=CategoriesOut(
            summary=(
                LimitsSummaryOut(
                    spent_in_limits=view.limits.spent_in_limits,
                    limits_total=view.limits.limits_total,
                    left=view.limits.left,
                    over_count=view.limits.over_count,
                )
                if view.limits
                else None
            ),
            items=[
                CategoryLimitOut(
                    category=_category(row.category),
                    spent=row.limit.spent,
                    limit=row.limit.limit,
                    remaining=row.limit.remaining,
                    pct_used=_pct(row.limit.pct_used),
                    status=row.limit.status,
                )
                for row in view.categories
            ],
        ),
        income_sources=[
            IncomeSourceOut(
                category=_category(s.category), amount=s.amount, prev_amount=s.prev_amount
            )
            for s in view.income_sources
        ],
        accounts=[
            AccountTotalsOut(
                account=_account(r.account),
                income=r.totals.income,
                spending=r.totals.spending,
                invested=r.totals.invested,
                net=r.totals.account_net,
            )
            for r in view.accounts
        ],
    )


@router.get("/months")
async def dashboard_months(service: DashboardServiceDep) -> DashboardMonths:
    return DashboardMonths(months=[_month(m) for m in await service.months()])


@router.get(
    "",
    response_model=DashboardOut | None,
    responses={304: {"description": "Not modified (send the ETag back in If-None-Match)"}},
)
async def dashboard(
    request: Request,
    response: Response,
    service: DashboardServiceDep,
    principal: PrincipalDep,
    month: Month = None,
    trail: Annotated[int, Query(ge=1, le=36)] = 12,
) -> DashboardOut | Response | None:
    """The selected month (default: the latest with transactions) and the cash-flow trail.
    `null` when there are no transactions yet. The ETag changes whenever the user's financial
    data does (`app_user.data_version`), so an unchanged dashboard costs one indexed lookup."""
    version = await service.data_version()
    tag = hashlib.sha256(f"{principal.user_id}|{version}|{month}|{trail}".encode()).hexdigest()[:32]
    etag = f'W/"{tag}"'
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if etag in request.headers.get("if-none-match", ""):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    view = await service.view(parse_month(month) if month else None, trail=trail)
    response.headers.update(headers)
    return to_out(view) if view else None
