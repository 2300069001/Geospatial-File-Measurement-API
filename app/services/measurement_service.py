"""Area / length calculation. Geometry is always projected before measuring."""

import logging
import math

import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from app.core.exceptions import AppError
from app.domain.models import MeasurementResult, MeasurementStatus, MeasurementType
from app.services.crs_service import CRSService

logger = logging.getLogger(__name__)

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString"}
POINT_TYPES = {"Point", "MultiPoint"}

AREA_UNIT = "square_meters"
LENGTH_UNIT = "meters"


class MeasurementService:
    def __init__(self, crs_service: CRSService | None = None) -> None:
        self._crs = crs_service or CRSService()

    def measure(
        self,
        geometry: BaseGeometry | None,
        source_crs: CRS,
        geometry_error: str | None = None,
    ) -> MeasurementResult:
        if geometry_error is not None:
            return self._invalid("None", geometry_error)
        if geometry is None or geometry.is_empty:
            return self._invalid("None", "Feature has no geometry or the geometry is empty.")

        geometry_type = geometry.geom_type

        if geometry_type in POINT_TYPES:
            return MeasurementResult(
                geometry_type=geometry_type,
                measurement_type=MeasurementType.NONE,
                value=None,
                unit=None,
                supported=True,
                status=MeasurementStatus.NOT_APPLICABLE,
                message="No measurement is defined for point geometries.",
            )

        if geometry_type in AREA_TYPES:
            kind, unit = MeasurementType.AREA, AREA_UNIT
        elif geometry_type in LENGTH_TYPES:
            kind, unit = MeasurementType.LENGTH, LENGTH_UNIT
        else:
            return MeasurementResult(
                geometry_type=geometry_type,
                measurement_type=MeasurementType.NONE,
                value=None,
                unit=None,
                supported=False,
                status=MeasurementStatus.UNSUPPORTED_GEOMETRY,
                message=f"Geometry type '{geometry_type}' is not supported for measurement.",
            )

        coords_problem = self._coordinate_problem(geometry, source_crs)
        if coords_problem:
            return self._invalid(geometry_type, coords_problem)
        if not geometry.is_valid:
            return self._invalid(geometry_type, f"Invalid geometry: {explain_validity(geometry)}")

        try:
            flat = shapely.force_2d(geometry)
            plan = self._crs.plan(flat, source_crs, kind)
            projected = self._crs.project(flat, plan)
            raw = projected.area if kind is MeasurementType.AREA else projected.length
            factor = plan.unit_factor ** (2 if kind is MeasurementType.AREA else 1)
            value = raw * factor
            if not math.isfinite(value):
                raise ValueError("non-finite measurement")
        except AppError as exc:
            return self._failed(geometry_type, kind, exc.message)
        except Exception:  # noqa: BLE001 - never let one feature break the whole file
            logger.exception("Measurement failed for %s", geometry_type)
            return self._failed(geometry_type, kind, "The measurement could not be computed.")

        return MeasurementResult(
            geometry_type=geometry_type,
            measurement_type=kind,
            value=round(value, 4),
            unit=unit,
            supported=True,
            status=MeasurementStatus.MEASURED,
            calculation_crs=plan.label,
        )

    # -- helpers -----------------------------------------------------------------------------

    def _coordinate_problem(self, geometry: BaseGeometry, crs: CRS) -> str | None:
        minx, miny, maxx, maxy = geometry.bounds
        if not all(math.isfinite(v) for v in (minx, miny, maxx, maxy)):
            return "Geometry contains non-finite coordinates."
        if self._crs.is_geographic(crs) and (
            minx < -180 or maxx > 180 or miny < -90 or maxy > 90
        ):
            return "Coordinates are outside the valid longitude/latitude range."
        return None

    @staticmethod
    def _invalid(geometry_type: str, message: str) -> MeasurementResult:
        return MeasurementResult(
            geometry_type=geometry_type,
            measurement_type=MeasurementType.NONE,
            value=None,
            unit=None,
            supported=False,
            status=MeasurementStatus.INVALID_GEOMETRY,
            message=message,
        )

    @staticmethod
    def _failed(geometry_type: str, kind: MeasurementType, message: str) -> MeasurementResult:
        return MeasurementResult(
            geometry_type=geometry_type,
            measurement_type=kind,
            value=None,
            unit=None,
            supported=True,
            status=MeasurementStatus.MEASUREMENT_FAILED,
            message=message,
        )
