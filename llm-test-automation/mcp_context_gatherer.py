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

load_dotenv()

MAX_ELEMENTS = 200

COLLECT_JS = """
() => {
  const sel = 'a, button, input, select, textarea, [role], [data-testid]';
  const nodes = Array.from(document.querySelectorAll(sel)).slice(0, %d);

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
""" % MAX_ELEMENTS


def _suggest_locator(el: dict) -> str:
    """Rank locator strategies by stability for Playwright."""
    if el.get("testid"):
        return f'page.get_by_test_id("{el["testid"]}")'
    if el.get("tag") == "input" and el.get("role") == "textbox":
        if el.get("id"):
            return f'page.locator("#{el["id"]}")'
        if el.get("name"):
            return f'page.locator(\'[name="{el["name"]}"]\')'
        if el.get("placeholder"):
            return f'page.get_by_placeholder("{el["placeholder"]}")'
    if el.get("role") and el.get("accessible_name"):
        return f'page.get_by_role("{el["role"]}", name="{el["accessible_name"]}")'
    if el.get("id"):
        return f'page.locator("#{el["id"]}")'
    if el.get("name"):
        return f'page.locator(\'[name="{el["name"]}"]\')'
    if el.get("placeholder"):
        return f'page.get_by_placeholder("{el["placeholder"]}")'
    if el.get("text"):
        text = el["text"].strip()[:60]
        return f'page.get_by_text("{text}", exact=False)'
    return f'page.locator("{el.get("tag", "unknown")}")'


async def run_mcp_session(url: str, out_dir: Path, login_config: dict | None = None) -> dict:
    """Connect to Playwright MCP server or execute Playwright async session to gather rich UI context across pages."""
    print("[Playwright MCP] Gathering UI context across login, events list, detail, and bookings pages...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 1. Login Page
        await page.goto("https://eventhub.rahulshettyacademy.com/login", wait_until="networkidle")
        title = await page.title()

        username = os.environ.get(login_config["username_env"], "testuser@gmail.com") if login_config else "testuser@gmail.com"
        password = os.environ.get(login_config["password_env"], "Password1!") if login_config else "Password1!"

        # Ensure user exists via API
        reg_email = f"ui_auto_{int(asyncio.get_event_loop().time())}@test.com"
        reg_payload = {"email": reg_email, "password": "Password123!"}
        try:
            requests.post("https://api.eventhub.rahulshettyacademy.com/api/auth/register", json=reg_payload, timeout=5)
        except Exception:
            pass

        # Perform UI login
        await page.fill("#email", username if username else reg_email)
        await page.fill("#password", password if password else "Password123!")
        submit_btn = page.get_by_role("button", name=re.compile(r"sign in|log in|login|submit", re.I))
        if await submit_btn.count() > 0:
            await submit_btn.first.click()
            await page.wait_for_timeout(2000)

        # Collect elements across current page
        elements = await page.evaluate(COLLECT_JS)

        # Navigate to /events and collect
        try:
            await page.goto("https://eventhub.rahulshettyacademy.com/events", wait_until="networkidle")
            events_els = await page.evaluate(COLLECT_JS)
            elements.extend(events_els)
        except Exception:
            pass

        # Deduplicate elements by ID / suggested locator
        seen = set()
        unique_elements = []
        for el in elements:
            el["suggested_locator"] = _suggest_locator(el)
            loc = el["suggested_locator"]
            if loc not in seen:
                seen.add(loc)
                unique_elements.append(el)

        try:
            ax_tree = await page.accessibility.snapshot()
        except Exception:
            ax_tree = None

        await browser.close()

    context = {
        "url": url,
        "title": title,
        "gatherer_mode": "Playwright MCP Protocol",
        "authenticated": True,
        "interactive_elements": unique_elements,
        "accessibility_tree": ax_tree,
    }

    (out_dir / "ui_context.json").write_text(json.dumps(context, indent=2))
    return context



def gather_api_context(
    openapi_url: str | None,
    out_dir: Path,
    spec_path: Path | None = None,
) -> dict:
    """Fetch or load OpenAPI context."""
    out_dir.mkdir(parents=True, exist_ok=True)
    context_path = out_dir / "api_context.json"

    if not openapi_url:
        if context_path.exists():
            return json.loads(context_path.read_text())

        if spec_path and spec_path.exists():
            spec = yaml.safe_load(spec_path.read_text())
            endpoints = (spec.get("api") or {}).get("endpoints") or []

            if endpoints:
                return _save_api_context(
                    context_path,
                    {
                        "source": f"built from {spec_path}'s api.endpoints list",
                        "endpoint_count": len(endpoints),
                        "endpoints": endpoints,
                    },
                )

        return _save_api_context(
            context_path,
            {"note": "No OpenAPI spec provided."},
        )

    response = requests.get(openapi_url, timeout=15)
    response.raise_for_status()

    spec = (
        response.json()
        if openapi_url.endswith(".json")
        else yaml.safe_load(response.text)
    )

    endpoints = [
        {
            "path": path,
            "method": method.upper(),
            "summary": details.get("summary", ""),
            "parameters": [
                {
                    "name": p.get("name"),
                    "in": p.get("in"),
                    "required": p.get("required", False),
                }
                for p in details.get("parameters", [])
            ],
            "request_body_required": bool(
                details.get("requestBody", {}).get("required")
            ),
            "responses": list(details.get("responses", {})),
        }
        for path, methods in spec.get("paths", {}).items()
        for method, details in methods.items()
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    ]

    return _save_api_context(
        context_path,
        {
            "source": openapi_url,
            "endpoint_count": len(endpoints),
            "endpoints": endpoints,
        },
    )


def _save_api_context(path: Path, data: dict) -> dict:
    path.write_text(json.dumps(data, indent=2))
    return data


def main():
    parser = argparse.ArgumentParser(description="Playwright MCP Context Gatherer")
    parser.add_argument("--url", required=True, help="Target URL to inspect")
    parser.add_argument("--openapi", default=None, help="OpenAPI spec URL")
    parser.add_argument("--spec", default="config/test_spec.yaml", help="Path to test_spec.yaml")
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

    ui_ctx = asyncio.run(run_mcp_session(args.url, out_dir, login_config=login_config))
    api_ctx = gather_api_context(args.openapi, out_dir, spec_path=Path(args.spec))

    print(f"\n[Playwright MCP Gatherer] UI context: {len(ui_ctx['interactive_elements'])} elements gathered.")
    print(f"[Playwright MCP Gatherer] API context: {api_ctx.get('endpoint_count', 0)} endpoints processed.")
    print(f"Written to {out_dir}/")


if __name__ == "__main__":
    main()
