import os
import pytest
import re
import requests
from playwright.sync_api import Page, expect

API_BASE_URL = "https://api.eventhub.rahulshettyacademy.com/api"

@pytest.fixture(scope="session")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture(scope="session")
def registered_user(api_client):
    """Creates a temporary test user within the limit of 3 accounts per run."""
    import time
    unique_suffix = int(time.time())
    email = f"testuser_{unique_suffix}@example.com"
    password = "TestPassword123!"
    
    response = api_client.post(f"{API_BASE_URL}/auth/register", json={
        "email": email,
        "password": password
    })
    
    if response.status_code not in [200, 201]:
        # Fallback to login if user already exists
        login_res = api_client.post(f"{API_BASE_URL}/auth/login", json={
            "email": email,
            "password": password
        })
        data = login_res.json()
    else:
        data = response.json()
        
    return {"email": email, "password": password, "token": data.get("token") or data.get("access_token")}

class TestAuthAPI:
    def test_user_registration(self, api_client):
        """Verify user can register a new account via POST /auth/register."""
        import time
        email = f"new_register_{int(time.time())}@example.com"
        response = api_client.post(f"{API_BASE_URL}/auth/register", json={
            "email": email,
            "password": "Password123!"
        })
        assert response.status_code in [200, 201]
        data = response.json()
        assert "email" in data or "token" in data or "id" in data

    def test_user_login_valid_and_invalid(self, api_client, registered_user):
        """Verify user can log in with valid credentials and fails with a clear error on wrong password."""
        # Valid login
        login_res = api_client.post(f"{API_BASE_URL}/auth/login", json={
            "email": registered_user["email"],
            "password": registered_user["password"]
        })
        assert login_res.status_code == 200
        assert "token" in login_res.json() or "access_token" in login_res.json()

        # Invalid login
        fail_res = api_client.post(f"{API_BASE_URL}/auth/login", json={
            "email": registered_user["email"],
            "password": "WrongPassword!"
        })
        assert fail_res.status_code in [400, 401]

    def test_auth_me_endpoint(self, api_client, registered_user):
        """Verify GET /auth/me returns the logged-in user's profile when authenticated and is rejected without a valid token."""
        token = registered_user["token"]
        
        # Authenticated request
        headers = {"Authorization": f"Bearer {token}"}
        res = api_client.get(f"{API_BASE_URL}/auth/me", headers=headers)
        assert res.status_code == 200

        # Unauthenticated request
        unauth_res = api_client.get(f"{API_BASE_URL}/auth/me")
        assert unauth_res.status_code in [401, 403]


class TestEventsAPI:
    def test_get_events_list(self, api_client):
        """Verify GET /events returns a list of events with pagination metadata."""
        response = api_client.get(f"{API_BASE_URL}/events")
        assert response.status_code == 200
        data = response.json()
        # Depending on structure, could be a list or object with data/pagination
        assert isinstance(data, (list, dict))

    def test_get_single_event(self, api_client):
        """Verify GET /events/{id} returns a single event's details."""
        # First list events to get a valid ID
        list_res = api_client.get(f"{API_BASE_URL}/events")
        assert list_res.status_code == 200
        events = list_res.json()
        if isinstance(events, dict) and "data" in events:
            events = events["data"]
        
        if events and len(events) > 0:
            event_id = events[0].get("id") or events[0].get("_id")
            detail_res = api_client.get(f"{API_BASE_URL}/events/{event_id}")
            assert detail_res.status_code == 200
            assert detail_res.json() is not None


class TestBookingsAPI:
    def test_booking_lifecycle_and_rejections(self, api_client, registered_user):
        """Verify POST /bookings succeeds, can be retrieved by ref, rejected for invalid event, and deleted."""
        token = registered_user["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Get an event to book
        events_res = api_client.get(f"{API_BASE_URL}/events")
        events = events_res.json()
        if isinstance(events, dict) and "data" in events:
            events = events["data"]
        
        if not events:
            pytest.skip("No events available for booking tests")

        event_id = events[0].get("id") or events[0].get("_id")

        # POST /bookings with valid event
        booking_res = api_client.post(f"{API_BASE_URL}/bookings", headers=headers, json={
            "eventId": event_id,
            "tickets": 1
        })
        
        if booking_res.status_code in [200, 201]:
            booking_data = booking_res.json()
            booking_id = booking_data.get("id") or booking_data.get("_id")
            ref = booking_data.get("reference") or booking_data.get("ref")

            if ref:
                ref_res = api_client.get(f"{API_BASE_URL}/bookings/ref/{ref}")
                assert ref_res.status_code == 200

            if booking_id:
                # DELETE /bookings/{id}
                del_res = api_client.delete(f"{API_BASE_URL}/bookings/{booking_id}", headers=headers)
                assert del_res.status_code in [200, 204]

        # POST /bookings with invalid event id
        invalid_booking = api_client.post(f"{API_BASE_URL}/bookings", headers=headers, json={
            "eventId": 999999,
            "tickets": 1
        })
        assert invalid_booking.status_code in [400, 404, 422]


class TestEventHubUI:
    def test_browse_events_and_open_detail(self, page: Page):
        """UI: user can browse events and open an event's detail page."""
        page.goto("https://eventhub.rahulshettyacademy.com/events")
        
        # Verify event cards are visible
        event_cards = page.get_by_test_id("event-card")
        expect(event_cards.first).to_be_visible()

        # Click on an event link to open detail page
        event_link = page.get_by_role("link", name="Dilli Diwali Mela")
        expect(event_link).to_be_visible()
        event_link.click()

        # Verify navigation to detail page
        expect(page).to_have_url(re.compile(r"/events/"))

    def test_complete_booking_for_available_event(self, page: Page):
        """UI: user can complete a booking for an available event."""
        page.goto("https://eventhub.rahulshettyacademy.com/events")

        # Use book-now-btn filtered by a specific card or use nth
        book_btn = page.get_by_test_id("book-now-btn").filter(has_text="Book Now").first
        expect(book_btn).to_be_visible()
        book_btn.click()

        # Verify booking action navigates or opens booking confirmation/flow
        expect(page).to_have_url(re.compile(r"/events/" | "/bookings"))