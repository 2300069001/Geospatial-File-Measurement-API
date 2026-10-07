"""CRS handling: choose a suitable projected CRS so areas/lengths are never computed on degrees."""

from dataclasses import dataclass
from functools import lru_cache

from pyproj import CRS, Transformer
from pyproj.crs import ProjectedCRS
from pyproj.crs.coordinate_operation import (
    AzimuthalEquidistantConversion,
    LambertAzimuthalEqualAreaConversion,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from app.core.exceptions import UnsupportedCRSError
from app.domain.models import MeasurementType

WGS84 = CRS.from_epsg(4326)
UTM_ZONE_WIDTH_DEG = 6
NORTH_POLE_LAT = 84.0
SOUTH_POLE_LAT = -80.0


@dataclass(frozen=True)
class ProjectionPlan:
    """How a geometry must be projected before measuring."""

    source: CRS
    target: CRS
    label: str
    strategy: str  # SOURCE_PROJECTED | UTM | UPS | LAEA | AEQD
    unit_factor: float  # metres per target CRS linear unit


@lru_cache(maxsize=256)
def _transformer(source: CRS, target: CRS) -> Transformer:
    return Transformer.from_crs(source, target, always_xy=True)


def describe_crs(crs: CRS) -> str:
    epsg = crs.to_epsg()
    if epsg:
        return f"EPSG:{epsg}"
    authority = crs.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.name


def utm_zone(lon: float) -> int:
    return min(int((lon + 180.0) // UTM_ZONE_WIDTH_DEG) + 1, 60)


class CRSService:
    def plan(
        self, geometry: BaseGeometry, source: CRS, measurement_type: MeasurementType
    ) -> ProjectionPlan:
        """Choose the projected CRS in which `geometry` should be measured."""
        base = self._horizontal(source)

        if base.is_projected and not self._is_mercator(base):
            return ProjectionPlan(
                source=base,
                target=base,
                label=describe_crs(base),
                strategy="SOURCE_PROJECTED",
                unit_factor=self._linear_unit_factor(base),
            )
        if not (base.is_projected or base.is_geographic):
            raise UnsupportedCRSError("The dataset CRS is neither geographic nor projected.")

        minx, miny, maxx, maxy = self._lonlat_bounds(geometry, base)
        return self._local_plan(base, minx, miny, maxx, maxy, measurement_type)

    def project(self, geometry: BaseGeometry, plan: ProjectionPlan) -> BaseGeometry:
        if plan.source == plan.target:
            return geometry
        transformer = _transformer(plan.source, plan.target)
        return shapely_transform(transformer.transform, geometry)

    @staticmethod
    def is_geographic(crs: CRS) -> bool:
        return CRSService._horizontal(crs).is_geographic

    # -- internals ---------------------------------------------------------------------------

    @staticmethod
    def _horizontal(crs: CRS) -> CRS:
        if crs.is_compound and crs.sub_crs_list:
            return crs.sub_crs_list[0]
        return crs

    @staticmethod
    def _is_mercator(crs: CRS) -> bool:
        """Mercator variants (incl. Web Mercator) hugely distort area; never measure in them."""
        operation = crs.coordinate_operation
        if operation is None:
            return False
        method = operation.method_name.lower()
        return "mercator" in method and "transverse" not in method and "oblique" not in method

    @staticmethod
    def _linear_unit_factor(crs: CRS) -> float:
        try:
            return float(crs.axis_info[0].unit_conversion_factor) or 1.0
        except (IndexError, AttributeError):
            return 1.0

    def _lonlat_bounds(
        self, geometry: BaseGeometry, base: CRS
    ) -> tuple[float, float, float, float]:
        if base.is_geographic:
            if base.axis_info and base.axis_info[0].unit_name != "degree":
                raise UnsupportedCRSError("Geographic CRS with non-degree units is not supported.")
            return geometry.bounds
        return shapely_transform(_transformer(base, WGS84).transform, geometry).bounds

    def _local_plan(
        self,
        base: CRS,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
        measurement_type: MeasurementType,
    ) -> ProjectionPlan:
        center_lat = (miny + maxy) / 2.0
        center_lon = (minx + maxx) / 2.0
        if maxx - minx > 180.0:  # geometry crosses the antimeridian
            center_lon = (center_lon + 360.0) % 360.0 - 180.0

        if center_lat >= NORTH_POLE_LAT or center_lat <= SOUTH_POLE_LAT:
            epsg = 5041 if center_lat > 0 else 5042  # Universal Polar Stereographic
            return self._plan_from_crs(base, CRS.from_epsg(epsg), "UPS")

        if utm_zone(minx) == utm_zone(maxx):
            zone = utm_zone(center_lon)
            epsg = (32600 if center_lat >= 0 else 32700) + zone
            return self._plan_from_crs(base, CRS.from_epsg(epsg), "UTM")

        # Spans several UTM zones: use a custom projection centred on the geometry.
        lat0, lon0 = round(center_lat, 2), round(center_lon, 2)
        if measurement_type is MeasurementType.AREA:
            conversion = LambertAzimuthalEqualAreaConversion(lat0, lon0)
            strategy = "LAEA"
        else:
            conversion = AzimuthalEquidistantConversion(lat0, lon0)
            strategy = "AEQD"
        target = ProjectedCRS(conversion=conversion, geodetic_crs=WGS84, name=f"Custom {strategy}")
        return ProjectionPlan(
            source=base,
            target=target,
            label=f"{strategy}(lat_0={lat0}, lon_0={lon0})",
            strategy=strategy,
            unit_factor=1.0,
        )

    @staticmethod
    def _plan_from_crs(base: CRS, target: CRS, strategy: str) -> ProjectionPlan:
        return ProjectionPlan(
            source=base,
            target=target,
            label=describe_crs(target),
            strategy=strategy,
            unit_factor=1.0,
        )
