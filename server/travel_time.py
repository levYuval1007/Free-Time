import sys

import ors

if len(sys.argv) not in (3, 4):
    sys.exit('Usage: python travel_time.py "origin" "destination" [country code, default IL]')

country = sys.argv[3] if len(sys.argv) == 4 else "IL"
try:
    result = ors.route(country, sys.argv[1], sys.argv[2])
except ors.RouteError as err:
    sys.exit(str(err))

print(f"From: {result['from']}")
print(f"To:   {result['to']}")
print(f"Driving: {result['minutes']} min, {result['km']} km (no live traffic)")
