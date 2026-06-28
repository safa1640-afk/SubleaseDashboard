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
GROUP_IDS = ["61441708", "100216530"]
OUTPUT_FILE = "subleases_bulkV3.txt"
FLYERS_FILE = "potential_flyers_bulk.txt"
LIMIT_PER_REQUEST = 100

START_TIMESTAMP = int(datetime(2026, 1, 1).timestamp())

# Positive keywords — word boundaries prevent substring false matches
SUBLEASE_KEYWORDS = [
    r"\bsublease\b", r"\bsublet\b", r"\bsummer\b",
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
    """Stable hash for deduplication across groups."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.md5(normalized.encode()).hexdigest()


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


def classify_message(text, retries=3):
    """
    Ask Gemini whether a message is a genuine sublease offer.
    Retries with exponential backoff on rate-limit / transient errors.
    Returns YES or NO.
    """

    prompt = f"""

Is this message offering housing for rent, sublease, relet, or lease takeover?

Reply ONLY with valid JSON in exactly one of these formats:

{{"sublease": true}}

or

{{"sublease": false}}

Message:
{text}
"""

    delay = 5

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

            return "YES" if data.get("sublease") is True else "NO"

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
                print(
                    f"  API Error (all retries exhausted): "
                    f"{err}. Skipping message."
                )
                return "NO"




def main():
    print("Starting sublease extraction (V3) with AI filtering...")
    total_saved = 0
    total_flyers = 0

    # Tracks content hashes across all groups to deduplicate cross-posted messages
    seen_hashes = set()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f, \
         open(FLYERS_FILE, "w", encoding="utf-8") as flyer_file:

        for group_id in GROUP_IDS:
            print(f"\nScanning Group ID: {group_id}")
            before_id = None
            group_saved = 0
            flyer_saved = 0
            reached_cutoff = False

            while not reached_cutoff:
                messages = fetch_messages(group_id, ACCESS_TOKEN, before_id)

                if messages is None:
                    time.sleep(3)
                    continue

                if not messages:
                    print(f"  Reached the beginning of group {group_id}.")
                    break

                for msg in messages:
                    created_at_unix = msg.get("created_at", 0)

                    if created_at_unix < START_TIMESTAMP:
                        print(f"  Reached January 2026 cutoff for group {group_id}.")
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
                        # Cross-group dedup: skip exact same content already saved from another group
                        h = content_hash(text)
                        if h in seen_hashes:
                            print(f"  Skipping cross-group duplicate: {text[:40].replace(chr(10), ' ')}...")
                            continue

                        print(f"  Testing: {text[:40].replace(chr(10), ' ')}...")
                        decision = classify_message(text)

                        if decision == "YES":
                            print("  -> AI Confirmed! Saving.")
                            seen_hashes.add(h)
                            f.write("--- SUBLEASE ENTRY START ---\n")
                            f.write(f"GROUP ID: {group_id}\n")
                            f.write(f"DATE: {date_str}\n")
                            f.write(f"IMAGE ATTACHED: {has_image}\n")
                            f.write(f"IMAGE URL: {image_url}\n")
                            f.write(f"CONTENT:\n{text}\n")
                            f.write("--- SUBLEASE ENTRY END ---\n\n")
                            group_saved += 1
                            total_saved += 1
                        else:
                            print("  -> AI Rejected.")

                        # 4s delay keeps us under the 15 RPM free-tier limit
                        time.sleep(4)

                    elif has_image == "YES" and not text.strip():
                        flyer_file.write("--- FLYER ENTRY START ---\n")
                        flyer_file.write(f"GROUP ID: {group_id}\n")
                        flyer_file.write(f"DATE: {date_str}\n")
                        flyer_file.write(f"IMAGE URL: {image_url}\n")
                        flyer_file.write("[Image Only]\n")
                        flyer_file.write("--- FLYER ENTRY END ---\n\n")
                        flyer_saved += 1
                        total_flyers += 1

                if not reached_cutoff and messages:
                    before_id = messages[-1]["id"]
                    print(f"  Processed down to: {datetime.fromtimestamp(messages[-1].get('created_at', 0)).strftime('%Y-%m-%d')}")
                    time.sleep(0.5)

            print(f"Finished Group {group_id}. Saved {group_saved} listings and {flyer_saved} image flyers.")

    print(f"\nAll done! Saved {total_saved} confirmed listings to '{OUTPUT_FILE}'.")
    print(f"Saved {total_flyers} image-only entries to '{FLYERS_FILE}'.")


if __name__ == "__main__":
    main()
