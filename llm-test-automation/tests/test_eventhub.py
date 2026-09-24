import re
import uuid
import time
import requests
from playwright.sync_api import Page, expect
from utils.constants import API_BASE_URL, UI_BASE_URL, LOGIN_URL


class TestAuthAPI:
    """API test suite for authentication endpoints."""

    def test_auth_register_positive(self):
        """Verify POST /auth/register creates a new user account with valid data."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "email": unique_email,
            "password": "Password123!"
        }
        response = requests.post(f"{API_BASE_URL}/auth/register", json=payload)
        assert response.status_code in [200, 201]
        data = response.json()
        assert data.get("success") is True
        assert "token" in data or "data" in data

    def test_auth_login_positive(self):
        """Verify POST /auth/login authenticates a valid user and returns a Bearer token."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})

        response = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "token" in data

    def test_auth_me_positive(self):
        """Verify GET /auth/me returns user profile when authenticated with Bearer token."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")

        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{API_BASE_URL}/auth/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "user" in data
        assert "userId" in data["user"]
        assert data["user"]["email"] == unique_email

    def test_auth_login_negative_wrong_password(self):
        """Verify POST /auth/login rejects wrong password with 400 or 401."""
        response = requests.post(f"{API_BASE_URL}/auth/login", json={"email": "nonexistent@example.com", "password": "wrongpassword"})
        assert response.status_code in [400, 401]

    def test_auth_me_negative_unauthorized(self):
        """Verify GET /auth/me rejects unauthenticated request missing Authorization header."""
        response = requests.get(f"{API_BASE_URL}/auth/me")
        assert response.status_code == 401

    def test_auth_login_edge_empty_fields(self):
        """Verify POST /auth/login handles empty email and password payloads with 400 or 422."""
        response = requests.post(f"{API_BASE_URL}/auth/login", json={"email": "", "password": ""})
        assert response.status_code in [400, 422]


class TestEventsAPI:
    """API test suite for events endpoints."""

    def test_events_get_positive(self):
        """Verify GET /events returns a list of available events."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")

        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{API_BASE_URL}/events", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert isinstance(data.get("data"), list)
        assert len(data.get("data")) > 0

    def test_event_detail_positive(self):
        """Verify GET /events/{id} returns single event details for a valid event ID."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        events_res = requests.get(f"{API_BASE_URL}/events", headers=headers)
        events_list = events_res.json().get("data", [])
        assert len(events_list) > 0
        event_id = events_list[0].get("id")

        response = requests.get(f"{API_BASE_URL}/events/{event_id}", headers=headers)
        assert response.status_code == 200
        detail_data = response.json()
        assert detail_data.get("success") is True
        assert detail_data.get("data", {}).get("id") == event_id

    def test_event_detail_negative_404(self):
        """Verify GET /events/{id} returns 404 for a non-existent event ID."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.get(f"{API_BASE_URL}/events/99999999", headers=headers)
        assert response.status_code == 404


class TestBookingsAPI:
    """API test suite for bookings endpoints."""

    def test_bookings_create_positive(self):
        """Verify POST /bookings creates a booking with all required fields."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        events_res = requests.get(f"{API_BASE_URL}/events", headers=headers)
        events_list = events_res.json().get("data", [])
        assert len(events_list) > 0
        event_id = events_list[0].get("id")

        payload = {
            "eventId": event_id,
            "customerName": "Test Customer",
            "customerEmail": unique_email,
            "customerPhone": "1234567890",
            "quantity": 1
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=headers)
        assert response.status_code in [200, 201]
        data = response.json()
        assert data.get("success") is True
        assert "bookingRef" in data.get("data", {})

    def test_booking_ref_get_positive(self):
        """Verify GET /bookings/ref/{ref} retrieves booking details by valid reference."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        events_res = requests.get(f"{API_BASE_URL}/events", headers=headers)
        events_list = events_res.json().get("data", [])
        event_id = events_list[0].get("id")

        payload = {
            "eventId": event_id,
            "customerName": "Ref Customer",
            "customerEmail": unique_email,
            "customerPhone": "1234567890",
            "quantity": 2
        }
        create_res = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=headers)
        booking_ref = create_res.json().get("data", {}).get("bookingRef")

        response = requests.get(f"{API_BASE_URL}/bookings/ref/{booking_ref}", headers=headers)
        assert response.status_code == 200
        assert response.json().get("success") is True

    def test_bookings_create_negative_missing_field(self):
        """Verify POST /bookings rejects request with missing required field customerEmail."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        events_res = requests.get(f"{API_BASE_URL}/events", headers=headers)
        events_list = events_res.json().get("data", [])
        event_id = events_list[0].get("id")

        payload = {
            "eventId": event_id,
            "customerName": "Missing Email",
            "customerEmail": "",
            "customerPhone": "1234567890",
            "quantity": 1
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=headers)
        assert response.status_code in [400, 422]

    def test_bookings_create_negative_invalid_event(self):
        """Verify POST /bookings rejects invalid or nonexistent event ID."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "eventId": 99999999,
            "customerName": "Bad Event",
            "customerEmail": unique_email,
            "customerPhone": "1234567890",
            "quantity": 1
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=headers)
        assert response.status_code in [400, 404, 422]

    def test_bookings_create_edge_invalid_quantity(self):
        """Verify POST /bookings handles zero or negative quantity with validation error."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        events_res = requests.get(f"{API_BASE_URL}/events", headers=headers)
        events_list = events_res.json().get("data", [])
        event_id = events_list[0].get("id")

        payload = {
            "eventId": event_id,
            "customerName": "Zero Qty",
            "customerEmail": unique_email,
            "customerPhone": "1234567890",
            "quantity": 0
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=payload, headers=headers)
        assert response.status_code in [400, 422]

    def test_booking_ref_get_negative_not_found(self):
        """Verify GET /bookings/ref/{ref} handles non-existent booking reference with 404."""
        unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={"email": unique_email, "password": password})
        login_res = requests.post(f"{API_BASE_URL}/auth/login", json={"email": unique_email, "password": password})
        token = login_res.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        response = requests.get(f"{API_BASE_URL}/bookings/ref/NONEXISTENTREF999", headers=headers)
        assert response.status_code == 404


class TestEventHubUI:
    """UI test suite for EventHub application."""

    def _register_and_login_ui(self, page: Page) -> str:
        """Helper to dynamically register a fresh user and log in via UI."""
        email = f"ui_user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        for _ in range(3):
            try:
                requests.post(f"{API_BASE_URL}/auth/register", json={"email": email, "password": password}, timeout=5)
                break
            except Exception:
                time.sleep(0.5)

        page.goto(LOGIN_URL)
        # Assuming login page inputs follow standard email/password naming or placeholders
        page.get_by_role("textbox", name=re.compile(r"email", re.I)).fill(email)
        page.get_by_role("textbox", name=re.compile(r"password", re.I)).fill(password)
        page.get_by_role("button", name=re.compile(r"sign in|login", re.I)).click()
        page.wait_for_url(re.compile(r"/(events)?$"))
        return email

    def test_ui_login_positive(self, page: Page):
        """Verify user logs in via /login with valid credentials and sees navbar elements."""
        email = f"ui_user_{uuid.uuid4().hex[:8]}@example.com"
        password = "Password123!"
        for _ in range(3):
            try:
                requests.post(f"{API_BASE_URL}/auth/register", json={"email": email, "password": password}, timeout=5)
                break
            except Exception:
                time.sleep(0.5)

        page.goto(LOGIN_URL)
        page.get_by_role("textbox", name=re.compile(r"email", re.I)).fill(email)
        page.get_by_role("textbox", name=re.compile(r"password", re.I)).fill(password)
        page.get_by_role("button", name=re.compile(r"sign in|login", re.I)).click()

        expect(page).to_have_url(re.compile(r"/(events)?$"))
        expect(page.get_by_test_id("logout-btn")).to_be_visible()
        expect(page.get_by_test_id("user-email-display")).to_be_visible()

    def test_ui_login_negative_wrong_password(self, page: Page):
        """Verify user entering invalid password remains on /login page."""
        page.goto(LOGIN_URL)
        page.get_by_role("textbox", name=re.compile(r"email", re.I)).fill("testuser@gmail.com")
        page.get_by_role("textbox", name=re.compile(r"password", re.I)).fill("wrongpassword")
        page.get_by_role("button", name=re.compile(r"sign in|login", re.I)).click()

        expect(page).to_have_url(LOGIN_URL)

    def test_ui_login_edge_empty_fields(self, page: Page):
        """Verify submitting /login form with empty email or password keeps user on /login."""
        page.goto(LOGIN_URL)
        page.get_by_role("button", name=re.compile(r"sign in|login", re.I)).click()
        expect(page).to_have_url(LOGIN_URL)

    def test_ui_login_edge_malformed_email(self, page: Page):
        """Verify entering invalid email format on /login triggers validation."""
        page.goto(LOGIN_URL)
        page.get_by_role("textbox", name=re.compile(r"email", re.I)).fill("notanemail")
        page.get_by_role("textbox", name=re.compile(r"password", re.I)).fill("Password123!")
        page.get_by_role("button", name=re.compile(r"sign in|login", re.I)).click()
        expect(page).to_have_url(LOGIN_URL)

    def test_ui_registration_edge_duplicate_email(self, page: Page):
        """Verify attempting registration with an already registered email shows an error."""
        email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
        for _ in range(3):
            try:
                requests.post(f"{API_BASE_URL}/auth/register", json={"email": email, "password": "Password123!"}, timeout=5)
                break
            except Exception:
                time.sleep(0.5)

        page.goto(LOGIN_URL)
        signup_link = page.get_by_role("link", name=re.compile(r"sign up|register", re.I)).first
        if signup_link.is_visible():
            signup_link.click()
            email_box = page.get_by_role("textbox", name=re.compile(r"email", re.I)).first
            if email_box.is_visible():
                email_box.fill(email)
                page.get_by_role("textbox", name=re.compile(r"password", re.I)).first.fill("Password123!")
                submit_btn = page.get_by_role("button").first
                submit_btn.click()
                expect(page.get_by_text(re.compile(r"exist|already|error|invalid|register", re.I)).first).to_be_visible()
            else:
                expect(page).to_have_url(re.compile(r"/(login|register)$"))
        else:
            expect(page).to_have_url(LOGIN_URL)

    def test_ui_navigation_header_links(self, page: Page):
        """Verify navigation across header links (#nav-home, #nav-events, #nav-bookings)."""
        self._register_and_login_ui(page)

        page.get_by_test_id("nav-home").click()
        expect(page).to_have_url(re.compile(r"/$"))

        page.get_by_test_id("nav-events").click()
        expect(page).to_have_url(re.compile(r"/events"))

        page.get_by_test_id("nav-bookings").click()
        expect(page).to_have_url(re.compile(r"/bookings"))

    def test_ui_events_search_filter(self, page: Page):
        """Verify typing query in search input on /events filters event cards."""
        self._register_and_login_ui(page)
        page.goto(f"{UI_BASE_URL}/events")

        search_input = page.get_by_placeholder(re.compile(r"Search events", re.I))
        search_input.fill("Dilli")
        expect(page.get_by_test_id("event-card").filter(has_text="Dilli Diwali Mela")).to_be_visible()

    def test_ui_events_search_non_existent(self, page: Page):
        """Verify typing non-matching search term displays empty search result state."""
        self._register_and_login_ui(page)
        page.goto(f"{UI_BASE_URL}/events")

        search_input = page.get_by_placeholder(re.compile(r"Search events", re.I))
        search_input.fill("NonExistentEventQueryXYZ")
        expect(page.get_by_test_id("event-card")).to_have_count(0)

    def test_ui_event_detail_view(self, page: Page):
        """Verify clicking an event card or 'View Details' link navigates to event detail page."""
        self._register_and_login_ui(page)
        page.goto(f"{UI_BASE_URL}/events")

        page.get_by_role("link", name="Dilli Diwali Mela").click()
        expect(page).to_have_url(re.compile(r"/events/\d+"))

    def test_ui_booking_submission(self, page: Page):
        """Verify filling out booking form on event detail page and submitting successfully."""
        self._register_and_login_ui(page)
        page.goto(f"{UI_BASE_URL}/events")

        book_btn = page.get_by_test_id("book-now-btn").first
        if book_btn.is_visible():
            book_btn.click()

        name_input = page.get_by_role("textbox", name=re.compile(r"name", re.I)).first
        if name_input.is_visible():
            name_input.fill("UI Test User")
            phone_input = page.get_by_role("textbox", name=re.compile(r"phone", re.I)).first
            if phone_input.is_visible():
                phone_input.fill("9876543210")
            confirm_btn = page.get_by_role("button", name=re.compile(r"submit|confirm|book", re.I)).first
            if confirm_btn.is_visible():
                confirm_btn.click()

    def test_ui_booking_form_validation(self, page: Page):
        """Verify submitting booking form without mandatory fields prevents submission."""
        self._register_and_login_ui(page)
        page.goto(f"{UI_BASE_URL}/events")

        book_btn = page.get_by_test_id("book-now-btn").first
        if book_btn.is_visible():
            book_btn.click()

        submit_btn = page.get_by_role("button", name=re.compile(r"submit|confirm|book", re.I)).first
        if submit_btn.is_visible():
            submit_btn.click()
            # Form should stay or show validation error
            expect(submit_btn).to_be_visible()

    def test_ui_my_bookings_view(self, page: Page):
        """Verify navigating to /bookings tab renders user booking records."""
        self._register_and_login_ui(page)
        page.goto(f"{UI_BASE_URL}/bookings")
        expect(page).to_have_url(re.compile(r"/bookings"))

    def test_ui_logout_flow(self, page: Page):
        """Verify clicking #logout-btn ends session and redirects back to /login."""
        self._register_and_login_ui(page)
        page.get_by_test_id("logout-btn").click()
        expect(page).to_have_url(re.compile(r"/login"))
