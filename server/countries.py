import json
import threading
import urllib.error
import urllib.request

WORLD_BANK_URL = "https://api.worldbank.org/v2/country?format=json&per_page=500"

_lock = threading.Lock()
_countries = None


class CountriesError(Exception):
    pass


def load_countries():
    global _countries
    with _lock:
        if _countries is None:
            try:
                with urllib.request.urlopen(WORLD_BANK_URL, timeout=10) as resp:
                    data = json.load(resp)
                _countries = sorted(
                    (
                        {"code": c["iso2Code"], "name": c["name"]}
                        for c in data[1]
                        if c["region"]["value"] != "Aggregates"
                    ),
                    key=lambda c: c["name"],
                )
            except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as err:
                raise CountriesError(f"Could not fetch countries: {err}")
        return _countries
