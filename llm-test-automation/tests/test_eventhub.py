import time
import uuid
import re
import pytest
import requests
from playwright.sync_api import Page, expect
from utils.constants import API_BASE_URL, UI_BASE_URL, LOGIN_URL, TEST_USERNAME, TEST_PASSWORD


class TestAuthAPI:
    """Test suite for Authentication API endpoints."""

    def test_auth_register_positive(self):
        """Verify successful user registration with valid credentials."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "email": unique_email,
            "password": "Password123!"
        }
        response = requests.post(f"{API_BASE_URL}/auth/register", json=payload)
        assert response.status_code in [200, 201]
        data = response.json()
        assert data.get("success") is True
        assert "token" in data
        assert "data" in data or "user" in data

    def test_auth_login_positive(self):
        """Verify successful user login with valid credentials."""
        # Register a user first to guarantee valid credentials
        unique_email = f"login_user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        
        payload = {
            "email": unique_email,
            "password": password
        }
        response = requests.post(f"{API_BASE_URL}/auth/login", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "token" in data
        assert "user" in data
        assert data["user"].get("email") == unique_email

    def test_auth_login_negative_invalid_password(self):
        """Verify user login fails with an incorrect password."""
        payload = {
            "email": "testuser@gmail.com",
            "password": "WrongPassword999!"
        }
        response = requests.post(f"{API_BASE_URL}/auth/login", json=payload)
        assert response.status_code in [400, 401]

    def test_auth_me_positive(self):
        """Verify fetching the current authenticated user profile."""
        unique_email = f"me_user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        reg_res = requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        token = reg_res.json().get("token")
        
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{API_BASE_URL}/auth/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "user" in data
        assert data["user"].get("email") == unique_email

    def test_auth_me_negative_unauthorized(self):
        """Verify fetching user profile without a Bearer token returns 401."""
        response = requests.get(f"{API_BASE_URL}/auth/me")
        assert response.status_code == 401


class TestEventsAPI:
    """Test suite for Events API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_token(self):
        """Obtain a valid authentication token for event tests."""
        unique_email = f"event_tester_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        reg_res = requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        self.token = reg_res.json().get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_events_list_positive(self):
        """Verify listing all events with a valid Bearer token."""
        response = requests.get(f"{API_BASE_URL}/events", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert isinstance(data.get("data"), list)

    def test_events_detail_positive(self):
        """Verify fetching a single event by valid ID."""
        list_res = requests.get(f"{API_BASE_URL}/events", headers=self.headers)
        events = list_res.json().get("data", [])
        if not events:
            pytest.skip("No events available in the system to test detail view.")
        
        event_id = events[0].get("id")
        response = requests.get(f"{API_BASE_URL}/events/{event_id}", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("data").get("id") == event_id

    def test_events_detail_negative_not_found(self):
        """Verify fetching a non-existent event ID returns 404."""
        response = requests.get(f"{API_BASE_URL}/events/99999999", headers=self.headers)
        assert response.status_code == 404


class TestBookingsAPI:
    """Test suite for Bookings API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_token_and_event(self):
        """Obtain auth token and a valid event ID for booking tests."""
        unique_email = f"booking_tester_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        reg_res = requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        self.token = reg_res.json().get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}

        list_res = requests.get(f"{API_BASE_URL}/events", headers=self.headers)
        events = list_res.json().get("data", [])
        if events:
            self.event_id = events[0].get("id")
        else:
            self.event_id = 1

    def test_bookings_create_and_delete_positive(self):
        """Verify successful creation of a booking and subsequent cancellation via DELETE."""
        payload = {
            "eventId": self.event_id,
            "customerName": "Test Customer",
            "customerEmail": f"customer_{uuid.uuid4().hex[:6]}@example.com",
            "customerPhone": "9876543210",
            "quantity": 2
        }
        create_res = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=self.headers)
        assert create_res.status_code in [200, 201]
        create_data = create_res.json()
        assert create_data.get("success") is True
        
        booking_data = create_data.get("data", {})
        booking_id = booking_data.get("id")
        booking_ref = booking_data.get("bookingRef")
        assert booking_id is not None
        assert booking_ref is not None

        # Test get by ref endpoint
        ref_res = requests.get(f"{API_BASE_URL}/bookings/ref/{booking_ref}", headers=self.headers)
        assert ref_res.status_code == 200
        assert ref_res.json().get("success") is True

        # Cleanup: Delete the booking
        del_res = requests.delete(f"{API_BASE_URL}/bookings/{booking_id}", headers=self.headers)
        assert del_res.status_code in [200, 204]

    def test_bookings_create_negative_missing_fields(self):
        """Verify booking creation fails when required payload parameters are missing."""
        payload = {
            "eventId": self.event_id,
            "customerName": "Incomplete Customer"
            # Missing customerEmail, customerPhone, quantity
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=self.headers)
        assert response.status_code in [400, 422]


class TestEventHubUI:
    """Test suite for EventHub UI interactions using Playwright."""

    def login_to_app(self, page: Page):
        """Helper to log into the UI application."""
        page.goto(LOGIN_URL)
        page.locator("#email").fill(TEST_USERNAME)
        page.locator("#password").fill(TEST_PASSWORD)
        page.get_by_role("button", name=re.compile(r"Sign In", re.I)).click()
        page.wait_for_url(re.compile(r".*/(events|dashboard|)?"))

    def test_ui_home_page_navigation(self, page: Page):
        """Verify authenticated home page loads and displays key navigation and event cards."""
        self.login_to_app(page)
        page.goto(UI_BASE_URL)
        expect(page.get_by_test_id("nav-home")).to_be_visible()
        expect(page.get_by_test_id("event-card").first).to_be_visible()

    def test_ui_events_page_navigation(self, page: Page):
        """Verify navigating to the events page via top navigation bar."""
        self.login_to_app(page)
        page.get_by_test_id("nav-events").click()
        expect(page).to_have_url(re.compile(r"/events"))

    def test_ui_bookings_page_navigation(self, page: Page):
        """Verify navigating to the My Bookings page via top navigation bar."""
        self.login_to_app(page)
        page.get_by_test_id("nav-bookings").click()
        expect(page).to_have_url(re.compile(r"/bookings"))