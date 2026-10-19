"""Nightly scrape of Aeronet total flight hours -> docs/hours.json

Secrets (set in GitHub): AERONET_LOGIN_URL, AERONET_USER, AERONET_PASS
After logging in, the script taps through the menu (CLICK_PATH below) to the
aircraft list, then reads each registration and its total hours from the text.
"""
import json, os, re, sys
from datetime import datetime, timezone
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

OUT = "docs/hours.json"
HISTORY = "docs/history.json"
MIN_AIRCRAFT = 15  # fail loudly if we find fewer than this
CLICK_PATH = ["Tech Log"]  # menu items to tap after login, in order (we may need to adjust)
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
        if r.request.method == "POST":
            try:
                body = r.text()
                print("  reply contains 'Modules':", "Modules" in body,
                      "| contains 'Password':", "Password" in body)
            except Exception:
                pass


def fail(page, browser, message):
    try:  # clear the login fields so no credentials appear in the screenshot
        page.get_by_placeholder("Username").fill("")
        page.get_by_placeholder("Password").fill("")
    except Exception:
        pass
    page.screenshot(path="debug.png")
    browser.close()
    sys.exit(message)


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
        print("Typed username correctly:", user.input_value() == os.environ["AERONET_USER"].strip())
        print("Typed password correctly:", pwd.input_value() == os.environ["AERONET_PASS"].strip())
        page.get_by_role("button", name="Login").click()

        # The page after a successful login is titled "Modules"
        try:
            page.wait_for_function("document.body.innerText.includes('Modules')", timeout=20000)
        except Exception:
            print("Cookies set by Aeronet:", len(page.context.cookies()))
            fail(page, browser, "Did not reach the Modules page after login.")
        print("Logged in.")

        for label in CLICK_PATH:
            print("URL before click:", page.url)
            matches = page.get_by_text(label, exact=True)
            n = matches.count()
            print(f"Found {n} element(s) with text '{label}'")
            for i in range(n):
                el = matches.nth(i)
                print(f"  #{i}: tag={el.evaluate('e => e.tagName')} "
                      f"visible={el.is_visible()} "
                      f"html={el.evaluate('e => e.outerHTML')[:200]}")

            target = None
            for i in range(n):
                if matches.nth(i).is_visible():
                    target = matches.nth(i)
                    break
            if target is None:
                fail(page, browser, f"No visible menu item called '{label}'.")

            start_text = page.inner_text("body")
            # Try three ways of pressing it, stopping as soon as the page changes
            for method in ("click", "parent click", "tap"):
                try:
                    if method == "click":
                        target.click(timeout=10000)
                    elif method == "parent click":
                        target.locator("xpath=..").click(timeout=10000)
                    else:
                        target.dispatch_event("touchstart")
                        target.dispatch_event("touchend")
                        target.dispatch_event("click")
                except Exception as e:
                    print(f"  {method} failed:", str(e)[:100])
                page.wait_for_timeout(3000)
                if page.inner_text("body") != start_text:
                    print(f"  page changed after: {method}")
                    break
                print(f"  page did NOT change after: {method}")

            print("URL after click:", page.url)
            print("Text after click (first 300 chars):", page.inner_text("body")[:300])

        try:
            page.wait_for_function("document.body.innerText.includes('ZK-')", timeout=20000)
        except Exception:
            pass
        text = page.inner_text("body")
        hours, as_of = parse(text)

        if len(hours) < MIN_AIRCRAFT:
            print("Page text (first 300 chars):", text[:300])
            fail(page, browser, f"Only found {len(hours)} aircraft (expected at least {MIN_AIRCRAFT}).")
        browser.close()

    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(
            {"updated": datetime.now(timezone.utc).isoformat(), "aircraft": hours, "as_of": as_of},
            f, indent=2,
        )
    try:
        with open(HISTORY) as f:
            history = json.load(f)
    except Exception:
        history = []
    history.append({"time": datetime.now(timezone.utc).isoformat(), "count": len(hours)})
    history = history[-90:]  # keep the last 90 successful runs
    with open(HISTORY, "w") as f:
        json.dump(history, f, indent=2)    
    print(f"Saved {len(hours)} aircraft to {OUT}")


if __name__ == "__main__":
    main()
