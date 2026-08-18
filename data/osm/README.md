# Reviewed Technion place fixtures

`technion-way-66098525-v35.geojson` is a reproducible extraction of the
Technion – Israel Institute of Technology campus boundary from OpenStreetMap
way 66098525, version 35. It was retrieved from the OSM API on 2026-08-18; the
source revision timestamp is 2026-07-07T16:19:01Z.

- Source: https://www.openstreetmap.org/way/66098525/history/35
- Attribution: © OpenStreetMap contributors
- Licence: Open Database License (ODbL), https://www.openstreetmap.org/copyright

`taub-way-67222155-v10.geojson` is the reviewed nested boundary for Taub
Computer Science Building, OSM way 67222155, version 10. It was retrieved from
the OSM API on 2026-08-18; its OSM revision timestamp is
2026-06-07T19:29:33Z.

- Source: https://www.openstreetmap.org/way/67222155/history/10
- Attribution: © OpenStreetMap contributors
- Licence: Open Database License (ODbL), https://www.openstreetmap.org/copyright

The coordinate arrays are `[longitude, latitude]` in EPSG:4326. No OSM data is
fetched at runtime. Bootstrap validates fixture identity, ring closure,
coordinate ranges, and PostGIS validity. The independent
`milestone-4-osm-v1` seed also verifies that the existing Technion polygon
covers Taub before inserting Taub as its child.
