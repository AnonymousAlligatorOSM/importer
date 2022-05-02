from decimal import Decimal
from lxml import etree
from math import cos, tan, pi, floor, log
import typing as T
from shapely.geometry import MultiPolygon, Point


class ChangesetEmitter:
    def __init__(self):
        self._next_id = {"node": 0, "way": 0, "relation": 0}
        self._nodes = {}
        self.changes = []

    def add_change(self, change):
        self.changes.append(change)

    def get_warnings(self):
        for change in self.changes:
            yield from change.get_warnings()

    @property
    def warnings(self):
        return list(self.get_warnings())

    def write_to(self, path, generator=None, changeset_tags={}, source_file=None):
        self._xml = etree.Element("osm", version="0.6", generator=generator)

        for key, val in changeset_tags.items():
            self._xml.append(etree.Element("changeset_tag", k=key, v=val))

        if source_file:
            self._xml.append(etree.Element("changeset_tag", k="source_file", v=source_file))

        for change in self.changes:
            change.emit_xml(self)

        with open(path, "wb") as f:
            f.write(etree.tostring(self._xml, pretty_print=True, xml_declaration=True, encoding="utf8"))

    def get_id(self, type: str):
        self._next_id[type] -= 1
        return str(self._next_id[type])

    def add_node(self, location, tags=None):
        location = Point(location)

        rlon = int(float(location.x*10**7))
        rlat = int(float(location.y*10**7))
        if (rlon, rlat) in self._nodes:
            return self._nodes[(rlon, rlat)]

        id = self.get_id("node")
        node = etree.Element("node", visible="true", id=id)
        node.set('lat', str(Decimal(location.y)*Decimal(1)))
        node.set('lon', str(Decimal(location.x)*Decimal(1)))
        if tags:
            for key, val in tags.items():
                node.append(etree.Element('tag', k=key, v=val))
        self._nodes[(rlon, rlat)] = node
        self._xml.append(node)
        return node

    def add_way(self, points):
        nodes = [self.add_node(p) for p in points]
        id = self.get_id("way")
        way = etree.Element("way", visible="true", id=id)
        for node in nodes:
            way.append(etree.Element("nd", ref=node.get("id")))
        self._xml.append(way)
        return way

    def add_polygon(self, shape, tags):
        outers = []
        interiors = []
        if isinstance(shape, MultiPolygon):
            polygons = list(shape.geoms)
        else:
            polygons = [shape]

        for polygon in polygons:
            outers.append(self.add_way(list(polygon.exterior.coords)))
            for interior in polygon.interiors:
                interiors.append(self.add_way(list(interior.coords)))

        if len(interiors) > 0 or len(outers) > 1:
            relation = etree.Element('relation', visible='true', id=str(self.get_id("way")))
            for outer in outers:
                relation.append(etree.Element('member', type='way', role='outer', ref=outer.get('id')))
            for interior in interiors:
                relation.append(etree.Element('member', type='way', role='inner', ref=interior.get('id')))
            relation.append(etree.Element('tag', k='type', v='multipolygon'))
            self._xml.append(relation)
            way = relation
        else:
            way = outers[0]

        for key, val in tags.items():
            way.append(etree.Element('tag', k=key, v=val))

        return way

    def add_xml(self, element):
        self._xml.append(element)


class Change:
    @property
    def warnings(self) -> T.List[str]:
        return list(self.get_warnings())

    def get_warnings(self) -> T.Iterator[str]:
        yield from []

    @property
    def location(self):
        raise NotImplementedError()

    @property
    def tile_name(self):
        point = self.location
        zoom = 15
        n = 2 ** zoom
        lat_rad = point.y / 180 * pi
        xtile = floor(n * ((point.x + 180) / 360))
        ytile = floor(n * (1 - (log(tan(lat_rad) + 1/cos(lat_rad)) / pi)) / 2)
        return f"{xtile}_{ytile}"

    def emit_xml(self, ctx: ChangesetEmitter):
        raise NotImplementedError()


class NewBuildingChange(Change):
    def __init__(self, building):
        self.building = building

    @property
    def location(self):
        return self.building.location

    def emit_xml(self, ctx: ChangesetEmitter):
        ctx.add_polygon(self.building.shape, self.building.tags)


class NewAddressChange(Change):
    def __init__(self, address):
        self.address = address

    def get_warnings(self) -> T.Iterator[str]:
        yield from self.address.warnings

    @property
    def location(self):
        return self.address.location

    def emit_xml(self, ctx: ChangesetEmitter):
        ctx.add_node(self.location, self.address.tags)


class NewBuildingWithAddressChange(Change):
    def __init__(self, building, address):
        self.building = building
        self.address = address

    def get_warnings(self) -> T.Iterator[str]:
        yield from self.address.warnings

    @property
    def location(self):
        return self.address.location

    def emit_xml(self, ctx: ChangesetEmitter):
        element = ctx.add_polygon(self.building.shape, self.building.tags)
        for key, val in self.address.tags.items():
            element.append(etree.Element('tag', k=key, v=val))


class UpdateBuildingAddressChange(Change):
    def __init__(self, osm_element, address):
        self.osm_element = osm_element
        self.address = address

    def get_warnings(self) -> T.Iterator[str]:
        yield from self.address.warnings
        street = self.osm_element["tags"].get("addr:street")
        housenumber = self.osm_element["tags"].get("addr:housenumber")
        if "addr:street" in self.osm_element["tags"] or "addr:housenumer" in self.osm_element["tags"]:
            if (street != self.address.tags.get("addr:street") or housenumber != self.address.tags.get("addr:housenumber")):
                yield f"new building address ({self.address}) does not match the old one ({(housenumber, street)})"


    @property
    def location(self):
        return self.address.location

    def emit_xml(self, ctx: ChangesetEmitter):
        element = etree.Element(self.osm_element["type"], id=str(self.osm_element["id"]), version=str(self.osm_element["version"]))
        for key, val in self.address.tags.items():
            element.append(etree.Element('tag', k=key, v=val))
        ctx.add_xml(element)

