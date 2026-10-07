"""KML parser (stdlib XML, no DTD/entities allowed, namespace agnostic)."""

import xml.etree.ElementTree as ET
from xml.parsers import expat
from pathlib import Path
from typing import Any

from shapely.geometry import (
    GeometryCollection,
    LinearRing,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from app.core.exceptions import InvalidKMLError
from app.domain.models import ParsedFeature

GEOMETRY_TAGS = {"Point", "LineString", "LinearRing", "Polygon", "MultiGeometry"}


class _ForbiddenDTD(Exception):
    pass


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _reject_dtd(*_: Any) -> None:
    raise _ForbiddenDTD


def _assert_no_dtd(data: bytes) -> None:
    checker = expat.ParserCreate()
    checker.StartDoctypeDeclHandler = _reject_dtd
    checker.EntityDeclHandler = _reject_dtd
    checker.Parse(data, True)


def parse_kml(path: Path) -> list[ParsedFeature]:
    """Parse a KML file into features (always WGS84 lon/lat per the KML specification)."""
    data = path.read_bytes()
    try:
        _assert_no_dtd(data)
        root = ET.fromstring(data)
    except _ForbiddenDTD:
        raise InvalidKMLError("KML documents containing a DTD or entities are not allowed.") from None
    except (ET.ParseError, expat.ExpatError):
        raise InvalidKMLError() from None

    if _local(root.tag).lower() != "kml":
        raise InvalidKMLError("The XML document is not KML (root element must be <kml>).")

    features: list[ParsedFeature] = []
    for placemark in (el for el in root.iter() if _local(el.tag) == "Placemark"):
        features.append(_parse_placemark(len(features), placemark))
    return features


def _parse_placemark(index: int, placemark: ET.Element) -> ParsedFeature:
    properties = _properties(placemark)
    geometry_el = next((c for c in placemark if _local(c.tag) in GEOMETRY_TAGS), None)
    if geometry_el is None:
        return ParsedFeature(index, None, properties, "Placemark has no supported geometry.")
    try:
        return ParsedFeature(index, _geometry(geometry_el), properties)
    except (ValueError, TypeError, IndexError) as exc:
        return ParsedFeature(index, None, properties, f"Malformed geometry: {exc}")


def _properties(placemark: ET.Element) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for child in placemark:
        name = _local(child.tag)
        if name in ("name", "description") and _text(child):
            props[name] = _text(child)
        elif name == "ExtendedData":
            for item in child.iter():
                kind = _local(item.tag)
                if kind == "Data" and item.get("name"):
                    props[item.get("name")] = _text(next((v for v in item if _local(v.tag) == "value"), None))
                elif kind == "SimpleData" and item.get("name"):
                    props[item.get("name")] = _text(item)
    return props


def _coordinates(el: ET.Element) -> list[tuple[float, ...]]:
    coords_el = next((c for c in el.iter() if _local(c.tag) == "coordinates"), None)
    if coords_el is None or not _text(coords_el):
        raise ValueError("missing coordinates")
    result = []
    for token in _text(coords_el).split():
        parts = token.split(",")
        if len(parts) < 2:
            raise ValueError("coordinate tuple needs at least longitude,latitude")
        result.append(tuple(float(p) for p in parts[:3]))
    return result


def _ring_coords(boundary: ET.Element) -> list[tuple[float, ...]]:
    ring = next((c for c in boundary if _local(c.tag) == "LinearRing"), None)
    if ring is None:
        raise ValueError("boundary without LinearRing")
    return _coordinates(ring)


def _geometry(el: ET.Element) -> BaseGeometry:
    kind = _local(el.tag)
    if kind == "Point":
        return Point(_coordinates(el)[0])
    if kind == "LineString":
        return LineString(_coordinates(el))
    if kind == "LinearRing":
        return LinearRing(_coordinates(el))
    if kind == "Polygon":
        outer = next((c for c in el if _local(c.tag) == "outerBoundaryIs"), None)
        if outer is None:
            raise ValueError("polygon without outer boundary")
        holes = [_ring_coords(c) for c in el if _local(c.tag) == "innerBoundaryIs"]
        return Polygon(_ring_coords(outer), holes)
    if kind == "MultiGeometry":
        parts = [_geometry(c) for c in el if _local(c.tag) in GEOMETRY_TAGS]
        if not parts:
            raise ValueError("empty MultiGeometry")
        return _combine(parts)
    raise ValueError(f"unsupported element {kind}")


def _combine(parts: list[BaseGeometry]) -> BaseGeometry:
    if len(parts) == 1:
        return parts[0]
    types = {p.geom_type for p in parts}
    if types == {"Point"}:
        return MultiPoint(parts)
    if types == {"LineString"}:
        return MultiLineString(parts)
    if types == {"Polygon"}:
        return MultiPolygon(parts)
    return GeometryCollection(parts)
