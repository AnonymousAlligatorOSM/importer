from shapely.geometry import Polygon

class ExistingBuilding:
    def __init__(self, shape, osm_element):
        self.shape = Polygon(shape)
        self.osm_element = osm_element
        self.addresses = []
