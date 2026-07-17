import json
import os
import re
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


URL = os.getenv(
    "BOOKMYSHOW_URL",
    "https://in.bookmyshow.com/movies/bengaluru/jana-nayagan/buytickets/ET00430817/20260723",
)
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))


def load_state():
    if not STATE_FILE.exists():
        return {"theatres": []}
    return json.loads(STATE_FILE.read_text())


def save_state(theatres):
    STATE_FILE.write_text(json.dumps({"theatres": sorted(theatres)}, indent=2) + "\n")


def scrape_theatres():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="en-IN")
        page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(8_000)

        # Theatre cards on BookMyShow are linked to cinema pages. Keep only
        # visible, non-navigation links and de-duplicate by displayed name.
        names = set()
        for link in page.locator('a[href*="/cinemas/"]').all():
            if not link.is_visible():
                continue
            text = re.sub(r"\s+", " ", link.inner_text()).strip()
            if text and 3 <= len(text) <= 140:
                names.add(text)
        browser.close()
        return sorted(names)


def send_ntfy(message):
    topic = os.environ["NTFY_TOPIC"]
    requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode(),
        headers={"Title": "Jana Nayagan booking opened", "Priority": "urgent", "Tags": "cinema"},
        timeout=20,
    ).raise_for_status()


def send_whatsapp(message):
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        auth=(sid, token),
        data={
            "From": os.environ["TWILIO_WHATSAPP_FROM"],
            "To": os.environ["TWILIO_WHATSAPP_TO"],
            "Body": message,
        },
        timeout=20,
    ).raise_for_status()


def main():
    old = set(load_state().get("theatres", []))
    current = set(scrape_theatres())
    new = sorted(current - old)

    # Establish the initial baseline silently. Later runs alert only for new venues.
    if old and new:
        message = (
            "New Bengaluru theatre(s) now have Jana Nayagan listings for 23 July 2026:\n"
            + "\n".join(f"• {name}" for name in new)
            + f"\n\nBook now: {URL}"
        )
        # Keep the two channels independent: a Twilio issue must not cause
        # the same iPhone alert to be sent again on every hourly run.
        send_ntfy(message)
        if all(os.getenv(key) for key in (
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_WHATSAPP_FROM",
            "TWILIO_WHATSAPP_TO",
        )):
            try:
                send_whatsapp(message)
            except requests.RequestException as exc:
                print(f"WhatsApp notification failed: {exc}")

    save_state(current)
    print(json.dumps({"theatres": sorted(current), "new": new}, indent=2))


if __name__ == "__main__":
    main()
