import os
import json
import time
import hashlib
import urllib.request
import re
from datetime import datetime
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

# ==========================================
# CONFIGURATION
# ==========================================
ACCESS_TOKEN = os.getenv("GROUPME_ACCESS_TOKEN")
GROUP_IDS = [g.strip() for g in os.getenv("GROUPME_GROUP_IDS", "").split(",") if g.strip()]
OUTPUT_FILE = "subleases_bulkV3.txt"
FLYERS_FILE = "potential_flyers_bulk.txt"
STATE_FILE = "last_synced.json"
LIMIT_PER_REQUEST = 100

# What Gemini should treat as a relevant listing; change it in .env, no code edits needed
TARGET_TERM = os.getenv("TARGET_TERM", "Spring 2027 or Summer 2027")

# Fallback cutoff used only the very first time a group is synced
START_TIMESTAMP = int(datetime(2026, 1, 1).timestamp())

# Positive keywords — word boundaries prevent substring false matches
SUBLEASE_KEYWORDS = [
    r"\bsublease\w*", r"\bsublet\w*", r"\brelet\w*", r"\bsummer\b", r"\bspring\b",
    r"\blease\b", r"\brent\b", r"\broom\b", r"\bapartment\b"
]

# Negative keywords — only items that could NEVER appear in a housing post.
# Using word boundaries to avoid false matches (e.g. "tv" inside "university").
# Removed: selling, sold, buying, storage, bike, chair, tv — these legitimately
# appear in sublease listings ("furnished with a chair", "bike storage included").
EXCLUDE_PATTERNS = [
    r"\bipad\b", r"\bapple\s+pencil\b", r"\bmonitor\b",
    r"\bboilervault\b", r"\btickets?\b",
]


def content_hash(text):
    """Stable hash for deduplication across groups and across runs."""
    # An edited message is re-sent as: Name edited to: “original text”. Treat it as the original.
    text = re.sub(r"^[^\n]{0,60}?\bedited to:\s*[“\"]?", "", text.strip(), flags=re.IGNORECASE).rstrip("”\"")
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.md5(normalized.encode()).hexdigest()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def load_existing_hashes():
    """Read whatever's already in OUTPUT_FILE so appended runs don't duplicate entries."""
    hashes = set()
    if not os.path.exists(OUTPUT_FILE):
        return hashes

    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    for entry in content.split("--- SUBLEASE ENTRY START ---"):
        match = re.search(r"CONTENT:\s*\n([\s\S]*?)\n--- SUBLEASE ENTRY END ---", entry)
        if match:
            hashes.add(content_hash(match.group(1)))

    return hashes


def fetch_messages(group_id, token, before_id=None):
    url = (
        f"https://api.groupme.com/v3/groups/{group_id}/messages"
        f"?token={token}&limit={LIMIT_PER_REQUEST}"
    )
    if before_id:
        url += f"&before_id={before_id}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return data.get("response", {}).get("messages", [])
    except Exception as e:
        print(f"  Error fetching data for group {group_id}: {e}")
        return None
    return []


def classify_message(text, retries=5):
    """
    Ask Gemini whether a message is a genuine sublease offer.
    Retries with exponential backoff on rate-limit / transient errors.
    Returns a dict: {"sublease": False}, or {"sublease": True, rent, layout, gender,
    location, term}. Raises RuntimeError if Gemini keeps failing.
    """

    prompt = f"""

Today's date is {datetime.now().strftime("%B %d, %Y")}.

Is this message OFFERING housing (rent, sublease, relet, or lease takeover) that would be
available for: {TARGET_TERM}?

Rules:
- Posts covering multiple terms count if one of them matches (e.g. "Spring/Summer sublease").
- Posts with no dates at all count, since they are probably current.
- Reject posts that are only for a term that has already passed or a different, non-matching term.
- Reject people who are LOOKING for housing or a roommate rather than offering a place.

If it IS a matching offer, also extract these fields from the post (use null when not stated):
- "rent": monthly rent for ONE person's spot, as an integer in USD. Ignore parking, deposits,
  fees, utilities and one-time costs. If a total and a per-person price are both given, use per-person.
- "layout": the whole unit as "<beds>B/<baths>B" (e.g. "2B/2B"), or "Studio".
- "gender": "Female Only" or "Male Only" if the post restricts or prefers one, else "Co-ed / Any".
- "location": the apartment complex name or street address, as written in the post.
- "term": the dates or semesters it is available, short (e.g. "Jan 2027 - Jul 2027").

Reply ONLY with valid JSON in exactly one of these formats:

{{"sublease": true, "rent": 850, "layout": "2B/2B", "gender": "Co-ed / Any", "location": "The Lark", "term": "May 2027 - Aug 2027"}}

or

{{"sublease": false}}

Message:
{text}
"""

    delay = 15

    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt,
            )

            raw = response.text.strip()

            # Remove markdown code fences if present
            raw = raw.replace("```json", "")
            raw = raw.replace("```", "")
            raw = raw.strip()

            data = json.loads(raw)

            return data if data.get("sublease") is True else {"sublease": False}

        except Exception as e:
            err = str(e)

            if attempt < retries - 1:
                print(
                    f"  API Error (attempt {attempt + 1}/{retries}): "
                    f"{err}. Retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2
            else:
                # Don't guess "NO": that would drop a real listing for good once the
                # sync cutoff moves past it. Abort so the next run re-checks it.
                raise RuntimeError(f"Gemini classification failed after {retries} attempts: {err}")


def entry_fields(info):
    """AI-extracted fields as header lines for a saved entry; the dashboard reads these."""
    def one_line(v):
        if v in (None, "") or str(v).strip().lower() == "null":
            return "UNKNOWN"
        # models sometimes write ranges like "Jan 2027 - null"
        return re.sub(r"\s*[-–]\s*null\b", "", re.sub(r"\s+", " ", str(v))).strip()

    return (
        f"RENT: {one_line(info.get('rent'))}\n"
        f"LAYOUT: {one_line(info.get('layout'))}\n"
        f"GENDER: {one_line(info.get('gender') or 'Co-ed / Any')}\n"
        f"LOCATION: {one_line(info.get('location'))}\n"
        f"TERM: {one_line(info.get('term'))}\n"
    )


def sync(group_ids=None, progress=print):
    """
    Fetch messages newer than the last synced timestamp for each group,
    classify candidates, and append confirmed listings to OUTPUT_FILE.

    Returns the number of newly confirmed listings saved.
    """
    group_ids = group_ids if group_ids is not None else GROUP_IDS
    state = load_state()
    seen_hashes = load_existing_hashes()

    total_saved = 0
    total_flyers = 0

    with open(OUTPUT_FILE, "a", encoding="utf-8") as f, \
         open(FLYERS_FILE, "a", encoding="utf-8") as flyer_file:

        for group_id in group_ids:
            cutoff = state.get(group_id, START_TIMESTAMP)
            progress(f"\nScanning Group ID: {group_id} (since {datetime.fromtimestamp(cutoff)})")

            before_id = None
            group_saved = 0
            flyer_saved = 0
            reached_cutoff = False
            newest_seen = cutoff

            while not reached_cutoff:
                messages = fetch_messages(group_id, ACCESS_TOKEN, before_id)

                if messages is None:
                    time.sleep(3)
                    continue

                if not messages:
                    progress(f"  Reached the beginning of group {group_id}.")
                    break

                if before_id is None and messages:
                    newest_seen = max(newest_seen, messages[0].get("created_at", 0))

                for msg in messages:
                    created_at_unix = msg.get("created_at", 0)

                    if created_at_unix <= cutoff:
                        reached_cutoff = True
                        break

                    text = msg.get("text") or ""
                    attachments = msg.get("attachments") or []

                    has_image = "NO"
                    image_url = "NONE"
                    for att in attachments:
                        if att.get("type") == "image":
                            has_image = "YES"
                            image_url = att.get("url", "NONE")
                            break

                    text_lower = text.lower()
                    date_str = datetime.fromtimestamp(created_at_unix).strftime("%Y-%m-%d %H:%M:%S")

                    is_sublease_mention = any(re.search(kw, text_lower) for kw in SUBLEASE_KEYWORDS)
                    is_noise = any(re.search(pat, text_lower) for pat in EXCLUDE_PATTERNS)

                    if is_sublease_mention and not is_noise:
                        h = content_hash(text)
                        if h in seen_hashes:
                            progress(f"  Skipping duplicate: {text[:40].replace(chr(10), ' ')}...")
                            continue

                        progress(f"  Testing: {text[:40].replace(chr(10), ' ')}...")
                        info = classify_message(text)

                        if info["sublease"]:
                            progress("  -> AI Confirmed! Saving.")
                            seen_hashes.add(h)
                            f.write("--- SUBLEASE ENTRY START ---\n")
                            f.write(f"GROUP ID: {group_id}\n")
                            f.write(f"DATE: {date_str}\n")
                            f.write(f"IMAGE ATTACHED: {has_image}\n")
                            f.write(f"IMAGE URL: {image_url}\n")
                            f.write(entry_fields(info))
                            f.write(f"CONTENT:\n{text}\n")
                            f.write("--- SUBLEASE ENTRY END ---\n\n")
                            f.flush()
                            group_saved += 1
                            total_saved += 1
                        else:
                            progress("  -> AI Rejected.")

                        # 4s delay keeps us under the 15 RPM free-tier limit
                        time.sleep(4)

                    elif has_image == "YES" and not text.strip():
                        flyer_file.write("--- FLYER ENTRY START ---\n")
                        flyer_file.write(f"GROUP ID: {group_id}\n")
                        flyer_file.write(f"DATE: {date_str}\n")
                        flyer_file.write(f"IMAGE URL: {image_url}\n")
                        flyer_file.write("[Image Only]\n")
                        flyer_file.write("--- FLYER ENTRY END ---\n\n")
                        flyer_file.flush()
                        flyer_saved += 1
                        total_flyers += 1

                if not reached_cutoff and messages:
                    before_id = messages[-1]["id"]
                    progress(f"  Processed down to: {datetime.fromtimestamp(messages[-1].get('created_at', 0)).strftime('%Y-%m-%d')}")
                    time.sleep(0.5)

            state[group_id] = newest_seen
            progress(f"Finished Group {group_id}. Saved {group_saved} new listings and {flyer_saved} new image flyers.")

    save_state(state)
    progress(f"\nSync complete. Saved {total_saved} newly confirmed listings, {total_flyers} new image-only entries.")
    return total_saved


def main():
    print("Starting sublease extraction (V3) with AI filtering...")
    sync()


if __name__ == "__main__":
    main()
