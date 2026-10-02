import json
import os
import re
from datetime import datetime

def parse_bulk_file(filename="subleases_bulkV3.txt"):
    if not os.path.exists(filename):
        return []

    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()

    entries = content.split("--- SUBLEASE ENTRY START ---")
    parsed_listings = []

    for entry in entries:
        if "--- SUBLEASE ENTRY END ---" not in entry:
            continue

        # Extract structural fields using basic regex
        group_id_match = re.search(r"GROUP ID:\s*(\d+)", entry)
        date_match = re.search(r"DATE:\s*([\d\-\s:]+)", entry)
        image_match = re.search(r"IMAGE ATTACHED:\s*(YES|NO)", entry)
        url_match = re.search(r"IMAGE URL:\s*(http[^\n]+|NONE)", entry)

        # Extract message content body
        content_block = ""
        content_search = re.search(
            r"CONTENT:\s*\n([\s\S]*?)\n--- SUBLEASE ENTRY END ---", entry
        )
        if content_search:
            content_block = content_search.group(1).strip()

        if not content_block or "[Image Only]" in content_block:
            continue

        group_id = group_id_match.group(1) if group_id_match else "Unknown"
        date_str = date_match.group(1).strip() if date_match else "Unknown"
        has_image = image_match.group(1) if image_match else "NO"
        img_url = url_match.group(1).strip() if url_match and url_match.group(1) != "NONE" else ""

        # High-accuracy data extraction heuristics
        price_match = re.search(r"\$(\d{3,4})", content_block)
        price = f"${price_match.group(1)}" if price_match else "Unlisted"

        layout_match = re.search(r"(\d)\s*[bB](?:ed|R).+?(\d)\s*[bB](?:ath|A)", content_block)
        if not layout_match:
            layout_match = re.search(r"(\d)\s*b\s*\/\s*(\d)\s*b", content_block, re.IGNORECASE)
        layout = f"{layout_match.group(1)}B/{layout_match.group(2)}B" if layout_match else "Unknown"

        gender = "Co-ed / Any"
        if re.search(r"\bfemale\b", content_block, re.IGNORECASE) or re.search(r"\bgirls\b", content_block, re.IGNORECASE):
            gender = "Female Only"
        elif re.search(r"\bmale\b", content_block, re.IGNORECASE) or re.search(r"\bguys\b", content_block, re.IGNORECASE):
            gender = "Male Only"

        # Location: try named complex first, then street address, then city fallback
        location = "Unknown"
        complex_match = re.search(
            r"\b(lark|hub|lodge|verve|rise|fuse|station|grant|campus|walk|chauncey|the cottages|"
            r"the districts|vie|aspire|HERE|evolve|sterling|landmark|summit|meadows|the flats)\b",
            content_block, re.IGNORECASE
        )
        if complex_match:
            location = complex_match.group(1).title()
        else:
            # Street address: "123 N/S Street Name St/Ave/Dr/Rd/Blvd/Ln/Way/Ct"
            addr_match = re.search(
                r"\d+\s+[NSEW]\.?\s+\w+(?:\s+\w+)?\s+(?:St|Ave|Dr|Rd|Blvd|Ln|Way|Ct|Circle|Place|Pl)\b",
                content_block, re.IGNORECASE
            )
            if addr_match:
                location = addr_match.group(0).strip()
            else:
                # City fallback
                city_match = re.search(r"\b(West Lafayette|Lafayette)\b", content_block, re.IGNORECASE)
                if city_match:
                    location = city_match.group(1).title()

        # AI-extracted header fields (written by GroupMeParser) beat the regex guesses above.
        # Entries saved before those fields existed just keep the regex values.
        header = entry.split("CONTENT:")[0]

        def header_field(name):
            m = re.search(rf"^{name}:[ \t]*(.+)$", header, re.MULTILINE)
            v = m.group(1).strip() if m else ""
            return "" if v.upper() == "UNKNOWN" else v

        if header_field("RENT").isdigit():
            price = f"${header_field('RENT')}"
        layout = header_field("LAYOUT") or layout
        gender = header_field("GENDER") or gender
        location = header_field("LOCATION") or location
        term = header_field("TERM")

        clean_text = content_block.replace("\n", "<br>")

        parsed_listings.append(
            {
                "date": date_str,
                "group": "Group 1" if group_id == "61441708" else "Group 2",
                "location": location,
                "price": price,
                "layout": layout,
                "term": term,
                "gender": gender,
                "image": has_image,
                "image_url": img_url,
                "details": clean_text,
            }
        )

    return parsed_listings

def render_html(listings):
    json_data = json.dumps(listings)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sublease Dashboard</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f4f4f9; padding: 20px; }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .controls {{ display: flex; gap: 15px; justify-content: center; margin-bottom: 20px; flex-wrap: wrap; }}
        select, input {{ padding: 10px; border-radius: 6px; border: 1px solid #ccc; font-size: 14px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }}
        .card {{ background: white; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); display: flex; flex-direction: column; }}
        .card-header {{ font-weight: bold; font-size: 18px; margin-bottom: 10px; color: #333; }}
        .tags {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 15px; }}
        .tag {{ background: #eee; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; color: #555; }}
        .tag.price {{ background: #e6f4ea; color: #1e8e3e; }}
        .tag.gender {{ background: #fce8e6; color: #d93025; }}
        .card-body {{ font-size: 14px; color: #444; line-height: 1.5; flex-grow: 1; }}
        .card-footer {{ margin-top: 15px; font-size: 12px; color: #888; border-top: 1px solid #eee; padding-top: 10px; }}
    </style>
</head>
<body>

<div class="header">
    <h1>Housing Offers Dashboard</h1>
    <p>Filtered genuinely extracted offers.</p>
</div>

<div class="controls">
    <input type="text" id="searchInput" placeholder="Search locations or details..." onkeyup="filterCards()">
    <select id="genderFilter" onchange="filterCards()">
        <option value="all">All Genders</option>
        <option value="Female Only">Female Only</option>
        <option value="Male Only">Male Only</option>
        <option value="male_and_coed">Male & Co-ed</option>
    </select>
    <select id="imageFilter" onchange="filterCards()">
        <option value="all">Images & Text</option>
        <option value="YES">Has Image Attached</option>
        <option value="NO">Text Only</option>
    </select>
    <select id="sortFilter" onchange="filterCards()">
        <option value="newest">Sort by: Newest</option>
        <option value="lowToHigh">Sort by: Price (Low to High)</option>
    </select>
    <div style="display:flex; align-items:center; gap:8px;">
        <label for="maxPrice" style="font-size:14px; color:#555;">Max $</label>
        <input type="number" id="maxPrice" placeholder="e.g. 900" min="0" step="50"
               style="width:110px;" oninput="filterCards()">
    </div>
    <button id="updateBtn" onclick="runUpdate()"
            style="padding:10px 18px; border-radius:6px; border:none; background:#1e8e3e; color:white; font-size:14px; font-weight:600; cursor:pointer;">
        Update
    </button>
</div>

<p id="updateStatus" style="text-align:center; font-size:13px; color:#888; margin-bottom:8px;"></p>
<p id="resultCount" style="text-align:center; font-size:14px; color:#888; margin-bottom:16px;"></p>
<div class="grid" id="cardContainer"></div>

<script>
    let data = {json_data};
    const container = document.getElementById('cardContainer');

    async function runUpdate() {{
        const btn = document.getElementById('updateBtn');
        const status = document.getElementById('updateStatus');
        btn.disabled = true;
        btn.textContent = 'Checking for new listings...';
        status.textContent = '';

        try {{
            const res = await fetch('/update', {{ method: 'POST' }});
            if (!res.ok) throw new Error(`Server returned ${{res.status}}`);
            const result = await res.json();

            data = result.listings;
            filterCards();

            const now = new Date().toLocaleTimeString();
            status.textContent = result.added > 0
                ? `Added ${{result.added}} new listing(s) — last checked ${{now}}`
                : `No new listings since last check — last checked ${{now}}`;
        }} catch (err) {{
            status.textContent = `Update failed: ${{err.message}}`;
        }} finally {{
            btn.disabled = false;
            btn.textContent = 'Update';
        }}
    }}

    function displayCards(filteredData) {{
        container.innerHTML = '';
        filteredData.forEach(item => {{
            const card = document.createElement('div');
            card.className = 'card';
            
            // Image rendering block
            const imageHtml = item.image_url 
                ? `<img src="${{item.image_url}}" style="width: 100%; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">` 
                : '';

            card.innerHTML = `
                <div class="card-header">${{item.location}}</div>
                <div class="tags">
                    <span class="tag price">${{item.price}}</span>
                    <span class="tag">${{item.layout}}</span>
                    <span class="tag gender">${{item.gender}}</span>
                    ${{item.term ? `<span class="tag">${{item.term}}</span>` : ''}}
                </div>
                <div class="card-body">
                    ${{imageHtml}}
                    ${{item.details}}
                </div>
                <div class="card-footer">
                    Posted: ${{item.date}} | Source: ${{item.group}}
                </div>
            `;
            container.appendChild(card);
        }});
    }}

    function parsePrice(priceStr) {{
        const n = parseInt(priceStr.replace(/[^0-9]/g, ''), 10);
        return isNaN(n) ? null : n;
    }}

    function filterCards() {{
        const query = document.getElementById('searchInput').value.toLowerCase();
        const gender = document.getElementById('genderFilter').value;
        const image = document.getElementById('imageFilter').value;
        const sortOrder = document.getElementById('sortFilter').value;
        const maxPriceVal = document.getElementById('maxPrice').value;
        const maxPrice = maxPriceVal ? parseInt(maxPriceVal, 10) : null;

        let filtered = data.filter(item => {{
            const matchesSearch = item.details.toLowerCase().includes(query) ||
                                  item.location.toLowerCase().includes(query);

            let matchesGender = false;
            if (gender === 'all') {{
                matchesGender = true;
            }} else if (gender === 'male_and_coed') {{
                matchesGender = item.gender === 'Male Only' || item.gender === 'Co-ed / Any';
            }} else {{
                matchesGender = item.gender === gender;
            }}

            const matchesImage = image === 'all' || item.image === image;

            let matchesPrice = true;
            if (maxPrice !== null) {{
                const p = parsePrice(item.price);
                matchesPrice = p === null || p <= maxPrice;
            }}

            return matchesSearch && matchesGender && matchesImage && matchesPrice;
        }});

        if (sortOrder === 'lowToHigh') {{
            filtered.sort((a, b) => {{
                const pa = parsePrice(a.price);
                const pb = parsePrice(b.price);
                if (pa === null) return 1;
                if (pb === null) return -1;
                return pa - pb;
            }});
        }}

        document.getElementById('resultCount').textContent =
            `Showing ${{filtered.length}} of ${{data.length}} listings`;

        displayCards(filtered);
    }}

    // Initial render
    filterCards();
</script>
</body>
</html>"""


def generate_html_dashboard(listings, output_path="index.html"):
    html = render_html(listings)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard compiled successfully as '{output_path}'!")

if __name__ == "__main__":
    raw_data = parse_bulk_file("subleases_bulkV3.txt")
    generate_html_dashboard(raw_data)