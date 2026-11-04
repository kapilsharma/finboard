import uuid

from fastapi import APIRouter, Request, Response, status
from starlette.datastructures import UploadFile

from finboard.api.deps import DataServiceDep
from finboard.api.routers.imports import _UPLOAD_BODY, MULTIPART_OVERHEAD
from finboard.api.schemas import DeleteAllIn, JobAccepted, JobOut
from finboard.domain.errors import PayloadTooLarge, ValidationFailed
from finboard.services.data import MAX_ZIP_BYTES

router = APIRouter(prefix="/data", tags=["data"])


@router.post("/export", status_code=status.HTTP_202_ACCEPTED)
async def start_export(service: DataServiceDep) -> JobAccepted:
    """Export all your data (JSON + archived statements, as one zip) in the background.
    Download it from `/data/exports/{job_id}` when the job has succeeded."""
    return JobAccepted(job=JobOut.model_validate(await service.start_export()))


@router.get(
    "/exports/{job_id}",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
async def download_export(job_id: uuid.UUID, service: DataServiceDep) -> Response:
    export = await service.download(job_id)
    return Response(
        export.data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{export.file_name}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/import", status_code=status.HTTP_202_ACCEPTED, openapi_extra=_UPLOAD_BODY)
async def start_import(request: Request, service: DataServiceDep) -> JobAccepted:
    """Load a Finboard export (multipart field `file`) into this Finboard, which must have no
    accounts, transactions or imports yet. The zip is checked completely before anything is
    written."""
    length = request.headers.get("content-length")
    if length is None or not length.isdigit():
        raise ValidationFailed("The upload needs a Content-Length")
    if int(length) > MAX_ZIP_BYTES + MULTIPART_OVERHEAD:
        raise PayloadTooLarge("Exports can be at most 512 MB")
    form = await request.form(max_files=1, max_fields=1, max_part_size=MAX_ZIP_BYTES)
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise ValidationFailed("Attach the export as the multipart field 'file'")
    data = await upload.read()
    await form.close()
    return JobAccepted(job=JobOut.model_validate(await service.start_import(data)))


@router.get(
    "/transactions.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def transactions_csv(service: DataServiceDep) -> Response:
    return Response(
        await service.transactions_csv(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="finboard-transactions.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/delete-all", status_code=status.HTTP_202_ACCEPTED)
async def delete_all(body: DeleteAllIn, service: DataServiceDep) -> JobAccepted:
    """Delete all your data and files (not other users'). Send `{"confirm": "DELETE ALL"}`."""
    return JobAccepted(job=JobOut.model_validate(await service.start_delete_all(body.confirm)))
