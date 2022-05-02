# Importer script

Originally written for the Jefferson Parish, Louisiana import, but designed to
be generic enough to easily adapt to other imports.

# Goal

The aim of this script is to make imports easier, especially when OSM already
contains a lot of data that needs to be conflated. It downloads and works with
existing data and is capable of generating changes that add tags to existing
objects.

Process your shapefiles using this tool, then manually review and upload
changesets via JOSM.

# Process

- Read buildings and addresses as shapefiles
- Apply tag mappings and text transforms from a file
- Download existing buildings, addresses, and streets from Overpass
- Delete added buildings and addresses that already exist in OSM
- Match addresses to new and existing buildings
- Run some validations
 - Address doesn't match a street name
 - New building address doesn't match old one
- Generate changesets by tile, split by passed/failed validation

# Tips

- You can list command line arguments in a file (such as `args.txt` and then
invoke the script with `./importer.py @args.txt`). That way you don't forget
what arguments you use!

# Contributing

If you want to use this script in an import, and you make any modifications,
feel free to submit them as a pull request. That way everyone can benefit from
a better import script.
