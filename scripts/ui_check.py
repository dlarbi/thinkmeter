#!/usr/bin/env python3
"""Headless check for session browser, cost labels, and narrative inspector."""

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto("http://127.0.0.1:8000/", wait_until="networkidle")
        page.wait_for_selector(".tg-brand")

        # Force reload demos so narrative + extras exist
        page.evaluate(
            """async () => {
              await fetch('/api/demo', {
                method: 'POST',
                headers: {'content-type':'application/json'},
                body: JSON.stringify({force:true})
              });
            }"""
        )
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".tg-session-card")

        cards = page.locator(".tg-session-card")
        assert cards.count() >= 2, f"expected multiple sessions, got {cards.count()}"

        page.wait_for_selector(".tg-node")
        # Cost should appear on request nodes even in Direct metric mode
        body = page.locator(".tg-node-metric").all_inner_texts()
        assert any("$" in t for t in body), f"expected cost on nodes, got {body[:8]}"

        # Open a request / thinking / prompt node if present
        think = page.locator(".tg-node", has_text="thinking")
        if think.count():
            think.first.click()
        else:
            page.locator(".tg-node").first.click()
        page.wait_for_selector(".tg-inspector-title")
        # Narrative section or cost banner should exist for rich nodes
        page.wait_for_timeout(400)

        # Switch session via browser
        if cards.count() > 1:
            cards.nth(1).click()
            page.wait_for_timeout(800)
            page.wait_for_selector(".tg-node")

        page.screenshot(path="/tmp/token-graph-sessions.png", full_page=True)
        print("sessions", cards.count())
        print("UI_CHECK_OK")
        browser.close()


if __name__ == "__main__":
    main()
