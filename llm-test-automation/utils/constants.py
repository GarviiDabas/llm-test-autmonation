"""
utils/constants.py

Centralized project constants, environment defaults, timeouts,
and test configuration parameters to ensure sensitive data and endpoints
are not hardcoded or openly exposed in generated test files.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Base URLs ---
DEFAULT_API_BASE_URL = "https://api.eventhub.rahulshettyacademy.com/api"
DEFAULT_UI_BASE_URL = "https://eventhub.rahulshettyacademy.com"
DEFAULT_LOGIN_URL = "https://eventhub.rahulshettyacademy.com/login"

API_BASE_URL = os.environ.get("API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
UI_BASE_URL = os.environ.get("UI_BASE_URL", DEFAULT_UI_BASE_URL).rstrip("/")
LOGIN_URL = os.environ.get("LOGIN_URL", DEFAULT_LOGIN_URL)

# --- Default Credentials ---
TEST_USERNAME = os.environ.get("TEST_USERNAME")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD")

# --- Framework & Execution Constants ---
DEFAULT_TIMEOUT_MS = 10000  # 10 seconds default Playwright timeout
DEFAULT_HTTP_TIMEOUT_SEC = 15  # 15 seconds HTTP request timeout

# --- API Endpoint Constants ---
ENDPOINT_AUTH_REGISTER = "/auth/register"
ENDPOINT_AUTH_LOGIN = "/auth/login"
ENDPOINT_AUTH_ME = "/auth/me"
ENDPOINT_EVENTS = "/events"
ENDPOINT_BOOKINGS = "/bookings"

# --- Test Data Placeholders & Headers ---
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}
