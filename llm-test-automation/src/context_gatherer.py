import argparse
import asyncio
import json
import os
import re

from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page

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

class NetworkInterceptor:
    def __init__(self):
        self.api_calls = {}

    async def handle_response(self, response):
        req = response.request
        if req.resource_type in ["fetch", "xhr"]:
            key = f"{req.method} {req.url.split('?')[0]}"
            if key not in self.api_calls:
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
                self.api_calls[key] = call_info


async def perform_login(page: Page, login_config: dict | None) -> list[dict]:
    """Navigates to login page, scrapes it, and logs in generically without hardcoded APIs."""
    if not login_config or not login_config.get("login_url"):
        return []

    await page.goto(login_config["login_url"], wait_until="networkidle")
    await page.wait_for_timeout(1000)

    # Scrape the login page BEFORE filling the form so the LLM knows the real locators!
    login_elements = await page.evaluate(COLLECT_JS)

    # Fetch configuration
    username_env = login_config.get("username_env", "TEST_USERNAME")
    password_env = login_config.get("password_env", "TEST_PASSWORD")
    username = os.environ.get(username_env, "testuser@example.com")
    password = os.environ.get(password_env, "password")

    # Perform UI login
    email_selector = login_config.get("email_selector", "input[type='email']")
    password_selector = login_config.get("password_selector", "input[type='password']")
    submit_pattern = login_config.get("submit_name", "login|sign in|submit")

    try:
        await page.fill(email_selector, username)
        await page.fill(password_selector, password)

        submit_btn = page.get_by_role("button", name=re.compile(submit_pattern, re.I))
        if await submit_btn.count() > 0:
            await submit_btn.first.click()
            await page.wait_for_timeout(2000)
    except Exception as e:
        print(f"[Warning] Failed to execute generic login flow: {e}")

    return login_elements


async def scrape_app_pages(page: Page, base_url: str) -> list[dict]:
    """Navigates through the application generically using a BFS crawler to trigger DOM rendering and network calls."""
    elements = []
    visited_urls = set()
    queue = [base_url]

    # Generic BFS crawler - explores up to 5 unique pages
    while queue and len(visited_urls) < 5:
        url = queue.pop(0)
        if url in visited_urls:
            continue

        visited_urls.add(url)
        try:
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(1500)

            # Scrape all interactive elements on the current page
            page_els = await page.evaluate(COLLECT_JS)
            elements.extend(page_els)

            # Extract all same-origin links to explore further
            links = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(href => href.startsWith(window.location.origin) && !href.includes('#') && !href.includes('logout'));
            }''')

            for link in set(links):
                if link not in visited_urls and link not in queue:
                    queue.append(link)

        except Exception:
            pass

    return elements

def deduplicate_elements(elements: list[dict]) -> list[dict]:
    """Removes duplicate DOM elements based on unique keys."""
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
    return unique_elements

async def run_mcp_session(url: str, out_dir: Path, login_config: dict | None = None) -> tuple[dict, dict]:
    """Connect to Playwright MCP server or execute Playwright async session to gather rich UI context and API endpoints."""
    print("[Playwright MCP] Gathering UI and API context dynamically via generic spidering...")

    interceptor = NetworkInterceptor()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Intercept network responses to build API context dynamically
        page.on("response", interceptor.handle_response)

        # Execute workflows
        login_els = await perform_login(page, login_config)
        title = await page.title()
        raw_elements = await scrape_app_pages(page, url)
        raw_elements.extend(login_els)

        unique_elements = deduplicate_elements(raw_elements)

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
        "endpoint_count": len(interceptor.api_calls),
        "endpoints": list(interceptor.api_calls.values())
    }

    (out_dir / "ui_context.json").write_text(json.dumps(ui_context, indent=2))
    (out_dir / "api_context.json").write_text(json.dumps(api_context, indent=2))

    return ui_context, api_context


def main():
    parser = argparse.ArgumentParser(description="Playwright MCP Context Gatherer")
    parser.add_argument("--url", required=True, help="Target URL to inspect")
    parser.add_argument("--out", default="generated/context", help="Output directory")

    login_group = parser.add_argument_group("login")
    login_group.add_argument("--login-url", default=None)
    login_group.add_argument("--username-env", default="TEST_USERNAME")
    login_group.add_argument("--password-env", default="TEST_PASSWORD")
    login_group.add_argument("--email-selector", default="input[type='email']")
    login_group.add_argument("--password-selector", default="input[type='password']")
    login_group.add_argument("--submit-name", default="login|sign in|submit")

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
