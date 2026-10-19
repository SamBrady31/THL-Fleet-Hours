"""Nightly scrape of Aeronet total flight hours -> docs/hours.json

Credentials come from environment variables (GitHub Actions secrets):
  AERONET_LOGIN_URL, AERONET_FLEET_URL, AERONET_USER, AERONET_PASS

Lines marked TODO need adjusting to Aeronet's real page.
"""
import json, os, re, sys
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

EXPECTED_AIRCRAFT = 24
OUT = "docs/hours.json"

# TODO: replace with the real selectors from the Aeronet pages
USER_FIELD = "input[name='username']"
PASS_FIELD = "input[name='password']"
SUBMIT_BTN = "button[type='submit']"
ROW_SELECTOR = "table tbody tr"   # one row per helicopter
TAIL_COL = 0                      # column index of tail number
HOURS_COL = 3                     # column index of total hours


def parse_hours(text):
    m = re.search(r"\d[\d,]*\.?\d*", text)
    if not m:
        raise ValueError(f"No number in {text!r}")
    return float(m.group().replace(",", ""))


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(os.environ["AERONET_LOGIN_URL"])
        page.fill(USER_FIELD, os.environ["AERONET_USER"])
        page.fill(PASS_FIELD, os.environ["AERONET_PASS"])
        page.click(SUBMIT_BTN)
        page.wait_for_load_state("networkidle")
        page.goto(os.environ["AERONET_FLEET_URL"])
        page.wait_for_selector(ROW_SELECTOR)

        aircraft = {}
        for row in page.query_selector_all(ROW_SELECTOR):
            cells = [c.inner_text().strip() for c in row.query_selector_all("td")]
            if len(cells) <= max(TAIL_COL, HOURS_COL):
                continue
            aircraft[cells[TAIL_COL]] = parse_hours(cells[HOURS_COL])
        browser.close()

    # Fail loudly rather than publish partial or stale-looking data
    if len(aircraft) != EXPECTED_AIRCRAFT:
        sys.exit(f"Expected {EXPECTED_AIRCRAFT} aircraft, found {len(aircraft)}")

    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(
            {"updated": datetime.now(timezone.utc).isoformat(), "aircraft": aircraft},
            f, indent=2,
        )
    print(f"Saved {len(aircraft)} aircraft to {OUT}")


if __name__ == "__main__":
    main()
