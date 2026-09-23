import re
import uuid
import pytest
import requests
from playwright.sync_api import Page, expect

API_BASE_URL = "https://api.eventhub.rahulshettyacademy.com/api"
UI_BASE_URL = "https://eventhub.rahulshettyacademy.com"


@pytest.fixture(scope="session")
def registered_user():
    """Fixture to create a unique test user for API tests."""
    email = f"test_{uuid.uuid4().hex[:6]}@example.com"
    password = "Password123!"
    response = requests.post(f"{API_BASE_URL}/auth/register", json={
        "email": email,
        "password": password
    })
    # If registration returns 200/201 or if user already exists, login to get token
    if response.status_code not in [200, 201]:
        # Fallback registration / login
        pass
    
    login_res = requests.post(f"{API_BASE_URL}/auth/login", json={
        "email": email,
        "password": password
    })
    token = ""
    if login_res.status_code == 200:
        data = login_res.json()
        token = data.get("token") or data.get("accessToken") or data.get("access_token")
    
    return {"email": email, "password": password, "token": token}


class TestAuthAPI:
    """Suite for testing authentication endpoints."""

    def test_auth_register(self):
        """Verify POST /auth/register creates a new user account successfully."""
        email = f"reg_{uuid.uuid4().hex[:6]}@example.com"
        response = requests.post(f"{API_BASE_URL}/auth/register", json={
            "email": email,
            "password": "Password123!"
        })
        assert response.status_code in [200, 201]

    def test_auth_login(self, registered_user):
        """Verify POST /auth/login authenticates a valid user and returns a token."""
        response = requests.post(f"{API_BASE_URL}/auth/login", json={
            "email": registered_user["email"],
            "password": registered_user["password"]
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data or "accessToken" in data or "access_token" in data

    def test_auth_login_wrong_password(self, registered_user):
        """Verify POST /auth/login rejects wrong password with 400 or 401."""
        response = requests.post(f"{API_BASE_URL}/auth/login", json={
            "email": registered_user["email"],
            "password": "WrongPassword999!"
        })
        assert response.status_code in [400, 401]

    def test_auth_me_authenticated(self, registered_user):
        """Verify GET /auth/me returns user profile when authenticated."""
        token = registered_user["token"]
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{API_BASE_URL}/auth/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "user" in data
        assert "userId" in data["user"]
        assert "email" in data["user"]

    def S_test_auth_me_unauthenticated(self):
        """Verify GET /auth/me rejects unauthenticated requests with 401."""
        response = requests.get(f"{API_BASE_URL}/auth/me")
        assert response.status_code == 401


class TestEventsAPI:
    """Suite for testing event management endpoints."""

    def test_events_list(self, registered_user):
        """Verify GET /events returns a list of available events."""
        headers = {"Authorization": f"Bearer {registered_user['token']}"}
        response = requests.get(f"{API_BASE_URL}/events", headers=headers)
        assert response.status_code == 200
        data = response.json()
        # Depending on structure, it could be a list or wrapped in an object
        events = data if isinstance(data, list) else data.get("events", [])
        assert isinstance(events, list)

    def test_event_details(self, registered_user):
        """Verify GET /events/{id} returns single event details."""
        headers = {"Authorization": f"Bearer {registered_user['token']}"}
        events_res = requests.get(f"{API_BASE_URL}/events", headers=headers)
        assert events_res.status_code == 200
        events_data = events_res.json()
        events = events_data if isinstance(events_data, list) else events_data.get("events", [])
        
        if len(events) > 0:
            event_id = events[0].get("id") or events[0].get("_id")
            detail_res = requests.get(f"{API_BASE_URL}/events/{event_id}", headers=headers)
            assert detail_res.status_code == 200
            detail_data = detail_res.json()
            assert detail_data is not None


class TestBookingsAPI:
    """Suite for testing booking creation, retrieval, and deletion."""

    def test_bookings_lifecycle(self, registered_user):
        """Verify creating, retrieving by ref, and deleting a booking."""
        headers = {"Authorization": f"Bearer {registered_user['token']}"}
        events_res = requests.get(f"{API_BASE_URL}/events", headers=headers)
        assert events_res.status_code == 200
        events_data = events_res.json()
        events = events_data if isinstance(events_data, list) else events_data.get("events", [])
        
        if len(events) > 0:
            event_id = events[0].get("id") or events[0].get("_id")
            booking_payload = {
                "eventId": event_id,
                "customerName": "Test Customer",
                "customerEmail": f"cust_{uuid.uuid4().hex[:6]}@example.com",
                "customerPhone": "1234567890",
                "quantity": 1
            }
            create_res = requests.post(f"{API_BASE_URL}/bookings", json=booking_payload, headers=headers)
            assert create_res.status_code in [200, 201]
            create_data = create_res.json()
            
            booking_id = create_data.get("id") or create_data.get("_id") or create_data.get("bookingId")
            ref = create_data.get("reference") or create_data.get("ref")

            if ref:
                ref_res = requests.get(f"{API_BASE_URL}/bookings/ref/{ref}")
                assert ref_res.status_code == 200

            if booking_id:
                del_res = requests.delete(f"{API_BASE_URL}/bookings/{booking_id}", headers=headers)
                assert del_res.status_code in [200, 204]

    def test_bookings_invalid_event(self, registered_user):
        """Verify POST /bookings rejects invalid or nonexistent event ID."""
        headers = {"Authorization": f"Bearer {registered_user['token']}"}
        booking_payload = {
            "eventId": "nonexistent_event_id_99999",
            "customerName": "Test Customer",
            "customerEmail": f"cust_{uuid.uuid4().hex[:6]}@example.com",
            "customerPhone": "1234567890",
            "quantity": 1
        }
        response = requests.post(f"{API_BASE_URL}/bookings", json=booking_payload, headers=headers)
        assert response.status_code in [400, 404, 422]


class TestEventHubUI:
    """Suite for testing EventHub UI elements and flows."""

    def test_login_page_elements(self, page: Page):
        """Verify login page loads successfully with email input, password input, and Sign In button."""
        page.goto(UI_BASE_URL)
        expect(page).to_have_url(re.compile(r"/"))
        
        email_input = page.locator("#email")
        password_input = page.locator("#password")
        login_button = page.get_by_role("button", name="Sign In")

        expect(email_input).to_be_visible()
        expect(password_input).to_be_visible()
        expect(login_button).to_be_visible()
        expect(login_button).to_be_enabled()