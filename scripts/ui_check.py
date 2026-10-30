#!/usr/bin/env python3
"""Headless check that view/metric toggles and node clicks work."""

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        page.wait_for_selector(".tg-brand")
        console = []
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: console.append(f"PAGEERROR: {e}"))

        # Wait for graph nodes
        page.wait_for_selector(".tg-node", timeout=15000)
        assert page.locator(".tg-segment button.active", has_text="Execution").count() == 1

        page.get_by_role("button", name="Attribution", exact=True).click()
        page.wait_for_timeout(800)
        assert page.locator(".tg-segment button.active", has_text="Attribution").count() == 1, (
            "Attribution did not become active"
        )
        page.wait_for_selector(".tg-node", timeout=10000)

        page.get_by_role("button", name="Amplified", exact=True).click()
        page.wait_for_timeout(500)
        assert page.locator(".tg-segment button.active", has_text="Amplified").count() == 1

        page.get_by_role("button", name="Cost", exact=True).click()
        page.wait_for_timeout(500)
        assert page.locator(".tg-segment button.active", has_text="Cost").count() == 1

        # Click a node
        page.locator(".tg-node").first.click()
        page.wait_for_selector(".tg-inspector-title", timeout=5000)
        title = page.locator(".tg-inspector-title").inner_text()
        print("inspector:", title)

        page.screenshot(path="/tmp/token-graph-attribution.png", full_page=True)
        page.get_by_role("button", name="Execution", exact=True).click()
        page.wait_for_timeout(600)
        page.screenshot(path="/tmp/token-graph-execution.png", full_page=True)

        if console:
            print("console:")
            for line in console[-20:]:
                print(" ", line)
        print("UI_CHECK_OK")
        browser.close()


if __name__ == "__main__":
    main()
