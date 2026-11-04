"""Statement imports, end to end (ARCHITECTURE §7).

API side:     create · get · list · unlock · reparse · update_row · commit · discard · rollback
Worker side:  process (the `imports.process` job) · mark_killed (hard time limit)

Statuses: uploaded (waiting for a parse slot) → queued → processing → needs_password | parsed |
failed; parsed → committed → rolled_back; anything not committed → discarded.

Privacy: file names, descriptions and amounts are never logged; error messages stored on the
import are fixed, user-safe strings (ParserError messages are written to be safe).
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.categorisation.matcher import TxnFacts
from finboard.categorisation.normalise import normalise
from finboard.core.config import Settings
from finboard.db.models import Account, ImportBatch, Job, StagedRow
from finboard.db.uow import UnitOfWork, unit_of_work
from finboard.domain.enums import (
    AccountType,
    CategorisedBy,
    Direction,
    ImportRowOutcome,
    ImportStatus,
    JobStatus,
    ReconStatus,
)
from finboard.domain.errors import (
    Conflict,
    FinboardError,
    NotFound,
    PayloadTooLarge,
    ReconciliationMismatch,
    ServiceUnavailable,
    ValidationFailed,
)
from finboard.domain.fingerprint import (
    FINGERPRINT_VERSION,
    FingerprintInput,
    fingerprints,
    possible_duplicates,
)
from finboard.domain.reconcile import BalanceKind, ReconRow, reconcile
from finboard.parsers.registry import ParserRegistry
from finboard.parsers.sdk import (
    DocumentError,
    ParsedStatement,
    ParserError,
    PasswordRequired,
    WrongPassword,
    is_pdf,
    open_document,
)
from finboard.services.categoriser import Categoriser, Decision
from finboard.services.jobs import JobQueue, JobService
from finboard.services.parser_settings import ParserSettingsService, parse_options
from finboard.storage.blob import BlobNotFound, BlobStore, import_blob_key
from finboard.storage.secrets import SecretStore

log = structlog.get_logger(__name__)

PARSE_TASK = "imports.process"
TRANSFER_SUGGEST_TASK = "transfers.suggest"
ARCHIVE_SETTING = "archive_statements"  # keep the original PDF after commit (OQ-5: default on)

MSG_TIMEOUT = "Reading the statement took too long"
MSG_UNREADABLE = "This statement couldn't be read"
MSG_PASSWORD_EXPIRED = "The password expired before the statement was read; enter it again"  # noqa: S105
MSG_NO_PARSER = "No parser recognised this statement. Choose one and re-parse."
MSG_FILE_MISSING = "The uploaded file is no longer available; upload it again"


class ImportFailed(FinboardError):
    """The parse job failed with a user-safe reason (also stored on the import)."""

    code = "import_failed"
    title = "Import failed"

    def __init__(self, detail: str, *, candidates: list[dict[str, Any]] | None = None) -> None:
        super().__init__(detail)
        self.candidates = candidates


@dataclass(frozen=True, slots=True)
class AccountDraft:
    name: str
    type: AccountType
    institution: str | None = None
    masked_number: str | None = None


@dataclass
class ImportView:
    batch: ImportBatch
    job: Job | None
    account: Account | None
    rows: Sequence[StagedRow] | None
    already_imported: ImportBatch | None
    counts: dict[str, int] | None = field(default=None)


@dataclass(frozen=True, slots=True)
class ImportLimits:
    max_upload_bytes: int
    max_pages: int
    parse_concurrency_per_user: int
    staged_ttl: timedelta

    @classmethod
    def from_settings(cls, settings: Settings) -> ImportLimits:
        return cls(
            max_upload_bytes=settings.max_upload_bytes,
            max_pages=settings.max_pages,
            parse_concurrency_per_user=settings.parse_concurrency_per_user,
            staged_ttl=timedelta(days=settings.staged_import_ttl_days),
        )


def _now() -> datetime:
    return datetime.now(UTC)


class ImportService:
    def __init__(
        self,
        uow: UnitOfWork,
        *,
        blobs: BlobStore,
        queue: JobQueue,
        registry: ParserRegistry,
        limits: ImportLimits,
        secrets: SecretStore | None = None,
    ) -> None:
        self.uow = uow
        self.blobs = blobs
        self.queue = queue
        self.registry = registry
        self.limits = limits
        self.secrets = secrets
        self.jobs = JobService(uow, queue)

    # ================================================================ API side

    async def create(self, *, file_name: str, data: bytes) -> ImportBatch:
        """Store an uploaded statement and queue it for parsing (or wait for a free slot)."""
        if len(data) > self.limits.max_upload_bytes:
            raise PayloadTooLarge(
                f"Statements can be at most {self.limits.max_upload_bytes // (1024 * 1024)} MB"
            )
        if not is_pdf(data):
            raise ValidationFailed("Only PDF statements are supported")
        batch = await self.uow.imports.add(
            ImportBatch(
                status=ImportStatus.UPLOADED,
                file_name=_safe_file_name(file_name),
                file_sha256=hashlib.sha256(data).hexdigest(),
                file_size=len(data),
                expires_at=_now() + self.limits.staged_ttl,
            )
        )
        batch.blob_key = import_blob_key(self.uow.user_id, batch.id)
        await self.blobs.put(batch.blob_key, data)

        await self.uow.imports.lock_parse_slots()
        if await self.uow.imports.count_in_flight() < self.limits.parse_concurrency_per_user:
            await self._submit_parse(batch)
        else:
            await self.uow.commit()  # waits as `uploaded`; a worker starts it when a slot frees
        log.info("import.created", import_id=str(batch.id), size=len(data), status=batch.status)
        return batch

    async def get(self, import_id: uuid.UUID) -> ImportBatch:
        batch = await self.uow.imports.get(import_id)
        if batch is None:
            raise NotFound("Import not found")
        return batch

    async def view(self, batch: ImportBatch, *, with_rows: bool = True) -> ImportView:
        job = await self.uow.jobs.get(batch.job_id) if batch.job_id else None
        account = await self.uow.accounts.get(batch.account_id) if batch.account_id else None
        rows = None
        counts = None
        if batch.status in (ImportStatus.PARSED, ImportStatus.COMMITTED):
            staged = await self.uow.staged_rows.list(batch.id)
            counts = _counts(staged)
            rows = staged if with_rows else None
        already = await self.uow.imports.committed_with_sha256(
            batch.file_sha256, exclude_id=batch.id
        )
        return ImportView(batch, job, account, rows, already, counts)

    async def history(
        self, *, statuses: Sequence[ImportStatus] | None, before: uuid.UUID | None, limit: int
    ) -> Sequence[ImportBatch]:
        return await self.uow.imports.list(statuses=statuses, before=before, limit=limit)

    async def unlock(self, import_id: uuid.UUID, password: str) -> ImportBatch:
        batch = await self._locked(import_id)
        if batch.status is not ImportStatus.NEEDS_PASSWORD:
            raise Conflict("This statement isn't waiting for a password")
        if self.secrets is None:
            raise ServiceUnavailable(
                "Unlocking statements needs FINBOARD_SECRET_KEY; run `finboard init`"
            )
        ref = await self.secrets.put(password)
        await self._submit_parse(batch, secret_ref=ref)
        return batch

    async def reparse(
        self,
        import_id: uuid.UUID,
        *,
        parser_id: str | None = None,
        account_id: uuid.UUID | None = None,
    ) -> ImportBatch:
        """Change the parser and/or account. An account change alone is applied at once from
        the staged rows; a parser change parses the file again (asking for the password again
        if the file is encrypted, because passwords are never stored)."""
        batch = await self._locked(import_id)
        allowed = (ImportStatus.PARSED, ImportStatus.FAILED, ImportStatus.NEEDS_PASSWORD)
        if batch.status not in allowed:
            raise Conflict("Only a parsed, failed or locked import can be re-parsed")
        if parser_id is not None and parser_id not in self.registry:
            raise ValidationFailed(f"Unknown parser '{parser_id}'")
        account = await self._account(account_id) if account_id is not None else None

        parser_changes = parser_id is not None and parser_id != batch.parser_id
        if account is not None:
            batch.account_id = account.id
            batch.account_suggestion = None
        if batch.status is ImportStatus.PARSED and not parser_changes:
            if account is not None:
                await self._restage_for_account(batch, account)
            await self.uow.commit()
            return batch

        if parser_id is not None:
            batch.requested_parser_id = parser_id
        if batch.encrypted:
            batch.status = ImportStatus.NEEDS_PASSWORD
            batch.error = None
            await self.uow.commit()
            return batch
        await self._submit_parse(batch)
        return batch

    async def update_row(
        self, import_id: uuid.UUID, seq: int, changes: dict[str, Any]
    ) -> StagedRow:
        batch = await self._locked(import_id)
        if batch.status is not ImportStatus.PARSED:
            raise Conflict("Rows can only be changed before the import is committed")
        row = await self.uow.staged_rows.get(batch.id, seq)
        if row is None:
            raise NotFound("Row not found")
        if "include" in changes:
            row.include = bool(changes["include"])
        if "category_id" in changes:
            category_id = changes["category_id"]
            if category_id is None:
                row.category_id, row.categorised_by = None, None
            else:
                if await self.uow.categories.get(category_id) is None:
                    raise ValidationFailed("Unknown category")
                row.category_id, row.categorised_by = category_id, CategorisedBy.MANUAL
        await self.uow.session.flush()
        await self.uow.commit()
        return row

    async def commit(
        self,
        import_id: uuid.UUID,
        *,
        override_reconciliation: bool = False,
        create_account: AccountDraft | None = None,
    ) -> ImportBatch:
        """Turn the staged rows into transactions in one database transaction.

        The import row is locked (double clicks and retries wait, then see `committed`);
        duplicates are skipped by the unique fingerprint index (ON CONFLICT DO NOTHING), so two
        overlapping imports committed at the same moment can't both insert a row.
        """
        await self.uow.imports.lock_ledger(exclusive=False)
        batch = await self._locked(import_id)
        if batch.status is ImportStatus.COMMITTED:
            raise Conflict("This import is already committed")
        if batch.status is not ImportStatus.PARSED:
            raise Conflict("Only a parsed import can be committed")

        if create_account is not None:
            account = await self._create_account(create_account, batch.parser_id)
            batch.account_id = account.id
            batch.account_suggestion = None
            await self._restage_for_account(batch, account)
        if batch.account_id is None:
            raise ValidationFailed("Choose or create the account this statement belongs to")
        account = await self._account(batch.account_id)
        rows = await self.uow.staged_rows.list(batch.id)
        if any(r.fingerprint is None for r in rows):
            await self._restage_for_account(batch, account)
            rows = await self.uow.staged_rows.list(batch.id)

        if batch.recon_status is ReconStatus.MISMATCH:
            if not override_reconciliation:
                raise ReconciliationMismatch(
                    "The statement's totals don't add up. Check the highlighted row, "
                    "or commit anyway with the override."
                )
            batch.recon_overridden = True

        # Rules may have changed since the preview: decide again, keeping the user's own choices.
        categoriser = await Categoriser.load(self.uow)
        to_insert = [r for r in rows if r.include and r.duplicate_of is None]
        values = []
        rule_by_fingerprint: dict[str, uuid.UUID] = {}
        for row in to_insert:
            decision = self._manual_decision(categoriser, row) or categoriser.decide(
                _facts(row, account.id), account.type
            )
            if decision.rule_id is not None and row.fingerprint:
                rule_by_fingerprint[row.fingerprint] = decision.rule_id
            values.append(
                {
                    "account_id": account.id,
                    "import_id": batch.id,
                    "date": row.date,
                    "value_date": row.value_date,
                    "description_raw": row.description_raw,
                    "description_norm": row.description_norm,
                    "amount": row.amount,
                    "direction": row.direction,
                    "balance_after": row.balance_after,
                    "category_id": decision.category_id,
                    "type": decision.type,
                    "categorised_by": decision.categorised_by,
                    "rule_id": decision.rule_id,
                    "needs_review": decision.needs_review,
                    "fingerprint": row.fingerprint,
                    "fingerprint_version": FINGERPRINT_VERSION,
                    "raw": row.raw,
                }
            )
        inserted = await self.uow.txns.insert_new(values)
        hits = Counter(rule_by_fingerprint[fp] for fp in inserted if fp in rule_by_fingerprint)
        await self.uow.rules.add_hits(hits, _now())
        await categoriser.record_timeouts(self.uow)

        # Everything this import saw (except rows the user excluded) goes into import_row, so a
        # later rollback of another import can hand shared rows over to this one.
        seen = [r for r in rows if r.include or r.duplicate_of is not None]
        others = [r.fingerprint for r in seen if r.fingerprint and r.fingerprint not in inserted]
        existing = await self.uow.txns.ids_by_fingerprint(others)
        import_rows: list[tuple[str, uuid.UUID, str]] = [
            (fp, txn_id, ImportRowOutcome.INSERTED) for fp, txn_id in inserted.items()
        ]
        import_rows += [(fp, existing[fp], ImportRowOutcome.DUPLICATE) for fp in existing]
        await self.uow.import_rows.add_all(batch.id, import_rows)

        batch.status = ImportStatus.COMMITTED
        batch.committed_at = _now()
        batch.rows_inserted = len(inserted)
        batch.rows_skipped = len(seen) - len(inserted)
        batch.rows_excluded = len(rows) - len(seen)
        archive = (await self.uow.settings.all()).get(ARCHIVE_SETTING, True)
        blob_to_delete = None if archive else batch.blob_key
        batch.archived = bool(archive)
        if blob_to_delete:
            batch.blob_key = None
        await self.uow.users.bump_data_version(self.uow.user_id)
        # New rows may complete transfers between the user's accounts (ARCHITECTURE §9).
        pairing = await self.jobs.create(TRANSFER_SUGGEST_TASK) if inserted else None
        await self.uow.session.flush()
        await self.uow.commit()
        if blob_to_delete:
            await self.blobs.delete(blob_to_delete)
        if pairing is not None:
            # The commit stands if the queue is down; pairing runs after the next commit.
            with contextlib.suppress(ServiceUnavailable):
                await self.jobs.dispatch(pairing)
        log.info(
            "import.committed",
            import_id=str(batch.id),
            inserted=batch.rows_inserted,
            skipped=batch.rows_skipped,
            excluded=batch.rows_excluded,
        )
        return batch

    async def discard(self, import_id: uuid.UUID) -> None:
        batch = await self._locked(import_id)
        if batch.status is ImportStatus.COMMITTED:
            raise Conflict("A committed import can't be discarded; roll it back instead")
        if batch.status.is_in_flight:
            raise Conflict("This statement is still being read; try again in a moment")
        if batch.status in (ImportStatus.DISCARDED, ImportStatus.ROLLED_BACK):
            return
        await self.uow.staged_rows.delete_all(batch.id)
        blob_key, batch.blob_key = batch.blob_key, None
        batch.status = ImportStatus.DISCARDED
        await self.uow.commit()
        if blob_key:
            await self.blobs.delete(blob_key)

    async def rollback(self, import_id: uuid.UUID) -> ImportBatch:
        """Undo a commit. Rows that another committed import also saw are handed over to the
        earliest such import; the rest are deleted."""
        await self.uow.imports.lock_ledger(exclusive=True)
        batch = await self._locked(import_id)
        if batch.status is not ImportStatus.COMMITTED:
            raise Conflict("Only a committed import can be rolled back")
        owned = await self.uow.import_rows.inserted_by(batch.id)
        heirs = await self.uow.import_rows.heirs(batch.id, [fp for fp, _ in owned])
        orphans: list[uuid.UUID] = []
        for fp, txn_id in owned:
            heir = heirs.get(fp)
            if heir is None:
                orphans.append(txn_id)
            else:
                await self.uow.txns.reassign(txn_id, heir)
                await self.uow.import_rows.mark_inserted(heir, fp)
        await self.uow.import_rows.delete_all(batch.id)
        await self.uow.txns.delete_ids(orphans)
        batch.status = ImportStatus.ROLLED_BACK
        batch.rolled_back_at = _now()
        await self.uow.users.bump_data_version(self.uow.user_id)
        await self.uow.commit()
        log.info(
            "import.rolled_back",
            import_id=str(batch.id),
            deleted=len(orphans),
            reassigned=len(owned) - len(orphans),
        )
        return batch

    # ================================================================ worker side

    async def process(
        self,
        job: Job,
        *,
        secret_ref: str | None = None,
        timeout_errors: tuple[type[BaseException], ...] = (),
    ) -> dict[str, Any]:
        """The `imports.process` job: decrypt → detect → parse → reconcile → match account →
        fingerprint/dedupe → stage. Safe to run twice (only a `queued` import is processed)."""
        import_id = uuid.UUID(str(job.params["import_id"]))
        batch = await self.uow.imports.get(import_id, for_update=True)
        if batch is None or batch.status is not ImportStatus.QUEUED or batch.job_id != job.id:
            return {"skipped": True}
        batch.status = ImportStatus.PROCESSING
        await self.uow.commit()

        try:
            result = await self._process(batch, secret_ref, timeout_errors)
        except ImportFailed as exc:
            await self._fail(import_id, exc.detail, candidates=exc.candidates)
            raise
        except timeout_errors:
            await self._fail(import_id, MSG_TIMEOUT)
            raise ImportFailed(MSG_TIMEOUT) from None
        except Exception as exc:
            # The message of an unexpected error may quote statement contents: log the type,
            # keep the traceback at DEBUG, and don't chain it into the job failure.
            log.error("import.process_error", import_id=str(import_id), error=type(exc).__name__)
            log.debug("import.process_traceback", import_id=str(import_id), exc_info=True)
            await self._fail(import_id, MSG_UNREADABLE)
            raise ImportFailed(MSG_UNREADABLE) from None
        finally:
            await self.start_waiting()
        return result

    async def start_waiting(self) -> None:
        """Start uploaded imports while this user has free parse slots."""
        try:
            while True:
                await self.uow.imports.lock_parse_slots()
                if (
                    await self.uow.imports.count_in_flight()
                    >= self.limits.parse_concurrency_per_user
                ):
                    break
                waiting = await self.uow.imports.oldest_waiting()
                if waiting is None:
                    break
                await self._submit_parse(waiting)
            await self.uow.commit()
        except Exception as exc:  # never let this hide the import's own outcome
            await self.uow.rollback()
            log.error("import.start_waiting_failed", error=type(exc).__name__)

    async def _process(
        self,
        batch: ImportBatch,
        secret_ref: str | None,
        timeout_errors: tuple[type[BaseException], ...],
    ) -> dict[str, Any]:
        password: str | None = None
        if secret_ref is not None:
            password = await self.secrets.take(secret_ref) if self.secrets else None
            if password is None:
                return await self._needs_password(batch, MSG_PASSWORD_EXPIRED)
        if batch.blob_key is None:
            raise ImportFailed(MSG_FILE_MISSING)
        try:
            data = await self.blobs.get(batch.blob_key)
        except BlobNotFound as exc:
            raise ImportFailed(MSG_FILE_MISSING) from exc

        try:
            doc = open_document(
                data, file_name=batch.file_name, password=password, max_pages=self.limits.max_pages
            )
        except WrongPassword:
            return await self._needs_password(batch, WrongPassword().user_message)
        except PasswordRequired:
            return await self._needs_password(batch, None)
        except DocumentError as exc:
            raise ImportFailed(exc.user_message) from exc
        finally:
            password = None  # drop our reference as soon as the document is open
        batch.encrypted = doc.encrypted

        settings = ParserSettingsService(self.uow, self.registry)
        choices = {c.parser.id: c for c in await settings.choices()}
        enabled = [pid for pid, c in choices.items() if c.enabled]
        with doc:
            account = await self._account(batch.account_id) if batch.account_id else None
            if batch.requested_parser_id:
                parser = self.registry.get(batch.requested_parser_id)
                if parser is None:
                    raise ImportFailed(f"Parser '{batch.requested_parser_id}' isn't installed")
                detection = self.registry.detect(doc, reraise=timeout_errors)
                confidence = next(
                    (c.confidence for c in detection.candidates if c.parser_id == parser.id), 0.0
                )
            else:
                detection = self.registry.detect(
                    doc,
                    preferred_id=account.parser_id if account else None,
                    enabled=enabled,
                    reraise=timeout_errors,
                )
                chosen = detection.chosen
                if chosen is None:
                    raise ImportFailed(MSG_NO_PARSER, candidates=_candidates(detection.candidates))
                parser = self.registry.get(chosen.parser_id)
                assert parser is not None
                confidence = chosen.confidence
            batch.candidates = _candidates(detection.candidates)
            try:
                # An explicitly requested parser runs even if it is switched off for detection.
                stored = choices[parser.id].options if parser.id in choices else {}
                statement = parser.parse(doc, parse_options(parser, stored))
            except ParserError as exc:
                raise ImportFailed(exc.user_message) from exc

        batch.parser_id, batch.parser_version = parser.id, parser.version
        batch.parser_confidence = confidence
        warnings = list(statement.warnings)
        if detection.ambiguous and not batch.requested_parser_id:
            warnings.append("More than one parser matched this file; check the parser choice")
        await self._stage(batch, statement, warnings)
        await self.uow.commit()
        log.info("import.parsed", import_id=str(batch.id), rows=batch.rows_parsed)
        return {"status": batch.status.value, "rows": batch.rows_parsed}

    async def _needs_password(self, batch: ImportBatch, message: str | None) -> dict[str, Any]:
        batch.status = ImportStatus.NEEDS_PASSWORD
        batch.encrypted = True
        batch.error = message
        await self.uow.commit()
        return {"status": batch.status.value}

    async def _fail(
        self,
        import_id: uuid.UUID,
        message: str,
        *,
        candidates: list[dict[str, Any]] | None = None,
    ) -> None:
        await self.uow.rollback()
        batch = await self.uow.imports.get(import_id, for_update=True)
        if batch is not None:
            batch.status = ImportStatus.FAILED
            batch.error = message
            if candidates is not None:
                batch.candidates = candidates  # so the user can pick a parser and re-parse
            await self.uow.commit()

    # ================================================================ staging

    async def _stage(
        self, batch: ImportBatch, statement: ParsedStatement, warnings: list[str]
    ) -> None:
        batch.institution = statement.institution[:120]
        batch.account_hint = statement.account_hint
        batch.balance_kind = statement.balance_kind
        batch.period_start, batch.period_end = statement.period_start, statement.period_end
        batch.opening_balance = statement.opening_balance
        batch.closing_balance = statement.closing_balance
        batch.warnings = warnings
        batch.error = None

        rows = [
            StagedRow(
                seq=seq,
                date=txn.date,
                value_date=txn.value_date,
                description_raw=txn.description,
                description_norm=normalise(txn.description),
                amount=txn.amount,
                direction=Direction(txn.direction),
                balance_after=txn.balance_after,
                raw=dict(txn.raw),
                include=True,
            )
            for seq, txn in enumerate(statement.transactions)
        ]
        await self.uow.staged_rows.replace(batch.id, rows)
        batch.rows_parsed = len(rows)

        account = None
        if batch.account_id is not None:
            account = await self.uow.accounts.get(batch.account_id)
        if account is None:
            account = await self._match_account(batch, statement)
        if account is not None:
            batch.account_id = account.id
            batch.account_suggestion = None
            await self._restage_for_account(batch, account, rows=rows)
        else:
            batch.account_id = None
            batch.account_suggestion = _suggestion(batch, statement, self.registry)
            self._reconcile(batch, statement.balance_kind, rows)
            await self._categorise_staged(rows, None)
        batch.status = ImportStatus.PARSED
        batch.expires_at = _now() + self.limits.staged_ttl

    async def _restage_for_account(
        self, batch: ImportBatch, account: Account, *, rows: Sequence[StagedRow] | None = None
    ) -> None:
        """Fingerprints, duplicates and reconciliation depend on the account."""
        if rows is None:
            rows = await self.uow.staged_rows.list(batch.id)
        inputs = [
            FingerprintInput(
                r.date, r.direction.value, r.amount, r.description_raw, r.balance_after
            )
            for r in rows
        ]
        prints = fingerprints(account.id, inputs)
        existing = await self.uow.txns.ids_by_fingerprint(prints)
        flagged: set[int] = set()
        if rows:
            first, last = min(r.date for r in rows), max(r.date for r in rows)
            known = [
                FingerprintInput(d, str(direction), amount, text, None)
                for d, direction, amount, text in await self.uow.txns.money_keys(
                    account.id, first, last
                )
            ]
            flagged = possible_duplicates(inputs, known)
        for index, (row, fp) in enumerate(zip(rows, prints, strict=True)):
            was_duplicate = row.duplicate_of is not None
            row.fingerprint = fp
            row.duplicate_of = existing.get(fp)
            row.possible_duplicate = row.duplicate_of is None and index in flagged
            if row.duplicate_of is not None:
                row.include = False
            elif was_duplicate:
                row.include = True
        kind: BalanceKind = "liability" if account.type.is_liability else "asset"
        self._reconcile(batch, kind, rows)
        await self._categorise_staged(rows, account)
        await self.uow.session.flush()

    async def _categorise_staged(self, rows: Sequence[StagedRow], account: Account | None) -> None:
        """Propose categories for the preview. Rows the user categorised keep their choice; a
        row with no proposal (category_id NULL) goes to the fallback category at commit."""
        categoriser = await Categoriser.load(self.uow)
        for row in rows:
            if row.categorised_by is CategorisedBy.MANUAL:
                continue
            decision = categoriser.decide(
                _facts(row, account.id if account else None), account.type if account else None
            )
            if decision.needs_review:
                row.category_id, row.rule_id, row.categorised_by = None, None, None
            else:
                row.category_id, row.rule_id = decision.category_id, decision.rule_id
                row.categorised_by = decision.categorised_by
        await categoriser.record_timeouts(self.uow)

    @staticmethod
    def _manual_decision(categoriser: Categoriser, row: StagedRow) -> Decision | None:
        if row.categorised_by is not CategorisedBy.MANUAL or row.category_id is None:
            return None
        category = categoriser.category(row.category_id)
        if category is None:
            return None
        return Decision(category.id, category.type, CategorisedBy.MANUAL, None, False)

    @staticmethod
    def _reconcile(batch: ImportBatch, kind: BalanceKind, rows: Sequence[StagedRow]) -> None:
        result = reconcile(
            kind,
            batch.opening_balance,
            batch.closing_balance,
            [ReconRow(r.seq, r.direction.value, r.amount, r.balance_after) for r in rows],
        )
        batch.balance_kind = kind
        batch.recon_status = ReconStatus(result.status)
        batch.recon_credits, batch.recon_debits = result.credits, result.debits
        batch.recon_expected_closing = result.expected_closing
        batch.recon_diff = result.diff
        batch.recon_first_break_seq = result.first_break_seq
        batch.recon_overridden = False

    async def _match_account(
        self, batch: ImportBatch, statement: ParsedStatement
    ) -> Account | None:
        if statement.account_hint:
            candidates = await self.uow.accounts.by_masked_number(statement.account_hint)
            if len(candidates) == 1:
                return candidates[0]
            if candidates:
                return None  # ambiguous: let the user choose
        if batch.parser_id:
            parser = self.registry.get(batch.parser_id)
            if parser is not None and not getattr(parser, "fallback", False):
                by_parser = await self.uow.accounts.by_parser(batch.parser_id)
                if len(by_parser) == 1:
                    return by_parser[0]
        return None

    # ================================================================ helpers

    async def _submit_parse(self, batch: ImportBatch, *, secret_ref: str | None = None) -> None:
        job = await self.jobs.create(PARSE_TASK, {"import_id": str(batch.id)})
        batch.job_id = job.id
        batch.status = ImportStatus.QUEUED
        batch.error = None
        try:
            await self.jobs.dispatch(job, secret_ref=secret_ref)
        except ServiceUnavailable:
            batch.status = ImportStatus.FAILED
            batch.error = "The background worker is unavailable; try re-parsing later"
            await self.uow.commit()
            raise

    async def _locked(self, import_id: uuid.UUID) -> ImportBatch:
        batch = await self.uow.imports.get(import_id, for_update=True)
        if batch is None:
            raise NotFound("Import not found")
        return batch

    async def _account(self, account_id: uuid.UUID) -> Account:
        account = await self.uow.accounts.get(account_id)
        if account is None:
            raise ValidationFailed("Unknown account")
        return account

    async def _create_account(self, draft: AccountDraft, parser_id: str | None) -> Account:
        if await self.uow.accounts.name_taken(draft.name):
            raise Conflict(f"An account called '{draft.name}' already exists")
        parser = self.registry.get(parser_id) if parser_id else None
        keep_parser = parser is not None and not getattr(parser, "fallback", False)
        return await self.uow.accounts.add(
            Account(
                name=draft.name,
                type=draft.type,
                institution=draft.institution,
                masked_number=draft.masked_number,
                parser_id=parser_id if keep_parser else None,
            )
        )


# ---------------------------------------------------------------- module helpers


def _safe_file_name(name: str) -> str:
    """Display only (never a path): strip directories and control characters."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable()).strip()
    return (cleaned or "statement.pdf")[:255]


def _candidates(candidates: Sequence[Any]) -> list[dict[str, Any]]:
    return [{"id": c.parser_id, "name": c.name, "confidence": c.confidence} for c in candidates[:5]]


def _suggestion(
    batch: ImportBatch, statement: ParsedStatement, registry: ParserRegistry
) -> dict[str, Any]:
    parser = registry.get(batch.parser_id) if batch.parser_id else None
    types = list(getattr(parser, "account_types", ()) or ())
    if statement.balance_kind == "liability":
        kind = "credit_card"
    else:
        kind = next((t for t in types if t not in ("credit_card", "loan")), "savings")
    hint = statement.account_hint
    name = statement.institution if statement.institution != "Unknown bank" else "New account"
    if hint:
        name = f"{name} {hint}"
    return {
        "name": name[:80],
        "type": kind,
        "institution": statement.institution[:80],
        "masked_number": hint,
    }


def _facts(row: StagedRow, account_id: uuid.UUID | None) -> TxnFacts:
    return TxnFacts(row.description_norm, row.direction.value, row.amount, account_id)


def _counts(rows: Sequence[StagedRow]) -> dict[str, int]:
    duplicate = sum(1 for r in rows if r.duplicate_of is not None)
    excluded = sum(1 for r in rows if not r.include and r.duplicate_of is None)
    new = sum(1 for r in rows if r.include and r.duplicate_of is None)
    return {
        "parsed": len(rows),
        "new": new,
        "duplicate": duplicate,
        "excluded": excluded,
        "possible_duplicate": sum(1 for r in rows if r.possible_duplicate),
        "needs_review": sum(
            1 for r in rows if r.include and r.duplicate_of is None and r.category_id is None
        ),
    }


async def mark_killed(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    queue: JobQueue,
    blobs: BlobStore,
    registry: ParserRegistry,
    limits: ImportLimits,
) -> None:
    """Called after a hard time limit killed the worker process mid-parse: the task's own error
    handling never ran, so record the failure here and free the parse slot."""
    async with unit_of_work(sessionmaker, user_id) as uow:
        job = await uow.jobs.get(job_id, for_update=True)
        if job is not None and not job.status.is_finished:
            job.status = JobStatus.FAILED
            job.error = MSG_TIMEOUT
            job.finished_at = _now()
        batch = await uow.imports.by_job(job_id, for_update=True)
        if batch is not None and batch.status.is_in_flight:
            batch.status = ImportStatus.FAILED
            batch.error = MSG_TIMEOUT
        await uow.commit()
        service = ImportService(uow, blobs=blobs, queue=queue, registry=registry, limits=limits)
        await service.start_waiting()
    log.warning("import.parse_killed", job_id=str(job_id))
