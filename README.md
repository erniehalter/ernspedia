# ✈️ Ernspedia: Tournament Flight Search

A powerful Streamlit-based flight search engine that finds all flight combinations across multiple origin and destination airports, then displays them as sortable tournament brackets with optional car rental search.

## 🚀 How to Run

1. **Navigate to the project folder:**
   ```bash
   cd /Users/erniehalter/Desktop/CODING/PYTHON/google_flights_api
   ```

2. **Activate the virtual environment:**
   ```bash
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the Streamlit app:**
   ```bash
   streamlit run ernspedia.py
   ```

## ✨ Features

- **Tournament Flight Search:** Search all origin/destination combinations and view results as a sortable table
- **Multi-leg Itineraries:** Build multi-leg trips with flexible routing
- **Airport Shortcuts:** Use shortcuts like "SOCAL" (BUR, LAX, ONT, LGB, SNA) and "NORCAL" (SFO, OAK, SJC)
- **Advanced Filtering:** Filter by stops, layover duration, departure/arrival times, and airlines
- **Baggage Cost Calculation:** Automatically adds baggage fees based on airline rules
- **Flight Pinning:** Pin flights for side-by-side comparison
- **Car Rental Search:** Integrated car rental search via Expedia and Kayak
- **Live Filter Updates:** All filters work dynamically without re-running searches

## 📦 Dependencies

- `streamlit` - Web app framework
- `pandas` - Data manipulation and display
- `fli` - Google Flights API library
- `playwright` - Browser automation for car rental scraping
- `playwright-stealth` - Bypass anti-bot detection
- `pytz` - Timezone support

Install all with: `pip install -r requirements.txt`

## 🔍 Usage Tips

- Use commas or spaces to separate multiple airports in the origin/destination fields
- Create airport shortcuts by editing the `SHORTCUTS` dict in the main code
- The baggage rules are loaded from `baggage_rules.json` if available
- Run without filters first to see all options, then refine with sidebar controls
