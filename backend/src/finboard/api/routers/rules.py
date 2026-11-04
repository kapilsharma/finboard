import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from finboard.api.deps import RuleServiceDep
from finboard.api.schemas import (
    JobAccepted,
    JobOut,
    RuleApplyIn,
    RuleCreate,
    RuleList,
    RuleOut,
    RulePackImportIn,
    RulePackImportOut,
    RuleReorderIn,
    RuleTestIn,
    RuleTestOut,
    RuleUpdate,
    ShadowOut,
    TxnBrief,
)
from finboard.services.rules import ApplyScope, PackImportResult, RuleDraft, RuleTestResult

router = APIRouter(prefix="/rules", tags=["rules"])


def test_out(result: RuleTestResult) -> RuleTestOut:
    return RuleTestOut(
        match_count=result.match_count,
        would_change=result.would_change,
        uncategorised=result.uncategorised,
        shadowed=result.shadowed,
        shadowed_by=[
            ShadowOut(rule_id=s.rule_id, pattern=s.pattern, count=s.count)
            for s in result.shadowed_by
        ],
        sample=[
            TxnBrief(
                id=r.id,
                account_id=r.account_id,
                date=r.date,
                description=r.description_raw,
                amount=r.amount,
                direction=r.direction,
                category_id=r.category_id,
                categorised_by=r.categorised_by,
            )
            for r in result.sample
        ],
    )


def _pack_out(result: PackImportResult) -> RulePackImportOut:
    return RulePackImportOut(
        added=result.added,
        skipped=result.skipped,
        replaced=result.replaced,
        categories_created=result.categories_created,
    )


@router.get("")
async def list_rules(service: RuleServiceDep) -> RuleList:
    """All rules in the order they run (priority, then id)."""
    return RuleList(items=[RuleOut.model_validate(r) for r in await service.list()])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rule(body: RuleCreate, service: RuleServiceDep) -> RuleOut:
    """Add a rule after the existing ones."""
    return RuleOut.model_validate(await service.create(**body.model_dump()))


@router.post("/reorder")
async def reorder_rules(body: RuleReorderIn, service: RuleServiceDep) -> RuleList:
    """Set the order of all rules (every rule id, exactly once, first runs first)."""
    return RuleList(items=[RuleOut.model_validate(r) for r in await service.reorder(body.ids)])


@router.post("/test")
async def test_rule(body: RuleTestIn, service: RuleServiceDep) -> RuleTestOut:
    """Dry-run a rule against the committed transactions. Changes nothing."""
    fields = body.model_dump(exclude={"rule_id"})
    return test_out(await service.test(RuleDraft(**fields), rule_id=body.rule_id))


@router.post("/apply", status_code=status.HTTP_202_ACCEPTED)
async def apply_rules(body: RuleApplyIn, service: RuleServiceDep) -> JobAccepted:
    """Re-apply the rules in the background (`rules.apply`). With `dry_run` (the default) the
    job's result is the diff; nothing changes."""
    job = await service.start_apply(
        scope=ApplyScope(body.scope.value), include_manual=body.include_manual, dry_run=body.dry_run
    )
    return JobAccepted(job=JobOut.model_validate(job))


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"application/yaml": {}, "application/json": {}}}},
)
async def export_rules(
    service: RuleServiceDep,
    format: Annotated[Literal["yaml", "json"], Query()] = "yaml",
) -> Response:
    """A rule pack: categories by path, account constraints left out."""
    content = await service.export_pack(format)
    media = "application/json" if format == "json" else "application/yaml"
    return Response(
        content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="finboard-rules.{format}"'},
    )


@router.post("/import")
async def import_rules(body: RulePackImportIn, service: RuleServiceDep) -> RulePackImportOut:
    """Load a YAML or JSON rule pack: `merge` adds its rules after yours (skipping exact
    duplicates), `replace` swaps your rules for the pack's."""
    return _pack_out(await service.import_pack(body.content, mode=body.mode))


@router.post("/starter-pack")
async def add_starter_pack(service: RuleServiceDep) -> RulePackImportOut:
    """Merge the built-in starter rules (Indian merchants and payment types)."""
    return _pack_out(await service.add_starter_pack())


@router.get("/{rule_id}")
async def get_rule(rule_id: uuid.UUID, service: RuleServiceDep) -> RuleOut:
    return RuleOut.model_validate(await service.get(rule_id))


@router.patch("/{rule_id}")
async def update_rule(rule_id: uuid.UUID, body: RuleUpdate, service: RuleServiceDep) -> RuleOut:
    return RuleOut.model_validate(await service.update(rule_id, body.changes()))


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: uuid.UUID, service: RuleServiceDep) -> None:
    await service.delete(rule_id)
