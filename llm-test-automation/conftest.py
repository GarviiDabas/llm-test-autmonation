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
from utils.logger import get_logger
from utils.constants import (
    API_BASE_URL,
    UI_BASE_URL,
    LOGIN_URL,
    DEFAULT_TEST_PASSWORD,
    PROJECT_NAME,
    REPORT_TITLE
)

logger = get_logger("conftest")

load_dotenv()

# ============================================================================
# Environment & Client Fixtures
# ============================================================================

@pytest.fixture
def test_logger(request):
    """Provides a test-specific logger fixture for test functions."""
    return get_logger(request.node.name)


@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Returns the Base URL for API endpoints."""
    return API_BASE_URL.rstrip("/")


@pytest.fixture(scope="session")
def ui_base_url() -> str:
    """Returns the Base URL for the frontend application."""
    return UI_BASE_URL.rstrip("/")


@pytest.fixture
def api_client(api_base_url: str) -> requests.Session:
    """Returns a requests.Session pre-authenticated with a fresh Bearer token."""
    session = requests.Session()
    email_suffix = uuid.uuid4().hex[:6]
    test_email = f"apiuser_{email_suffix}@example.com"
    test_password = "SecurePassword123!"

    logger.info(f"Setting up API client session for user: {test_email}")
    reg_resp = session.post(f"{api_base_url}/auth/register", json={"email": test_email, "password": test_password})
    logger.debug(f"Registration response status: {reg_resp.status_code}")

    login_resp = session.post(f"{api_base_url}/auth/login", json={"email": test_email, "password": test_password})
    token_data = login_resp.json()
    token = token_data.get("token") or token_data.get("accessToken")

    if not token:
        pytest.fail(
            f"api_client fixture: failed to obtain auth token. "
            f"Login status: {login_resp.status_code}. Response: {login_resp.text}"
        )
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
        logger.error("TEST_USERNAME/TEST_PASSWORD not found in environment settings.")
        pytest.fail("TEST_USERNAME/TEST_PASSWORD not set in .env - can't log in for this test.")

    logger.info(f"Navigating to login page: {LOGIN_URL}")
    page.goto(LOGIN_URL, wait_until="networkidle")
    page.locator("#email").fill(username)
    page.locator("#password").fill(password)
    page.get_by_role("button", name=re.compile("sign in|log in|login", re.I)).first.click()

    # Wait for redirect away from login page
    page.wait_for_url(lambda u: u != LOGIN_URL, timeout=10000)
    page.wait_for_load_state("networkidle")
    logger.info(f"Successfully authenticated UI session. Redirected to: {page.url}")

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
    if console_errors:
        node_logger = get_logger(request.node.name)
        node_logger.warning(f"[Browser Console Errors in {request.node.name}]:\n" + "\n".join(console_errors))



# ============================================================================
# Pytest-HTML Report Hooks
# ============================================================================

def pytest_html_report_title(report):
    report.title = "EventHub Test Automation Suite — Test Execution Report"


def pytest_configure(config):
    if hasattr(config, "_metadata"):
        config._metadata["Project Name"] = "EventHub Test Automation"
        config._metadata["Target API / App"] = API_BASE_URL
        config._metadata["Execution Mode"] = "Pytest + Playwright (Headless)"


def pytest_unconfigure(config):
    """Ensure generated HTML reports include lang='en' for WCAG accessibility and SonarQube compliance."""
    htmlpath = getattr(config.option, "htmlpath", None)
    if htmlpath:
        from pathlib import Path
        p = Path(htmlpath)
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8")
                if "<html>" in text:
                    p.write_text(text.replace("<html>", '<html lang="en">', 1), encoding="utf-8")
            except Exception:
                pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if call.when == "call":
        setattr(item, "rep_call", report)

    # Format human-readable test name for Pytest HTML report
    doc = item.obj.__doc__.strip().split("\n")[0] if (item.obj and item.obj.__doc__) else ""
    class_name = item.cls.__name__ if item.cls else ""
    pretty_class = re.sub(r"^Test", "", class_name)
    pretty_class = re.sub(r"([A-Z])", r" \1", pretty_class).strip()

    if doc:
        if pretty_class:
            report.nodeid = f"{pretty_class} - {doc}"
        else:
            report.nodeid = doc
    else:
        func_name = item.name.split("[")[0]
        pretty_func = re.sub(r"^test_", "", func_name).replace("_", " ").title()
        if pretty_class:
            report.nodeid = f"{pretty_class} - {pretty_func}"
        else:
            report.nodeid = pretty_func

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


@pytest.fixture(scope="session")
def registered_user():
    """Fixture to create a unique test user for API tests."""
    email = f"test_{uuid.uuid4().hex[:6]}@example.com"
    password = DEFAULT_TEST_PASSWORD

    reg_res = requests.post(f"{API_BASE_URL}/auth/register", json={"email": email, "password": password})

    if reg_res.status_code in [200, 201]:
        data = reg_res.json()
        token = data.get("token") or data.get("accessToken") or data.get("access_token")
        if token:
            return {"email": email, "password": password, "token": token}

    # Fallback: attempt login (user may already exist)
    login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": email, "password": password})
    if login_res.status_code != 200:
        pytest.fail(
            f"registered_user fixture: registration returned {reg_res.status_code} "
            f"and login fallback returned {login_res.status_code}. "
            f"Cannot proceed. Login response: {login_res.text}"
        )

    data = login_res.json()
    token = data.get("token") or data.get("accessToken") or data.get("access_token")
    if not token:
        pytest.fail(f"registered_user fixture: login succeeded but no token in response: {data}")

    return {"email": email, "password": password, "token": token}
