import pytest
from pyproj import CRS, Geod
from shapely.geometry import LineString, Polygon

from app.core.exceptions import UnsupportedCRSError
from app.domain.models import MeasurementStatus, MeasurementType
from app.services.crs_service import CRSService, describe_crs, utm_zone
from app.services.measurement_service import MeasurementService

WGS84 = CRS.from_epsg(4326)
GEOD = Geod(ellps="WGS84")
crs_service = CRSService()
LOCAL_CRS = CRS.from_wkt(
    'ENGCRS["local",EDATUM["x"],CS[Cartesian,2],AXIS["x",east],AXIS["y",north],UNIT["metre",1]]'
)


def square(lon, lat, size=0.01):
    return Polygon([(lon, lat), (lon + size, lat), (lon + size, lat + size), (lon, lat + size)])


@pytest.mark.parametrize(
    "lon,lat,epsg",
    [
        (77.0, 12.0, 32643),
        (-122.4, 37.7, 32610),
        (151.2, -33.9, 32756),
        (0.5, 51.5, 32631),
        (-179.99, 10.0, 32601),
        (179.98, 10.0, 32660),
    ],
)
def test_utm_selection(lon, lat, epsg):
    plan = crs_service.plan(square(lon, lat, 0.001), WGS84, MeasurementType.AREA)
    assert plan.strategy == "UTM" and plan.target.to_epsg() == epsg
    assert plan.unit_factor == 1.0


def test_utm_zone_edges():
    assert utm_zone(-180) == 1 and utm_zone(180) == 60 and utm_zone(0) == 31


def test_polar_uses_ups():
    assert crs_service.plan(square(10, 87), WGS84, MeasurementType.AREA).target.to_epsg() == 5041
    assert crs_service.plan(square(10, -85), WGS84, MeasurementType.AREA).target.to_epsg() == 5042


def test_multi_zone_area_uses_equal_area_projection():
    big = Polygon([(70, 10), (90, 10), (90, 20), (70, 20)])
    plan = crs_service.plan(big, WGS84, MeasurementType.AREA)
    assert plan.strategy == "LAEA" and plan.target.is_projected


def test_multi_zone_length_uses_equidistant_projection():
    plan = crs_service.plan(LineString([(70, 10), (90, 20)]), WGS84, MeasurementType.LENGTH)
    assert plan.strategy == "AEQD"


def test_multi_zone_area_accuracy():
    big = Polygon([(70, 10), (90, 10), (90, 20), (70, 20)])
    result = MeasurementService(crs_service).measure(big, WGS84)
    expected = abs(GEOD.geometry_area_perimeter(big)[0])
    # Edges of a 2000 km polygon are straight in the projection but geodesic in Geod, so a
    # ~1% difference is inherent to the edge interpretation, not to the equal-area property.
    assert result.value == pytest.approx(expected, rel=0.02)


def test_antimeridian_crossing_geometry_is_centered_on_the_date_line():
    line = LineString([(179.5, 10), (-179.5, 10)])
    plan = crs_service.plan(line, WGS84, MeasurementType.LENGTH)
    assert plan.strategy == "AEQD"
    assert "lon_0=180.0" in plan.label or "lon_0=-180.0" in plan.label
    # The line is ~109.6 km long (1 degree of longitude at 10N), not ~39,000 km.
    result = MeasurementService(crs_service).measure(line, WGS84)
    assert result.value == pytest.approx(109_600, rel=0.01)


def test_projected_source_is_used_directly_with_unit_conversion():
    feet_crs = CRS.from_epsg(2263)  # NY Long Island, US survey feet
    geom = square(1000000, 200000, 100)
    plan = crs_service.plan(geom, feet_crs, MeasurementType.AREA)
    assert plan.strategy == "SOURCE_PROJECTED"
    assert plan.unit_factor == pytest.approx(0.3048006, rel=1e-5)
    result = MeasurementService(crs_service).measure(geom, feet_crs)
    assert result.value == pytest.approx(100 * 100 * 0.3048006**2, rel=1e-4)


def test_web_mercator_is_not_used_for_measuring():
    geom = square(1_113_194, 5_621_521, 100)
    plan = crs_service.plan(geom, CRS.from_epsg(3857), MeasurementType.AREA)
    assert plan.strategy == "UTM"


def test_transverse_mercator_is_accepted_as_is():
    plan = crs_service.plan(square(500000, 1000000, 100), CRS.from_epsg(32643), MeasurementType.AREA)
    assert plan.strategy == "SOURCE_PROJECTED"


def test_non_geographic_non_projected_crs_rejected():
    with pytest.raises(UnsupportedCRSError):
        crs_service.plan(square(0, 0), LOCAL_CRS, MeasurementType.AREA)


def test_local_crs_measurement_reports_failure_not_crash():
    result = MeasurementService(crs_service).measure(square(0, 0), LOCAL_CRS)
    assert result.status is MeasurementStatus.MEASUREMENT_FAILED


def test_describe_crs():
    assert describe_crs(WGS84) == "EPSG:4326"
    assert describe_crs(CRS.from_epsg(32643)) == "EPSG:32643"
