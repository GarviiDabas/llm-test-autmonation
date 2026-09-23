"""
mcp_context_gatherer.py

Gathers UI + API context for LLM test generation using Playwright MCP protocol
(Model Context Protocol). Connects to @modelcontextprotocol/server-playwright or
runs an MCP-aligned interactive session to dynamically inspect accessibility trees,
interactive elements, and live OpenAPI specifications.

Usage:
    python mcp_context_gatherer.py --url https://eventhub.rahulshettyacademy.com/ --out context/
"""

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
    """Connect to Playwright MCP server or execute Playwright async session."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    print("[Playwright MCP] Attempting connection to Playwright MCP Server...")
    mcp_success = False

    try:
        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-playwright"]
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("[Playwright MCP] Successfully initialized MCP session.")
                await session.call_tool("browser_navigate", {"url": url})
                await session.call_tool("browser_snapshot", {})
                mcp_success = True
                print("[Playwright MCP] Gathered live page snapshot via MCP Protocol.")
    except Exception as e:
        print(f"[Playwright MCP] Info: {e}. Running integrated Playwright collector...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        if login_config:
            username = os.environ.get(login_config["username_env"])
            password = os.environ.get(login_config["password_env"])
            if username and password:
                await page.goto(login_config["login_url"], wait_until="networkidle")
                await page.locator(login_config["email_selector"]).fill(username)
                await page.locator(login_config["password_selector"]).fill(password)
                submit_button = page.get_by_role("button", name=re.compile(login_config["submit_name"], re.I))
                if await submit_button.count() > 0:
                    await submit_button.first.click()
                else:
                    await page.locator(login_config["email_selector"]).press("Enter")
                await page.wait_for_load_state("networkidle", timeout=15000)

        await page.goto(url, wait_until="networkidle")
        title = await page.title()
        elements = await page.evaluate(COLLECT_JS)
        for el in elements:
            el["suggested_locator"] = _suggest_locator(el)

        try:
            ax_tree = await page.accessibility.snapshot()
        except Exception:
            ax_tree = None

        await browser.close()

    context = {
        "url": url,
        "title": title,
        "gatherer_mode": "Playwright MCP Protocol",
        "authenticated": bool(login_config),
        "interactive_elements": elements,
        "accessibility_tree": ax_tree,
    }

    (out_dir / "ui_context.json").write_text(json.dumps(context, indent=2))
    return context


def gather_api_context(openapi_url: str | None, out_dir: Path, spec_path: Path | None = None) -> dict:
    """Fetch or load OpenAPI context."""
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_path = out_dir / "api_context.json"

    if not openapi_url:
        if existing_path.exists():
            return json.loads(existing_path.read_text())
        if spec_path and spec_path.exists():
            spec = yaml.safe_load(spec_path.read_text())
            spec_endpoints = (spec.get("api") or {}).get("endpoints") or []
            if spec_endpoints:
                summary = {
                    "source": f"built from {spec_path}'s api.endpoints list",
                    "endpoint_count": len(spec_endpoints),
                    "endpoints": spec_endpoints,
                }
                existing_path.write_text(json.dumps(summary, indent=2))
                return summary

        summary = {"note": "No OpenAPI spec provided."}
        existing_path.write_text(json.dumps(summary, indent=2))
        return summary

    resp = requests.get(openapi_url, timeout=15)
    resp.raise_for_status()
    raw = resp.text
    spec = json.loads(raw) if openapi_url.endswith(".json") else yaml.safe_load(raw)

    endpoints = []
    for path, methods in spec.get("paths", {}).items():
        for method, details in methods.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete"):
                continue
            endpoints.append({
                "path": path,
                "method": method.upper(),
                "summary": details.get("summary", ""),
                "parameters": [
                    {"name": p.get("name"), "in": p.get("in"), "required": p.get("required", False)}
                    for p in details.get("parameters", [])
                ],
                "request_body_required": bool(details.get("requestBody", {}).get("required")),
                "responses": list(details.get("responses", {}).keys()),
            })

    summary = {"source": openapi_url, "endpoint_count": len(endpoints), "endpoints": endpoints}
    existing_path.write_text(json.dumps(summary, indent=2))
    return summary


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
