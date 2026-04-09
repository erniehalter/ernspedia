# Ernspedia: Tournament Flight Search

A Streamlit app that searches all combinations of origin and destination airports via Google Flights, then displays results as a sortable table with filtering. Includes car rental search via Expedia/Kayak scraping.

## GitHub
- Repo: https://github.com/erniehalter/ernspedia

## Stack
- Python + Streamlit (web UI)
- `fli` library (Google Flights API wrapper)
- `playwright` (car rental scraping)
- `pandas` (data display)

## Run locally
```bash
source venv/bin/activate
streamlit run ernspedia.py
```
Opens at http://localhost:8501

## Key files
- `ernspedia.py` — main Streamlit app
- `expedia_engine.py` — car rental scraping logic
- `baggage_rules.json` — airline baggage fee data
- `airport_id_library.json` — airport code lookup
- `requirements.txt` — Python dependencies

## API
- Uses `fli` (PyPI: `flights`, github.com/punitarani/fli) — an open-source unofficial Google Flights scraper
- No API key, no account, no cost — scrapes Google Flights directly
- No published rate limits; heavy use could trigger Google throttling
- Rental car results (Booking.com) use RapidAPI — `booking-com18.p.rapidapi.com` — free tier: 530 requests/month. Key stored in `.env` as `RAPIDAPI_KEY`. Pricing: https://rapidapi.com/ntd119/api/booking-com18/pricing

## Notes
- Safe to move or rename this folder — no hardcoded paths in the project code
- venv must be rebuilt after moving: `python3 -m venv venv && pip install -r requirements.txt`
- Supports airport shortcuts like "SOCAL" and "NORCAL" (edit `SHORTCUTS` dict in ernspedia.py)
