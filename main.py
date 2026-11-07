"""Save the rendered HTML from the Transact page."""

from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from playwright.sync_api import sync_playwright


URL = "https://weborder.transactcampus.com/7"
USER_AGENT = "PageHTMLExtractor/1.0"
OUTPUT_PATH = Path(__file__).with_name("output.html")


def allowed_by_robots(url):
    parts = urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        response = requests.get(
            robots_url, headers={"User-Agent": USER_AGENT}, timeout=15
        )
        if response.status_code == 404:
            return True
        response.raise_for_status()
        rules = RobotFileParser()
        rules.parse(response.text.splitlines())
        return rules.can_fetch(USER_AGENT, url)
    except requests.RequestException:
        return False


def main():
    if not allowed_by_robots(URL):
        raise SystemExit(
            "Robots policy disallows scraping, or could not be checked."
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(user_agent=USER_AGENT)
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#root > *", timeout=30000)
            page.wait_for_load_state("networkidle", timeout=30000)
            html = page.content()
        finally:
            browser.close()

    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Rendered HTML saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
