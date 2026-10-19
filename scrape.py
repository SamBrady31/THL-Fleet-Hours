"""Nightly scrape of Aeronet total flight hours -> docs/hours.json

Secrets (set in GitHub): AERONET_LOGIN_URL, AERONET_FLEET_URL, AERONET_USER, AERONET_PASS
The fleet page is a list of aircraft, so we read the page text and pull out
each registration with its total hours, rather than relying on table selectors.
"""
import json, os, re, sys
from datetime import datetime, timezone
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

OUT = "docs/hours.json"
MIN_AIRCRAFT = 15  # fail loudly if we find fewer than this
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

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


def log_response(r):
    # Print only the method, status and path (never full addresses or form data)
    if r.request.method == "POST" or r.status >= 400:
        print(f"  network: {r.request.method} {r.status} {urlparse(r.url).path}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1280, "height": 900}
        ).new_page()
        page.on("response", log_response)

        # .strip() removes stray spaces or line breaks pasted into the secrets
        page.goto(os.environ["AERONET_LOGIN_URL"].strip())
        user = page.get_by_placeholder("Username")
        pwd = page.get_by_placeholder("Password")
        user.click()
        user.press_sequentially(os.environ["AERONET_USER"].strip(), delay=40)
        pwd.click()
        pwd.press_sequentially(os.environ["AERONET_PASS"].strip(), delay=40)
        page.get_by_role("button", name="Login").click()
        try:
            # If login worked, the password box normally disappears
            pwd.wait_for(state="hidden", timeout=10000)
        except Exception:
            print("Login form still showing after 10s; trying the fleet page anyway.")
        page.wait_for_load_state("networkidle")

        page.goto(os.environ["AERONET_FLEET_URL"].strip())
        page.wait_for_load_state("networkidle")
        try:
            page.wait_for_function("document.body.innerText.includes('ZK-')", timeout=15000)
        except Exception:
            pass
        text = page.inner_text("body")
        hours, as_of = parse(text)

        if len(hours) < MIN_AIRCRAFT:
            print("Login box showing on fleet page:", page.get_by_placeholder("Password").count() > 0)
            print("Page text (first 300 chars):", text[:300])
            page.screenshot(path="debug.png")
            browser.close()
            sys.exit(f"Only found {len(hours)} aircraft (expected at least {MIN_AIRCRAFT}).")
        browser.close()

    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(
            {"updated": datetime.now(timezone.utc).isoformat(), "aircraft": hours, "as_of": as_of},
            f, indent=2,
        )
    print(f"Saved {len(hours)} aircraft to {OUT}")


if __name__ == "__main__":
    main()
