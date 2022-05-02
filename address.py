import typing as T

from shapely.geometry import shape, Point

class Address:
    def __init__(self, data, tags: T.Dict[str, str], tag_maps: T.List[T.Tuple[str, str]] = [], tag_filter=None):
        self._location = shape(data["geometry"])
        if not isinstance(self._location, Point):
            raise ValueError(f"Expected point geometry (got {self._location})")

        self._tags = {**tags}
        for map_to, map_from in tag_maps:
            if prop := data["properties"].get(map_from):
                self._tags[map_to] = tag_filter(prop)

        self._no_nearby_street_warning = None

    @property
    def tags(self) -> T.Dict[str, str]:
        return self._tags

    @property
    def location(self) -> Point:
        return self._location

    @property
    def address_tuple(self) -> T.Tuple[str, str]:
        return (self.tags.get("addr:housenumber"), self.tags.get("addr:street"))

    @property
    def warnings(self) -> T.Iterator[str]:
        if not self.tags.get("addr:housenumber"):
            yield f"address has no house number: {self}"

        if not self.tags.get("addr:street"):
            yield f"address has no street: {self}"

        if self._no_nearby_street_warning:
            yield self._no_nearby_street_warning

    def __str__(self):
        return f"{self.address_tuple} https://osm.org/?mlat={self.location.y}&mlon={self.location.x}&zoom=16"

    def warn_no_nearby_street(self):
        self._no_nearby_street_warning = f"address does not match a street: {self}"
