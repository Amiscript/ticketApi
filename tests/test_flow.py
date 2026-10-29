from datetime import UTC, datetime, timedelta

from core.database import SessionLocal
from core.security import hash_password
from models import Role, User
from tests.conftest import register_and_login


def make_admin_headers(client):
    with SessionLocal() as db:
        db.add(User(email="admin@x.com", full_name="Admin", hashed_password=hash_password("password123"), role=Role.ADMIN))
        db.commit()
    r = client.post("/auth/login", data={"username": "admin@x.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_approved_event(client, seated=False):
    org = register_and_login(client, "org@x.com", "organizer")
    admin = make_admin_headers(client)
    starts = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    ev = client.post("/events", headers=org, json={"name": "Concert", "venue": "Hall", "starts_at": starts, "is_seated": seated}).json()
    assert client.post(f"/admin/events/{ev['id']}/approve", headers=admin).status_code == 200
    return ev, org, admin


def test_general_admission_full_flow(client):
    ev, org, admin = make_approved_event(client)
    tt = client.post(f"/events/{ev['id']}/ticket-types", headers=org, json={"name": "Regular", "price": "5000", "quantity": 2}).json()
    buyer = register_and_login(client, "buyer@x.com")

    order = client.post("/orders", headers=buyer, json={"event_id": ev["id"], "items": [{"ticket_type_id": tt["id"], "quantity": 2}]})
    assert order.status_code == 201, order.text
    assert order.json()["total_amount"] == "10000.00"

    # sold out now
    again = client.post("/orders", headers=buyer, json={"event_id": ev["id"], "items": [{"ticket_type_id": tt["id"], "quantity": 1}]})
    assert again.status_code == 409

    oid = order.json()["id"]
    ref = client.post(f"/orders/{oid}/pay", headers=buyer).json()["reference"]
    assert client.post(f"/orders/{oid}/confirm", headers=buyer, json={"reference": "wrong"}).status_code == 400
    paid = client.post(f"/orders/{oid}/confirm", headers=buyer, json={"reference": ref})
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    # idempotent
    assert client.post(f"/orders/{oid}/confirm", headers=buyer, json={"reference": ref}).status_code == 200

    tid = paid.json()["tickets"][0]["id"]
    qr = client.get(f"/tickets/{tid}/qr", headers=buyer)
    assert qr.status_code == 200 and qr.content.startswith(b"\x89PNG")

    refund = client.post(f"/admin/orders/{oid}/refund", headers=admin, json={"reason": "test"})
    assert refund.status_code == 200 and refund.json()["status"] == "refunded"
    types = client.get(f"/events/{ev['id']}/ticket-types").json()
    assert types[0]["available"] == 2  # inventory returned


def test_seat_cannot_be_double_booked(client):
    ev, org, _ = make_approved_event(client, seated=True)
    tt = client.post(f"/events/{ev['id']}/ticket-types", headers=org, json={"name": "VIP", "price": "100"}).json()
    assert client.post(f"/events/{ev['id']}/seats/generate", headers=org, json={"ticket_type_id": tt["id"], "section": "A", "rows": 1, "seats_per_row": 2}).status_code == 201
    seat_id = client.get(f"/events/{ev['id']}/seats").json()[0]["id"]

    a, b = register_and_login(client, "a@x.com"), register_and_login(client, "b@x.com")
    assert client.post("/orders", headers=a, json={"event_id": ev["id"], "seat_ids": [seat_id]}).status_code == 201
    assert client.post("/orders", headers=b, json={"event_id": ev["id"], "seat_ids": [seat_id]}).status_code == 409


def test_cancel_releases_inventory(client):
    ev, org, _ = make_approved_event(client)
    tt = client.post(f"/events/{ev['id']}/ticket-types", headers=org, json={"name": "Regular", "price": "1", "quantity": 1}).json()
    buyer = register_and_login(client, "buyer@x.com")
    oid = client.post("/orders", headers=buyer, json={"event_id": ev["id"], "items": [{"ticket_type_id": tt["id"], "quantity": 1}]}).json()["id"]
    assert client.post(f"/orders/{oid}/cancel", headers=buyer).json()["status"] == "cancelled"
    assert client.get(f"/events/{ev['id']}/ticket-types").json()[0]["available"] == 1


def test_permissions(client):
    ev, org, _ = make_approved_event(client)
    cust = register_and_login(client, "c@x.com")
    assert client.post("/events", headers=cust, json={}).status_code in (403, 422)
    assert client.get("/admin/dashboard", headers=cust).status_code == 403
    assert client.get("/admin/dashboard").status_code == 401
    assert client.patch(f"/events/{ev['id']}", headers=org, json={"name": None}).status_code == 200  # no 500
