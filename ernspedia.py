import streamlit as st
import pandas as pd
from datetime import date, timedelta
import itertools
import json
import re
import sys
import os
from fli.search import SearchFlights
from fli.models import (
    FlightSearchFilters, Airport, PassengerInfo, FlightSegment,
    TripType, SeatType, MaxStops
)

sys.path.insert(0, os.path.dirname(__file__))
from booking_cars import search_cars

# Constants & Setup
st.set_page_config(page_title="Ernspedia", page_icon="✈️", layout="wide")

# Password gate
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("✈️ Ernspedia")
    pw = st.text_input("Password", type="password")
    if st.button("Enter"):
        if pw == st.secrets.get("APP_PASSWORD", ""):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()

st.title("✈️ Ernspedia: Tournament Flight Search")

SHORTCUTS = {
    "SOCAL": ["BUR", "LAX", "ONT", "LGB", "SNA"],
    "NORCAL": ["SFO", "OAK", "SJC"]
}

def expand_airports(input_str):
    if not input_str:
        return []
    raw_list = [x.strip().upper() for x in re.split(r"[\s,]+", input_str) if x.strip()]
    expanded = []
    for item in raw_list:
        if item in SHORTCUTS:
            expanded.extend(SHORTCUTS[item])
        else:
            expanded.append(item)
    return list(dict.fromkeys(expanded))

def fmt_dur(mins):
    if not mins: return "-"
    return f"{mins // 60}h {mins % 60}m"

# Session state
if "legs" not in st.session_state:
    st.session_state.legs = [{
        "id": 1,
        "origin": "IND FWA",
        "dest": "SNA LGB BUR ONT LAX",
        "date": date.today() + timedelta(days=7)
    }]
if "excluded_airlines" not in st.session_state:
    st.session_state.excluded_airlines = []
if "only_airline" not in st.session_state:
    st.session_state.only_airline = None
if "leg_raw_results" not in st.session_state:
    st.session_state.leg_raw_results = []
if "num_legs" not in st.session_state:
    st.session_state.num_legs = 0
if "free_bag_airlines" not in st.session_state:
    st.session_state.free_bag_airlines = []
if "pinned_flights" not in st.session_state:
    st.session_state.pinned_flights = []
if "hidden_flight_keys" not in st.session_state:
    st.session_state.hidden_flight_keys = set()
if "car_results" not in st.session_state:
    st.session_state.car_results = []
if "car_search_meta" not in st.session_state:
    st.session_state.car_search_meta = {}
if "car_results_per_leg" not in st.session_state:
    st.session_state.car_results_per_leg = []
if "return_airport_override" not in st.session_state:
    st.session_state.return_airport_override = False
if "excluded_car_vendors" not in st.session_state:
    st.session_state.excluded_car_vendors = []
if "last_search_legs" not in st.session_state:
    st.session_state.last_search_legs = []
if "_price_range_min" not in st.session_state:
    st.session_state._price_range_min = 0
if "_price_range_max" not in st.session_state:
    st.session_state._price_range_max = 5000
if "include_carry_on" not in st.session_state:
    st.session_state.include_carry_on = True
if "include_checked" not in st.session_state:
    st.session_state.include_checked = True

FREE_BAG_DEFAULTS = ["american", "delta"]
_hours = [f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}" for h in range(24)]
_next_day_arr_hours = [f"{h % 12 or 12} {'AM' if h < 12 else 'PM'} +1" for h in range(8)]  # 12 AM +1 … 7 AM +1

BAGGAGE_RULES_PATH = os.path.join(os.path.dirname(__file__), "baggage_rules.json")
try:
    with open(BAGGAGE_RULES_PATH) as _f:
        BAGGAGE_RULES = json.load(_f)
except Exception:
    BAGGAGE_RULES = {"Default": {"carry_on": 35, "checked": 40}}

def get_bag_fees(airline_name, overrides):
    """Look up carry-on + checked fees for an airline. Partial case-insensitive match."""
    name_lower = str(airline_name).lower()
    # Check user overrides first (free = 0)
    for free_airline in overrides:
        if free_airline.lower() in name_lower or name_lower in free_airline.lower():
            return {"carry_on": 0, "checked": 0}
    # Then check rules file
    for key, fees in BAGGAGE_RULES.items():
        if key == "Default":
            continue
        if key.lower() in name_lower:
            return fees
    return BAGGAGE_RULES.get("Default", {"carry_on": 35, "checked": 40})


# --- SIDEBAR ---
with st.sidebar:
    st.header("Filters")

    # Price range filter (reads range stored from last search/filter pass)
    st.subheader("💰 Total Price")
    _p_min = st.session_state._price_range_min
    _p_max = st.session_state._price_range_max
    if _p_min < _p_max:
        price_filter = st.slider(
            "Price range",
            min_value=_p_min,
            max_value=_p_max,
            value=(_p_min, _p_max),
            step=10,
            format="$%d",
            label_visibility="collapsed"
        )
    else:
        price_filter = (_p_min, _p_max)
        st.caption("Run a search to enable price filter.")

    st.divider()
    stops = st.selectbox("Max Stops", ["Any", "Non-stop", "1 Stop", "2 Stops"], index=2)
    min_layover = st.select_slider("Min Layover", options=["No Limit", "30m", "1h", "2h", "3h", "4h"], value="No Limit")
    max_layover = st.select_slider("Max Layover", options=["1h", "2h", "3h", "4h", "6h", "8h", "12h", "No Limit"], value="4h")

    # Collect airlines from results for all multiselects below
    all_airlines = []
    for leg_flights in st.session_state.leg_raw_results:
        for f in leg_flights:
            all_airlines.append(f["Airline"])
    all_airlines = sorted(set(all_airlines))

    st.divider()
    # Wrap all multiselects in a form so the dropdown stays open while making multiple selections
    with st.form("sidebar_filters_form"):
        st.subheader("Exclude Airlines")
        free_bag_options = all_airlines if all_airlines else list(BAGGAGE_RULES.keys())
        new_excluded = st.multiselect(
            "Excluded airlines",
            options=all_airlines,
            default=[a for a in (st.session_state.excluded_airlines or []) if a in all_airlines],
            placeholder="Run a search to see airlines..." if not all_airlines else "Select to exclude...",
            label_visibility="collapsed"
        )

        st.subheader("Baggage (per leg)")
        new_carry_on = st.checkbox("Include Carry-on", value=st.session_state.include_carry_on)
        new_checked = st.checkbox("Include Checked Bag", value=st.session_state.include_checked)
        st.caption("Fees auto-loaded from baggage_rules.json by airline.")
        st.caption("My free-bag airlines (overrides rules):")
        free_bag_default = [
            a for a in free_bag_options
            if any(k in a.lower() for k in FREE_BAG_DEFAULTS)
        ] if not st.session_state.free_bag_airlines else [
            a for a in st.session_state.free_bag_airlines if a in free_bag_options
        ]
        new_free_bag = st.multiselect(
            "Free bags on",
            options=free_bag_options,
            default=free_bag_default,
            placeholder="Run a search to see airlines..." if not all_airlines else "Select airlines...",
            label_visibility="collapsed"
        )

        st.subheader("🚗 Car Vendors")
        all_car_vendors = sorted({
            r["Vendor"]
            for car_data in (st.session_state.car_results_per_leg or [])
            if car_data and car_data.get("results")
            for r in car_data["results"]
        })
        if all_car_vendors:
            new_excluded_cars = st.multiselect(
                "Exclude vendors",
                options=all_car_vendors,
                default=[v for v in st.session_state.excluded_car_vendors if v in all_car_vendors],
                placeholder="Select to exclude...",
                label_visibility="collapsed"
            )
            st.caption(f"{len(all_car_vendors)} vendor(s) found")
        else:
            new_excluded_cars = st.session_state.excluded_car_vendors
            st.caption("Run a search to see vendors...")

        if st.form_submit_button("✅ Apply", use_container_width=True):
            st.session_state.excluded_airlines = new_excluded
            st.session_state.free_bag_airlines = new_free_bag
            st.session_state.excluded_car_vendors = new_excluded_cars
            st.session_state.include_carry_on = new_carry_on
            st.session_state.include_checked = new_checked

    # Read committed values from session state for filtering below
    include_carry_on = st.session_state.include_carry_on
    include_checked = st.session_state.include_checked

    st.divider()
    top_n = st.slider("Show Top N Results", min_value=5, max_value=500, value=50, step=5)
    debug_mode = st.checkbox("Show Debug Info", value=False)

    if st.session_state.pinned_flights or st.session_state.hidden_flight_keys:
        st.divider()
        if st.session_state.pinned_flights:
            st.caption(f"📌 {len(st.session_state.pinned_flights)} flight(s) pinned")
        if st.session_state.hidden_flight_keys:
            st.caption(f"🙈 {len(st.session_state.hidden_flight_keys)} flight(s) hidden")
        if st.button("Clear pins & hidden"):
            st.session_state.pinned_flights = []
            st.session_state.hidden_flight_keys = set()
            st.rerun()

# Map UI to Enums
stops_map = {
    "Any": MaxStops.ANY,
    "Non-stop": MaxStops.NON_STOP,
    "1 Stop": MaxStops.ONE_STOP_OR_FEWER,
    "2 Stops": MaxStops.TWO_OR_FEWER_STOPS
}

# --- MAIN PAGE: ITINERARY BUILDER ---
st.subheader("1. Build Your Itinerary")

leg_time_filters = []
for i, leg in enumerate(st.session_state.legs):
    with st.expander(f"Leg {i+1}: {leg['origin']} ➔ {leg['dest']} on {leg['date']}", expanded=True):
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            leg['origin'] = st.text_input("Origin(s) (e.g. JFK or SOCAL)", value=leg['origin'], key=f"orig_{i}").upper()
        with col2:
            leg['dest'] = st.text_input("Destination(s)", value=leg['dest'], key=f"dest_{i}").upper()
        with col3:
            leg['date'] = st.date_input("Date", value=leg['date'], key=f"date_{i}", format="MM/DD/YYYY")

        st.caption("Time Filters")
        tcol1, tcol2 = st.columns(2)
        with tcol1:
            dep_range_i = st.select_slider("Departure Window", options=_hours,
                value=(_hours[0], _hours[23]), key=f"dep_range_{i}")
        with tcol2:
            arr_latest_i = st.select_slider("Arrive No Later Than",
                options=_hours + _next_day_arr_hours + ["Any Time"], value="Any Time", key=f"arr_latest_{i}")
        leg_time_filters.append((dep_range_i, arr_latest_i))

        st.divider()
        st.checkbox("🚗 Rent a car when I land?", key=f"car_leg_{i}")


col1, col2 = st.columns([1, 4])
with col1:
    if st.button("➕ Add Leg"):
        st.session_state.legs.append({
            "id": len(st.session_state.legs) + 1,
            "origin": st.session_state.legs[-1]["dest"],
            "dest": st.session_state.legs[0]["origin"],  # default return to home airports
            "date": st.session_state.legs[-1]["date"] + timedelta(days=3)
        })
        st.rerun()
with col2:
    if len(st.session_state.legs) > 1:
        if st.button("🗑️ Remove Last Leg"):
            st.session_state.legs.pop()
            st.rerun()

# Car return date: only shown when the LAST leg has "Rent a car" checked (disappears when a leg is added)
_last_leg_idx = len(st.session_state.legs) - 1
if st.session_state.get(f"car_leg_{_last_leg_idx}", False):
    _default_dropoff = st.session_state.legs[-1]["date"] + timedelta(days=4)
    st.date_input(
        "🚗 Car return date (for last leg rental)",
        value=_default_dropoff,
        key="leg_car_dropoff_date",
        format="MM/DD/YYYY"
    )

if len(st.session_state.legs) >= 2:
    first_origins_raw = st.session_state.legs[0]["origin"]
    st.info(f"↩️ Return flight auto-filtered to land at your departure airport(s): **{first_origins_raw}**")
    st.session_state.return_airport_override = st.checkbox(
        "Override: I'm using a different return airport (Uber/ride from airport)",
        value=st.session_state.return_airport_override,
        key="return_override_cb"
    )

st.divider()

# --- TOURNAMENT SEARCH ---
_scol1, _scol2 = st.columns([4, 1])
with _scol1:
    search_button = st.button("🚀 Run Tournament Search", type="primary", use_container_width=True)
with _scol2:
    if st.session_state.last_search_legs:
        last = st.session_state.last_search_legs
        label = " → ".join(f"{l['origin'].split()[0]}→{l['dest'].split()[0]}" for l in last)
        if st.button(f"↩️ {label}", use_container_width=True, help="Restore the last searched itinerary"):
            import copy
            st.session_state.legs = copy.deepcopy(last)
            # Clear widget keys so Streamlit re-reads from session state
            for k in list(st.session_state.keys()):
                if k.startswith(("orig_", "dest_", "date_")):
                    del st.session_state[k]
            st.rerun()

if search_button:
    # Snapshot legs so "Restore Last Search" can reload them
    import copy
    st.session_state.last_search_legs = copy.deepcopy(st.session_state.legs)

    expanded_legs = []
    for leg in st.session_state.legs:
        o_list = expand_airports(leg['origin'])
        d_list = expand_airports(leg['dest'])
        expanded_legs.append({"leg": leg, "origins": o_list, "dests": d_list})

    st.write("### 🏟️ Tournament Progress")
    progress_bar = st.progress(0)
    status_text = st.empty()

    all_leg_results = []

    try:
        search_engine = SearchFlights()

        for leg_idx, el in enumerate(expanded_legs):
            leg_data = el["leg"]
            leg_results = []

            # All time/stop filtering happens at display time

            valid_origins = [o for o in el["origins"] if o in Airport.__members__]
            valid_dests = [d for d in el["dests"] if d in Airport.__members__]

            if not valid_origins or not valid_dests:
                st.error(f"Invalid Airport Code(s) in Leg {leg_idx+1}")
                st.stop()

            # Search each origin→dest pair individually for complete results
            pairs = [(o, d) for o, d in itertools.product(valid_origins, valid_dests) if o != d]
            for pair_idx, (orig, dest) in enumerate(pairs):
                status_text.text(f"Leg {leg_idx+1}: {orig} ➔ {dest} ({pair_idx+1}/{len(pairs)})...")

                filters = FlightSearchFilters(
                    trip_type=TripType.ONE_WAY,
                    seat_type=SeatType.ECONOMY,
                    stops=MaxStops.ANY,
                    passenger_info=PassengerInfo(adults=1),
                    flight_segments=[
                        FlightSegment(
                            departure_airport=[[Airport[orig], 1]],
                            arrival_airport=[[Airport[dest], 1]],
                            travel_date=leg_data['date'].strftime("%Y-%m-%d")
                        )
                    ]
                )

                try:
                    encoded_filters = filters.encode()
                    response = search_engine.client.post(
                        url=search_engine.BASE_URL,
                        data=f"f.req={encoded_filters}",
                        impersonate="chrome",
                        allow_redirects=True,
                    )
                    raw_text = response.text.lstrip(")]}'")
                    parsed_outer = json.loads(raw_text)
                    if not parsed_outer[0][2]:
                        continue
                    inner_data = json.loads(parsed_outer[0][2])
                except Exception:
                    continue

                # Scan every index in the response — try both [0] and [1] sub-lists per bucket
                # Google puts "Top flights" in bucket[i][0] and "Other flights" in bucket[i][1]
                flight_lists_to_scan = []
                for i_idx in range(len(inner_data)):
                    try:
                        bucket = inner_data[i_idx]
                        if not bucket or not isinstance(bucket, list):
                            continue
                        for sub in [0, 1]:
                            if sub < len(bucket) and isinstance(bucket[sub], list) and bucket[sub]:
                                # Check it looks like a list of flight entries (each item is a list)
                                if isinstance(bucket[sub][0], list):
                                    flight_lists_to_scan.append(bucket[sub])
                    except Exception:
                        continue
                parse_errors = []
                for flight_list in flight_lists_to_scan:
                    for f_raw in flight_list:
                        try:
                            data_main = f_raw[0]
                            # Try multiple price locations — structure varies by fare type
                            price = None
                            for price_path in [
                                lambda r: r[1][0][1],
                                lambda r: r[1][1][1],
                                lambda r: r[1][0][0],
                                lambda r: r[2][0][1],
                            ]:
                                try:
                                    val = price_path(f_raw)
                                    if isinstance(val, (int, float)) and val > 0:
                                        price = val
                                        break
                                except Exception:
                                    pass
                            if price is None:
                                parse_errors.append(f"no price: {str(f_raw)[:120]}")
                                continue

                            # Marketing airline first; fall back through structure variants
                            if data_main[1] and isinstance(data_main[1], list) and data_main[1][0]:
                                airline_name = data_main[1][0]
                            else:
                                airline_name = data_main[0] if data_main[0] else "Unknown"
                            first_seg = data_main[2][0]
                            last_seg = data_main[2][-1]
                            stops_count = len(data_main[2]) - 1

                            layover_cities = []
                            layover_mins_total = 0
                            if stops_count > 0 and len(data_main) > 13 and data_main[13]:
                                for lyr in data_main[13]:
                                    try:
                                        layover_cities.append(lyr[5])
                                        layover_mins_total += lyr[0]
                                    except: pass

                            dep_h = first_seg[8][0]
                            dep_m = first_seg[8][1] if len(first_seg[8]) > 1 else 0
                            arr_h_raw = last_seg[10][0]
                            arr_m = last_seg[10][1] if len(last_seg[10]) > 1 else 0
                            # None hour means next-day arrival (e.g. Frontier 8:30 PM → 12:12 AM+1)
                            next_day = arr_h_raw is None
                            arr_h = 0 if next_day else arr_h_raw

                            # Extract flight number(s) — data at seg[22]: ['IATA','num',None,'Airline']
                            try:
                                seg_nums = []
                                for seg in data_main[2]:
                                    fn_data = seg[22] if len(seg) > 22 else None
                                    if fn_data and isinstance(fn_data, list) and len(fn_data) >= 2:
                                        iata, num = fn_data[0], fn_data[1]
                                        if iata and num:
                                            seg_nums.append(f"{iata}{num}")
                                flight_nums = " / ".join(seg_nums) if seg_nums else "-"
                            except Exception:
                                flight_nums = "-"

                            arr_label = f"{arr_h % 12 or 12}:{arr_m:02d} {'AM' if arr_h < 12 else 'PM'}{' +1' if next_day else ''}"
                            leg_results.append({
                                "From": first_seg[3],
                                "To": last_seg[6],
                                "Airline": airline_name,
                                "Flight #": flight_nums,
                                "Departure": f"{dep_h % 12 or 12}:{dep_m:02d} {'AM' if dep_h < 12 else 'PM'}",
                                "Arrival": arr_label,
                                "_stops": stops_count,
                                "_layover_mins": layover_mins_total,
                                "_dep_mins": dep_h * 60 + dep_m,
                                "_arr_mins": (24 * 60 + arr_m) if next_day else (arr_h * 60 + arr_m),
                                "Via": ", ".join(layover_cities) if layover_cities else "-",
                                "Layover": fmt_dur(layover_mins_total),
                                "Price": price
                            })
                        except Exception as _e:
                            parse_errors.append(str(_e)[:120])
                            continue
                # Always surface parse errors — silent drops are the enemy
                flight_errors = [e for e in parse_errors if "NoneType" not in e and "string index" not in e and "int' object" not in e]
                if flight_errors:
                    st.warning(f"⚠️ Leg {leg_idx+1}: {len(flight_errors)} flight(s) failed to parse and were dropped. Check debug for details.")
                if debug_mode and parse_errors:
                    with st.expander(f"🔬 Leg {leg_idx+1} parse errors ({len(parse_errors)} total, {len(flight_errors)} likely flights)", expanded=True):
                        for err in parse_errors:
                            st.code(err)

            progress_bar.progress((leg_idx + 1) / len(expanded_legs))

            if leg_results:
                all_leg_results.append(leg_results)
            else:
                st.error(f"No flights found for Leg {leg_idx+1}.")
                st.stop()

        # Dedup each leg by (airline, departure, from, to), sort by price
        for i, leg_flights in enumerate(all_leg_results):
            seen = set()
            deduped = []
            for f in leg_flights:
                key = (f['Airline'], f['Departure'], f['From'], f['To'])
                if key not in seen:
                    seen.add(key)
                    deduped.append(f)
            all_leg_results[i] = sorted(deduped, key=lambda x: x['Price'])

        st.session_state.leg_raw_results = all_leg_results
        st.session_state.num_legs = len(all_leg_results)

        # Car search per leg
        car_results_per_leg = [None] * len(all_leg_results)
        legs_list = st.session_state.legs
        for i, leg in enumerate(legs_list):
            if not st.session_state.get(f"car_leg_{i}", False):
                continue
            raw_dest = leg["dest"]
            pickup_airport = re.split(r"[\s,]+", raw_dest)[0].strip().upper()
            expanded = expand_airports(pickup_airport)
            pickup_airport = expanded[0] if expanded else pickup_airport

            d1 = leg["date"].strftime("%Y-%m-%d")
            if i + 1 < len(legs_list):
                d2 = legs_list[i + 1]["date"].strftime("%Y-%m-%d")
            else:
                dropoff = st.session_state.get("leg_car_dropoff_date")
                d2 = dropoff.strftime("%Y-%m-%d") if dropoff else (leg["date"] + timedelta(days=4)).strftime("%Y-%m-%d")

            status_text.text(f"Searching cars at {pickup_airport} ({d1} → {d2})...")
            try:
                results, _ = search_cars(pickup_airport, d1, d2)
                car_results_per_leg[i] = {"airport": pickup_airport, "d1": d1, "d2": d2, "results": results}
            except Exception as e:
                st.warning(f"Car search for leg {i+1} failed: {e}")

        st.session_state.car_results_per_leg = car_results_per_leg
        st.session_state._search_done = True
        st.rerun()

    except Exception as e:
        st.error(f"Tournament failed: {e}")

# --- DISPLAY RESULTS (outside search block so filters work live) ---
if st.session_state.get("_search_done"):
    st.success("✅ Done. Adjust filters on the left to find your best options.")

if st.session_state.leg_raw_results:
    num_legs = st.session_state.num_legs
    free_overrides = st.session_state.free_bag_airlines

    max_layover_map = {"1h": 60, "2h": 120, "3h": 180, "4h": 240, "6h": 360, "8h": 480, "12h": 720}
    min_layover_map = {"30m": 30, "1h": 60, "2h": 120, "3h": 180, "4h": 240}
    stop_limit = {"Non-stop": 0, "1 Stop": 1, "2 Stops": 2}.get(stops)
    max_layover_mins = max_layover_map.get(max_layover)
    min_layover_mins = min_layover_map.get(min_layover)

    # Step 1: Filter each leg independently
    filtered_legs = []
    for n in range(1, num_legs + 1):
        raw = st.session_state.leg_raw_results[n - 1]
        dep_range_i, arr_latest_i = leg_time_filters[n - 1] if n - 1 < len(leg_time_filters) else ((_hours[0], _hours[23]), "Any Time")
        dep_earliest_mins = _hours.index(dep_range_i[0]) * 60
        dep_latest_mins = (_hours.index(dep_range_i[1]) + 1) * 60 - 1
        if arr_latest_i == "Any Time":
            arr_cutoff_mins = None
        elif arr_latest_i in _next_day_arr_hours:
            arr_cutoff_mins = (24 + _next_day_arr_hours.index(arr_latest_i)) * 60
        else:
            arr_cutoff_mins = _hours.index(arr_latest_i) * 60
        leg = [f for f in raw
            if (stop_limit is None or f['_stops'] <= stop_limit)
            and (not max_layover_mins or f['_layover_mins'] == 0 or f['_layover_mins'] <= max_layover_mins)
            and (not min_layover_mins or f['_layover_mins'] == 0 or f['_layover_mins'] >= min_layover_mins)
            and (dep_earliest_mins <= f['_dep_mins'] <= dep_latest_mins)
            and (arr_cutoff_mins is None or f['_arr_mins'] <= arr_cutoff_mins)
            and f['Airline'] not in st.session_state.excluded_airlines
        ]
        filtered_legs.append(leg)

    # Return constraint: last leg must land at first leg's origin airport(s)
    if len(filtered_legs) >= 2 and not st.session_state.return_airport_override:
        first_origins = {a.strip().upper() for a in re.split(r"[\s,]+", st.session_state.legs[0]["origin"]) if a.strip()}
        expanded_first = set()
        for code in first_origins:
            expanded_first.update(expand_airports(code))
        filtered_legs[-1] = [f for f in filtered_legs[-1] if f.get("To", "").upper() in expanded_first]

    # Guard: warn if any leg is empty
    any_empty = False
    for n, leg in enumerate(filtered_legs, 1):
        if not leg:
            st.warning(f"Leg {n} has 0 flights matching current filters. Relax some filters to see results.")
            any_empty = True

    if not any_empty:
        # Pre-compute cheapest car per leg (respecting vendor exclusions)
        cheapest_car = {}
        excluded_vendors = st.session_state.excluded_car_vendors
        car_data_list = st.session_state.car_results_per_leg if st.session_state.car_results_per_leg else []
        for idx, car_data in enumerate(car_data_list):
            if car_data and car_data.get("results"):
                filtered_cars = [r for r in car_data["results"] if r["Vendor"] not in excluded_vendors]
                if filtered_cars:
                    cheapest_car[idx] = filtered_cars[0]

        # Step 2: Cartesian product → build itinerary rows with inline bag fees + car
        all_trips = list(itertools.product(*filtered_legs))
        final_itins = []
        for trip in all_trips:
            row = {}
            total = 0
            for j, f in enumerate(trip):
                n = j + 1
                bag = get_bag_fees(f['Airline'], free_overrides)
                co = bag['carry_on'] if include_carry_on else 0
                ch = bag['checked'] if include_checked else 0
                row[f"{n}: From"] = f['From']
                row[f"{n}: To"] = f['To']
                row[f"{n}: Airline"] = f['Airline']
                row[f"{n}: Flight #"] = f.get('Flight #', '-')
                row[f"{n}: Depart"] = f['Departure']
                row[f"{n}: Arrive"] = f['Arrival']
                row[f"{n}: Via"] = f['Via']
                row[f"{n}: Layover"] = f['Layover']
                row[f"{n}: Flight ($)"] = f['Price']
                row[f"{n}: Carry-on ($)"] = co
                row[f"{n}: Checked ($)"] = ch
                total += f['Price'] + co + ch

                # Google Flights search link for this leg
                leg_date_obj = st.session_state.legs[j]["date"]
                date_str = f"{leg_date_obj.strftime('%B')}+{leg_date_obj.day}+{leg_date_obj.year}"
                row[f"{n}: GF"] = f"https://www.google.com/travel/flights?q=One+way+flights+from+{f['From']}+to+{f['To']}+{date_str}"

                # Add cheapest car rental for this leg
                if j in cheapest_car:
                    car = cheapest_car[j]
                    car_price = car.get("Price_Num", 0)
                    row[f"{n}: Car Vendor"] = car["Vendor"]
                    row[f"{n}: Car"] = car["Vehicle"]
                    row[f"{n}: Car ($)"] = round(car_price, 2)
                    row[f"{n}: Car Link"] = car.get("Link", "")
                    total += car_price

            row["Total ($)"] = round(total, 2)

            # Extra day flag: check if 2h-before-departure dropoff crosses pickup time
            car_notes = []
            for j in range(len(trip)):
                if j not in cheapest_car:
                    continue
                pickup_mins = trip[j]["_arr_mins"]
                if j + 1 < len(trip):
                    dropoff_mins = trip[j + 1]["_dep_mins"] - 120
                    if dropoff_mins > pickup_mins:
                        cutoff_h = pickup_mins // 60
                        cutoff_m = pickup_mins % 60
                        cutoff_ampm = "AM" if cutoff_h < 12 else "PM"
                        cutoff_h12 = cutoff_h % 12 or 12
                        car_notes.append(f"L{j+1} ⚠️ arrive by {cutoff_h12}:{cutoff_m:02d} {cutoff_ampm} to avoid extra day")
                else:
                    car_notes.append(f"L{j+1} (verify return time)")
            if car_notes:
                row["🚗 Car Notes"] = " | ".join(car_notes)

            # Open jaw indicator: does leg 1 depart from same airport as last leg arrives?
            if len(trip) >= 2:
                depart_from = trip[0]["From"]
                return_to = trip[-1]["To"]
                row["Routing"] = "✅ Matched" if depart_from == return_to else f"↔️ Open Jaw ({depart_from}→{return_to})"

            final_itins.append(row)

        df = pd.DataFrame(final_itins).drop_duplicates().reset_index(drop=True)
        df = df.sort_values("Total ($)").reset_index(drop=True)

        # Remove open-jaw itineraries: must depart and return to the exact same airport (car is parked there)
        if num_legs >= 2 and "Routing" in df.columns:
            df = df[df["Routing"] == "✅ Matched"].reset_index(drop=True)

        # Store price range for sidebar slider (before price filtering so range stays stable)
        if not df.empty:
            st.session_state._price_range_min = int(df["Total ($)"].min())
            st.session_state._price_range_max = int(df["Total ($)"].max())

        # Apply price range filter from sidebar slider
        df = df[(df["Total ($)"] >= price_filter[0]) & (df["Total ($)"] <= price_filter[1])].reset_index(drop=True)

        flight_cols = [f"{n}: Flight ($)" for n in range(1, num_legs + 1)]
        airline_display_cols = [f"{n}: Airline" for n in range(1, num_legs + 1)]

        def flight_key(row):
            return tuple(row[c] for c in flight_cols + airline_display_cols if c in row.index)

        # Hide individually hidden flights
        if st.session_state.hidden_flight_keys:
            df = df[~df.apply(flight_key, axis=1).isin(st.session_state.hidden_flight_keys)]

        col_config = {"Total ($)": st.column_config.NumberColumn("Total ($)", format="$%.2f")}
        if "🚗 Car Notes" in df.columns:
            col_config["🚗 Car Notes"] = st.column_config.TextColumn("🚗 Car Notes", width="large")
        for col in df.columns:
            if col.endswith(": Flight ($)") or col.endswith(": Carry-on ($)") or col.endswith(": Checked ($)"):
                col_config[col] = st.column_config.NumberColumn(col, format="$%d")
            if col.endswith(": Car ($)"):
                col_config[col] = st.column_config.NumberColumn(col, format="$%.2f")
            if col.endswith(": Car Link"):
                col_config[col] = st.column_config.LinkColumn(col, display_text="Book →")
            if col.endswith(": GF"):
                col_config[col] = st.column_config.LinkColumn(col, display_text="🔍 Google")

        st.markdown("""
        <style>
        [data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th {
            text-align: center !important;
        }
        </style>
        """, unsafe_allow_html=True)

        # Build chronological column order: Total ($) first, then per-leg fields, then Routing / Car Notes
        detail_cols = []
        for n in range(1, num_legs + 1):
            for suffix in ["From", "To", "Airline", "Flight #", "Depart", "Arrive", "Via", "Layover",
                           "Flight ($)", "Carry-on ($)", "Checked ($)", "GF",
                           "Car Vendor", "Car", "Car ($)", "Car Link"]:
                col = f"{n}: {suffix}"
                if col in df.columns:
                    detail_cols.append(col)
        if "🚗 Car Notes" in df.columns:
            detail_cols.append("🚗 Car Notes")
        ordered_cols = ["Total ($)"] + detail_cols

        df = df[ordered_cols]
        view_df = df.head(top_n).reset_index(drop=True)
        st.success(f"Showing {len(view_df)} of {len(df)} combinations.")
        st.caption("💡 Select rows to pin for comparison or hide them.")

        event = st.dataframe(
            view_df,
            use_container_width=True,
            column_config=col_config,
            on_select="rerun",
            selection_mode="multi-row"
        )

        if event and event.selection.rows:
            selected_rows = event.selection.rows
            c1, c2 = st.columns(2)
            with c1:
                if st.button(f"📌 Pin {len(selected_rows)} selected for comparison"):
                    for idx in selected_rows:
                        row = view_df.iloc[idx].to_dict()
                        if row not in st.session_state.pinned_flights:
                            st.session_state.pinned_flights.append(row)
                    st.rerun()
            with c2:
                if st.button(f"🙈 Hide {len(selected_rows)} selected"):
                    for idx in selected_rows:
                        key = flight_key(view_df.iloc[idx])
                        st.session_state.hidden_flight_keys.add(key)
                    st.rerun()

        # CSV download (full filtered result set, not just top-N)
        st.divider()
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label=f"⬇️ Download CSV ({len(df)} rows)",
            data=csv_bytes,
            file_name="ernspedia_results.csv",
            mime="text/csv",
        )

        # Pinned comparison table
        if st.session_state.pinned_flights:
            st.divider()
            st.subheader("📌 Pinned for Comparison")
            pinned_df = pd.DataFrame(st.session_state.pinned_flights)
            for n in range(1, num_legs + 1):
                if f"{n}: Airline" in pinned_df.columns:
                    pfees = pinned_df[f"{n}: Airline"].apply(lambda a: get_bag_fees(a, free_overrides))
                    pinned_df[f"{n}: Carry-on ($)"] = pfees.apply(lambda f: f["carry_on"] if include_carry_on else 0)
                    pinned_df[f"{n}: Checked ($)"] = pfees.apply(lambda f: f["checked"] if include_checked else 0)
            p_bag_cols = [f"{n}: Carry-on ($)" for n in range(1, num_legs + 1)] + [f"{n}: Checked ($)" for n in range(1, num_legs + 1)]
            p_car_cols = [f"{n}: Car ($)" for n in range(1, num_legs + 1)]
            all_cost_cols = flight_cols + p_bag_cols + p_car_cols
            if all(c in pinned_df.columns for c in flight_cols):
                pinned_df["Total ($)"] = pinned_df[[c for c in all_cost_cols if c in pinned_df.columns]].sum(axis=1)
            st.dataframe(pinned_df, use_container_width=True, column_config=col_config)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Clear pinned"):
                    st.session_state.pinned_flights = []
                    st.rerun()
            with c2:
                pinned_csv = pinned_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label=f"⬇️ Download pinned ({len(pinned_df)} rows)",
                    data=pinned_csv,
                    file_name="ernspedia_pinned.csv",
                    mime="text/csv",
                )

        # Per-leg breakdown (hidden by default)
        with st.expander("🔍 Show per-leg options (pre-combination)"):
            for n in range(1, num_legs + 1):
                raw = st.session_state.leg_raw_results[n - 1]
                raw_count = len(raw)
                filtered_count = len(filtered_legs[n - 1])
                st.caption(f"Leg {n}: {filtered_count} flights after filters (of {raw_count} found)")

                raw_airlines = sorted({f["Airline"] for f in raw})
                filtered_airlines = sorted({f["Airline"] for f in filtered_legs[n - 1]})
                dropped = sorted(set(raw_airlines) - set(filtered_airlines))
                st.caption(f"✅ In results: {', '.join(filtered_airlines) or 'none'}")
                if dropped:
                    st.warning(f"⚠️ Filtered OUT for Leg {n}: {', '.join(dropped)} — check stops/layover/time filters")

                if filtered_legs[n - 1]:
                    leg_df = pd.DataFrame(filtered_legs[n - 1])
                    leg_df = leg_df.drop(columns=[c for c in leg_df.columns if c.startswith("_")])
                    st.dataframe(leg_df, use_container_width=True)

            # Car vendor options per leg
            car_data_list = st.session_state.car_results_per_leg if st.session_state.car_results_per_leg else []
            for idx, car_data in enumerate(car_data_list):
                if car_data and car_data["results"]:
                    st.caption(f"Leg {idx+1} car options at {car_data['airport']} ({car_data['d1']} → {car_data['d2']})")
                    car_browse_df = pd.DataFrame(car_data["results"]).drop(columns=["Price_Num"], errors="ignore")
                    st.dataframe(car_browse_df, use_container_width=True, hide_index=True,
                                 column_config={"Link": st.column_config.LinkColumn("Link", display_text="Book →")})
