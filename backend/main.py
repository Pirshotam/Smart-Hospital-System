"""Smart Hospital Bed & Emergency Capacity System - FastAPI backend.
Run:  uvicorn main:app --reload
Docs: http://localhost:8000/docs
"""
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from database import close_pool, get_cursor, init_pool
from services import matcher, reservations

CURRENT_USER_ID = 1  # TODO: replace with the logged-in user (JWT/session) + role checks

# Allowed request status transitions (the workflow from the brief)
ALLOWED = {
    "searching": {"request_sent", "no_capacity", "cancelled"},
    "request_sent": {"hospital_reviewing", "accepted", "rejected", "cancelled", "expired"},
    "hospital_reviewing": {"accepted", "rejected", "cancelled", "expired"},
    "accepted": {"patient_transferred", "cancelled", "expired"},
    "patient_transferred": {"admitted"},
}


def run_expiry():
    with get_cursor() as cur:
        return reservations.expire_stale(cur)


async def expiry_loop():
    while True:
        try:
            await asyncio.to_thread(run_expiry)
        except Exception as e:
            print("expiry job error:", e)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()
    task = asyncio.create_task(expiry_loop())
    yield
    task.cancel()
    close_pool()


app = FastAPI(title="Smart Hospital Bed & Emergency Capacity System", lifespan=lifespan)


# ---------- schemas ----------
class SearchIn(BaseModel):
    resource_type: str                 # e.g. 'icu_bed'
    latitude: float
    longitude: float
    needs_ventilator: bool = False
    service_id: Optional[int] = None


class RequestIn(SearchIn):
    patient_reference: str
    urgency: str = "medium"
    case_summary: Optional[str] = None
    location: Optional[str] = None


class SendIn(BaseModel):
    hospital_id: int


class CapacityUpdate(BaseModel):
    total_capacity: Optional[int] = None
    occupied: Optional[int] = None
    unavailable: Optional[int] = None


# ---------- helpers ----------
def get_request(cur, request_id):
    cur.execute("SELECT * FROM referral_requests WHERE request_id = %s FOR UPDATE", (request_id,))
    req = cur.fetchone()
    if not req:
        raise HTTPException(404, "Request not found")
    return req


def check_transition(req, new_status):
    if new_status not in ALLOWED.get(req["request_status"], set()):
        raise HTTPException(409, f"Cannot move from {req['request_status']} to {new_status}")


# ---------- search & matching ----------
@app.post("/search")
def search_hospitals(body: SearchIn):
    with get_cursor() as cur:
        return matcher.rank_hospitals(
            cur, body.resource_type, body.latitude, body.longitude,
            body.needs_ventilator, body.service_id,
        )


@app.get("/hospitals/{hospital_id}/capacity")
def hospital_capacity(hospital_id: int):
    with get_cursor() as cur:
        cur.execute(
            """SELECT capacity_id, resource_type, total_capacity, occupied, reserved,
                      unavailable, available, last_updated,
                      TIMESTAMPDIFF(MINUTE, last_updated, NOW()) > 60 AS possibly_outdated
               FROM capacity WHERE hospital_id = %s ORDER BY resource_type""",
            (hospital_id,),
        )
        return cur.fetchall()


@app.get("/hospitals")
def list_hospitals():
    with get_cursor() as cur:
        cur.execute(
            """SELECT hospital_id, hospital_name, location, city, latitude, longitude, contact,
                      verification_status, emergency_available, account_status
               FROM hospitals ORDER BY hospital_name""")
        return cur.fetchall()


@app.post("/hospitals/{hospital_id}/verify")
def verify_hospital(hospital_id: int):
    """Admin action: mark a hospital account as verified."""
    with get_cursor() as cur:
        cur.execute("SELECT hospital_id FROM hospitals WHERE hospital_id = %s", (hospital_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Hospital not found")
        cur.execute("UPDATE hospitals SET verification_status = 'verified' "
                    "WHERE hospital_id = %s", (hospital_id,))
        return {"status": "verified"}


@app.get("/hospitals/{hospital_id}/requests")
def hospital_requests(hospital_id: int):
    """Incoming referral requests for a hospital's dashboard."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT r.request_id, r.patient_reference, r.required_resource, r.needs_ventilator,
                      r.urgency, r.case_summary, r.request_status, r.created_at,
                      res.expires_at AS reserved_until
               FROM referral_requests r
               LEFT JOIN reservations res ON res.request_id = r.request_id AND res.state = 'active'
               WHERE r.selected_hospital = %s
               ORDER BY r.created_at DESC LIMIT 50""", (hospital_id,))
        return cur.fetchall()


# ---------- referral workflow ----------
@app.post("/requests")
def create_request(body: RequestIn):
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO referral_requests
               (patient_reference, created_by, required_resource, needs_ventilator,
                required_service, location, latitude, longitude, urgency, case_summary)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (body.patient_reference, CURRENT_USER_ID, body.resource_type, body.needs_ventilator,
             body.service_id, body.location, body.latitude, body.longitude,
             body.urgency, body.case_summary),
        )
        rid = cur.lastrowid
        reservations.set_status(cur, rid, "searching", CURRENT_USER_ID)
        return {"request_id": rid, "status": "searching"}


@app.post("/requests/{request_id}/send")
def send_request(request_id: int, body: SendIn):
    """Send referral to a hospital and place the 15-minute hold."""
    reservation = None
    with get_cursor() as cur:
        req = get_request(cur, request_id)
        check_transition(req, "request_sent")
        cur.execute(
            "SELECT capacity_id FROM capacity WHERE hospital_id = %s AND resource_type = %s",
            (body.hospital_id, req["required_resource"]),
        )
        cap = cur.fetchone()
        reservation = reservations.reserve(cur, request_id, cap["capacity_id"]) if cap else None
        if reservation:
            cur.execute("UPDATE referral_requests SET selected_hospital = %s WHERE request_id = %s",
                        (body.hospital_id, request_id))
            reservations.set_status(cur, request_id, "request_sent", CURRENT_USER_ID)
        else:
            reservations.set_status(cur, request_id, "no_capacity", CURRENT_USER_ID)
    # raised after the block so the no_capacity status is committed
    if not reservation:
        raise HTTPException(409, "No capacity available at that hospital")
    return {"status": "request_sent", "reserved_until": reservation["expires_at"]}


@app.post("/requests/{request_id}/review")
def start_review(request_id: int):
    with get_cursor() as cur:
        req = get_request(cur, request_id)
        check_transition(req, "hospital_reviewing")
        reservations.set_status(cur, request_id, "hospital_reviewing", CURRENT_USER_ID)
        return {"status": "hospital_reviewing"}


@app.post("/requests/{request_id}/accept")
def accept_request(request_id: int):
    with get_cursor() as cur:
        req = get_request(cur, request_id)
        check_transition(req, "accepted")
        reservations.set_status(cur, request_id, "accepted", CURRENT_USER_ID)
        return {"status": "accepted"}


@app.post("/requests/{request_id}/reject")
def reject_request(request_id: int):
    with get_cursor() as cur:
        req = get_request(cur, request_id)
        check_transition(req, "rejected")
        reservations.release(cur, request_id)
        reservations.set_status(cur, request_id, "rejected", CURRENT_USER_ID)
        return {"status": "rejected"}


@app.post("/requests/{request_id}/cancel")
def cancel_request(request_id: int):
    with get_cursor() as cur:
        req = get_request(cur, request_id)
        check_transition(req, "cancelled")
        reservations.release(cur, request_id)
        reservations.set_status(cur, request_id, "cancelled", CURRENT_USER_ID)
        return {"status": "cancelled"}


@app.post("/requests/{request_id}/transfer")
def confirm_transfer(request_id: int):
    with get_cursor() as cur:
        req = get_request(cur, request_id)
        check_transition(req, "patient_transferred")
        if not reservations.confirm_transfer(cur, request_id, CURRENT_USER_ID):
            raise HTTPException(409, "Reservation expired - capacity was released")
        reservations.set_status(cur, request_id, "patient_transferred", CURRENT_USER_ID)
        return {"status": "patient_transferred"}


@app.post("/requests/{request_id}/admit")
def admit_patient(request_id: int):
    with get_cursor() as cur:
        req = get_request(cur, request_id)
        check_transition(req, "admitted")
        reservations.set_status(cur, request_id, "admitted", CURRENT_USER_ID)
        return {"status": "admitted"}


@app.get("/requests/{request_id}")
def track_request(request_id: int):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM referral_requests WHERE request_id = %s", (request_id,))
        req = cur.fetchone()
        if not req:
            raise HTTPException(404, "Request not found")
        cur.execute(
            "SELECT status, changed_at FROM request_status_history "
            "WHERE request_id = %s ORDER BY changed_at", (request_id,))
        return {"request": req, "history": cur.fetchall()}


# ---------- hospital staff: capacity updates ----------
@app.patch("/capacity/{capacity_id}")
def update_capacity(capacity_id: int, body: CapacityUpdate):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM capacity WHERE capacity_id = %s FOR UPDATE", (capacity_id,))
        old = cur.fetchone()
        if not old:
            raise HTTPException(404, "Capacity row not found")
        new_total = old["total_capacity"] if body.total_capacity is None else body.total_capacity
        new_occ = old["occupied"] if body.occupied is None else body.occupied
        new_unav = old["unavailable"] if body.unavailable is None else body.unavailable
        # big sudden jumps are flagged for admin review
        flagged = abs(new_occ - old["occupied"]) > max(5, 0.5 * new_total)
        if min(new_total, new_occ, new_unav) < 0 or new_occ + old["reserved"] + new_unav > new_total:
            raise HTTPException(422, "Values cannot be negative, and occupied + reserved + "
                                     "unavailable cannot exceed total")
        cur.execute(
            "UPDATE capacity SET total_capacity=%s, occupied=%s, unavailable=%s, "
            "last_updated=NOW() WHERE capacity_id=%s",
            (new_total, new_occ, new_unav, capacity_id),
        )
        cur.execute("SELECT * FROM capacity WHERE capacity_id = %s", (capacity_id,))
        row = cur.fetchone()
        reservations.log_change(cur, capacity_id, CURRENT_USER_ID, old["total_capacity"],
                                new_total, old["occupied"], new_occ, "manual_update", flagged)
        return row


# ---------- analytics ----------
@app.get("/analytics/summary")
def analytics_summary():
    with get_cursor() as cur:
        cur.execute(
            """SELECT h.hospital_name, c.resource_type,
                      ROUND(100.0 * c.occupied / NULLIF(c.total_capacity, 0), 1) AS occupancy_pct
               FROM capacity c JOIN hospitals h USING (hospital_id)
               ORDER BY occupancy_pct DESC LIMIT 5""")
        highest = cur.fetchall()
        cur.execute("SELECT request_status, COUNT(*) AS n FROM referral_requests GROUP BY 1")
        by_status = cur.fetchall()
        cur.execute(
            """SELECT ROUND(AVG(TIMESTAMPDIFF(SECOND, created_at, responded_at)) / 60.0, 1)
                      AS avg_response_min
               FROM referral_requests WHERE responded_at IS NOT NULL""")
        avg_resp = cur.fetchone()
        cur.execute(
            """SELECT required_resource, COUNT(*) AS n FROM referral_requests
               GROUP BY 1 ORDER BY n DESC LIMIT 5""")
        top_services = cur.fetchall()
        return {"highest_occupancy": highest, "requests_by_status": by_status,
                "avg_response_minutes": avg_resp["avg_response_min"],
                "most_requested_resources": top_services}


@app.get("/admin/flagged")
def flagged_updates():
    """Suspicious capacity changes waiting for admin review."""
    with get_cursor() as cur:
        cur.execute(
            """SELECT l.log_id, h.hospital_name, c.resource_type, l.old_occupied,
                      l.new_occupied, l.reason, l.changed_at
               FROM capacity_audit_log l
               JOIN capacity c ON c.capacity_id = l.capacity_id
               JOIN hospitals h ON h.hospital_id = c.hospital_id
               WHERE l.flagged ORDER BY l.changed_at DESC LIMIT 50""")
        return cur.fetchall()
