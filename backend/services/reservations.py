"""Reservation + capacity logic. Every function expects to run inside ONE
transaction (a single get_cursor() block) so the row locks do their job."""

RESERVATION_MINUTES = 15


def log_change(cur, capacity_id, user_id, old_total, new_total,
               old_occ, new_occ, reason, flagged=False):
    cur.execute(
        """INSERT INTO capacity_audit_log
           (capacity_id, changed_by, old_total, new_total, old_occupied, new_occupied, reason, flagged)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (capacity_id, user_id, old_total, new_total, old_occ, new_occ, reason, flagged),
    )


def set_status(cur, request_id, status, user_id=None):
    extra = ""
    if status == "accepted":
        extra = ", accepted_at = now(), responded_at = COALESCE(responded_at, now())"
    elif status == "rejected":
        extra = ", responded_at = COALESCE(responded_at, now())"
    cur.execute(
        f"UPDATE referral_requests SET request_status = %s{extra} WHERE request_id = %s",
        (status, request_id),
    )
    cur.execute(
        "INSERT INTO request_status_history (request_id, status, changed_by) VALUES (%s,%s,%s)",
        (request_id, status, user_id),
    )


def reserve(cur, request_id, capacity_id):
    """Hold one unit for 15 minutes. Returns reservation row, or None if full."""
    # Row lock: two simultaneous requests cannot both grab the last bed
    cur.execute("SELECT available FROM capacity WHERE capacity_id = %s FOR UPDATE", (capacity_id,))
    row = cur.fetchone()
    if not row or row["available"] < 1:
        return None
    cur.execute(
        "UPDATE capacity SET reserved = reserved + 1, last_updated = now() WHERE capacity_id = %s",
        (capacity_id,),
    )
    cur.execute(
        """INSERT INTO reservations (request_id, capacity_id, expires_at)
           VALUES (%s, %s, DATE_ADD(NOW(), INTERVAL %s MINUTE))""",
        (request_id, capacity_id, RESERVATION_MINUTES),
    )
    cur.execute("SELECT reservation_id, expires_at FROM reservations WHERE reservation_id = %s",
                (cur.lastrowid,))
    return cur.fetchone()


def release(cur, request_id):
    """Give the held unit back (reject / cancel)."""
    cur.execute(
        "SELECT reservation_id, capacity_id, units FROM reservations "
        "WHERE request_id = %s AND state = 'active' FOR UPDATE",
        (request_id,),
    )
    for r in cur.fetchall():
        cur.execute("UPDATE reservations SET state = 'released' WHERE reservation_id = %s",
                    (r["reservation_id"],))
        cur.execute(
            "UPDATE capacity SET reserved = GREATEST(reserved - %s, 0), last_updated = now() "
            "WHERE capacity_id = %s",
            (r["units"], r["capacity_id"]),
        )


def confirm_transfer(cur, request_id, user_id):
    """Patient arrived: reserved -> occupied. False if the hold already expired."""
    cur.execute(
        "SELECT reservation_id, capacity_id, units FROM reservations "
        "WHERE request_id = %s AND state = 'active' FOR UPDATE",
        (request_id,),
    )
    r = cur.fetchone()
    if not r:
        return False
    cur.execute("SELECT total_capacity, occupied FROM capacity WHERE capacity_id = %s FOR UPDATE",
                (r["capacity_id"],))
    old = cur.fetchone()
    cur.execute(
        "UPDATE capacity SET reserved = GREATEST(reserved - %s, 0), occupied = occupied + %s, "
        "last_updated = now() WHERE capacity_id = %s",
        (r["units"], r["units"], r["capacity_id"]),
    )
    cur.execute("UPDATE reservations SET state = 'confirmed' WHERE reservation_id = %s",
                (r["reservation_id"],))
    log_change(cur, r["capacity_id"], user_id, old["total_capacity"], old["total_capacity"],
               old["occupied"], old["occupied"] + r["units"], "referral_transfer_confirmed")
    return True


def expire_stale(cur):
    """Background job: free holds older than 15 minutes. Returns how many expired."""
    cur.execute(
        "SELECT reservation_id, request_id, capacity_id, units FROM reservations "
        "WHERE state = 'active' AND expires_at < now() FOR UPDATE SKIP LOCKED"
    )
    rows = cur.fetchall()
    for r in rows:
        cur.execute("UPDATE reservations SET state = 'expired' WHERE reservation_id = %s",
                    (r["reservation_id"],))
        cur.execute(
            "UPDATE capacity SET reserved = GREATEST(reserved - %s, 0), last_updated = now() "
            "WHERE capacity_id = %s",
            (r["units"], r["capacity_id"]),
        )
        cur.execute(
            "SELECT request_status FROM referral_requests WHERE request_id = %s", (r["request_id"],)
        )
        req = cur.fetchone()
        if req and req["request_status"] in ("request_sent", "hospital_reviewing", "accepted"):
            set_status(cur, r["request_id"], "expired")
    return len(rows)
