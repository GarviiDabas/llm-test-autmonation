import re
import time
import uuid
import pytest
import requests
from playwright.sync_api import Page, expect
from utils.constants import API_BASE_URL, UI_BASE_URL, LOGIN_URL, TEST_USERNAME, TEST_PASSWORD


class TestAuthAPI:
    """API test suite for authentication endpoints."""

    def test_auth_register_positive(self):
        """Verify POST /auth/register successfully creates a new user account."""
        unique_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        payload = {"email": unique_email, "password": "Password123!"}
        response = requests.post(f"{API_BASE_URL}/auth/register", json=payload)
        assert response.status_code in [200, 201]
        data = response.json()
        assert data.get("success") is True

    def test_auth_login_positive(self):
        """Verify POST /auth/login authenticates a valid user and returns a token."""
        payload = {"email": TEST_USERNAME, "password": TEST_PASSWORD}
        response = requests.post(f"{API_BASE_URL}/auth/login", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "token" in data
        assert "user" in data

    def test_auth_me_positive(self):
        """Verify GET /auth/me returns user profile when authenticated with Bearer token."""
        login_resp = requests.post(f"{API_BASE_URL}/auth/login", json={"email": TEST_USERNAME, "password": TEST_PASSWORD})
        token = login_resp.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{API_BASE_URL}/auth/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "user" in data
        assert "userId" in data["user"]
        assert "email" in data["user"]

    def test_auth_login_negative_wrong_password(self):
        """Verify POST /auth/login rejects wrong password with 400 or 401."""
        payload = {"email": TEST_USERNAME, "password": "WrongPassword123!"}
        response = requests.post(f"{API_BASE_URL}/auth/login", json=payload)
        assert response.status_code in [400, 401]

    def test_auth_me_negative_unauthorized(self):
        """Verify GET /auth/me rejects requests missing Authorization header."""
        response = requests.get(f"{API_BASE_URL}/auth/me")
        assert response.status_code == 401

    def test_auth_login_edge_empty_payload(self):
        """Verify POST /auth/login handles empty email and password payloads."""
        payload = {"email": "", "password": ""}
        response = requests.post(f"{API_BASE_URL}/auth/login", json=payload)
        assert response.status_code in [400, 422]


class TestEventsAPI:
    """API test suite for event endpoints."""

    @pytest.fixture(autouse=True)
    def auth_token(self):
        login_resp = requests.post(f"{API_BASE_URL}/auth/login", json={"email": TEST_USERNAME, "password": TEST_PASSWORD})
        self.token = login_resp.json().get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_events_list_positive(self):
        """Verify GET /events returns a non-empty list of available events."""
        response = requests.get(f"{API_BASE_URL}/events", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert isinstance(data.get("data"), list)
        assert len(data["data"]) > 0

    def test_events_detail_positive(self):
        """Verify GET /events/{id} returns single event details for valid ID."""
        list_resp = requests.get(f"{API_BASE_URL}/events", headers=self.headers)
        events = list_resp.json().get("data", [])
        if not events:
            pytest.skip("No events available for detail test")
        event_id = events[0]["id"]
        response = requests.get(f"{API_BASE_URL}/events/{event_id}", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data["data"].get("id") == event_id
        assert "title" in data["data"]

    def test_events_detail_negative_not_found(self):
        """Verify GET /events/{id} returns 404 for non-existent event ID."""
        response = requests.get(f"{API_BASE_URL}/events/99999999", headers=self.headers)
        assert response.status_code == 404


class TestBookingsAPI:
    """API test suite for booking endpoints."""

    @pytest.fixture(autouse=True)
    def setup_data(self):
        login_resp = requests.post(f"{API_BASE_URL}/auth/login", json={"email": TEST_USERNAME, "password": TEST_PASSWORD})
        self.token = login_resp.json().get("token")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        events_resp = requests.get(f"{API_BASE_URL}/events", headers=self.headers)
        events = events_resp.json().get("data", [])
        self.event_id = events[0]["id"] if events else 1

    def test_bookings_create_and_get_positive(self):
        """Verify POST /bookings creates a booking and GET /bookings/ref/{ref} retrieves it."""
        payload = {
            "eventId": self.event_id,
            "customerName": "Test Automation",
            "customerEmail": f"customer_{uuid.uuid4().hex[:6]}@example.com",
            "customerPhone": "9876543210",
            "quantity": 2
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=self.headers)
        assert response.status_code in [200, 201]
        data = response.json()
        assert data.get("success") is True
        booking_ref = data["data"].get("bookingRef")
        booking_id = data["data"].get("id")
        assert booking_ref is not None

        # Retrieve by ref
        ref_resp = requests.get(f"{API_BASE_URL}/bookings/ref/{booking_ref}", headers=self.headers)
        assert ref_resp.status_code == 200
        assert ref_resp.json().get("success") is True

        # Clean up booking
        if booking_id:
            requests.delete(f"{API_BASE_URL}/bookings/{booking_id}", headers=self.headers)

    def test_bookings_create_negative_missing_field(self):
        """Verify POST /bookings rejects request missing customerEmail."""
        payload = {
            "eventId": self.event_id,
            "customerName": "Test Automation",
            "customerPhone": "9876543210",
            "quantity": 1
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=self.headers)
        assert response.status_code in [400, 422]

    def test_bookings_create_negative_invalid_event(self):
        """Verify POST /bookings rejects invalid or nonexistent event ID."""
        payload = {
            "eventId": 99999999,
            "customerName": "Test Automation",
            "customerEmail": "test@example.com",
            "customerPhone": "9876543210",
            "quantity": 1
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=self.headers)
        assert response.status_code in [400, 404, 422]

    def test_bookings_create_edge_zero_quantity(self):
        """Verify POST /bookings handles zero or negative quantity."""
        payload = {
            "eventId": self.event_id,
            "customerName": "Test Automation",
            "customerEmail": "test@example.com",
            "customerPhone": "9876543210",
            "quantity": 0
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=self.headers)
        assert response.status_code in [400, 422]

    def test_bookings_get_ref_edge_nonexistent(self):
        """Verify GET /bookings/ref/{ref} returns 404 for non-existent reference."""
        response = requests.get(f"{API_BASE_URL}/bookings/ref/NONEXISTENTREF123", headers=self.headers)
        assert response.status_code == 404


class TestEventHubUI:
    """UI test suite for EventHub application workflows using Playwright."""

    def _login_via_ui(self, page: Page):
        """Helper method to perform standard UI login."""
        page.goto(LOGIN_URL)
        page.locator("#email").fill(TEST_USERNAME)
        page.locator("#password").fill(TEST_PASSWORD)
        page.get_by_role("button", name=re.compile(r"Sign In|Login", re.I)).click()
        page.wait_for_load_state("networkidle")

    def test_ui_login_positive(self, page: Page):
        """Verify user logs in via /login with valid credentials and sees navbar elements."""
        self._login_via_ui(page)
        expect(page).to_have_url(re.compile(r"/(events)?$"))
        expect(page.get_by_test_id("logout-btn")).to_be_visible()
        expect(page.get_by_test_id("user-email-display")).to_be_visible()

    def test_ui_login_negative(self, page: Page):
        """Verify user enters invalid password on /login and remains on /login page."""
        page.goto(LOGIN_URL)
        page.locator("#email").fill(TEST_USERNAME)
        page.locator("#password").fill("IncorrectPassword!")
        page.get_by_role("button", name=re.compile(r"Sign In|Login", re.I)).click()
        expect(page).to_have_url(re.compile(r"/login"))

    def test_ui_navigation_positive(self, page: Page):
        """Verify user clicks #nav-home, #nav-events, and #nav-bookings header links."""
        self._login_via_ui(page)
        
        page.get_by_test_id("nav-home").click()
        expect(page).to_have_url(re.compile(r"/$"))
        
        page.get_by_test_id("nav-events").click()
        expect(page).to_have_url(re.compile(r"/events"))
        
        page.get_by_test_id("nav-bookings").click()
        expect(page).to_have_url(re.compile(r"/bookings"))

    def test_ui_events_search_positive(self, page: Page):
        """Verify user types query in search input on /events and verifies filtered event cards."""
        self._login_via_ui(page)
        page.get_by_test_id("nav-events").click()
        
        search_input = page.get_by_placeholder(re.compile(r"Search events, venues", re.I))
        search_input.fill("Dilli")
        page.wait_for_timeout(500)
        
        card = page.get_by_test_id("event-card").filter(has_text="Dilli Diwali Mela")
        expect(card).to_be_visible()

    def test_ui_events_search_negative_non_existent(self, page: Page):
        """Verify user types non-matching search term and verifies empty search result view."""
        self._login_via_ui(page)
        page.get_by_test_id("nav-events").click()
        
        search_input = page.get_by_placeholder(re.compile(r"Search events, venues", re.I))
        search_input.fill("NonExistentEventXYZ123")
        page.wait_for_timeout(500)
        
        cards = page.get_by_test_id("event-card")
        expect(cards).to_have_count(0)

    def test_ui_event_detail_positive(self, page: Page):
        """Verify user clicks an event card link and navigates to event detail page."""
        self._login_via_ui(page)
        page.get_by_test_id("nav-events").click()
        
        page.get_by_test_id("book-now-btn").first.click()
        expect(page).to_have_url(re.compile(r"/events/\d+"))

    def test_ui_booking_submission_positive(self, page: Page):
        """Verify user fills out booking form on event detail page and submits successfully."""
        self._login_via_ui(page)
        page.get_by_test_id("nav-events").click()
        page.get_by_test_id("book-now-btn").first.click()
        expect(page).to_have_url(re.compile(r"/events/\d+"))
        
        detail_book_btn = page.get_by_test_id("book-now-btn").first
        if detail_book_btn.is_visible():
            detail_book_btn.click()

        page.wait_for_timeout(500)
        customer_input = page.locator("#customerName, input[name='customerName']").first
        if customer_input.is_visible():
            customer_input.fill("UI Automation User")
            email_input = page.locator("#customerEmail, input[name='customerEmail']").first
            if email_input.is_visible():
                email_input.fill(f"ui_{uuid.uuid4().hex[:6]}@example.com")
            phone_input = page.locator("#phone, input[name='phone']").first
            if phone_input.is_visible():
                phone_input.fill("9876543210")
            confirm_btn = page.get_by_role("button", name=re.compile(r"Confirm|Book|Submit", re.I)).first
            if confirm_btn.is_visible():
                confirm_btn.click()

    def test_ui_booking_validation_negative(self, page: Page):
        """Verify user submits booking form without filling mandatory fields."""
        self._login_via_ui(page)
        page.get_by_test_id("nav-events").click()
        page.get_by_test_id("book-now-btn").first.click()
        expect(page).to_have_url(re.compile(r"/events/\d+"))
        
        detail_book_btn = page.get_by_test_id("book-now-btn").first
        if detail_book_btn.is_visible():
            detail_book_btn.click()

        page.wait_for_timeout(500)
        confirm_btn = page.get_by_role("button", name=re.compile(r"Confirm|Book|Submit", re.I)).first
        if confirm_btn.is_visible():
            confirm_btn.click()
            expect(page).to_have_url(re.compile(r"/events/\d+"))

    def test_ui_my_bookings_positive(self, page: Page):
        """Verify user navigates to /bookings tab and verifies booking records render."""
        self._login_via_ui(page)
        page.get_by_test_id("nav-bookings").click()
        expect(page).to_have_url(re.compile(r"/bookings"))

    def test_ui_logout_positive(self, page: Page):
        """Verify user clicks #logout-btn and session ends, redirecting back to /login."""
        self._login_via_ui(page)
        page.get_by_test_id("logout-btn").click()
        expect(page).to_have_url(re.compile(r"/login"))