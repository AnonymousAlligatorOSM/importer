from math import *
import typing as T

from shapely.geometry import shape, Point, Polygon, MultiPolygon

class Building:
    def __init__(self, data, tags: T.Dict[str, str], tag_maps: T.List[T.Tuple[str, str]] = [], tag_filters={}):
        self._shape = squarify(shape(data["geometry"]))
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


def squarify(polygon: Polygon) -> Polygon:
    """
    Attempts to "squarify" a building outline by snapping the corners to right
    and 45-degree angles.

    The algorithm finds the center point and angle of each side of the polygon,
    finds the average side angle mod 45 degrees, tries to snap every side to
    45 degree multiples of that average angle, then finds the intersections
    of the sides to get a new series of points. All this happens in Web
    Mercator coordinate space.

    If the process results in an invalid polygon, or if the intersection over
    union of the old and new polygons is less than .95 (indicating a significant
    change), then the squared polygon is discarded and the original one is
    returned.
    """

    try:
        # Get the coordinates of the corners
        coords = polygon.exterior.coords

        mod_angle = 45 * pi / 180
        snap_threshold = 10 * pi / 180

        # For each side of the polygon, find the center point and the angle
        segments = []
        len_sum = 0
        angle_sum = 0
        for i, (px, py) in enumerate(coords):
            if i == len(coords) - 1:
                continue
            nx, ny = coords[(i+1)%len(coords)]

            def to_tile(x, y):
                lat_rad = y / 180 * pi
                return (
                    (x + 180) / 360,
                    (1 - (log(tan(lat_rad) + 1/cos(lat_rad)) / pi)) / 2
                )

            nx, ny = to_tile(nx, ny)
            px, py = to_tile(px, py)
            center = (px + nx) / 2, (py + ny) / 2

            angle = atan2(ny - py, nx - px)

            seg_len = sqrt((px - nx) ** 2 + (py - ny) ** 2)
            len_sum += seg_len
            # Note that the angle average is mod 45 from the beginning--we want
            # the average of (each angle mod 45), not (the average of each angle)
            # mod 45, otherwise the result will be meaningless
            angle_sum += (angle % mod_angle) * seg_len
            segments.append((center, angle))

        # Find the average angle, weighted by segment length
        avg_angle = (angle_sum / len_sum) % mod_angle

        # Snap each segment to the 45-degree increments of the average angle
        def snap_segment(segment):
            center, angle = segment
            diff = angle % mod_angle - avg_angle
            if abs(diff) < snap_threshold:
                return center, angle - diff
            elif abs(diff) > mod_angle - snap_threshold:
                return center, angle - diff
            else:
                return center, angle

        segments = [snap_segment(segment) for segment in segments]

        # Now that we have a list of segments by center point and (now snapped)
        # angle, intersect adjacent lines to get back to a list of corners
        points = []
        for i, ((ax, ay), angleA) in enumerate(segments):
            (bx, by), angleB = segments[(i+1)%len(segments)]

            # I hope you remember high school algebra and precalc
            x = (-ay + by - tan(angleB) * bx + tan(angleA) * ax) / (tan(angleA) - tan(angleB))
            y = tan(angleA) * (x - ax) + ay

            def from_tile(x, y):
                return (
                    x * 360 - 180,
                    atan(sinh(pi * (1 - 2 * y))) * 180 / pi
                )
            points.append(from_tile(x, y))

        square_polygon = Polygon(points)

        # There's no guarantee the algorithm generates valid polygons. We don't
        # need a super reliable algorithm here, just something to handle the
        # majority of cases, so just ignore this polygon.
        if not square_polygon.is_valid:
            return polygon

        # Find both the union and the intersection of the new and old polygons.
        # Divide the area of the intersection by the area of the union. This
        # gives us a number between 0 and 1 that measures how much the polygons
        # overlap. If they don't almost exactly overlap, leave the squaring for
        # the manual review step.
        intersection = square_polygon.intersection(polygon).area
        union = square_polygon.union(polygon).area
        if intersection / union > 0.95:
            return square_polygon
        else:
            return polygon
    except Exception as e:
        # We might get ZeroDivisionErrors and such, just ignore them and return
        # the original polygon
        return polygon
