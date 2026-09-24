"""
utils/constants.py
Centralized project configuration and constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Base URLs ---
API_BASE_URL = os.environ.get("API_BASE_URL", "https://api.eventhub.rahulshettyacademy.com/api").rstrip("/")
UI_BASE_URL = os.environ.get("UI_BASE_URL", "https://eventhub.rahulshettyacademy.com").rstrip("/")
LOGIN_URL = os.environ.get("LOGIN_URL", "https://eventhub.rahulshettyacademy.com/login")

# --- Default Credentials ---
TEST_USERNAME = os.environ.get("TEST_USERNAME")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD")

# --- Execution Limits ---
DEFAULT_TIMEOUT_MS = 10000
DEFAULT_HTTP_TIMEOUT_SEC = 15

# --- Dynamic Generation Defaults ---
DEFAULT_TEST_PASSWORD = "Password123!"
SUBMIT_BUTTON_PATTERN = "sign in|log in|login|submit"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_PROJECT_SLUG = "eventhub"

# --- Reporting ---
PROJECT_NAME = "EventHub Test Automation"
REPORT_TITLE = f"{PROJECT_NAME} Suite - Test Execution Report"
