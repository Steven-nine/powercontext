"""用 Playwright + 本机 Edge 打开《记忆剧场》网页并截图，作为运行证据。

    python3 scripts/capture-ui.py

需要：pip install playwright（本机已装 Edge，无需额外下载浏览器）。
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence"
URL = "http://127.0.0.1:8787"

STEPS = [
    ("B 整蛊鸽子议会", "第一次整蛊"),
    ("C 和门卫协商", "门卫翻旧账"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(URL, wait_until="networkidle")
        page.fill("#name", "证据玩家")
        page.select_option("#channel", "surreal")
        for action, _ in STEPS:
            page.click(f'button[data-quick="{action}"]')
            page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "ui-desktop.png"), full_page=False)
        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(URL, wait_until="networkidle")
        mobile.wait_for_timeout(1200)
        mobile.screenshot(path=str(OUT / "ui-mobile.png"), full_page=False)
        overflow = mobile.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
        browser.close()
    print("screenshots written to", OUT)
    print("page errors:", errors)
    print("mobile horizontal overflow:", overflow)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
