"""Generate the sample files in sample_data/ (run: python scripts/generate_sample_data.py)."""

import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

OUT = Path(__file__).resolve().parent.parent / "sample_data"

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Plot A</name>
      <ExtendedData><Data name="owner"><value>Asha</value></Data></ExtendedData>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        77.000,12.000,0 77.010,12.000,0 77.010,12.010,0 77.000,12.010,0 77.000,12.000,0
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
    <Placemark>
      <name>Access road</name>
      <LineString><coordinates>77.000,12.000,0 77.000,13.000,0</coordinates></LineString>
    </Placemark>
    <Placemark>
      <name>Borewell</name>
      <Point><coordinates>77.005,12.005,0</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Self-intersecting plot (invalid)</name>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        77.0,12.0,0 77.01,12.01,0 77.01,12.0,0 77.0,12.01,0 77.0,12.0,0
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
  </Document>
</kml>
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "survey.kml").write_text(KML, encoding="utf-8")

    plots = gpd.GeoDataFrame(
        {"name": ["North field", "South field"]},
        geometry=[
            Polygon([(77, 12), (77.01, 12), (77.01, 12.01), (77, 12.01)]),
            Polygon([(77, 11.98), (77.01, 11.98), (77.01, 11.99), (77, 11.99)]),
        ],
        crs="EPSG:4326",
    )
    tmp = OUT / "_shp"
    tmp.mkdir(exist_ok=True)
    plots.to_file(tmp / "plots.shp")
    with zipfile.ZipFile(OUT / "plots_shapefile.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(tmp.iterdir()):
            zf.write(f, f.name)
            f.unlink()
    tmp.rmdir()


if __name__ == "__main__":
    main()
