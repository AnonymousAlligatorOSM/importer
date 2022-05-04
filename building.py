import typing as T

from shapely.geometry import shape, Point, Polygon, MultiPolygon

class Building:
    def __init__(self, data, tags: T.Dict[str, str], tag_maps: T.List[T.Tuple[str, str]] = [], tag_filters={}):
        self._shape = shape(data["geometry"])
        if not (isinstance(self._shape, Polygon) or isinstance(self._shape, MultiPolygon)):
            raise ValueError(f"Expected a Polygon or MultiPolygon geometry (got {self._location})")

        if isinstance(self._shape, Polygon) and len(self._shape.exterior.coords) >= 100:
            self._shape = self._shape.simplify(0.000004)

        self._tags = {**tags}
        for map_to, map_from in tag_maps:
            if prop := data["properties"].get(map_from):
                if tag_filter := tag_filters.get(map_to):
                    prop = tag_filter(prop)
                self._tags[map_to] = prop

        self.addresses = []

    @property
    def tags(self) -> T.Dict[str, str]:
        return self._tags

    @property
    def shape(self) -> Polygon | MultiPolygon:
        return self._shape

    @property
    def location(self) -> Point:
        return self._shape.representative_point()
