"""
context_gatherer.py

Gathers the context an LLM needs to write good tests, so we never hand it a
free-text description and hope for the best.

For UI testing:
  - full accessibility tree snapshot (roles, names, states)
  - a flat list of interactive elements (links, buttons, inputs, selects)
    each with a SUGGESTED PLAYWRIGHT LOCATOR, ranked by stability:
    data-testid > aria-label/role > id > name > visible text
  - a full-page screenshot (only used for genuinely visual checks)
  - optionally logs in first, so pages behind authentication can be
    inspected too (see --login-url below)

For API testing:
  - fetches and trims an OpenAPI/Swagger spec into a compact summary
    (path, method, params, request body shape, response codes)

Usage (no login needed):
    python context_gatherer.py --url https://example.com/login \
        --openapi https://example.com/api/openapi.json \
        --out context/

Usage (page requires being logged in first):
    python context_gatherer.py --url https://example.com/dashboard \
        --login-url https://example.com/login \
        --out context/
    (reads TEST_USERNAME / TEST_PASSWORD from your .env by default;
    override field selectors with --email-selector / --password-selector
    if the login form doesn't use #email / #password)
"""

import argparse
import base64
import json
import os
import re
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

MAX_ELEMENTS = 200  # keep the context small enough to be cheap and precise


def _suggest_locator(el: dict) -> str:
    """Rank locator strategies by stability and return the best one as
    ready-to-use Playwright Python code."""
    if el.get("testid"):
        return f'page.get_by_test_id("{el["testid"]}")'

    # For text-entry inputs, id/name/placeholder are usually more specific
    # than role="textbox" (a page can have several textboxes with no
    # distinguishing accessible name), so try those first for input tags.
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
    return f'page.locator("{el.get("tag", "unknown")}")  # no stable attribute found'


COLLECT_JS = """
() => {
  const sel = 'a, button, input, select, textarea, [role], [data-testid]';
  const nodes = Array.from(document.querySelectorAll(sel)).slice(0, %d);

  // Map tag/type to the ARIA role Playwright's get_by_role expects.
  // An explicit role="" attribute always wins; otherwise fall back to
  // each element's implicit role. Never treat an <input type="..."> as
  // a role directly - "submit", "email", "password" etc are NOT roles.
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
      // text, email, password, search, tel, url, number, or no type at all
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


def login(page, login_url: str, username_env: str, password_env: str,
          email_selector: str, password_selector: str, submit_name: str) -> None:
    """Log in on `login_url` using credentials from environment variables,
    then wait for navigation away from the login page. Raises a clear error
    if credentials are missing or login doesn't appear to succeed - fails
    loudly rather than silently continuing as an anonymous/logged-out user."""
    username = os.environ.get(username_env)
    password = os.environ.get(password_env)
    if not username or not password:
        raise RuntimeError(
            f"Login requested but {username_env} and/or {password_env} are not "
            f"set in your environment/.env file. Refusing to guess credentials."
        )

    page.goto(login_url, wait_until="networkidle")
    page.locator(email_selector).fill(username)
    page.locator(password_selector).fill(password)

    # Try a role-based submit button first (most robust); fall back to a
    # generic form submit if no button matches the given name.
    submit_button = page.get_by_role("button", name=re.compile(submit_name, re.I))
    if submit_button.count() > 0:
        submit_button.first.click()
    else:
        page.locator(email_selector).press("Enter")

    # Wait for the URL to change away from the login page, or for the
    # network to settle - whichever signal the app gives us. Don't hang
    # forever if the site doesn't redirect as expected.
    try:
        page.wait_for_url(lambda u: u != login_url, timeout=10000)
    except Exception:
        pass
    page.wait_for_load_state("networkidle", timeout=15000)

    if page.url == login_url:
        raise RuntimeError(
            "Login was submitted but the browser is still on the login page "
            "(URL didn't change). Login likely failed - check TEST_USERNAME/"
            "TEST_PASSWORD, or that --email-selector/--password-selector/"
            "--submit-name match the actual form."
        )


def gather_ui_context(url: str, out_dir: Path, headless: bool = True,
                       login_config: dict | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()

        if login_config:
            login(page, **login_config)

        page.goto(url, wait_until="networkidle")

        title = page.title()
        elements = page.evaluate(COLLECT_JS)
        for el in elements:
            el["suggested_locator"] = _suggest_locator(el)

        try:
            ax_tree = page.accessibility.snapshot()
        except Exception:
            ax_tree = None  # not fatal - the element list above is usually enough

        screenshot_path = out_dir / "screenshot.png"
        page.screenshot(path=str(screenshot_path), full_page=True)

        browser.close()

    context = {
        "url": url,
        "title": title,
        "authenticated": bool(login_config),
        "interactive_elements": elements,
        "accessibility_tree": ax_tree,
        "screenshot_path": str(screenshot_path),
    }
    (out_dir / "ui_context.json").write_text(json.dumps(context, indent=2))
    return context


def gather_api_context(openapi_url: str | None, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_path = out_dir / "api_context.json"

    if not openapi_url:
        # Don't clobber a real api_context.json (e.g. one built manually from
        # a Swagger page) just because this particular run didn't pass
        # --openapi. Only write the placeholder if nothing is there yet.
        if existing_path.exists():
            existing = json.loads(existing_path.read_text())
            print(f"  (no --openapi given - keeping existing {existing_path})")
            return existing
        summary = {"note": "No OpenAPI spec provided - list endpoints manually in the spec file."}
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


def image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gather UI + API context for test generation")
    parser.add_argument("--url", required=True,
                         help="Page to inspect for UI locators (the page you land on AFTER login, if using --login-url)")
    parser.add_argument("--openapi", default=None, help="OpenAPI/Swagger spec URL (optional)")
    parser.add_argument("--out", default="context", help="Output directory")
    parser.add_argument("--headed", action="store_true", help="Run browser with a visible window")

    login_group = parser.add_argument_group("login (optional - for pages behind authentication)")
    login_group.add_argument("--login-url", default=None,
                              help="If set, logs in here first before navigating to --url")
    login_group.add_argument("--username-env", default="TEST_USERNAME",
                              help="Env var holding the login username/email (default: TEST_USERNAME)")
    login_group.add_argument("--password-env", default="TEST_PASSWORD",
                              help="Env var holding the login password (default: TEST_PASSWORD)")
    login_group.add_argument("--email-selector", default="#email",
                              help="CSS selector for the email/username field (default: #email)")
    login_group.add_argument("--password-selector", default="#password",
                              help="CSS selector for the password field (default: #password)")
    login_group.add_argument("--submit-name", default="sign in|log in|login|submit",
                              help="Case-insensitive regex matching the submit button's accessible name")
    args = parser.parse_args()

    out_dir = Path(args.out)

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

    ui_ctx = gather_ui_context(args.url, out_dir, headless=not args.headed, login_config=login_config)
    api_ctx = gather_api_context(args.openapi, out_dir)

    print(f"UI context: {len(ui_ctx['interactive_elements'])} interactive elements found"
          f"{' (authenticated session)' if login_config else ''}")
    print(f"API context: {api_ctx.get('endpoint_count', 0)} endpoints found")
    print(f"Written to {out_dir}/")