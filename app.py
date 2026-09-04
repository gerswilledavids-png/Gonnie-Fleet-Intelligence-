import os
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import requests
import streamlit as st
from supabase import Client, create_client

# =========================================================
# GONNIE FLEET INTELLIGENCE
# Secure Streamlit + Supabase configuration
# =========================================================

def _clean_secret(value) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    bad = ("YOUR_", "PASTE_YOUR_", "REPLACE_ME", "CHANGE_ME")
    return "" if any(x in value.upper() for x in bad) else value


def _setting(name: str, default: str = "") -> str:
    try:
        value = _clean_secret(st.secrets.get(name))
        if value:
            return value
        for section_name in ("supabase", "SUPABASE"):
            section = st.secrets.get(section_name)
            if hasattr(section, "get"):
                value = _clean_secret(section.get(name))
                if not value:
                    value = _clean_secret(section.get(name.lower()))
                if value:
                    return value
    except Exception:
        pass
    return _clean_secret(os.getenv(name, default))


SUPABASE_URL = _setting("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = _setting("SUPABASE_PUBLISHABLE_KEY")
SUPABASE_ANON_KEY = _setting("SUPABASE_ANON_KEY")
SUPABASE_KEY = _setting("SUPABASE_KEY")
SUPABASE_CLIENT_KEY = (
    SUPABASE_PUBLISHABLE_KEY or SUPABASE_ANON_KEY or SUPABASE_KEY
)

APP_BASE_URL = _setting("APP_BASE_URL")
CHECKOUT_FUNCTION_URL = _setting(
    "CHECKOUT_FUNCTION_URL",
    f"{SUPABASE_URL}/functions/v1/create-yoco-checkout" if SUPABASE_URL else "",
)

if not SUPABASE_URL or not SUPABASE_CLIENT_KEY:
    st.error(
        "Supabase is not configured. In Streamlit Cloud open "
        "App → Settings → Secrets and add SUPABASE_URL and "
        "SUPABASE_PUBLISHABLE_KEY, then reboot the app."
    )
    st.stop()

st.set_page_config(
    page_title="Gonnie Fleet Intelligence",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main { background:#f7f8fa; }
    [data-testid="stMetric"] { border-radius:12px; padding:10px; }
    .block-container { padding-top:1.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_base_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_CLIENT_KEY)


def get_client() -> Client:
    client = create_client(SUPABASE_URL, SUPABASE_CLIENT_KEY)
    session = st.session_state.get("session")
    if session:
        try:
            client.auth.set_session(session.access_token, session.refresh_token)
        except Exception:
            pass
    return client


def logout():
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    st.session_state.clear()
    st.rerun()


def safe_df(client, table, tenant_id=None):
    try:
        q = client.table(table).select("*")
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        result = q.execute()
        return pd.DataFrame(result.data or [])
    except Exception:
        return pd.DataFrame()


def profile_for(client, user_id):
    try:
        r = client.table("profiles").select("*").eq("id", user_id).single().execute()
        return r.data or {}
    except Exception:
        return {}


def write_audit(client, user, profile, action, table_name=None, record_id=None,
                tenant_id=None, old_data=None, new_data=None):
    try:
        client.table("audit_logs").insert({
            "actor_user_id": str(user.id) if user else None,
            "actor_role": profile.get("role"),
            "tenant_id": tenant_id,
            "table_name": table_name,
            "record_id": str(record_id) if record_id else None,
            "action": action,
            "old_data": old_data,
            "new_data": new_data,
        }).execute()
    except Exception:
        pass


def compliance_status(value):
    if not value:
        return "⚪ UNKNOWN", None
    try:
        days = (pd.to_datetime(value).date() - date.today()).days
    except Exception:
        return "⚪ UNKNOWN", None
    if days < 0:
        return "🔴 EXPIRED", days
    if days <= 7:
        return "🟠 URGENT", days
    if days <= 30:
        return "🟡 EXPIRING SOON", days
    return "🟢 COMPLIANT", days


def trip_metrics(row, vehicle=None):
    distance = float(row.get("distance_km") or 0)
    fuel = float(row.get("fuel_used_liters") or 0)
    price = float(row.get("cost_per_liter") or 0)
    revenue = float(row.get("revenue") or 0)
    fixed = float(row.get("fixed_cost") or 0)
    variable = row.get("variable_cost")
    variable = float(variable) if variable is not None else fuel * price
    expected = 2.0
    if vehicle is not None:
        try:
            expected = float(vehicle.get("expected_km_l") or 2.0)
        except Exception:
            expected = 2.0
    km_l = distance / fuel if fuel else 0
    variance = ((km_l - expected) / expected) * 100 if expected else 0
    profit = revenue - fixed - variable
    return {
        "km_per_l": round(km_l, 2),
        "fuel_cost": round(fuel * price, 2),
        "expected_km_l": round(expected, 2),
        "fuel_variance_pct": round(variance, 1),
        "theft_alert": variance <= -20,
        "net_profit": round(profit, 2),
        "profit_margin": round((profit / revenue) * 100, 1) if revenue else 0,
        "cost_per_km": round((fixed + variable) / distance, 2) if distance else 0,
    }


def tenant_id_for(profile):
    return profile.get("tenant_id")


def insert_scoped(client, table, payload, profile):
    payload = dict(payload)
    if profile.get("role") != "master_admin":
        tid = tenant_id_for(profile)
        if not tid:
            raise RuntimeError("No tenant is assigned to this account.")
        payload["tenant_id"] = tid
    elif not payload.get("tenant_id"):
        raise RuntimeError("Master Admin must select a tenant.")
    result = client.table(table).insert(payload).execute()
    return result.data or []


def update_scoped(client, table, record_id, payload, profile):
    q = client.table(table).update(payload).eq("id", record_id)
    if profile.get("role") != "master_admin":
        q = q.eq("tenant_id", tenant_id_for(profile))
    result = q.execute()
    return result.data or []


def delete_scoped(client, table, record_id, profile):
    q = client.table(table).delete().eq("id", record_id)
    if profile.get("role") != "master_admin":
        q = q.eq("tenant_id", tenant_id_for(profile))
    result = q.execute()
    return result.data or []


# =========================================================
# AUTH
# =========================================================
def show_auth():
    st.title("🚚 Gonnie Fleet Intelligence")
    st.caption("Diesel on Wheels — Multi-Fleet Intelligence Platform")

    login, signup = st.tabs(["Log In", "Create Account"])

    with login:
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log In", use_container_width=True):
                try:
                    res = get_base_client().auth.sign_in_with_password(
                        {"email": email.strip(), "password": password}
                    )
                    if not res.session:
                        st.warning("Login succeeded, but no session was returned.")
                    else:
                        st.session_state.session = res.session
                        st.session_state.user = res.user
                        st.rerun()
                except Exception as exc:
                    st.error(f"Login failed: {exc}")

    with signup:
        with st.form("signup"):
            company = st.text_input("Company Name")
            name = st.text_input("Your Full Name")
            email = st.text_input("Email", key="new_email")
            password = st.text_input("Password", type="password", key="new_password")
            if st.form_submit_button("Create Account", use_container_width=True):
                if not company.strip() or not name.strip():
                    st.error("Company Name and Full Name are required.")
                elif len(password) < 6:
                    st.error("Use a password of at least 6 characters.")
                else:
                    try:
                        get_base_client().auth.sign_up({
                            "email": email.strip(),
                            "password": password,
                            "options": {
                                "data": {
                                    "company_name": company.strip(),
                                    "full_name": name.strip(),
                                }
                            },
                        })
                        st.success("Account created. Check your email, confirm it, then log in.")
                    except Exception as exc:
                        st.error(f"Sign up failed: {exc}")


# =========================================================
# DASHBOARD
# =========================================================
def dashboard(client, profile, tenant):
    trips = safe_df(client, "trips", tenant)
    vehicles = safe_df(client, "vehicles", tenant)
    drivers = safe_df(client, "drivers", tenant)
    maintenance = safe_df(client, "maintenance_log", tenant)

    revenue = trips["revenue"].fillna(0).sum() if "revenue" in trips else 0
    distance = trips["distance_km"].fillna(0).sum() if "distance_km" in trips else 0
    fuel = trips["fuel_used_liters"].fillna(0).sum() if "fuel_used_liters" in trips else 0
    fuel_cost = 0
    profit = 0
    alerts = 0

    if not trips.empty:
        vehicle_map = {}
        if not vehicles.empty and "id" in vehicles:
            vehicle_map = vehicles.set_index("id").to_dict("index")
        for _, row in trips.iterrows():
            v = vehicle_map.get(row.get("vehicle_id"))
            m = trip_metrics(row, v)
            fuel_cost += m["fuel_cost"]
            profit += m["net_profit"]
            alerts += int(m["theft_alert"])

    st.title("Executive Dashboard")
    st.caption(f"Workspace: {tenant or 'All Fleets'}")

    a, b, c, d = st.columns(4)
    a.metric("Total Revenue", f"R{revenue:,.0f}")
    b.metric("Net Profit", f"R{profit:,.0f}")
    c.metric("Distance Covered", f"{distance:,.0f} km")
    d.metric("Fuel Theft Alerts", str(alerts))

    st.divider()
    x, y = st.columns(2)
    with x:
        st.subheader("Fleet")
        st.metric("Vehicles", len(vehicles))
        st.metric("Drivers", len(drivers))
    with y:
        st.subheader("Operations")
        st.metric("Fuel Used", f"{fuel:,.0f} L")
        st.metric("Maintenance Records", len(maintenance))

    if not trips.empty:
        st.subheader("Recent Trips")
        cols = [c for c in ["trip_date", "date", "vehicle_id", "driver_name",
                            "start_location", "end_location", "distance_km",
                            "fuel_used_liters", "revenue"] if c in trips.columns]
        st.dataframe(trips[cols].tail(10), use_container_width=True, hide_index=True)


def trip_log(client, profile, tenant):
    st.header("Trip Master Log")
    trips = safe_df(client, "trips", tenant)
    vehicles = safe_df(client, "vehicles", tenant)
    drivers = safe_df(client, "drivers", tenant)

    with st.expander("➕ Capture Trip", expanded=False):
        with st.form("capture_trip"):
            c1, c2, c3 = st.columns(3)
            trip_date = c1.date_input("Trip Date", value=date.today())
            vehicle_id = c2.selectbox(
                "Vehicle",
                vehicles["id"].tolist() if not vehicles.empty and "id" in vehicles else [],
                format_func=lambda x: str(x),
            )
            driver = c3.text_input("Driver")
            c4, c5, c6 = st.columns(3)
            start = c4.text_input("Start")
            end = c5.text_input("Destination")
            distance = c6.number_input("Distance (km)", min_value=0.0, step=1.0)
            c7, c8, c9 = st.columns(3)
            fuel = c7.number_input("Fuel Used (L)", min_value=0.0, step=1.0)
            price = c8.number_input("Cost/L (R)", min_value=0.0, value=23.50, step=0.10)
            revenue = c9.number_input("Revenue (R)", min_value=0.0, step=100.0)
            fixed = st.number_input("Fixed Cost (R)", min_value=0.0, step=100.0)
            if st.form_submit_button("Save Trip", use_container_width=True):
                try:
                    payload = {
                        "trip_date": str(trip_date),
                        "vehicle_id": vehicle_id or None,
                        "driver_name": driver,
                        "start_location": start,
                        "end_location": end,
                        "distance_km": distance,
                        "fuel_used_liters": fuel,
                        "cost_per_liter": price,
                        "revenue": revenue,
                        "fixed_cost": fixed,
                    }
                    rows = insert_scoped(client, "trips", payload, profile)
                    if rows:
                        write_audit(client, st.session_state.user, profile, "INSERT",
                                     "trips", rows[0].get("id"), tenant, None, payload)
                    st.success("Trip saved.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not save trip: {exc}")

    if trips.empty:
        st.info("No trips recorded yet.")
        return

    st.dataframe(trips, use_container_width=True, hide_index=True)


def vehicle_register(client, profile, tenant):
    st.header("Vehicle Register")
    vehicles = safe_df(client, "vehicles", tenant)
    with st.form("vehicle"):
        c1, c2, c3 = st.columns(3)
        reg = c1.text_input("Registration")
        fleet_no = c2.text_input("Fleet No.")
        make = c3.text_input("Make")
        c4, c5, c6 = st.columns(3)
        model = c4.text_input("Model")
        year = c5.number_input("Year", min_value=1900, max_value=2100, value=date.today().year)
        expected = c6.number_input("Expected KM/L", min_value=0.1, value=2.0, step=0.1)
        odo = st.number_input("Current Odometer", min_value=0.0, step=100.0)
        status = st.selectbox("Status", ["Active", "Maintenance", "Inactive"])
        if st.form_submit_button("Add Vehicle", use_container_width=True):
            try:
                insert_scoped(client, "vehicles", {
                    "registration": reg, "fleet_no": fleet_no, "make": make,
                    "model": model, "year": year, "expected_km_l": expected,
                    "current_odometer": odo, "status": status,
                }, profile)
                st.success("Vehicle added.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not add vehicle: {exc}")
    st.dataframe(vehicles, use_container_width=True, hide_index=True)


def driver_register(client, profile, tenant):
    st.header("Driver Register")
    drivers = safe_df(client, "drivers", tenant)
    with st.form("driver"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Driver Name")
        phone = c2.text_input("Phone")
        c3, c4 = st.columns(2)
        license_no = c3.text_input("License Number")
        supervisor = c4.text_input("Supervisor")
        c5, c6 = st.columns(2)
        license_expiry = c5.date_input("License Expiry", value=date.today() + timedelta(days=365))
        prdp_expiry = c6.date_input("PRDP Expiry", value=date.today() + timedelta(days=365))
        if st.form_submit_button("Add Driver", use_container_width=True):
            try:
                insert_scoped(client, "drivers", {
                    "driver_name": name, "driver_phone": phone,
                    "license_number": license_no,
                    "license_expiry": str(license_expiry),
                    "prdp_expiry": str(prdp_expiry),
                    "supervisor": supervisor,
                    "status": "Active",
                }, profile)
                st.success("Driver added.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not add driver: {exc}")
    st.dataframe(drivers, use_container_width=True, hide_index=True)


def compliance(client, profile, tenant):
    st.header("Compliance Tracker")
    drivers = safe_df(client, "drivers", tenant)
    if drivers.empty:
        st.info("No drivers recorded.")
        return
    rows = []
    for _, r in drivers.iterrows():
        ls, ld = compliance_status(r.get("license_expiry"))
        ps, pdays = compliance_status(r.get("prdp_expiry"))
        rows.append({
            "Driver": r.get("driver_name"),
            "License": ls,
            "License Days": ld,
            "PRDP": ps,
            "PRDP Days": pdays,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def fuel_analytics(client, profile, tenant):
    st.header("Fuel Theft & Analytics")
    trips = safe_df(client, "trips", tenant)
    vehicles = safe_df(client, "vehicles", tenant)
    if trips.empty:
        st.info("No trips recorded.")
        return
    vehicle_map = vehicles.set_index("id").to_dict("index") if not vehicles.empty and "id" in vehicles else {}
    rows = []
    for _, r in trips.iterrows():
        m = trip_metrics(r, vehicle_map.get(r.get("vehicle_id")))
        rows.append({**r.to_dict(), **m})
    df = pd.DataFrame(rows)
    a, b, c = st.columns(3)
    a.metric("Fuel Used", f"{df['fuel_used_liters'].fillna(0).sum():,.0f} L")
    b.metric("Average KM/L", f"{df['km_per_l'].replace([np.inf, -np.inf], np.nan).mean():.2f}")
    c.metric("Theft Alerts", int(df["theft_alert"].sum()))
    st.dataframe(
        df[[c for c in ["trip_date", "date", "vehicle_id", "distance_km",
                        "fuel_used_liters", "km_per_l", "expected_km_l",
                        "fuel_variance_pct", "theft_alert"] if c in df.columns]],
        use_container_width=True, hide_index=True,
    )


def maintenance(client, profile, tenant):
    st.header("Maintenance Log")
    vehicles = safe_df(client, "vehicles", tenant)
    logs = safe_df(client, "maintenance_log", tenant)
    with st.form("maintenance"):
        c1, c2 = st.columns(2)
        vehicle_id = c1.selectbox("Vehicle", vehicles["id"].tolist() if not vehicles.empty and "id" in vehicles else [])
        service_type = c2.text_input("Service Type", value="Scheduled Service")
        service_date = st.date_input("Service Date", value=date.today())
        cost = st.number_input("Cost (R)", min_value=0.0, step=100.0)
        notes = st.text_area("Notes")
        if st.form_submit_button("Save Maintenance", use_container_width=True):
            try:
                insert_scoped(client, "maintenance_log", {
                    "vehicle_id": vehicle_id or None,
                    "service_type": service_type,
                    "service_date": str(service_date),
                    "cost": cost,
                    "notes": notes,
                }, profile)
                st.success("Maintenance record saved.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save maintenance: {exc}")
    st.dataframe(logs, use_container_width=True, hide_index=True)


def gps_log(client, profile, tenant):
    st.header("GPS Tracker Log")
    logs = safe_df(client, "gps_tracker_log", tenant)
    with st.form("gps"):
        c1, c2, c3 = st.columns(3)
        vehicle_id = c1.text_input("Vehicle ID / Registration")
        latitude = c2.number_input("Latitude", value=0.0, format="%.6f")
        longitude = c3.number_input("Longitude", value=0.0, format="%.6f")
        recorded_at = st.text_input("Recorded At", value=datetime.now().isoformat(timespec="seconds"))
        if st.form_submit_button("Save GPS Point", use_container_width=True):
            try:
                insert_scoped(client, "gps_tracker_log", {
                    "vehicle_id": vehicle_id, "latitude": latitude,
                    "longitude": longitude, "recorded_at": recorded_at,
                }, profile)
                st.success("GPS point saved.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not save GPS point: {exc}")
    st.dataframe(logs, use_container_width=True, hide_index=True)


def profitability():
    st.header("Job Profitability Estimator")
    c1, c2 = st.columns(2)
    revenue = c1.number_input("Revenue (R)", min_value=0.0, step=500.0)
    distance = c2.number_input("Distance (km)", min_value=0.0, step=10.0)
    c3, c4, c5 = st.columns(3)
    fuel = c3.number_input("Fuel (L)", min_value=0.0, step=10.0)
    price = c4.number_input("Fuel Cost/L (R)", min_value=0.0, value=23.50, step=0.10)
    fixed = c5.number_input("Fixed Costs (R)", min_value=0.0, step=100.0)
    variable_other = st.number_input("Other Variable Costs (R)", min_value=0.0, step=100.0)
    total = fuel * price + fixed + variable_other
    profit = revenue - total
    a, b, c = st.columns(3)
    a.metric("Total Cost", f"R{total:,.2f}")
    b.metric("Net Profit", f"R{profit:,.2f}")
    c.metric("Margin", f"{(profit/revenue*100 if revenue else 0):.1f}%")


def forecast(client, profile, tenant):
    st.header("Financial Forecast")
    trips = safe_df(client, "trips", tenant)
    if trips.empty or "revenue" not in trips.columns:
        st.info("Add trips with revenue to build a forecast.")
        return
    df = trips.copy()
    date_col = "trip_date" if "trip_date" in df.columns else "date" if "date" in df.columns else None
    if date_col:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        monthly = df.dropna(subset=[date_col]).groupby(df[date_col].dt.to_period("M"))["revenue"].sum()
        st.line_chart(monthly)
        avg = monthly.tail(3).mean() if len(monthly) else 0
        st.metric("Projected Next-Month Revenue", f"R{avg:,.0f}")


def billing(client, profile, tenant):
    st.header("Billing & Subscription")
    rows = safe_df(client, "billing_subscriptions", tenant)
    if rows.empty:
        st.info("No subscription record exists yet.")
    else:
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Plans")
    cols = st.columns(3)
    plans = [
        ("Starter", "R350 / month"),
        ("Professional", "R1,500 / month"),
        ("Enterprise", "Custom pricing"),
    ]
    for col, (name, price) in zip(cols, plans):
        with col:
            st.markdown(f"### {name}")
            st.write(price)
            st.caption("Contact the platform administrator to activate or change a plan.")

    if CHECKOUT_FUNCTION_URL:
        st.caption("Yoco checkout is available only when the Supabase Edge Function is deployed and configured.")


def platform_admin(client, profile):
    st.header("⚙️ Platform Control Centre")
    if profile.get("role") != "master_admin":
        st.error("Master Admin access required.")
        return
    tenants = safe_df(client, "tenants")
    profiles = safe_df(client, "profiles")
    st.metric("Tenants", len(tenants))
    st.metric("Users", len(profiles))
    if not tenants.empty:
        st.dataframe(tenants, use_container_width=True, hide_index=True)
    if not profiles.empty:
        st.subheader("Profiles")
        st.dataframe(profiles, use_container_width=True, hide_index=True)


# =========================================================
# APP ROUTER
# =========================================================
if "session" not in st.session_state or "user" not in st.session_state:
    show_auth()
    st.stop()

client = get_client()
user = st.session_state.user
profile = profile_for(client, str(user.id))

if not profile:
    st.error("Your account profile has not been created yet. Confirm your email and try logging in again.")
    if st.button("Log out"):
        logout()
    st.stop()

is_master = profile.get("role") == "master_admin"

all_tenants = safe_df(client, "tenants")
tenant = profile.get("tenant_id")

with st.sidebar:
    st.title("🚚 GONNIE FLEET")
    st.caption(profile.get("role", "User").replace("_", " ").title())
    if is_master and not all_tenants.empty:
        options = ["All Fleets"] + all_tenants["id"].tolist()
        labels = {"All Fleets": "All Fleets"}
        labels.update(dict(zip(all_tenants["id"], all_tenants["name"])))
        selected = st.selectbox("Workspace", options, format_func=lambda x: labels.get(x, str(x)))
        tenant = None if selected == "All Fleets" else selected
    else:
        if tenant and not all_tenants.empty:
            name = all_tenants.loc[all_tenants["id"] == tenant, "name"]
            st.info(f"Workspace: {name.iloc[0] if len(name) else tenant}")
    st.divider()
    page = st.radio(
        "Navigation",
        [
            "Executive Dashboard",
            "Trip Master Log",
            "Vehicle Register",
            "Driver Register",
            "Compliance Tracker",
            "Fuel Theft & Analytics",
            "Maintenance Log",
            "Financial Forecast",
            "Job Profitability Estimator",
            "GPS Tracker Log",
            "Billing & Subscription",
        ] + (["Platform Control Centre"] if is_master else []),
    )
    st.divider()
    st.caption(user.email)
    if st.button("Log out", use_container_width=True):
        logout()

if page == "Executive Dashboard":
    dashboard(client, profile, tenant)
elif page == "Trip Master Log":
    trip_log(client, profile, tenant)
elif page == "Vehicle Register":
    vehicle_register(client, profile, tenant)
elif page == "Driver Register":
    driver_register(client, profile, tenant)
elif page == "Compliance Tracker":
    compliance(client, profile, tenant)
elif page == "Fuel Theft & Analytics":
    fuel_analytics(client, profile, tenant)
elif page == "Maintenance Log":
    maintenance(client, profile, tenant)
elif page == "Financial Forecast":
    forecast(client, profile, tenant)
elif page == "Job Profitability Estimator":
    profitability()
elif page == "GPS Tracker Log":
    gps_log(client, profile, tenant)
elif page == "Billing & Subscription":
    billing(client, profile, tenant)
elif page == "Platform Control Centre":
    platform_admin(client, profile)
