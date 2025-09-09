from geopy.geocoders import Nominatim
import requests
import time

_PARKING_CACHE = {}
_CACHE_TTL = 600

# klasyfikacja access

_ACCESS_PUBLIC = {"yes", "public", "permissive"}
_ACCESS_PRIVATE = {"private", "no"}
_ACCESS_RESTRICTED = {
    "customers", "destination", "delivery",
    "permit", "residents", "forestry"
}

def _classify_access(tags: dict) -> str:
    a = (tags.get("access") or "").strip().lower()
    if a in _ACCESS_PRIVATE:
        return "private"
    if a in _ACCESS_RESTRICTED:
        return "restricted"
    if a in _ACCESS_PUBLIC:
        return "public"

    name = (tags.get("name") or "").lower()
    operator = (tags.get("operator") or "").lower()
    hints_restricted = [
        "klient", "gosc", "pracownik", "staff",
        "residents", "mieszkani", "hotel", "szpital",
        "uniwersyt", "campus"
    ]
    if any(h in name for h in hints_restricted) or any(h in operator for h in hints_restricted):
        return "restricted"

    return "unknown"

def _normalize_fee(tags: dict) -> str:
    f = (tags.get("fee") or "").strip().lower()
    if f in {"yes", "ticket", "charge"}:
        return "paid"
    if f == "no":
        return "free"
    return "unknown"

# geokodowanie

def geocode_address(address: str):
    geolocator = Nominatim(user_agent="smart_parking_app")
    location = geolocator.geocode(f"{address}, Krakow, Polska")
    if location:
        return (location.latitude, location.longitude)
    return None

# zapytanie do overpass api

def _overpass_query(query: str):
    OVERPASS_URLS = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.openstreetmap.ru/api/interpreter",
    ]
    headers = {"User-Agent": "smart-parking-app/1.0 (contact: example@domain.com)"}
    last_err = None
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data={"data": query}, headers=headers, timeout=25)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            continue
    print("overpass failure:", last_err)
    return {"elements": []}

# parsowanie elementow osm

def _parse_elements(data):
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        if el["type"] == "node":
            plat, plon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            plat, plon = c.get("lat"), c.get("lon")
        if plat is None or plon is None:
            continue

        access_class = _classify_access(tags)
        fee_norm = _normalize_fee(tags)

        out.append({
            "id": el.get("id"),
            "name": tags.get("name") or "Parking",
            "lat": plat,
            "lon": plon,
            "access_raw": tags.get("access"),
            "fee_raw": tags.get("fee"),
            "access_class": access_class,
            "fee": fee_norm,
            "operator": tags.get("operator"),
            "capacity": tags.get("capacity"),
            "parking_type": tags.get("parking"),
        })
    return out

# pobieranie parkingow z cache

def fetch_parkings(lat: float, lon: float, radius_m: int = 100):
    key = (round(lat, 5), round(lon, 5), int(radius_m))
    now = time.time()
    cached = _PARKING_CACHE.get(key)
    if cached and (now - cached["ts"] < _CACHE_TTL):
        return cached["data"]

    q_nodes = f"""
    [out:json][timeout:20];
    node["amenity"="parking"](around:{radius_m},{lat},{lon});
    out tags;
    """
    data_nodes = _overpass_query(q_nodes)
    items = _parse_elements(data_nodes)

    if not items:
        
        q_wr = f"""
        [out:json][timeout:25];
        (
          way["amenity"="parking"](around:{radius_m},{lat},{lon});
          relation["amenity"="parking"](around:{radius_m},{lat},{lon});
        );
        out tags center;
        """
        data_wr = _overpass_query(q_wr)
        items = _parse_elements(data_wr)

    _PARKING_CACHE[key] = {"ts": now, "data": items}
    return items
