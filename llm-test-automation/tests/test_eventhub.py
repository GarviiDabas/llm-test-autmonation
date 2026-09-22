import re
import uuid
import requests
import pytest
from playwright.sync_api import Page, expect

API_BASE_URL = "https://api.eventhub.rahulshettyacademy.com/api"
UI_BASE_URL = "https://eventhub.rahulshettyacademy.com"

@pytest.fixture
def api_user():
    """Fixture to create a unique test user and obtain authentication credentials."""
    email = f"user_{uuid.uuid4().hex[:6]}@test.com"
    password = "TestPassword123!"
    
    # Register user
    reg_res = requests.post(f"{API_BASE_URL}/auth/register", json={
        "email": email,
        "password": password
    })
    
    # Login to get token
    login_res = requests.post(f"{API_BASE_URL}/auth/login", json={
        "email": email,
        "password": password
    })
    token = None
    if login_res.status_code == 200:
        data = login_res.json()
        token = data.get("token") or data.get("accessToken") or data.get("access_token")
    
    return {
        "email": email,
        "password": password,
        "token": token
    }

class TestAuthAPI:
    def test_auth_register(self):
        """Verify POST /auth/register creates a new user account."""
        email = f"reg_{uuid.uuid4().hex[:6]}@test.com"
        password = "Password123!"
        response = requests.post(f"{API_BASE_URL}/auth/register", json={
            "email": email,
            "password": password
        })
        assert response.status_code in [200, 201]
        data = response.json()
        assert "success" in data or "token" in data or "message" in data

    def test_auth_login(self):
        """Verify POST /auth/login authenticates a valid user and returns a token."""
        email = f"login_{uuid.uuid4().hex[:6]}@test.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={
            "email": email,
            "password": password
        })
        response = requests.post(f"{API_BASE_URL}/auth/login", json={
            "email": email,
            "password": password
        })
        assert response.status_code == 200
        data = response.json()
        # Verify token is returned
        has_token = any(k in data for k in ["token", "accessToken", "access_token"])
        assert has_token or "success" in data

    def test_auth_login_wrong_password(self):
        """Verify POST /auth/login rejects incorrect passwords with 400 or 401."""
        email = f"wrong_{uuid.uuid4().hex[:6]}@test.com"
        password = "Password123!"
        requests.post(f"{API_BASE_URL}/auth/register", json={
            "email": email,
            "password": password
        })
        response = requests.post(f"{API_BASE_URL}/auth/login", json={
            "email": email,
            "password": "WrongPassword999!"
        })
        assert response.status_code in [400, 401]

    def test_auth_me_authenticated(self, api_user):
        """Verify GET /auth/me returns user profile when authenticated."""
        token = api_user["token"]
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = requests.get(f"{API_BASE_URL}/auth/me", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert "user" in data
        assert "userId" in data["user"]
        assert "email" in data["user"]

    def test_auth_me_unauthenticated(self):
        """Verify GET /auth/me rejects unauthenticated requests with 401."""
        response = requests.get(f"{API_BASE_URL}/auth/me")
        assert response.status_code == 401


class TestEventsAPI:
    def test_events_list(self, api_user):
        """Verify GET /events returns a list of available events."""
        token = api_user["token"]
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = requests.get(f"{API_BASE_URL}/events", headers=headers)
        assert response.status_code == 200
        data = response.json()
        # Can be a list or wrapped in an object containing a list
        events = data if isinstance(data, list) else data.get("events", data.get("data", []))
        assert isinstance(events, list)

    def test_event_details(self, api_user):
        """Verify GET /events/{id} returns single event details."""
        token = api_user["token"]
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        events_res = requests.get(f"{API_BASE_URL}/events", headers=headers)
        assert events_res.status_code == 200
        events_data = events_res.json()
        events = events_data if isinstance(events_data, list) else events_data.get("events", events_data.get("data", []))
        
        if len(events) > 0:
            event_id = events[0].get("id") or events[0].get("_id") or events[0].get("eventId")
            if event_id:
                res = requests.get(f"{API_BASE_URL}/events/{event_id}", headers=headers)
                assert res.status_code == 200
                res_data = res.json()
                assert res_data is not None


class TestBookingsAPI:
    def test_create_and_manage_booking(self, api_user):
        """Verify POST /bookings, GET /bookings/ref/{ref}, and DELETE /bookings/{id} lifecycle."""
        token = api_user["token"]
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        
        # Get an event first
        events_res = requests.get(f"{API_BASE_URL}/events", headers=headers)
        assert events_res.status_code == 200
        events_data = events_res.json()
        events = events_data if isinstance(events_data, list) else events_data.get("events", events_data.get("data", []))
        
        if len(events) > 0:
            event = events[0]
            event_id = event.get("id") or event.get("_id") or event.get("eventId")
            
            booking_payload = {
                "eventId": event_id,
                "customerName": "Test Customer",
                "customerEmail": api_user["email"],
                "customerPhone": "1234567890",
                "quantity": 1
            }
            
            # Create Booking
            post_res = requests.post(f"{API_BASE_URL}/bookings", json=booking_payload, headers=headers)
            assert post_res.status_code in [200, 201]
            booking_data = post_res.json()
            
            booking_ref = booking_data.get("reference") or booking_data.get("ref") or booking_data.get("bookingReference")
            booking_id = booking_data.get("id") or booking_data.get("_id") or booking_data.get("bookingId")
            
            # Retrieve Booking by ref if reference exists
            if booking_ref:
                ref_res = requests.get(f"{API_BASE_URL}/bookings/ref/{booking_ref}")
                assert ref_res.status_code == 200
                
            # Delete Booking if ID exists
            if booking_id:
                del_res = requests.delete(f"{API_BASE_URL}/bookings/{booking_id}", headers=headers)
                assert del_res.status_code in [200, 204]

    def test_bookings_invalid_event(self, api_user):
        """Verify POST /bookings rejects nonexistent event ID."""
        token = api_user["token"]
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        
        booking_payload = {
            "eventId": "nonexistent_event_id_99999",
            "customerName": "Test Customer",
            "customerEmail": api_user["email"],
            "customerPhone": "1234567890",
            "quantity": 1
        }
        
        response = requests.post(f"{API_BASE_URL}/bookings", json=booking_payload, headers=headers)
        assert response.status_code in [400, 404, 422]


class TestEventHubUI:
    def test_login_page_load(self, page: Page):
        """Verify the login page loads successfully and interactive elements are visible."""
        page.goto(UI_BASE_URL)
        expect(page).to_have_url(re.compile(r"eventhub\.rahulshettyacademy\.com"))
        
        # Verify email input, password input, and Sign In button are visible
        email_input = page.locator("#email")
        password_input = page.locator("#password")
        sign_in_btn = page.get_by_role("button", name="Sign In")
        
        expect(email_input).to_be_visible()
        expect(password_input).to_be_visible()
        expect(sign_in_btn).to_be_visible()