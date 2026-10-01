"""Smart Hospital Bed & Emergency Capacity System - Streamlit frontend.
Run (backend must be running):  streamlit run app.py
"""
import os

import pandas as pd
import requests
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
st.set_page_config(page_title="Smart Hospital Capacity", page_icon="🏥", layout="wide")

RESOURCES = {"ICU bed": "icu_bed", "Emergency bed": "emergency_bed", "General bed": "general_bed",
             "NICU bed": "nicu_bed", "Isolation bed": "isolation_bed",
             "Operation theatre": "operation_theatre", "Dialysis": "dialysis",
             "Trauma": "trauma", "Ambulance": "ambulance"}
LOCATIONS = {"Latifabad, Hyderabad": (25.3797, 68.3547), "Qasimabad, Hyderabad": (25.4167, 68.3333),
             "Hirabad, Hyderabad": (25.3920, 68.3700), "Saddar, Hyderabad": (25.3850, 68.3650),
             "Jamshoro": (25.4290, 68.2810), "Kotri": (25.3660, 68.3080)}
STEPS = ["searching", "request_sent", "hospital_reviewing", "accepted",
         "patient_transferred", "admitted"]


def api(method, path, **kw):
    """Returns (data, error_message)."""
    try:
        r = requests.request(method, f"{API}{path}", timeout=15, **kw)
    except requests.RequestException as e:
        st.error(f"Cannot reach the backend at {API}. Is uvicorn running?\n\n{e}")
        st.stop()
    if r.status_code >= 400:
        try:
            return None, r.json().get("detail", r.text)
        except ValueError:
            return None, r.text
    return r.json(), None


# ------------------------------------------------------------------ patient / coordinator
def page_find():
    st.header("🔍 Find a hospital")
    with st.form("search"):
        c1, c2 = st.columns(2)
        res_label = c1.selectbox("Required facility", list(RESOURCES))
        area = c2.selectbox("Current location", list(LOCATIONS))
        vent = st.checkbox("Also needs a ventilator")
        urgency = st.select_slider("Urgency", ["low", "medium", "high", "critical"], value="high")
        go = st.form_submit_button("Search hospitals", type="primary")
    if go:
        lat, lon = LOCATIONS[area]
        ctx = {"resource_type": RESOURCES[res_label], "latitude": lat, "longitude": lon,
               "needs_ventilator": vent}
        data, err = api("POST", "/search", json=ctx)
        if err:
            st.error(err)
            return
        st.session_state["results"] = data
        st.session_state["ctx"] = {**ctx, "urgency": urgency}

    results = st.session_state.get("results")
    if results is None:
        return
    if not results:
        st.warning("No verified hospital currently has the required capacity. Try widening the need.")
        return

    st.subheader(f"{len(results)} suitable hospital(s), best match first")
    st.map(pd.DataFrame(results), latitude="latitude", longitude="longitude", size=80)
    ref = st.text_input("Patient reference (name or ID) - needed to send a referral")
    for h in results:
        with st.container(border=True):
            c = st.columns([4, 1.3, 1.3, 1.3, 1.6])
            c[0].markdown(f"**{h['hospital_name']}**  \n{h['available']} available · "
                          f"updated {h['last_updated_min_ago']} min ago")
            c[1].metric("Match", f"{h['match_percent']}%")
            c[2].metric("Distance", f"{h['distance_km']} km")
            c[3].metric("Travel", f"~{h['est_travel_min']} min")
            if c[4].button("Send referral", key=f"send{h['hospital_id']}"):
                if not ref.strip():
                    st.warning("Enter a patient reference first.")
                else:
                    req, err = api("POST", "/requests",
                                   json={**st.session_state["ctx"], "patient_reference": ref})
                    if err:
                        st.error(err)
                    else:
                        out, err = api("POST", f"/requests/{req['request_id']}/send",
                                       json={"hospital_id": h["hospital_id"]})
                        if err:
                            st.error(f"Request #{req['request_id']}: {err}")
                        else:
                            st.success(f"Referral #{req['request_id']} sent. Bed held until "
                                       f"{out['reserved_until'][11:16]} UTC.")
            if h["possibly_outdated"]:
                st.caption("⚠️ Capacity information may be outdated")


def page_track():
    st.header("📍 Track a request")
    rid = st.number_input("Request ID", min_value=1, step=1)
    if st.button("Check status"):
        data, err = api("GET", f"/requests/{int(rid)}")
        if err:
            st.error(err)
            return
        status = data["request"]["request_status"]
        if status in STEPS:
            i = STEPS.index(status)
            st.progress((i + 1) / len(STEPS), text=f"{status.replace('_', ' ').title()}  "
                                                  f"(step {i + 1} of {len(STEPS)})")
        else:
            st.error(f"Final status: {status.replace('_', ' ').title()}")
        st.dataframe(pd.DataFrame(data["history"]), use_container_width=True, hide_index=True)


# ------------------------------------------------------------------ hospital staff
def page_hospital():
    st.header("🏥 Hospital dashboard")
    hospitals, _ = api("GET", "/hospitals")
    names = {h["hospital_name"]: h["hospital_id"] for h in hospitals}
    hid = names[st.sidebar.selectbox("Your hospital", list(names))]

    st.subheader("Live capacity")
    caps, _ = api("GET", f"/hospitals/{hid}/capacity")
    df = pd.DataFrame(caps)
    if df.empty:
        st.info("No capacity rows yet.")
    else:
        if df["possibly_outdated"].any():
            st.warning("⚠️ Some capacity data is more than 60 minutes old - please update.")
        st.dataframe(df.drop(columns=["capacity_id"]), use_container_width=True, hide_index=True)
        with st.form("update"):
            row = st.selectbox("Resource", df["resource_type"])
            cur_row = df[df["resource_type"] == row].iloc[0]
            c1, c2, c3 = st.columns(3)
            total = c1.number_input("Total", 0, value=int(cur_row["total_capacity"]))
            occ = c2.number_input("Occupied", 0, value=int(cur_row["occupied"]))
            unav = c3.number_input("Temporarily unavailable", 0, value=int(cur_row["unavailable"]))
            if st.form_submit_button("Update capacity", type="primary"):
                _, err = api("PATCH", f"/capacity/{int(cur_row['capacity_id'])}",
                             json={"total_capacity": total, "occupied": occ, "unavailable": unav})
                st.error(err) if err else st.rerun()

    st.subheader("Incoming referrals")
    if st.button("🔄 Refresh"):
        st.rerun()
    reqs, _ = api("GET", f"/hospitals/{hid}/requests")
    if not reqs:
        st.info("No referrals yet.")
    for r in reqs:
        with st.container(border=True):
            c = st.columns([3, 2, 4])
            c[0].markdown(f"**#{r['request_id']} · {r['patient_reference']}**  \n"
                          f"{r['required_resource'].replace('_', ' ')} · urgency: {r['urgency']}")
            c[1].markdown(f"Status: **{r['request_status'].replace('_', ' ')}**")
            s, rid = r["request_status"], r["request_id"]
            actions = []
            if s == "request_sent":
                actions.append(("Start review", "review"))
            if s in ("request_sent", "hospital_reviewing"):
                actions += [("Accept", "accept"), ("Reject", "reject")]
            if s == "accepted":
                actions.append(("Confirm transfer", "transfer"))
            if s == "patient_transferred":
                actions.append(("Admit", "admit"))
            bc = c[2].columns(max(len(actions), 1))
            for col, (label, path) in zip(bc, actions):
                if col.button(label, key=f"{path}{rid}"):
                    _, err = api("POST", f"/requests/{rid}/{path}")
                    st.error(err) if err else st.rerun()


# ------------------------------------------------------------------ admin
def page_admin():
    st.header("🛡️ Admin dashboard")
    data, _ = api("GET", "/analytics/summary")
    c1, c2 = st.columns(2)
    c1.metric("Avg hospital response time", f"{data['avg_response_minutes'] or 0} min")
    c2.metric("Total requests", sum(x["n"] for x in data["requests_by_status"]))

    a, b = st.columns(2)
    a.subheader("Highest occupancy")
    occ = pd.DataFrame(data["highest_occupancy"])
    if not occ.empty:
        occ["label"] = occ["hospital_name"] + " · " + occ["resource_type"]
        occ["occupancy_pct"] = occ["occupancy_pct"].astype(float)
        a.bar_chart(occ.set_index("label")["occupancy_pct"])
    b.subheader("Requests by status")
    st_df = pd.DataFrame(data["requests_by_status"])
    if not st_df.empty:
        b.bar_chart(st_df.set_index("request_status")["n"])
    st.subheader("Most requested resources")
    top = pd.DataFrame(data["most_requested_resources"])
    if not top.empty:
        st.bar_chart(top.set_index("required_resource")["n"])

    st.subheader("Hospital verification")
    hospitals, _ = api("GET", "/hospitals")
    for h in hospitals:
        c = st.columns([4, 2, 2])
        c[0].write(h["hospital_name"])
        c[1].write(h["verification_status"])
        if h["verification_status"] != "verified" and c[2].button("Verify", key=f"v{h['hospital_id']}"):
            api("POST", f"/hospitals/{h['hospital_id']}/verify")
            st.rerun()

    st.subheader("Flagged capacity updates")
    flagged, _ = api("GET", "/admin/flagged")
    if flagged:
        st.dataframe(pd.DataFrame(flagged), use_container_width=True, hide_index=True)
    else:
        st.success("No suspicious updates.")


# ------------------------------------------------------------------ navigation
st.sidebar.title("🏥 Smart Hospital Capacity")
# Demo role switcher - replace with a real login that returns the user's role
role = st.sidebar.radio("Role", ["Patient / Coordinator", "Hospital Staff", "Administrator"])
if role == "Patient / Coordinator":
    page = st.sidebar.radio("Page", ["Find hospital", "Track request"])
    page_find() if page == "Find hospital" else page_track()
elif role == "Hospital Staff":
    page_hospital()
else:
    page_admin()
