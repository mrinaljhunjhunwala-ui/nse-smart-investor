"""Open the Streamlit Community Cloud app in a headless browser so it doesn't
hibernate (free apps sleep after ~12h without a visit; plain HTTP pings don't
count). If it is already asleep, click the wake-up button. Exit 1 when the app
never loads, so a red run in Actions means the app is actually down.

Usage: python scripts/keep_streamlit_awake.py [URL]   (default: STREAMLIT_APP_URL)
"""
from __future__ import annotations

import os
import sys

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

_WAKE_TEXT = "get this app back up"


def main() -> int:
    url = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("STREAMLIT_APP_URL", "")).strip()
    if not url:
        print("no URL given (arg or STREAMLIT_APP_URL)")
        return 1
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        try:
            btn = page.get_by_role("button", name=_WAKE_TEXT, exact=False)
            btn.wait_for(timeout=15_000)
            print("app was asleep — clicking the wake-up button")
            btn.click()
        except PWTimeout:
            print("app is awake (no wake-up button)")
        # The app renders inside an iframe on *.streamlit.app; wait for Streamlit's root.
        loaded = False
        for frame_wait in range(12):                   # up to ~3 min for a cold start
            for f in page.frames:
                try:
                    if f.query_selector('[data-testid="stApp"]'):
                        loaded = True
                        break
                except Exception:
                    pass
            if loaded:
                break
            page.wait_for_timeout(15_000)
        browser.close()
    print("app loaded" if loaded else "app did NOT load within ~3 min")
    return 0 if loaded else 1


if __name__ == "__main__":
    sys.exit(main())
