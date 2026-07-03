# Sublease Dashboard

Scrapes GroupMe housing groups, uses Gemini AI to filter genuine sublease offers, and generates an interactive HTML dashboard.

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/safa1640-afk/SubleaseDashboard.git
cd SubleaseDashboard
```

**2. Create a virtual environment and install dependencies**
```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**3. Add your API keys and group IDs**

Copy the example env file and fill it in:
```bash
cp .env.example .env
```

Then edit `.env` with your values:

- **`GROUPME_ACCESS_TOKEN`** → log in at [dev.groupme.com](https://dev.groupme.com) — your token is displayed on the page
- **`GOOGLE_API_KEY`** → create one at [aistudio.google.com](https://aistudio.google.com) (free, just needs a Google account)
- **`GROUPME_GROUP_IDS`** → comma-separated list of GroupMe group IDs you want to scan (e.g. `123456,789012`)

**Finding your Group IDs:**
1. Open [web.groupme.com](https://web.groupme.com) in a browser
2. Click into the group you want to scan
3. The URL will look like `https://web.groupme.com/groups/61441708` — the number at the end is the group ID
4. Add as many as you want, separated by commas: `GROUPME_GROUP_IDS=61441708,100216530`

## Usage

**Run the dashboard server:**
```bash
python app.py
```
Open [http://127.0.0.1:5001](http://127.0.0.1:5001) in your browser. The first load scans back to January 1 2026. From then on, just click **Update** on the dashboard whenever you want fresh listings — it only fetches messages newer than the last sync (tracked in `last_synced.json`), runs them through Gemini, and appends any confirmed listings without re-scanning or re-classifying anything already seen.

**Command-line alternative (no server):**
```bash
python GroupMeParser.py   # incremental fetch + filter, appends to subleases_bulkV3.txt
python DashboardScript.py # regenerates a static index.html from that file
```

## Notes

- The free Gemini tier allows 1,500 requests/day — more than enough for a full run
- The script paces itself at ~15 requests/minute to stay within rate limits
- Output files (`.txt`, `.html`, `last_synced.json`) are gitignored since they contain scraped data / local state
