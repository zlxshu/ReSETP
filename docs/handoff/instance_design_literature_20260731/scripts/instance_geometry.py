"""Read-only: great-circle depot separation and node bounding box for a China81 instance.

Usage: python instance_geometry.py <nodes.csv>
Straight-line approximation from lat/lon; not road-network distance.
"""
import csv
import math
import sys
from collections import Counter

R_KM = 6371.0


def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R_KM * math.asin(math.sqrt(h))


rows = list(csv.DictReader(open(sys.argv[1])))
lat = [float(r["latitude"]) for r in rows]
lon = [float(r["longitude"]) for r in rows]
depots = [(float(r["latitude"]), float(r["longitude"]))
          for r in rows if r["node_type"] == "depot"]

for i in range(len(depots)):
    for j in range(i + 1, len(depots)):
        print(f"depot pair {i}-{j}: {haversine(depots[i], depots[j]):.1f} km")

mean_lat = sum(lat) / len(lat)
ns = (max(lat) - min(lat)) * math.pi / 180 * R_KM
ew = (max(lon) - min(lon)) * math.pi / 180 * R_KM * math.cos(math.radians(mean_lat))
print(f"bounding box: {ns:.1f} km (N-S) x {ew:.1f} km (E-W)")
print("node types:", Counter(r["node_type"] for r in rows))
print("cities:", Counter(r["city"] for r in rows))
