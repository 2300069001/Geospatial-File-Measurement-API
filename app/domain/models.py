"""Framework-independent domain models shared by services, repository and schemas."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from shapely.geometry.base import BaseGeometry


class FileType(str, Enum):
    KML = "KML"
    SHAPEFILE = "SHAPEFILE"


class FileStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeasurementType(str, Enum):
    AREA = "AREA"
    LENGTH = "LENGTH"
    NONE = "NONE"


class MeasurementStatus(str, Enum):
    MEASURED = "MEASURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"  # e.g. points: nothing to measure
    UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    MEASUREMENT_FAILED = "MEASUREMENT_FAILED"


@dataclass(frozen=True)
class ParsedFeature:
    """A feature as read from a source file, before any measurement."""

    index: int
    geometry: BaseGeometry | None
    properties: dict[str, Any] = field(default_factory=dict)
    geometry_error: str | None = None


@dataclass(frozen=True)
class MeasurementResult:
    geometry_type: str
    measurement_type: MeasurementType
    value: float | None
    unit: str | None
    supported: bool
    status: MeasurementStatus
    message: str | None = None
    calculation_crs: str | None = None


@dataclass(frozen=True)
class FeatureRecord:
    feature_id: int
    geometry_type: str
    geometry: dict[str, Any] | None
    properties: dict[str, Any]
    measurement: MeasurementResult


@dataclass(frozen=True)
class FileRecord:
    id: str
    filename: str
    file_type: FileType
    size_bytes: int
    feature_count: int
    crs: str
    status: FileStatus
    created_at: datetime
    geometry_summary: dict[str, int]
