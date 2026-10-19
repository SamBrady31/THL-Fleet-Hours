"""Nightly scrape of Aeronet total flight hours -> docs/hours.json

Secrets (set in GitHub): AERONET_LOGIN_URL, AERONET_FLEET_URL, AERONET_USER, AERONET_PASS
The fleet page is a list of aircraft, so we read the page text and pull out
each registration with its total hours, rather than relying on table selectors.
"""
import json, os, re, sys
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

OUT = "docs/hours.json"
MIN_AIRCRAFT = 15  # fail loudly if we find fewer than this

# "ZK-HAA @13/10/2026 8532.25"  or  "ZK-HAO (2660.95)" (techlog not found)
# The (?![A-Za-z0-9-]) skips entries like "ZK-IBG-v2track" (the test aircraft)
ROW = re.compile(
    r"(ZK-[A-Z]{3})(?![A-Za-z0-9-])\s*"
    r"(?:@(\d{1,2})/(\d{1,2})/(\d{4})\s+|\()\s*([\d,]+(?:\.\d+)?)"
)


def parse(text):
    hours, as_of = {}, {}
    for m in ROW.finditer(text):
        tail = m.group(1)
        hours[tail] = float(m.group(5).replace(",", ""))
        if m.group(2):
            as_of[tail] = f"{m.group(4)}-{int(m.group(3)):02d}-{int(m.group(2)):02d}"
    return hours, as_of


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # .strip() removes stray spaces or line breaks pasted into the secrets
        page.goto(os.environ["AERONET_LOGIN_URL"].strip())
        page.get_by_placeholder("Username").fill(os.environ["AERONET_USER"].strip())
        page.get_by_placeholder("Password").fill(os.environ["AERONET_PASS"].strip())
        page.get_by_role("button", name="Login").click()
        try:
            # Wait up to 30s for the password box to disappear (= login worked)
            page.get_by_placeholder("Password").wait_for(state="hidden", timeout=30000)
        except Exception:
            print("Page address after login attempt:", page.url)
            print("Page text (first 300 chars):", page.inner_text("body")[:300])
            sys.exit("Login failed: still on the login page after 30 seconds.")
        page.wait_for_load_state("networkidle")

        page.goto(os.environ["AERONET_FLEET_URL"])
        page.wait_for_load_state("networkidle")
        try:
            page.wait_for_function("document.body.innerText.includes('ZK-')", timeout=30000)
        except Exception:
            pass
        text = page.inner_text("body")
        url = page.url
        browser.close()

    hours, as_of = parse(text)
    if len(hours) < MIN_AIRCRAFT:
        print("Page address:", url)
        print("First 300 characters of page text:\n", text[:300])
        sys.exit(f"Only found {len(hours)} aircraft (expected at least {MIN_AIRCRAFT}).")

    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(
            {"updated": datetime.now(timezone.utc).isoformat(), "aircraft": hours, "as_of": as_of},
            f, indent=2,
        )
    print(f"Saved {len(hours)} aircraft to {OUT}")


if __name__ == "__main__":
    main()
