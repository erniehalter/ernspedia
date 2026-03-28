import json
import os
import re
import requests

def _get_rapidapi_key() -> str:
    # 1. Environment variable (local dev)
    key = os.environ.get("RAPIDAPI_KEY", "")
    if key:
        return key
    # 2. Streamlit secrets (Streamlit Cloud deployment)
    try:
        import streamlit as st
        return st.secrets["RAPIDAPI_KEY"]
    except Exception:
        pass
    return ""

RAPIDAPI_HOST = "booking-com18.p.rapidapi.com"
BASE_URL = f"https://{RAPIDAPI_HOST}"

def _get_headers() -> dict:
    return {
        "x-rapidapi-key": _get_rapidapi_key(),
        "x-rapidapi-host": RAPIDAPI_HOST,
    }

LIBRARY_FILE = os.path.join(os.path.dirname(__file__), "airport_id_library.json")


def load_library() -> dict:
    if os.path.exists(LIBRARY_FILE):
        with open(LIBRARY_FILE, "r") as f:
            return json.load(f)
    return {}


def save_library(library: dict):
    with open(LIBRARY_FILE, "w") as f:
        json.dump(library, f, indent=2)


def resolve_airport_info(airport_code: str) -> tuple[str, str, dict] | tuple[None, None, None]:
    """Returns (pickup_id, display_name, meta) for the given airport code.
    meta keys: iata, lat, lng (may be None for old cache entries)."""
    code = airport_code.upper().strip()
    library = load_library()
    entry = library.get(code)

    # Handle old string format
    if isinstance(entry, str):
        return entry, code, {"iata": code, "lat": None, "lng": None}
    if isinstance(entry, dict):
        return entry["id"], entry["name"], entry

    resp = requests.get(
        f"{BASE_URL}/car/auto-complete",
        headers=_get_headers(),
        params={"query": code},
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return None, None

    hit = data[0]
    pickup_id = hit.get("id")
    name = hit.get("name") or code
    iata = hit.get("iata_code") or code
    coords = hit.get("coordinates") or {}
    lat = coords.get("latitude")
    lng = coords.get("longitude")
    if pickup_id:
        library[code] = {
            "id": pickup_id,
            "name": name,
            "iata": iata,
            "lat": lat,
            "lng": lng,
        }
        save_library(library)
    meta = {"iata": iata, "lat": lat, "lng": lng}
    return pickup_id, name, meta


def _parse_price(price_val) -> float:
    """Return numeric price for sorting, or large float if unparseable."""
    if isinstance(price_val, (int, float)):
        return float(price_val)
    try:
        return float(re.sub(r"[^\d.]", "", str(price_val)))
    except ValueError:
        return 999999.0


def _booking_search_url(iata: str, d1: str, d2: str, name: str = "", lat=None, lng=None) -> str:
    """Construct a verified working Booking.com car search URL."""
    from urllib.parse import quote
    pu_y, pu_m, pu_d = d1.split("-")
    do_y, do_m, do_d = d2.split("-")
    display = name or iata
    encoded_name = quote(display)
    coords = f"{lat},{lng}" if lat is not None and lng is not None else ""
    encoded_coords = quote(coords) if coords else ""
    return (
        f"https://cars.booking.com/search-results"
        f"?doDay={int(do_d)}&doHour=10&doMinute=0&doMonth={int(do_m)}&doYear={do_y}"
        f"&pickup_airport={iata}"
        f"&puDay={int(pu_d)}&puHour=10&puMinute=0&puMonth={int(pu_m)}&puYear={pu_y}"
        f"&location=&dropLocation="
        f"&locationName={encoded_name}&locationIata={iata}"
        f"&dropLocationName={encoded_name}&dropLocationIata={iata}"
        f"&coordinates={encoded_coords}&dropCoordinates={encoded_coords}"
        f"&driversAge=30&ftsType=A&dropFtsType=A"
        f"&filterCriteria_sortBy=PRICE&filterCriteria_sortAscending=true"
    )


def search_cars(airport: str, d1: str, d2: str) -> tuple[list[dict], str]:
    """Returns (results, airport_display_name). Results sorted by price ascending."""
    pickup_id, airport_name, meta = resolve_airport_info(airport)
    if not pickup_id:
        raise ValueError(f"Could not resolve airport ID for '{airport}'")

    resp = requests.get(
        f"{BASE_URL}/car/search",
        headers=_get_headers(),
        params={
            "pickUpId": pickup_id,
            "dropOffId": pickup_id,
            "pickUpDate": d1,
            "dropOffDate": d2,
            "pickUpTime": "10:00",
            "dropOffTime": "10:00",
        },
        timeout=30
    )
    resp.raise_for_status()
    raw = resp.json()

    iata = meta.get("iata") or airport.upper().strip()
    search_url = _booking_search_url(
        iata, d1, d2,
        name=airport_name,
        lat=meta.get("lat"),
        lng=meta.get("lng"),
    )

    results = []
    for item in raw.get("data", {}).get("search_results", []):
        vendor = item.get("supplier_info", {}).get("name", "—")
        vehicle = item.get("vehicle_info", {}).get("v_name", "—")
        group = item.get("vehicle_info", {}).get("group", "")
        vehicle_label = f"{vehicle} ({group})" if group and group.lower() not in vehicle.lower() else vehicle
        pricing = item.get("pricing_info", {})
        price_num = pricing.get("drive_away_price") or pricing.get("price") or 0
        currency = pricing.get("currency", "USD")
        price_str = f"${price_num:,.2f} {currency}" if isinstance(price_num, (int, float)) else "—"
        results.append({
            "Vendor": vendor,
            "Vehicle": vehicle_label,
            "Price": price_str,
            "_price_num": _parse_price(price_num),
            "Link": search_url,
        })

    results.sort(key=lambda x: x["_price_num"])
    for r in results:
        r["Price_Num"] = r.pop("_price_num")

    return results, airport_name
