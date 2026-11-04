"""Your data, out and back in (ARCHITECTURE §10, §13): export, import, CSV and delete-all.

**Export** (`data.export`, a job) writes one zip to the blob store:

    manifest.json   format, version, counts and a SHA-256 per table and per file
    data.json       every user-owned row, column by column (ids kept)
    pdfs/<id>.pdf   the archived statements (still bank-encrypted, as uploaded)

**Import** (`data.import`, a job) only goes into a Finboard with no accounts, transactions or
imports, and replaces its categories, rules, budgets and settings. The zip is untrusted input
(§13): only the members above, no paths outside them, sizes and compression ratios bounded,
the schema version known, every row checked against the table's columns and types, and every
checksum verified, before anything is written. Ids are kept, so a restored Finboard still
recognises statements it has seen (fingerprints contain the account id); if the ids already
exist in this database the import is refused.

**Delete-all** (`data.delete_user_data`) removes the caller's rows and files only, then gives
them the default categories and starter rules again.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import uuid
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

import structlog
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.exc import IntegrityError

from finboard import __version__
from finboard.db.base import Base
from finboard.db.models import (
    Account,
    Budget,
    Category,
    ImportBatch,
    ImportRow,
    Job,
    Rule,
    StagedRow,
    TransferPair,
    Txn,
    UserParserSetting,
    UserSetting,
)
from finboard.db.uow import UnitOfWork
from finboard.domain.enums import ImportStatus
from finboard.domain.errors import Conflict, FinboardError, NotFound, ValidationFailed
from finboard.services.jobs import JobQueue, JobService
from finboard.services.users import seed_defaults
from finboard.storage.blob import (
    BlobNotFound,
    BlobStore,
    data_import_blob_key,
    export_blob_key,
    import_blob_key,
    user_prefix,
)

log = structlog.get_logger(__name__)

EXPORT_TASK = "data.export"
IMPORT_TASK = "data.import"
DELETE_TASK = "data.delete_user_data"
FORMAT = "finboard-export"
VERSION = 1
DELETE_CONFIRMATION = "DELETE ALL"

MAX_ZIP_BYTES = 512 * 1024 * 1024
MAX_DATA_JSON_BYTES = 256 * 1024 * 1024
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_RATIO = 200  # uncompressed ÷ compressed, per member (zip bombs)
MAX_MEMBERS = 20_000
_PDF_MEMBER = re.compile(
    r"^pdfs/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.pdf$"
)

# Tables in insert order (parents first). Jobs and staged rows are transient: not exported.
TABLES: tuple[tuple[str, type[Base]], ...] = (
    ("categories", Category),
    ("accounts", Account),
    ("rules", Rule),
    ("budgets", Budget),
    ("imports", ImportBatch),
    ("transactions", Txn),
    ("import_rows", ImportRow),
    ("transfer_pairs", TransferPair),
    ("settings", UserSetting),
    ("parser_settings", UserParserSetting),
)
# Imports still in progress have no lasting data of their own (staged rows aren't exported).
EXPORTED_IMPORT_STATUSES = {
    ImportStatus.COMMITTED,
    ImportStatus.ROLLED_BACK,
    ImportStatus.DISCARDED,
    ImportStatus.FAILED,
}


class InvalidExport(FinboardError):
    code = "invalid_export"
    title = "Not a valid Finboard export"


# ---------------------------------------------------------------- (de)serialisation


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str | dict | list):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"can't export {type(value).__name__}")


def _decoder(column: Any) -> Callable[[Any], Any]:
    """A function turning the JSON form of `column` back into a Python value, strictly."""
    kind = column.type

    def check(value: Any, types: type | tuple[type, ...]) -> Any:
        if value is None:
            if not column.nullable and column.server_default is None:
                raise ValueError("null")
            return None
        if not isinstance(value, types) or (isinstance(value, bool) and types is not bool):
            raise ValueError(type(value).__name__)
        return value

    if isinstance(kind, Uuid):
        return lambda v: None if check(v, str) is None else uuid.UUID(v)
    if isinstance(kind, Numeric) and not isinstance(kind, Float):
        return lambda v: None if check(v, str) is None else Decimal(v)
    if isinstance(kind, DateTime):
        return lambda v: None if check(v, str) is None else datetime.fromisoformat(v)
    if isinstance(kind, Date):
        return lambda v: None if check(v, str) is None else date.fromisoformat(v)
    if isinstance(kind, Boolean):
        return lambda v: check(v, bool)
    if isinstance(kind, Float):
        return lambda v: None if check(v, (int, float)) is None else float(v)
    if isinstance(kind, Integer):
        return lambda v: check(v, int)
    if isinstance(kind, JSONB):  # any JSON value (a setting can be "dark" or 2)
        return lambda v: v if v is not None else check(v, dict)
    enum_class = getattr(kind, "enum_class", None)
    if enum_class is not None:
        return lambda v: None if check(v, str) is None else enum_class(v)
    if isinstance(kind, String | Text | CITEXT):
        length = getattr(kind, "length", None)

        def text(v: Any) -> Any:
            value = check(v, str)
            if value is not None and length is not None and len(value) > length:
                raise ValueError("too long")
            return value

        return text
    raise TypeError(f"no decoder for {column.name}")


def _columns(model: type[Base]) -> list[Any]:
    return [c for c in model.__table__.columns if c.name != "user_id"]


def _decode_rows(name: str, model: type[Base], rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        raise InvalidExport(f"'{name}' must be a list")
    columns = {c.name: (_decoder(c), c) for c in _columns(model)}
    decoded = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != set(columns):
            raise InvalidExport(f"{name}[{index}] doesn't have this version's columns")
        out = {}
        for key, (decode, _column) in columns.items():
            try:
                out[key] = decode(row[key])
            except (ValueError, TypeError, InvalidOperation):
                raise InvalidExport(f"{name}[{index}].{key} is not valid") from None
        decoded.append(out)
    return decoded


def _canonical(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        [{k: _encode(v) for k, v in row.items()} for row in rows],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def table_checksum(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical(rows)).hexdigest()


# ---------------------------------------------------------------- zip validation (§13)


@dataclass(frozen=True, slots=True)
class ExportContents:
    manifest: dict[str, Any]
    tables: dict[str, list[dict[str, Any]]]
    pdfs: dict[uuid.UUID, bytes]


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """Read a member without trusting its header: stop as soon as it grows past `limit`."""
    if info.file_size > limit:
        raise InvalidExport(f"{info.filename} is too large")
    if (
        info.compress_size
        and info.file_size / info.compress_size > MAX_RATIO
        and info.file_size > 1 << 20
    ):
        raise InvalidExport(f"{info.filename} is compressed suspiciously well")
    out = bytearray()
    with archive.open(info) as handle:
        while chunk := handle.read(1 << 16):
            out += chunk
            if len(out) > limit:
                raise InvalidExport(f"{info.filename} is larger than it says")
    return bytes(out)


def read_export(data: bytes) -> ExportContents:
    """Validate an export zip completely, before anything is written (§13)."""
    if len(data) > MAX_ZIP_BYTES:
        raise InvalidExport("The export is too large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise InvalidExport("This isn't a zip file") from None
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise InvalidExport("The export has too many files")
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise InvalidExport("The export has duplicate files")
        pdf_infos: dict[uuid.UUID, zipfile.ZipInfo] = {}
        for info in infos:
            name = info.filename
            if info.is_dir() or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise InvalidExport(f"Unexpected entry {name[:80]!r}")  # directories, symlinks
            match = _PDF_MEMBER.match(name)
            if match:
                pdf_infos[uuid.UUID(match.group(1))] = info
            elif name not in ("manifest.json", "data.json"):
                raise InvalidExport(f"Unexpected file {name[:80]!r} in the export")
        if "manifest.json" not in names or "data.json" not in names:
            raise InvalidExport("The export is missing manifest.json or data.json")
        if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
            raise InvalidExport("The export is too large once unpacked")

        try:
            manifest = json.loads(_read_member(archive, archive.getinfo("manifest.json"), 1 << 20))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise InvalidExport("manifest.json is not valid JSON") from None
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise InvalidExport("This isn't a Finboard export")
        version = manifest.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise InvalidExport("The export has no valid version")
        if version > VERSION:
            raise InvalidExport(
                f"This export is from a newer Finboard (format {version}); update Finboard first"
            )
        checksums = manifest.get("checksums")
        files = manifest.get("files")
        if not isinstance(checksums, dict) or not isinstance(files, dict):
            raise InvalidExport("manifest.json is incomplete")

        raw = _read_member(archive, archive.getinfo("data.json"), MAX_DATA_JSON_BYTES)
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise InvalidExport("data.json is not valid JSON") from None
        if not isinstance(payload, dict) or set(payload) != {name for name, _ in TABLES}:
            raise InvalidExport("data.json doesn't have this version's tables")
        tables = {name: _decode_rows(name, model, payload[name]) for name, model in TABLES}
        for name, rows in tables.items():
            if checksums.get(name) != table_checksum(rows):
                raise InvalidExport(f"The checksum of '{name}' doesn't match")

        pdfs = {}
        for import_id, info in pdf_infos.items():
            content = _read_member(archive, info, MAX_PDF_BYTES)
            if files.get(info.filename) != hashlib.sha256(content).hexdigest():
                raise InvalidExport(f"The checksum of {info.filename} doesn't match")
            pdfs[import_id] = content
        if set(files) != {i.filename for i in pdf_infos.values()}:
            raise InvalidExport("The export's files don't match its manifest")
    imports = {row["id"] for row in tables["imports"]}
    if not set(pdfs) <= imports:
        raise InvalidExport("The export has a statement file for an unknown import")
    return ExportContents(manifest, tables, pdfs)


# ---------------------------------------------------------------- the service


@dataclass(frozen=True, slots=True)
class ExportFile:
    data: bytes
    file_name: str


def _now() -> datetime:
    return datetime.now(UTC)


class DataService:
    def __init__(self, uow: UnitOfWork, queue: JobQueue, blobs: BlobStore) -> None:
        self.uow = uow
        self.blobs = blobs
        self.jobs = JobService(uow, queue)

    # ------------------------------------------------------------ export

    async def start_export(self) -> Job:
        return await self.jobs.submit(EXPORT_TASK)

    async def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Every exported row of the user, keyed by table (the dataset an export holds)."""
        tables = {name: await self.uow.data.dump(model) for name, model in TABLES}
        tables["imports"] = [
            {**row, "job_id": None, "blob_key": None}
            for row in tables["imports"]
            if row["status"] in EXPORTED_IMPORT_STATUSES
        ]
        kept = {row["id"] for row in tables["imports"]}
        tables["transactions"] = [
            {**row, "import_id": row["import_id"] if row["import_id"] in kept else None}
            for row in tables["transactions"]
        ]
        tables["import_rows"] = [r for r in tables["import_rows"] if r["import_id"] in kept]
        return tables

    async def run_export(self, job: Job) -> dict[str, Any]:
        tables = await self.snapshot()
        blob_keys = {
            row["id"]: row["blob_key"]
            for row in await self.uow.data.dump(ImportBatch)
            if row["blob_key"]
        }
        pdfs: dict[str, bytes] = {}
        for row in tables["imports"]:
            key = blob_keys.get(row["id"])
            if key and row["archived"]:
                try:
                    pdfs[f"pdfs/{row['id']}.pdf"] = await self.blobs.get(key)
                except BlobNotFound:
                    log.warning("data.export_blob_missing", import_id=str(row["id"]))
        manifest = {
            "format": FORMAT,
            "version": VERSION,
            "app_version": __version__,
            "exported_at": _now().isoformat(),
            "counts": {name: len(rows) for name, rows in tables.items()},
            "checksums": {name: table_checksum(rows) for name, rows in tables.items()},
            "files": {name: hashlib.sha256(content).hexdigest() for name, content in pdfs.items()},
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr(
                "data.json",
                json.dumps(
                    {
                        name: [{k: _encode(v) for k, v in row.items()} for row in rows]
                        for name, rows in tables.items()
                    },
                    ensure_ascii=False,
                ),
            )
            for name, content in pdfs.items():
                archive.writestr(name, content, compress_type=zipfile.ZIP_STORED)
        data = buffer.getvalue()
        await self.blobs.put(export_blob_key(self.uow.user_id, job.id), data)
        log.info("data.exported", size=len(data), files=len(pdfs))
        return {"size": len(data), "counts": manifest["counts"], "files": len(pdfs)}

    async def download(self, job_id: uuid.UUID) -> ExportFile:
        job = await self.uow.jobs.get(job_id)
        if job is None or job.kind != EXPORT_TASK:
            raise NotFound("Export not found")
        if job.status.value != "succeeded":
            raise Conflict("The export isn't ready yet")
        try:
            data = await self.blobs.get(export_blob_key(self.uow.user_id, job.id))
        except BlobNotFound:
            raise NotFound("This export has expired; make a new one") from None
        stamp = (job.finished_at or _now()).strftime("%Y%m%d-%H%M")
        return ExportFile(data, f"finboard-export-{stamp}.zip")

    # ------------------------------------------------------------ import

    async def start_import(self, data: bytes) -> Job:
        if len(data) > MAX_ZIP_BYTES:
            raise ValidationFailed("The export is too large")
        if await self.uow.data.has_financial_data():
            raise Conflict(
                "Import only goes into an empty Finboard. Delete all data first (Settings > Data)."
            )
        job = await self.jobs.create(IMPORT_TASK)
        await self.blobs.put(data_import_blob_key(self.uow.user_id, job.id), data)
        await self.jobs.dispatch(job)
        return job

    async def run_import(self, job: Job) -> dict[str, Any]:
        key = data_import_blob_key(self.uow.user_id, job.id)
        try:
            data = await self.blobs.get(key)
        except BlobNotFound:
            raise InvalidExport(
                "The uploaded export is no longer available; upload it again"
            ) from None
        try:
            contents = read_export(data)
            if await self.uow.data.has_financial_data():
                raise Conflict("Import only goes into an empty Finboard")
            await self._replace_with(contents)
        finally:
            await self.blobs.delete(key)
        counts = {name: len(rows) for name, rows in contents.tables.items()}
        log.info(
            "data.imported", files=len(contents.pdfs), **{f"n_{k}": v for k, v in counts.items()}
        )
        return {"counts": counts, "files": len(contents.pdfs)}

    async def _replace_with(self, contents: ExportContents) -> None:
        user = self.uow.user_id
        for _name, model in reversed(TABLES):  # the defaults this user was given
            await self.uow.data.delete(model)
        tables = dict(contents.tables)
        # Blob keys name the user: point them at this user's copies of the statement files.
        tables["imports"] = [
            {
                **row,
                "blob_key": import_blob_key(user, row["id"])
                if row["id"] in contents.pdfs
                else None,
            }
            for row in tables["imports"]
        ]
        # Categories reference their parent: insert top-level ones first.
        tables["categories"] = sorted(
            tables["categories"], key=lambda r: r["parent_id"] is not None
        )
        try:
            for name, model in TABLES:
                await self.uow.data.insert(model, tables[name])
            await self.uow.session.flush()
        except IntegrityError:
            raise Conflict(
                "This export's data already exists in this database (another user has it), "
                "or the export is inconsistent"
            ) from None
        for import_id, content in contents.pdfs.items():
            await self.blobs.put(import_blob_key(user, import_id), content)
        await self.uow.users.bump_data_version(user)

    # ------------------------------------------------------------ delete-all

    async def start_delete_all(self, confirm: str) -> Job:
        if confirm != DELETE_CONFIRMATION:
            raise ValidationFailed(f'Type "{DELETE_CONFIRMATION}" to confirm')
        return await self.jobs.submit(DELETE_TASK)

    async def run_delete_all(self, job: Job) -> dict[str, Any]:
        """Delete every row and file of this user (RLS and the user filter both apply), keep
        this job's own row, then give them the defaults again."""
        deleted = 0
        order: tuple[type[Base], ...] = (
            TransferPair, ImportRow, StagedRow, Txn, Rule, Budget, ImportBatch, Account,
            Category, UserSetting, UserParserSetting,
        )  # fmt: skip
        for model in order:  # children before parents
            deleted += await self.uow.data.delete(model)
        deleted += await self.uow.data.delete(Job, keep_ids=[job.id])
        await seed_defaults(self.uow)
        await self.uow.users.bump_data_version(self.uow.user_id)
        await self.uow.commit()
        files = await self.blobs.delete_prefix(user_prefix(self.uow.user_id))
        log.warning("data.deleted_all", rows=deleted, files=files)
        return {"rows": deleted, "files": files}

    # ------------------------------------------------------------ CSV

    async def transactions_csv(self) -> str:
        """Every transaction as CSV, for spreadsheets. Cells that a spreadsheet would run as a
        formula are prefixed with an apostrophe (CSV injection)."""
        accounts = {a.id: a.name for a in await self.uow.accounts.list()}
        categories = {c.id: c for c in await self.uow.categories.list()}

        def path(cid: uuid.UUID) -> str:
            c = categories.get(cid)
            if c is None:
                return ""
            parent = categories.get(c.parent_id) if c.parent_id else None
            return f"{parent.name} / {c.name}" if parent else c.name

        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(
            [
                "date",
                "description",
                "account",
                "category",
                "type",
                "direction",
                "amount",
                "needs_review",
                "notes",
            ]
        )
        for row in await self.uow.data.dump(Txn):
            writer.writerow(
                _safe_cell(v)
                for v in (
                    row["date"].isoformat(),
                    row["description_raw"],
                    accounts.get(row["account_id"], ""),
                    path(row["category_id"]),
                    row["type"].value,
                    row["direction"].value,
                    f"{row['amount']:.2f}",
                    "yes" if row["needs_review"] else "no",
                    row["notes"] or "",
                )
            )
        return out.getvalue()


def _safe_cell(value: str) -> str:
    return f"'{value}" if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def dataset_counts(tables: Mapping[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {name: len(rows) for name, rows in tables.items()}
