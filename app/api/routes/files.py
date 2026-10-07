from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status

from app.api.deps import get_file_service
from app.schemas.file import (
    ErrorResponse,
    FileResponse,
    MeasurementItem,
    MeasurementListResponse,
)
from app.services.file_service import FileService

router = APIRouter(prefix="/api/files", tags=["files"])

ServiceDep = Annotated[FileService, Depends(get_file_service)]

_errors = {
    400: {"model": ErrorResponse, "description": "Empty file"},
    413: {"model": ErrorResponse, "description": "File too large"},
    415: {"model": ErrorResponse, "description": "Unsupported file type"},
    422: {"model": ErrorResponse, "description": "Invalid or unprocessable file"},
}


@router.post(
    "/",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and process a KML file or a ZIP containing a Shapefile",
    responses=_errors,
)
async def upload_file(
    service: ServiceDep, file: Annotated[UploadFile, File(description=".kml or .zip file")]
) -> FileResponse:
    return FileResponse.model_validate(vars(await service.create_from_upload(file)))


@router.get(
    "/{file_id}/",
    response_model=FileResponse,
    summary="Get information about an uploaded file",
    responses={404: {"model": ErrorResponse}},
)
def get_file(file_id: str, service: ServiceDep) -> FileResponse:
    return FileResponse.model_validate(vars(service.get_file(file_id)))


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementListResponse,
    summary="Get per-feature measurements",
    responses={404: {"model": ErrorResponse}},
)
def get_measurements(
    file_id: str,
    service: ServiceDep,
    request: Request,
    limit: Annotated[int | None, Query(ge=1, description="Page size")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_geometry: Annotated[bool, Query(description="Include GeoJSON geometry")] = False,
) -> MeasurementListResponse:
    settings = request.app.state.settings
    limit = min(limit or settings.default_page_size, settings.max_page_size)
    record, features = service.get_measurements(file_id, limit, offset)
    items = [
        MeasurementItem(
            feature_id=f.feature_id,
            geometry_type=f.geometry_type,
            crs=record.crs,
            measurement_type=f.measurement.measurement_type,
            value=f.measurement.value,
            unit=f.measurement.unit,
            supported=f.measurement.supported,
            status=f.measurement.status,
            message=f.measurement.message,
            calculation_crs=f.measurement.calculation_crs,
            properties=f.properties,
            geometry=f.geometry if include_geometry else None,
        )
        for f in features
    ]
    return MeasurementListResponse(
        file_id=record.id,
        crs=record.crs,
        total=record.feature_count,
        limit=limit,
        offset=offset,
        measurements=items,
    )
