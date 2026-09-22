"""
conftest.py

Shared pytest fixtures for the EventHub test suite & Pytest-HTML report hooks.
"""

import base64
import os
import re
import uuid

import pytest
import requests
from dotenv import load_dotenv
from playwright.sync_api import Page

load_dotenv()

DEFAULT_API_BASE_URL = os.environ.get("API_BASE_URL", "https://api.eventhub.rahulshettyacademy.com/api")
DEFAULT_UI_BASE_URL = os.environ.get("UI_BASE_URL", "https://eventhub.rahulshettyacademy.com")
LOGIN_URL = os.environ.get("LOGIN_URL", "https://eventhub.rahulshettyacademy.com/login")


# ============================================================================
# Environment & Client Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Returns the Base URL for API endpoints."""
    return DEFAULT_API_BASE_URL.rstrip("/")


@pytest.fixture(scope="session")
def ui_base_url() -> str:
    """Returns the Base URL for the frontend application."""
    return DEFAULT_UI_BASE_URL.rstrip("/")


@pytest.fixture
def api_client(api_base_url: str) -> requests.Session:
    """Returns a requests.Session pre-authenticated with a fresh Bearer token."""
    session = requests.Session()
    email_suffix = uuid.uuid4().hex[:6]
    test_email = f"apiuser_{email_suffix}@example.com"
    test_password = "SecurePassword123!"

    # Register & Login
    session.post(f"{api_base_url}/auth/register", json={"email": test_email, "password": test_password})
    login_resp = session.post(f"{api_base_url}/auth/login", json={"email": test_email, "password": test_password})
    token_data = login_resp.json()
    token = token_data.get("token") or token_data.get("accessToken")

    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })
    return session


@pytest.fixture
def authenticated_page(page: Page) -> Page:
    """Logs into EventHub UI once and returns an authenticated Playwright Page."""
    username = os.environ.get("TEST_USERNAME")
    password = os.environ.get("TEST_PASSWORD")
    if not username or not password:
        pytest.fail("TEST_USERNAME/TEST_PASSWORD not set in .env - can't log in for this test.")

    page.goto(LOGIN_URL, wait_until="networkidle")
    page.locator("#email").fill(username)
    page.locator("#password").fill(password)
    page.get_by_role("button", name=re.compile("sign in|log in|login", re.I)).first.click()

    # Wait for redirect away from login page
    page.wait_for_url(lambda u: u != LOGIN_URL, timeout=10000)
    page.wait_for_load_state("networkidle")

    return page


# ============================================================================
# Browser Console Error Capture Hook
# ============================================================================

@pytest.fixture(autouse=True)
def capture_browser_console(request):
    """Automatically records browser console.error messages during UI test runs."""
    page = request.node.funcargs.get("page") or request.node.funcargs.get("authenticated_page")
    console_errors = []
    if page:
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    yield
    if console_errors and hasattr(request.node, "rep_call") and request.node.rep_call.failed:
        print(f"\n[Browser Console Errors in {request.node.name}]:\n" + "\n".join(console_errors))


# ============================================================================
# Pytest-HTML Report Hooks
# ============================================================================

def pytest_html_report_title(report):
    report.title = "EventHub Test Automation Suite — Test Execution Report"


def pytest_configure(config):
    if hasattr(config, "_metadata"):
        config._metadata["Project Name"] = "EventHub Test Automation"
        config._metadata["Target API / App"] = DEFAULT_API_BASE_URL
        config._metadata["Execution Mode"] = "Pytest + Playwright (Headless)"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if call.when == "call":
        setattr(item, "rep_call", report)

    extras = getattr(report, "extras", [])

    if report.when == "call" and report.failed:
        page = item.funcargs.get("page") or item.funcargs.get("authenticated_page")
        if page:
            try:
                screenshot_bytes = page.screenshot(full_page=True)
                encoded = base64.b64encode(screenshot_bytes).decode("ascii")
                pytest_html = item.config.pluginmanager.getplugin("html")
                if pytest_html:
                    extras.append(
                        pytest_html.extras.html(
                            f'<div style="margin-top:12px;">'
                            f'<strong style="color:#ef4444;">Failure Screenshot:</strong><br/>'
                            f'<img src="data:image/png;base64,{encoded}" '
                            f'style="max-width:750px; border-radius:8px; margin-top:6px; border:1px solid #475569; box-shadow:0 10px 15px -3px rgba(0,0,0,0.3);"/>'
                            f'</div>'
                        )
                    )
            except Exception:
                pass

    report.extras = extras
