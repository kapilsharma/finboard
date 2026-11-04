"""Statement imports (ARCHITECTURE §7, §10). Long work runs in the `imports.process` job; the
client polls `GET /imports/{id}` until the status leaves `queued`/`processing`."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from finboard.api.deps import ImportServiceDep, PrincipalDep, SettingsDep
from finboard.api.idempotency import idempotent
from finboard.api.schemas import (
    AccountDraft,
    AccountRef,
    AccountSuggestion,
    AlreadyImported,
    CommitIn,
    CommitResult,
    ImportCounts,
    ImportList,
    ImportOut,
    JobOut,
    ParserCandidate,
    ParserRef,
    Period,
    Reconciliation,
    ReparseIn,
    StagedRowOut,
    StagedRowUpdate,
    UnlockIn,
)
from finboard.domain.enums import ImportStatus
from finboard.domain.errors import PayloadTooLarge, ValidationFailed
from finboard.services import imports as svc
from finboard.services.imports import ImportService, ImportView

router = APIRouter(prefix="/imports", tags=["imports"])

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
MULTIPART_OVERHEAD = 64 * 1024

_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


def to_out(view: ImportView) -> ImportOut:
    b = view.batch
    reconciliation = None
    if b.recon_status is not None:
        reconciliation = Reconciliation(
            status=b.recon_status,
            balance_kind=b.balance_kind,
            credits=b.recon_credits,
            debits=b.recon_debits,
            expected_closing=b.recon_expected_closing,
            diff=b.recon_diff,
            first_break_seq=b.recon_first_break_seq,
            overridden=b.recon_overridden,
        )
    suggestion = None
    if b.account_suggestion:
        suggestion = AccountSuggestion(create=AccountDraft.model_validate(b.account_suggestion))
    return ImportOut(
        id=b.id,
        status=b.status,
        source=b.source,
        file_name=b.file_name,
        file_size=b.file_size,
        encrypted=b.encrypted,
        archived=b.archived,
        created_at=b.created_at,
        committed_at=b.committed_at,
        rolled_back_at=b.rolled_back_at,
        error=b.error,
        job=JobOut.model_validate(view.job) if view.job else None,
        parser=ParserRef(id=b.parser_id, version=b.parser_version, confidence=b.parser_confidence)
        if b.parser_id
        else None,
        candidates=[ParserCandidate.model_validate(c) for c in b.candidates],
        institution=b.institution,
        account=AccountRef(
            id=view.account.id,
            name=view.account.name,
            type=view.account.type,
            masked_number=view.account.masked_number,
        )
        if view.account
        else None,
        account_suggestion=suggestion,
        period=Period(start=b.period_start, end=b.period_end)
        if b.period_start or b.period_end
        else None,
        opening=b.opening_balance,
        closing=b.closing_balance,
        reconciliation=reconciliation,
        counts=ImportCounts(**view.counts) if view.counts else None,
        result=CommitResult(
            inserted=b.rows_inserted, skipped=b.rows_skipped, excluded=b.rows_excluded
        )
        if b.committed_at
        else None,
        rows=[
            StagedRowOut(
                seq=r.seq,
                date=r.date,
                value_date=r.value_date,
                description=r.description_raw,
                amount=r.amount,
                direction=r.direction,
                balance_after=r.balance_after,
                include=r.include,
                duplicate=r.duplicate_of is not None,
                possible_duplicate=r.possible_duplicate,
                category_id=r.category_id,
                categorised_by=r.categorised_by,
            )
            for r in view.rows
        ]
        if view.rows is not None
        else None,
        warnings=list(b.warnings),
        file_already_imported=AlreadyImported(
            import_id=view.already_imported.id, committed_at=view.already_imported.committed_at
        )
        if view.already_imported
        else None,
    )


async def _out(service: ImportService, import_id: uuid.UUID) -> ImportOut:
    return to_out(await service.view(await service.get(import_id)))


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ImportOut,
    openapi_extra=_UPLOAD_BODY,
    responses={413: {"description": "File too large"}},
)
async def create_import(
    request: Request,
    service: ImportServiceDep,
    principal: PrincipalDep,
    settings: SettingsDep,
    idempotency_key: IdempotencyKey = None,
) -> JSONResponse:
    """Upload one statement (multipart field `file`). One import per file; send several
    requests for several files. Retries with the same `Idempotency-Key` create one import."""
    limit = settings.max_upload_bytes
    length = request.headers.get("content-length")
    if length is None:
        raise ValidationFailed("The upload needs a Content-Length")
    if not length.isdigit() or int(length) > limit + MULTIPART_OVERHEAD:
        raise PayloadTooLarge(f"Statements can be at most {limit // (1024 * 1024)} MB")

    async def run() -> ImportOut:
        form = await request.form(max_files=1, max_fields=1, max_part_size=limit)
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ValidationFailed("Attach the statement as the multipart field 'file'")
        data = await upload.read()
        await form.close()
        batch = await service.create(file_name=upload.filename or "statement.pdf", data=data)
        return to_out(await service.view(batch))

    return await idempotent(
        request.app.state.redis,
        user_id=principal.user_id,
        scope="imports.create",
        key=idempotency_key,
        status_code=status.HTTP_202_ACCEPTED,
        call=run,
    )


@router.get("")
async def list_imports(
    service: ImportServiceDep,
    status_filter: Annotated[list[ImportStatus] | None, Query(alias="status")] = None,
    cursor: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ImportList:
    """Import history, newest first (no rows). `cursor` is the `next_cursor` of the last page."""
    batches = await service.history(statuses=status_filter, before=cursor, limit=limit + 1)
    page = list(batches[:limit])
    items = [to_out(await service.view(b, with_rows=False)) for b in page]
    next_cursor = str(page[-1].id) if len(batches) > limit else None
    return ImportList(items=items, next_cursor=next_cursor)


@router.get("/{import_id}")
async def get_import(import_id: uuid.UUID, service: ImportServiceDep) -> ImportOut:
    """Status, and the preview rows once parsed."""
    return await _out(service, import_id)


@router.post("/{import_id}/unlock", status_code=status.HTTP_202_ACCEPTED)
async def unlock_import(
    import_id: uuid.UUID, body: UnlockIn, service: ImportServiceDep
) -> ImportOut:
    """Send the statement password. It is never stored: it reaches the worker through a
    single-use, encrypted, 120-second handoff (ADR-0027)."""
    await service.unlock(import_id, body.password.get_secret_value())
    return await _out(service, import_id)


@router.post("/{import_id}/reparse", status_code=status.HTTP_202_ACCEPTED)
async def reparse_import(
    import_id: uuid.UUID, body: ReparseIn, service: ImportServiceDep
) -> ImportOut:
    """Choose a different parser and/or account. An account change alone applies at once."""
    await service.reparse(import_id, parser_id=body.parser_id, account_id=body.account_id)
    return await _out(service, import_id)


@router.patch("/{import_id}/rows/{seq}")
async def update_staged_row(
    import_id: uuid.UUID, seq: int, body: StagedRowUpdate, service: ImportServiceDep
) -> ImportOut:
    await service.update_row(import_id, seq, body.changes())
    return await _out(service, import_id)


@router.post("/{import_id}/commit", response_model=ImportOut)
async def commit_import(
    import_id: uuid.UUID,
    body: CommitIn,
    request: Request,
    service: ImportServiceDep,
    principal: PrincipalDep,
    idempotency_key: IdempotencyKey = None,
) -> JSONResponse:
    """Write the preview's included rows as transactions. A reconciliation mismatch blocks
    this unless `override_reconciliation` is set (and the override is recorded)."""
    draft = body.create_account

    async def run() -> ImportOut:
        await service.commit(
            import_id,
            override_reconciliation=body.override_reconciliation,
            create_account=svc.AccountDraft(**draft.model_dump()) if draft else None,
        )
        return await _out(service, import_id)

    return await idempotent(
        request.app.state.redis,
        user_id=principal.user_id,
        scope=f"imports.commit:{import_id}",
        key=idempotency_key,
        status_code=status.HTTP_200_OK,
        call=run,
    )


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_import(import_id: uuid.UUID, service: ImportServiceDep) -> None:
    """Discard a not-yet-committed import: its preview rows and the stored file are deleted."""
    await service.discard(import_id)


@router.post("/{import_id}/rollback")
async def rollback_import(import_id: uuid.UUID, service: ImportServiceDep) -> ImportOut:
    """Undo a commit. Rows another committed import also contains are kept (moved to it)."""
    await service.rollback(import_id)
    return await _out(service, import_id)
