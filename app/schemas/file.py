"""Pydantic response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import FileStatus, FileType, MeasurementStatus, MeasurementType


class FileResponse(BaseModel):
    id: str = Field(examples=["3f2a9c1d5e7b4a60b8c1d2e3f4a5b6c7"])
    filename: str = Field(examples=["survey.kml"])
    file_type: FileType
    size_bytes: int
    feature_count: int
    crs: str = Field(examples=["EPSG:4326"])
    status: FileStatus
    created_at: datetime
    geometry_summary: dict[str, int] = Field(
        description="Number of features per geometry type.", examples=[{"Polygon": 3, "Point": 1}]
    )


class MeasurementItem(BaseModel):
    feature_id: int = Field(description="Zero-based index of the feature in the source file.")
    geometry_type: str
    crs: str = Field(description="CRS of the source geometry.")
    measurement_type: MeasurementType
    value: float | None = None
    unit: str | None = Field(default=None, examples=["square_meters", "meters"])
    supported: bool = Field(description="False when the geometry cannot be measured.")
    status: MeasurementStatus
    message: str | None = None
    calculation_crs: str | None = Field(
        default=None, description="Projected CRS used for the calculation."
    )
    properties: dict[str, Any]
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON geometry in the source CRS (only if include_geometry=true)."
    )


class MeasurementListResponse(BaseModel):
    file_id: str
    crs: str
    total: int
    limit: int
    offset: int
    measurements: list[MeasurementItem]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
