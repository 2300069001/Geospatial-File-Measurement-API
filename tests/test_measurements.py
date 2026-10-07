import geopandas as gpd
import pytest
from pyproj import CRS, Geod
from shapely.geometry import (
    GeometryCollection,
    LinearRing,
    LineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from app.domain.models import MeasurementStatus, MeasurementType
from app.services.measurement_service import MeasurementService
from tests.conftest import (
    LINE_COORDS,
    SQUARE_COORDS,
    make_kml,
    placemark,
    polygon_kml,
    upload,
    write_shapefile_zip,
)

GEOD = Geod(ellps="WGS84")


def measurements(client, file_id, **params):
    r = client.get(f"/api/files/{file_id}/measurements/", params=params)
    assert r.status_code == 200
    return r.json()


def items_for(client, kml: bytes) -> list[dict]:
    return measurements(client, upload(client, "x.kml", kml).json()["id"])["measurements"]


def test_kml_measurements_end_to_end(client):
    extended = "<ExtendedData><Data name='owner'><value>Asha</value></Data></ExtendedData>"
    kml = make_kml(
        placemark("Plot A", polygon_kml(SQUARE_COORDS), extended),
        placemark("Road", f"<LineString><coordinates>{LINE_COORDS}</coordinates></LineString>"),
        placemark("Well", "<Point><coordinates>77.0,12.0,0</coordinates></Point>"),
    )
    file_id = upload(client, "s.kml", kml).json()["id"]
    body = measurements(client, file_id)

    assert body["total"] == 3 and body["crs"] == "EPSG:4326"
    area, line, point = body["measurements"]

    ring = Polygon([(77, 12), (77.01, 12), (77.01, 12.01), (77, 12.01)])
    expected_area = abs(GEOD.geometry_area_perimeter(ring)[0])
    assert area["feature_id"] == 0 and area["geometry_type"] == "Polygon"
    assert area["measurement_type"] == "AREA" and area["unit"] == "square_meters"
    assert area["status"] == "MEASURED" and area["supported"] is True
    assert area["value"] == pytest.approx(expected_area, rel=0.005)
    assert area["calculation_crs"] == "EPSG:32643"
    assert area["properties"] == {"name": "Plot A", "owner": "Asha"}
    assert area["geometry"] is None

    expected_len = GEOD.geometry_length(LineString([(77, 12), (77, 13)]))
    assert line["measurement_type"] == "LENGTH" and line["unit"] == "meters"
    assert line["value"] == pytest.approx(expected_len, rel=0.005)

    assert point["measurement_type"] == "NONE" and point["value"] is None
    assert point["status"] == "NOT_APPLICABLE" and point["supported"] is True


def test_area_is_not_computed_in_degrees(client):
    kml = make_kml(placemark("A", polygon_kml(SQUARE_COORDS)))
    value = items_for(client, kml)[0]["value"]
    assert value > 1_000_000  # ~1.2 km², not 0.0001 "square degrees"


def test_include_geometry_and_pagination(client):
    kml = make_kml(
        *[placemark(f"P{i}", f"<Point><coordinates>77,{12 + i / 10}</coordinates></Point>") for i in range(5)]
    )
    file_id = upload(client, "pts.kml", kml).json()["id"]
    body = measurements(client, file_id, limit=2, offset=1, include_geometry="true")
    assert body["total"] == 5 and body["limit"] == 2 and body["offset"] == 1
    assert [m["feature_id"] for m in body["measurements"]] == [1, 2]
    assert body["measurements"][0]["geometry"]["type"] == "Point"


def test_invalid_pagination_params(client):
    kml = make_kml(placemark("P", "<Point><coordinates>1,1</coordinates></Point>"))
    file_id = upload(client, "pts.kml", kml).json()["id"]
    assert client.get(f"/api/files/{file_id}/measurements/?limit=0").status_code == 422
    assert client.get(f"/api/files/{file_id}/measurements/?offset=-1").status_code == 422


def test_shapefile_polygon_measurements_geographic(client, shapefile_zip):
    file_id = upload(client, "l.zip", shapefile_zip().read_bytes()).json()["id"]
    first, second = measurements(client, file_id)["measurements"]
    assert first["status"] == "MEASURED" and first["value"] == pytest.approx(1.2e6, rel=0.05)
    assert first["calculation_crs"] == "EPSG:32643"
    assert second["calculation_crs"] == "EPSG:32644"  # 78E is the first meridian of zone 44
    assert first["properties"] == {"name": "f0"}


def test_shapefile_line_length_geographic(client, shapefile_zip):
    z = shapefile_zip([LineString([(77, 12), (77, 13)])])
    item = measurements(client, upload(client, "l.zip", z.read_bytes()).json()["id"])["measurements"][0]
    assert item["measurement_type"] == "LENGTH"
    assert item["value"] == pytest.approx(GEOD.geometry_length(LineString([(77, 12), (77, 13)])), rel=0.005)


def test_shapefile_points_have_no_measurement(client, shapefile_zip):
    z = shapefile_zip([Point(77, 12), Point(78, 13)])
    items = measurements(client, upload(client, "p.zip", z.read_bytes()).json()["id"])["measurements"]
    assert [i["status"] for i in items] == ["NOT_APPLICABLE", "NOT_APPLICABLE"]
    assert all(i["value"] is None for i in items)


def test_shapefile_in_projected_crs_uses_native_units(client, tmp_path):
    square = Polygon([(500000, 1000000), (500100, 1000000), (500100, 1000100), (500000, 1000100)])
    z = write_shapefile_zip(tmp_path, [square], crs="EPSG:32643")
    file_id = upload(client, "utm.zip", z.read_bytes()).json()["id"]
    item = measurements(client, file_id)["measurements"][0]
    assert item["crs"] == "EPSG:32643"
    assert item["value"] == pytest.approx(10_000.0)
    assert item["calculation_crs"] == "EPSG:32643"


def test_web_mercator_input_is_reprojected_for_measuring(client, tmp_path):
    # EPSG:3857 inflates area by ~1/cos(lat)^2 (x2 at 45N), so it must not be measured directly.
    geo_square = Polygon([(10, 45), (10.001, 45), (10.001, 45.001), (10, 45.001)])
    merc = gpd.GeoSeries([geo_square], crs="EPSG:4326").to_crs("EPSG:3857").iloc[0]
    z = write_shapefile_zip(tmp_path, [merc], crs="EPSG:3857")
    item = measurements(client, upload(client, "m.zip", z.read_bytes()).json()["id"])["measurements"][0]
    expected = abs(GEOD.geometry_area_perimeter(geo_square)[0])
    assert item["value"] == pytest.approx(expected, rel=0.005)
    assert item["calculation_crs"] == "EPSG:32632"


def test_invalid_polygon_in_kml_is_flagged_not_fatal(client):
    bowtie = polygon_kml("77,12,0 77.01,12.01,0 77.01,12,0 77,12.01,0 77,12,0")
    kml = make_kml(placemark("bad", bowtie), placemark("good", polygon_kml(SQUARE_COORDS)))
    items = items_for(client, kml)
    assert items[0]["status"] == "INVALID_GEOMETRY" and items[0]["supported"] is False
    assert items[0]["value"] is None and "self-intersection" in items[0]["message"].lower()
    assert items[1]["status"] == "MEASURED"


def test_malformed_coordinates_flag_feature_only(client):
    kml = make_kml(
        placemark("bad", "<Point><coordinates>abc,def</coordinates></Point>"),
        placemark("ok", "<Point><coordinates>1,1</coordinates></Point>"),
    )
    items = items_for(client, kml)
    assert items[0]["status"] == "INVALID_GEOMETRY"
    assert items[1]["status"] == "NOT_APPLICABLE"


def test_placemark_without_geometry(client):
    kml = make_kml(placemark("nothing", ""), placemark("ok", "<Point><coordinates>1,1</coordinates></Point>"))
    items = items_for(client, kml)
    assert items[0]["status"] == "INVALID_GEOMETRY" and items[0]["geometry_type"] == "None"


def test_mixed_multigeometry_is_unsupported(client):
    multi = f"<MultiGeometry><Point><coordinates>77,12</coordinates></Point>{polygon_kml(SQUARE_COORDS)}</MultiGeometry>"
    items = items_for(client, make_kml(placemark("mix", multi)))
    assert items[0]["geometry_type"] == "GeometryCollection"
    assert items[0]["status"] == "UNSUPPORTED_GEOMETRY" and items[0]["supported"] is False


def test_multipolygon_kml_area_is_summed(client):
    second = polygon_kml("78,12 78.01,12 78.01,12.01 78,12.01 78,12")
    multi = f"<MultiGeometry>{polygon_kml(SQUARE_COORDS)}{second}</MultiGeometry>"
    multi_item = items_for(client, make_kml(placemark("mp", multi)))[0]
    single = items_for(client, make_kml(placemark("a", polygon_kml(SQUARE_COORDS))))[0]["value"]
    assert multi_item["geometry_type"] == "MultiPolygon"
    assert multi_item["value"] == pytest.approx(2 * single, rel=0.01)


def test_polygon_with_hole_subtracts_area(client):
    outer = "77,12 77.01,12 77.01,12.01 77,12.01 77,12"
    hole = "77.002,12.002 77.004,12.002 77.004,12.004 77.002,12.004 77.002,12.002"
    holed_poly = (
        f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{outer}</coordinates></LinearRing></outerBoundaryIs>"
        f"<innerBoundaryIs><LinearRing><coordinates>{hole}</coordinates></LinearRing></innerBoundaryIs></Polygon>"
    )
    full = items_for(client, make_kml(placemark("f", polygon_kml(outer))))[0]["value"]
    holed = items_for(client, make_kml(placemark("h", holed_poly)))[0]["value"]
    assert holed == pytest.approx(full * 0.96, rel=0.01)  # hole covers 4% of the outer square


def test_measurements_file_not_found(client):
    r = client.get("/api/files/doesnotexist/measurements/")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "FILE_NOT_FOUND", "message": "No file exists with the given id."}}


def test_get_file_not_found(client):
    r = client.get("/api/files/doesnotexist/")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_unknown_route_returns_json_404(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_openapi_and_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert "/api/files/" in client.get("/openapi.json").json()["paths"]


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# -- MeasurementService unit tests ---------------------------------------------------------------


@pytest.fixture
def service():
    return MeasurementService()


@pytest.fixture
def wgs84():
    return CRS.from_epsg(4326)


def test_unit_unsupported_types(service, wgs84):
    for geom in (GeometryCollection([Point(1, 1)]), LinearRing([(0, 0), (1, 0), (1, 1), (0, 0)])):
        result = service.measure(geom, wgs84)
        assert result.status is MeasurementStatus.UNSUPPORTED_GEOMETRY
        assert result.supported is False and result.value is None


def test_unit_multipoint_not_applicable(service, wgs84):
    assert service.measure(MultiPoint([(1, 1), (2, 2)]), wgs84).status is MeasurementStatus.NOT_APPLICABLE


def test_unit_empty_and_none(service, wgs84):
    assert service.measure(None, wgs84).status is MeasurementStatus.INVALID_GEOMETRY
    assert service.measure(Polygon(), wgs84).status is MeasurementStatus.INVALID_GEOMETRY


def test_unit_out_of_range_geographic_coords(service, wgs84):
    result = service.measure(LineString([(200, 0), (201, 1)]), wgs84)
    assert result.status is MeasurementStatus.INVALID_GEOMETRY


def test_unit_degenerate_line_invalid(service, wgs84):
    assert service.measure(LineString([(1, 1), (1, 1)]), wgs84).status is MeasurementStatus.INVALID_GEOMETRY


def test_unit_measurement_failure_is_contained(service, wgs84, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(service._crs, "project", boom)
    result = service.measure(LineString([(1, 1), (2, 2)]), wgs84)
    assert result.status is MeasurementStatus.MEASUREMENT_FAILED
    assert "secret" not in result.message
    assert result.measurement_type is MeasurementType.LENGTH


def test_unit_z_coordinates_ignored(service, wgs84):
    flat = service.measure(LineString([(77, 12), (77, 13)]), wgs84).value
    with_z = service.measure(LineString([(77, 12, 500), (77, 13, 9000)]), wgs84).value
    assert flat == with_z


def test_unit_multipolygon_valid(service, wgs84):
    mp = MultiPolygon(
        [
            Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)]),
            Polygon([(1, 1), (1.01, 1), (1.01, 1.01), (1, 1.01)]),
        ]
    )
    result = service.measure(mp, wgs84)
    assert result.status is MeasurementStatus.MEASURED and result.value > 2_000_000
