import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from utils.constants import (
    API_BASE_URL,
    UI_BASE_URL,
    LOGIN_URL,
    DEFAULT_TEST_PASSWORD,
    SUBMIT_BUTTON_PATTERN,
    TEST_USERNAME,
    TEST_PASSWORD
)

load_dotenv()


COLLECT_JS = """
() => {
  const sel = 'a, button, input, select, textarea, [role], [data-testid]';
  const nodes = Array.from(document.querySelectorAll(sel));

  const implicitRole = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'button') return 'button';
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') {
      if (['submit', 'button', 'reset'].includes(type)) return 'button';
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      return 'textbox';
    }
    return null;
  };

  return nodes.map(el => ({
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role') || implicitRole(el),
    input_type: el.tagName.toLowerCase() === 'input' ? (el.getAttribute('type') || 'text') : null,
    id: el.id || null,
    name: el.getAttribute('name') || null,
    testid: el.getAttribute('data-testid') || null,
    placeholder: el.getAttribute('placeholder') || null,
    accessible_name: el.getAttribute('aria-label') || el.innerText?.trim().slice(0, 60) || null,
    text: el.innerText ? el.innerText.trim().slice(0, 60) : null,
    href: el.getAttribute('href') || null,
    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
  })).filter(e => e.visible);
}
"""



async def run_mcp_session(url: str, out_dir: Path, login_config: dict | None = None) -> tuple[dict, dict]:
    """Connect to Playwright MCP server or execute Playwright async session to gather rich UI context and API endpoints via network interception."""
    print("[Playwright MCP] Gathering UI and API context across login, events list, detail, and bookings pages...")

    api_calls = {}

    async def handle_response(response):
        req = response.request
        if "/api/" in req.url and req.resource_type in ["fetch", "xhr"]:
            # Deduplicate by METHOD + URL
            key = f"{req.method} {req.url.split('?')[0]}"
            if key not in api_calls:
                call_info = {
                    "method": req.method,
                    "url": req.url,
                    "status": response.status,
                    "request_post_data": req.post_data,
                    "response_keys": None
                }
                try:
                    data = await response.json()
                    if isinstance(data, dict):
                        call_info["response_keys"] = list(data.keys())
                    elif isinstance(data, list) and data and isinstance(data[0], dict):
                        call_info["response_keys"] = list(data[0].keys())
                except Exception:
                    pass
                api_calls[key] = call_info

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Intercept network responses to build API context dynamically
        page.on("response", handle_response)

        # 1. Login Page
        await page.goto(LOGIN_URL, wait_until="networkidle")
        title = await page.title()

        username_env = login_config.get("username_env", "TEST_USERNAME") if login_config else "TEST_USERNAME"
        password_env = login_config.get("password_env", "TEST_PASSWORD") if login_config else "TEST_PASSWORD"
        username = os.environ.get(username_env)
        password = os.environ.get(password_env)

        import time
        reg_email = f"ui_auto_{int(time.time())}@test.com"
        reg_payload = {"email": reg_email, "password": DEFAULT_TEST_PASSWORD}
        try:
            requests.post(f"{API_BASE_URL}/auth/register", json=reg_payload, timeout=5)
        except Exception:
            pass

        # Perform UI login
        email_selector = login_config.get("email_selector", "#email") if login_config else "#email"
        password_selector = login_config.get("password_selector", "#password") if login_config else "#password"
        submit_pattern = login_config.get("submit_name", SUBMIT_BUTTON_PATTERN) if login_config else SUBMIT_BUTTON_PATTERN

        await page.fill(email_selector, username if username else reg_email)
        await page.fill(password_selector, password if password else DEFAULT_TEST_PASSWORD)
        submit_btn = page.get_by_role("button", name=re.compile(submit_pattern, re.I))
        if await submit_btn.count() > 0:
            await submit_btn.first.click()
            await page.wait_for_timeout(2000)

        # Collect elements across current page
        elements = await page.evaluate(COLLECT_JS)

        # Navigate to /events and collect
        try:
            await page.goto(UI_BASE_URL, wait_until="networkidle")
            events_els = await page.evaluate(COLLECT_JS)
            elements.extend(events_els)

            # Click an event to trigger more API calls (events detail)
            event_cards = page.get_by_test_id("event-card")
            if await event_cards.count() > 0:
                await event_cards.first.click()
                await page.wait_for_timeout(2000)
                detail_els = await page.evaluate(COLLECT_JS)
                elements.extend(detail_els)

            # Navigate to bookings to trigger bookings API calls
            await page.goto(f"{UI_BASE_URL}/bookings", wait_until="networkidle")
            await page.wait_for_timeout(2000)
            bookings_els = await page.evaluate(COLLECT_JS)
            elements.extend(bookings_els)
        except Exception:
            pass

        # Deduplicate elements by identity
        seen = set()
        unique_elements = []
        for el in elements:
            key = (
                el.get("testid")
                or el.get("id")
                or (f"{el.get('role')}:{el.get('accessible_name')}" if el.get('role') and el.get('accessible_name') else None)
            )
            if key:
                if key not in seen:
                    seen.add(key)
                    unique_elements.append(el)
            else:
                unique_elements.append(el)

        try:
            ax_tree = await page.accessibility.snapshot()
        except Exception:
            ax_tree = None

        await browser.close()

    ui_context = {
        "url": url,
        "title": title,
        "gatherer_mode": "Playwright MCP Protocol",
        "authenticated": True,
        "interactive_elements": unique_elements,
        "accessibility_tree": ax_tree,
    }

    api_context = {
        "source": "Dynamic Network Interception",
        "endpoint_count": len(api_calls),
        "endpoints": list(api_calls.values())
    }

    (out_dir / "ui_context.json").write_text(json.dumps(ui_context, indent=2))
    (out_dir / "api_context.json").write_text(json.dumps(api_context, indent=2))

    return ui_context, api_context



def main():
    parser = argparse.ArgumentParser(description="Playwright MCP Context Gatherer")
    parser.add_argument("--url", required=True, help="Target URL to inspect")
    parser.add_argument("--out", default="context", help="Output directory")

    login_group = parser.add_argument_group("login")
    login_group.add_argument("--login-url", default=None)
    login_group.add_argument("--username-env", default="TEST_USERNAME")
    login_group.add_argument("--password-env", default="TEST_PASSWORD")
    login_group.add_argument("--email-selector", default="#email")
    login_group.add_argument("--password-selector", default="#password")
    login_group.add_argument("--submit-name", default="sign in|log in|login|submit")

    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    login_config = None
    if args.login_url:
        login_config = {
            "login_url": args.login_url,
            "username_env": args.username_env,
            "password_env": args.password_env,
            "email_selector": args.email_selector,
            "password_selector": args.password_selector,
            "submit_name": args.submit_name,
        }

    ui_ctx, api_ctx = asyncio.run(run_mcp_session(args.url, out_dir, login_config=login_config))

    print(f"\n[Playwright MCP Gatherer] UI context: {len(ui_ctx['interactive_elements'])} elements gathered.")
    print(f"[Playwright MCP Gatherer] API context: {api_ctx.get('endpoint_count', 0)} endpoints processed dynamically.")
    print(f"Written to {out_dir}/")


if __name__ == "__main__":
    main()
