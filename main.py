import argparse, hashlib, itertools, json, os, sys, time
from collections import defaultdict
from lxml import etree
from multiprocessing import Pool

from fiona import collection
import requests
from rtree import index
from shapely.geometry import Point, MultiPoint, MultiLineString, Polygon, MultiPolygon, LineString

from address import Address
from building import Building
from changes import *
from existing_building import ExistingBuilding
from filter import Filter

def main():
    args = argparse.ArgumentParser(fromfile_prefix_chars="@")
    args.convert_arg_line_to_args = convert_arg_line_to_args
    args.add_argument("output", help="output directory")
    args.add_argument("--jobs", dest="jobs", default=None, type=int, help="number of threads (defaults to number of detected CPU cores)")

    args.add_argument("--generator", dest="generator", default="AnonymousAlligator's import script", help="name of generator, to put in XML output")
    args.add_argument("--changeset-tags", dest="changeset_tags", action="append", default=[], help="tags to add to changesets (format key=value)")

    args.add_argument("--addresses", dest="addresses", help="path to addresses shapefile")
    args.add_argument("--map-address-tag", dest="address_tag_maps", action="append", default=[], help="mapping of <osm tag>=<shapefile property>")
    args.add_argument("--add-address-tag", dest="address_tags", action="append", default=[], help="mapping of <osm tag>=<shapefile property>")

    args.add_argument("--buildings", dest="buildings", help="path to buildings shapefile")
    args.add_argument("--map-building-tag", dest="building_tag_maps", action="append", default=[], help="mapping of <osm tag>=<shapefile property>")
    args.add_argument("--add-building-tag", dest="building_tags", action="append", default=[], help="mapping of <osm tag>=<shapefile property>")

    args.add_argument("--tag-filters", dest="tag_filters", action="append", default=[], help="pairs of tag,file where tag is the output tag to apply filter to and file is a file full of filters, one per line")

    if len(sys.argv) == 1:
        args.print_help()
        exit(1)

    opts = args.parse_args()

    tag_filters = {}
    for tag_filter in opts.tag_filters:
        tag, path = tag_filter.split(",", 1)
        if tag in tag_filters:
            raise ValueError(f"Filter file already specified for {tag}")
        tag_filters[tag] = Filter(path)

    addresses = []
    buildings = []

    points = MultiPoint()

    if not opts.addresses and not opts.buildings:
        print(f"No addresses or buildings specified. See {sys.argv[0]} --help.")
        exit(1)

    if opts.addresses:
        with section("Reading addresses"):
            address_tags = { tag.split("=", 1)[0]: tag.split("=", 1)[1] for tag in opts.address_tags }
            address_tag_maps = [(tag.split("=", 1)[0], tag.split("=", 1)[1]) for tag in opts.address_tag_maps]
            with collection(opts.addresses, "r") as shapefile:
                with Pool(opts.jobs) as p:
                    addresses = list(p.imap_unordered(PoolFunc(Address, address_tags, address_tag_maps, tag_filters), shapefile, chunksize=1024))
            points = MultiPoint([*points.geoms, *[address.location for address in addresses]])

    if opts.buildings:
        with section("Reading buildings"):
            building_tags = { tag.split("=", 1)[0]: tag.split("=", 1)[1] for tag in opts.building_tags }
            building_tag_maps = [(tag.split("=", 1)[0], tag.split("=", 1)[1]) for tag in opts.building_tag_maps]
            with collection(opts.buildings, "r") as shapefile:
                with Pool(opts.jobs) as p:
                    buildings = list(p.imap_unordered(PoolFunc(Building, building_tags, building_tag_maps, tag_filters), shapefile, chunksize=1024))
            points = MultiPoint([*points.geoms, *[building.location for building in buildings]])

    with section("Downloading existing data"):
        poly = " ".join([f"{lat} {lon}" for lon, lat in points.convex_hull.exterior.coords])

        with section("  Downloading existing addresses from overpass"):
            existing_address_result = overpass_query(f'[out:json][timeout:120]; ( node[~"^addr:.*$"~".*"](poly:"{poly}"); way[~"^addr:.*$"~".*"](poly:"{poly}"); relation[~"^addr:.*$"~".*"](poly:"{poly}"); ); out tags center;')
            with section("    Processing addresses"):
                existing_addresses = defaultdict(list)
                for element in existing_address_result['elements']:
                    existing_addresses[(element['tags'].get('addr:housenumber'), element['tags'].get('addr:street'))].append(overpass_to_geom(element))
                existing_addresses = { name: MultiPoint(points) for name, points in existing_addresses.items() }

        with section("  Downloading existing buildings from overpass"):
            existing_building_result = overpass_query(f'[out:json][timeout:120]; ( way["building"="yes"](poly:"{poly}"); relation["building"="yes"](poly:"{poly}"); ); out meta geom;')
            with section("    Processing buildings"):
                existing_buildings = [
                    ExistingBuilding(overpass_to_geom(element), element) for element in existing_building_result['elements']
                ]

        with section("  Downloading streets from overpass"):
            existing_street_result = overpass_query(f'[out:json][timeout:120]; way["highway"](poly:"{poly}"); out tags geom;')
            with section("    Processing streets"):
                existing_streets = defaultdict(list)
                for element in existing_street_result['elements']:
                    name = element['tags'].get('name')
                    existing_streets[name].append(overpass_to_geom(element))
                existing_streets = { name: MultiLineString(lines) for name, lines in existing_streets.items() }

    with section("Removing input addresses that already exist in OSM"):
        prev_len = len(addresses)
        addresses = list(filter(lambda addr: addr.address_tuple not in existing_addresses, addresses))
        print(f"  Removed {prev_len - len(addresses)} addresses")

    with section("Checking input addresses against existing street names"):
        for address in addresses:
            if address.tags.get("addr:street") not in existing_streets:
                address.warn_no_nearby_street()

    with section("Building spatial index of existing buildings"):
        existing_bldg_idx = index.Index()
        for i, bldg in enumerate(existing_buildings):
            bounds = bldg.shape.bounds
            if len(bounds) == 4:
                existing_bldg_idx.add(i, bounds)

    with section("Removing input buildings that already exist in OSM"):
        prev_len = len(buildings)

        def intersects(bldg):
            for i in existing_bldg_idx.intersection(bldg.shape.bounds):
                if existing_buildings[i].shape.intersects(bldg.shape):
                    return False
            return True

        buildings = list(filter(intersects, buildings))

        print(f"  Removed {prev_len - len(buildings)} buildings")

    with section("Building spatial index of new buildings"):
        new_bldg_idx = index.Index()
        for i, bldg in enumerate(buildings):
            bounds = bldg.shape.bounds
            if len(bounds) == 4:
                new_bldg_idx.add(i, bounds)

    # addresses with no building underneath
    lone_addresses = []

    with section("Matching input addresses to buildings"):
        for address in addresses:
            for i in existing_bldg_idx.intersection(address.location.bounds):
                if existing_buildings[i].shape.intersects(address.location):
                    existing_buildings[i].addresses.append(address)
                    break
            else:
                for i in new_bldg_idx.intersection(address.location.bounds):
                    if buildings[i].shape.intersects(address.location):
                        buildings[i].addresses.append(address)
                        break
                else:
                    lone_addresses.append(address)

    changes = []
    with section("Generating changes"):
        with section("  Generating new building changes"):
            for building in buildings:
                if len(building.addresses) == 1:
                    changes.append(NewBuildingWithAddressChange(building, building.addresses[0]))
                else:
                    changes.append(NewBuildingChange(building))
                    changes += [NewAddressChange(address) for address in building.addresses]

        with section("  Generating new address changes"):
            changes += [NewAddressChange(address) for address in lone_addresses]

        with section("  Generating address update changes"):
            for building in existing_buildings:
                if len(building.addresses) == 1:
                    changes.append(UpdateBuildingAddressChange(building.osm_element, building.addresses[0]))
                else:
                    changes += [NewAddressChange(address) for address in building.addresses]

    with section("Sorting changes by tile"):
        tiles = defaultdict(ChangesetEmitter)
        warned_tiles = defaultdict(ChangesetEmitter)
        for change in changes:
            if len(change.warnings) > 0:
                warned_tiles[change.tile_name].add_change(change)
            else:
                tiles[change.tile_name].add_change(change)

    print(f"Generated {len(tiles)} tiles and {len(warned_tiles)} warning tiles")

    with section("Generating files"):
        changeset_tags = { tag.split("=", 1)[0]: tag.split("=", 1)[1] for tag in opts.changeset_tags }

        os.makedirs(os.path.join(opts.output, "changesets"), exist_ok=True)
        os.makedirs(os.path.join(opts.output, "warnings"), exist_ok=True)

        with Pool(opts.jobs) as p:
            list(p.imap_unordered(PoolFunc(write_tile, os.path.join(opts.output, "changesets"), generator=opts.generator, changeset_tags=changeset_tags), tiles.items()))

        with Pool(opts.jobs) as p:
            list(p.imap_unordered(PoolFunc(write_tile, os.path.join(opts.output, "warnings"), generator=opts.generator, changeset_tags=changeset_tags), warned_tiles.items()))

    print("Done!")


def write_tile(arg, folder, **write_to_kwargs):
    name, tile = arg
    filename = f"change-{name}.osm"
    tile.write_to(os.path.join(folder, filename), source_file=name, **write_to_kwargs)

    warnings = tile.warnings
    if len(warnings):
        with open(os.path.join(folder, f"warn-{name}.log"), "w") as f:
            for warning in warnings:
                f.write(warning + "\n")


def overpass_to_geom(overpass_el):
    def point(p):
        return (p["lon"], p["lat"])

    if overpass_el["type"] == "node":
        return point(overpass_el)
    elif overpass_el["type"] == "way" and "geometry" in overpass_el:
        return [point(p) for p in overpass_el["geometry"]]
    elif overpass_el["type"] == "relation" and "members" in overpass_el:
        return Polygon([
            p
            for el in overpass_el["members"]
            for p in overpass_to_geom(el)
            if el["role"] == "outer"
        ])

    if "center" in overpass_el:
        return point(overpass_el["center"])


def overpass_query(query: str):
    """
    Submits an Overpass query and returns the parsed JSON.
    """

    path = os.path.join("importer_cache", hashlib.sha256(query.encode()).hexdigest())
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        data = requests.post("https://overpass-api.de/api/interpreter", data=query).text
        os.makedirs("importer_cache", exist_ok=True)
        with open(path, "w") as f:
            f.write(data)
        return json.loads(data)


def convert_arg_line_to_args(arg_line: str):
    """
    Parses lines from argument files, removing comments and blank lines for
    convenience.
    """

    arg_line = arg_line.strip()
    if arg_line == "" or arg_line.startswith("#"):
        return []
    return [arg_line]


class section:
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        print(f"{self.name}...")
        self.start = time.perf_counter()

    def __exit__(self, _type, _val, _traceback):
        print(f"{self.name}: {time.perf_counter() - self.start:.{3}}s")


class PoolFunc:
    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def __call__(self, obj):
        return self.func(obj, *self.args, **self.kwargs)
