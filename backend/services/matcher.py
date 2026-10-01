"""Smart hospital matcher: hard filters first, then a weighted score."""
import math
from datetime import datetime, timezone

AVG_SPEED_KMH = 40          # rough city ambulance speed for travel-time estimate
MAX_RADIUS_KM = 50          # distance score reaches 0 at this radius
FRESH_MINUTES = 15          # data this new gets full freshness score
STALE_MINUTES = 60          # data older than this is flagged as possibly outdated

# Weights (sum to 1.0) - tune these and explain them in your project document
W_DISTANCE, W_AVAILABILITY, W_FRESHNESS, W_EMERGENCY = 0.45, 0.30, 0.15, 0.10


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def find_candidates(cur, resource_type, needs_ventilator=False, service_id=None):
    """Step 1: remove hospitals that cannot serve the request at all."""
    sql = """
        SELECT h.hospital_id, h.hospital_name, h.latitude, h.longitude, h.contact,
               h.emergency_available,
               c.capacity_id, c.total_capacity, c.occupied, c.available, c.last_updated
        FROM hospitals h
        JOIN capacity c ON c.hospital_id = h.hospital_id AND c.resource_type = %(res)s
        WHERE h.verification_status = 'verified'
          AND h.account_status = 'active'
          AND c.available >= 1
    """
    params = {"res": resource_type}
    if needs_ventilator:
        sql += """ AND EXISTS (SELECT 1 FROM capacity v
                   WHERE v.hospital_id = h.hospital_id
                     AND v.resource_type = 'ventilator' AND v.available >= 1)"""
    if service_id:
        sql += """ AND EXISTS (SELECT 1 FROM hospital_services hs
                   WHERE hs.hospital_id = h.hospital_id
                     AND hs.service_id = %(svc)s AND hs.is_available)"""
        params["svc"] = service_id
    cur.execute(sql, params)
    return cur.fetchall()


def score_hospital(h, distance_km, age_minutes):
    """Step 2: score 0-100. Higher = better match."""
    distance_score = max(0.0, 1 - distance_km / MAX_RADIUS_KM)

    occupancy = h["occupied"] / h["total_capacity"] if h["total_capacity"] else 1
    availability_score = 0.5 * min(h["available"] / 5, 1) + 0.5 * (1 - occupancy)

    if age_minutes <= FRESH_MINUTES:
        freshness_score = 1.0
    elif age_minutes >= STALE_MINUTES:
        freshness_score = 0.0
    else:
        freshness_score = 1 - (age_minutes - FRESH_MINUTES) / (STALE_MINUTES - FRESH_MINUTES)

    emergency_score = 1.0 if h["emergency_available"] else 0.0

    total = (W_DISTANCE * distance_score + W_AVAILABILITY * availability_score
             + W_FRESHNESS * freshness_score + W_EMERGENCY * emergency_score)
    return round(total * 100, 1)


def rank_hospitals(cur, resource_type, latitude, longitude,
                   needs_ventilator=False, service_id=None):
    now = datetime.now(timezone.utc).replace(tzinfo=None)   # DB stores naive UTC
    ranked = []
    for h in find_candidates(cur, resource_type, needs_ventilator, service_id):
        dist = haversine_km(latitude, longitude, h["latitude"], h["longitude"])
        age_min = (now - h["last_updated"]).total_seconds() / 60
        ranked.append({
            "hospital_id": h["hospital_id"],
            "hospital_name": h["hospital_name"],
            "latitude": h["latitude"],
            "longitude": h["longitude"],
            "capacity_id": h["capacity_id"],
            "available": h["available"],
            "distance_km": round(dist, 1),
            "est_travel_min": round(dist / AVG_SPEED_KMH * 60),
            "match_percent": score_hospital(h, dist, age_min),
            "last_updated_min_ago": round(age_min),
            "possibly_outdated": age_min > STALE_MINUTES,
            "contact": h["contact"],
        })
    ranked.sort(key=lambda x: x["match_percent"], reverse=True)
    return ranked
