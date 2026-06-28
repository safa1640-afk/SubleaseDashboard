# Sublease Dashboard

Scrapes GroupMe housing groups, uses Gemini AI to filter genuine sublease offers, and generates an interactive HTML dashboard.

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/safa1640-afk/SubleaseDashboard.git
cd SubleaseDashboard
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Add your API keys**

Copy the example env file and fill it in:
```bash
cp .env.example .env
```

- **GroupMe token** → log in at [dev.groupme.com](https://dev.groupme.com), your token is shown on the page
- **Gemini API key** → create one at [aistudio.google.com](https://aistudio.google.com) (free, just needs a Google account)

**4. Set your Group IDs**

In `GroupMeParser.py`, update `GROUP_IDS` with the GroupMe group IDs you want to scan. You can find a group's ID in its URL on the GroupMe web app.

## Usage

**Step 1 — Fetch and filter listings:**
```bash
python GroupMeParser.py
```
This scans your groups, runs each candidate message through Gemini, and writes confirmed listings to `subleases_bulkV3.txt`.

**Step 2 — Build the dashboard:**
```bash
python DashboardScript.py
```
Opens `index.html` — open it in any browser. Supports filtering by price, gender preference, and image, with live search.

## Notes

- The free Gemini tier allows 1,500 requests/day — more than enough for a full run
- The script paces itself at ~15 requests/minute to stay within rate limits
- Output files (`.txt`, `.html`) are gitignored since they contain scraped data
