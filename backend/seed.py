"""Demo seed data.   Run from backend/:  python seed.py
WARNING: wipes every table first. Hospital names are fictional; coordinates are
approximate points around Hyderabad / Jamshoro - edit freely."""
import hashlib
import random
from datetime import datetime, timedelta, timezone

from database import get_cursor, init_pool

random.seed(42)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def pw(p):  # demo only - use bcrypt/argon2 in the real app
    return hashlib.sha256(p.encode()).hexdigest()


# cap = {resource: (total, occupied)}; age = minutes since last capacity update
HOSPITALS = [
    dict(name="Indus City General Hospital", loc="Latifabad, Hyderabad", lat=25.3797, lon=68.3547,
         verified=True, age=4, services=["Cardiology", "Neurology", "Orthopedics", "Dialysis"],
         cap={"general_bed": (120, 95), "emergency_bed": (20, 14), "icu_bed": (20, 17), "nicu_bed": (10, 6),
              "ventilator": (12, 9), "operation_theatre": (6, 2), "isolation_bed": (10, 4),
              "dialysis": (8, 5), "trauma": (6, 3), "ambulance": (5, 2)}),
    dict(name="Sindh Care Medical Center", loc="Qasimabad, Hyderabad", lat=25.4167, lon=68.3333,
         verified=True, age=10, services=["Cardiology", "Orthopedics"],
         cap={"general_bed": (80, 60), "emergency_bed": (15, 9), "icu_bed": (12, 12), "ventilator": (8, 8),
              "operation_theatre": (4, 1), "trauma": (4, 1), "ambulance": (4, 3)}),
    dict(name="Jamshoro Teaching Hospital", loc="Jamshoro", lat=25.4290, lon=68.2810,
         verified=True, age=6, services=["Cardiology", "Neurology", "Pediatrics", "Obstetrics", "Dialysis"],
         cap={"general_bed": (200, 170), "emergency_bed": (30, 22), "icu_bed": (25, 20), "nicu_bed": (15, 11),
              "ventilator": (15, 10), "operation_theatre": (8, 4), "isolation_bed": (15, 9),
              "dialysis": (10, 6), "trauma": (10, 5), "ambulance": (8, 4)}),
    dict(name="Hirabad Heart & Trauma Institute", loc="Hirabad, Hyderabad", lat=25.3920, lon=68.3700,
         verified=True, age=3, services=["Cardiology", "Orthopedics", "Neurology"],
         cap={"emergency_bed": (18, 10), "icu_bed": (16, 9), "ventilator": (10, 6),
              "operation_theatre": (5, 2), "trauma": (12, 6), "ambulance": (4, 1)}),
    dict(name="Saddar Community Hospital", loc="Saddar, Hyderabad", lat=25.3850, lon=68.3650,
         verified=True, age=25, services=["Pediatrics"],     # no ventilators on purpose
         cap={"general_bed": (50, 44), "emergency_bed": (8, 6), "icu_bed": (4, 3), "ambulance": (2, 1)}),
    dict(name="Kotri District Hospital", loc="Kotri", lat=25.3660, lon=68.3080,
         verified=True, age=180, services=["Pediatrics", "Obstetrics"],   # stale data on purpose
         cap={"general_bed": (90, 70), "emergency_bed": (12, 8), "icu_bed": (8, 7),
              "ventilator": (4, 3), "nicu_bed": (6, 2)}),
    dict(name="Al-Noor Women & Children Hospital", loc="Hyderabad", lat=25.4000, lon=68.3450,
         verified=True, age=8, services=["Pediatrics", "Obstetrics"],
         cap={"general_bed": (60, 40), "nicu_bed": (12, 7), "emergency_bed": (10, 4),
              "icu_bed": (6, 2), "ventilator": (5, 2)}),
    dict(name="New Horizon Clinic", loc="Hyderabad", lat=25.4100, lon=68.3700,
         verified=False, age=15, services=["Orthopedics"],   # pending admin verification
         cap={"general_bed": (30, 10), "emergency_bed": (5, 2), "icu_bed": (2, 0)}),
]
SERVICES = ["Cardiology", "Neurology", "Pediatrics", "Orthopedics", "Dialysis", "Obstetrics"]
PATHS = {
    "admitted": ["searching", "request_sent", "hospital_reviewing", "accepted",
                 "patient_transferred", "admitted"],
    "rejected": ["searching", "request_sent", "hospital_reviewing", "rejected"],
    "expired": ["searching", "request_sent", "expired"],
    "cancelled": ["searching", "request_sent", "cancelled"],
}


def main():
    init_pool()
    with get_cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for t in ["capacity_snapshots", "capacity_audit_log", "request_status_history",
                  "reservations", "referral_requests", "hospital_services", "services",
                  "capacity", "users", "hospitals"]:
            cur.execute(f"TRUNCATE TABLE {t}")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        now = utc_now()

        # hospitals
        hids = []
        for h in HOSPITALS:
            cur.execute(
                """INSERT INTO hospitals (hospital_name, location, city, latitude, longitude,
                       contact, verification_status)
                   VALUES (%s,%s,'Hyderabad',%s,%s,%s,%s)""",
                (h["name"], h["loc"], h["lat"], h["lon"], "+92-22-0000000",
                 "verified" if h["verified"] else "pending"))
            hids.append(cur.lastrowid)

        # users: id 1 = coordinator (the backend's placeholder CURRENT_USER_ID)
        cur.execute("INSERT INTO users (full_name,email,password_hash,role) VALUES "
                    "('Demo Coordinator','coordinator@demo.local',%s,'coordinator'),"
                    "('Demo Admin','admin@demo.local',%s,'admin'),"
                    "('Demo Patient','patient@demo.local',%s,'patient')",
                    (pw("demo123"), pw("demo123"), pw("demo123")))
        for i, hid in enumerate(hids, 1):
            cur.execute("INSERT INTO users (full_name,email,password_hash,role,hospital_id) "
                        "VALUES (%s,%s,%s,'hospital_staff',%s)",
                        (f"Staff {i}", f"staff{i}@demo.local", pw("demo123"), hid))

        # services
        sid = {}
        for s in SERVICES:
            cur.execute("INSERT INTO services (service_name) VALUES (%s)", (s,))
            sid[s] = cur.lastrowid
        for h, hid in zip(HOSPITALS, hids):
            for s in h["services"]:
                cur.execute("INSERT INTO hospital_services (hospital_id, service_id) VALUES (%s,%s)",
                            (hid, sid[s]))

        # capacity + 7-day snapshots for trend charts
        cap_ids = {}
        for h, hid in zip(HOSPITALS, hids):
            for res, (total, occ) in h["cap"].items():
                cur.execute(
                    """INSERT INTO capacity (hospital_id, resource_type, total_capacity, occupied,
                           last_updated)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (hid, res, total, occ, now - timedelta(minutes=h["age"])))
                cap_ids[(hid, res)] = cur.lastrowid
                if res in ("icu_bed", "emergency_bed", "general_bed"):
                    for d in range(7, 0, -1):
                        o = max(0, min(total, occ + random.randint(-3, 3)))
                        cur.execute(
                            "INSERT INTO capacity_snapshots (hospital_id, resource_type, occupied, "
                            "total_capacity, captured_at) VALUES (%s,%s,%s,%s,%s)",
                            (hid, res, o, total, now - timedelta(days=d)))

        # historical referral requests (for analytics)
        verified = [hid for h, hid in zip(HOSPITALS, hids) if h["verified"]]
        resources = ["icu_bed", "emergency_bed", "general_bed", "nicu_bed", "trauma"]
        outcomes = ["admitted"] * 10 + ["rejected"] * 4 + ["expired"] * 3 + ["cancelled"] * 2
        for i in range(25):
            hid = random.choice(verified)
            res = random.choice(resources)
            outcome = random.choice(outcomes)
            hrs = random.randint(1, 150)
            respond = random.randint(2, 25)
            created = now - timedelta(hours=hrs)
            responded = created + timedelta(minutes=respond) if outcome in ("admitted", "rejected") else None
            accepted = created + timedelta(minutes=respond) if outcome == "admitted" else None
            cur.execute(
                """INSERT INTO referral_requests
                   (patient_reference, created_by, required_resource, urgency, selected_hospital,
                    request_status, created_at, responded_at, accepted_at)
                   VALUES (%s,1,%s,%s,%s,%s,%s,%s,%s)""",
                (f"PT-{1000 + i}", res, random.choice(["medium", "high", "critical"]), hid, outcome,
                 created, responded, accepted))
            rid = cur.lastrowid
            for step, st_ in enumerate(PATHS[outcome]):
                cur.execute(
                    "INSERT INTO request_status_history (request_id, status, changed_by, changed_at) "
                    "VALUES (%s,%s,1,%s)", (rid, st_, created + timedelta(minutes=step * 3)))

        # one flagged update so the admin page has something to review
        cid = cap_ids[(hids[2], "icu_bed")]
        cur.execute(
            """INSERT INTO capacity_audit_log (capacity_id, changed_by, old_total, new_total,
                   old_occupied, new_occupied, reason, flagged)
               VALUES (%s,4,25,25,5,20,'manual_update',1)""", (cid,))
    print("Seeded. Logins: coordinator@demo.local / admin@demo.local / staffN@demo.local  (pw: demo123)")


if __name__ == "__main__":
    main()
