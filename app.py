import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import date
from supabase import create_client, Client

# =========================================================
# CONFIG
# =========================================================
SUPABASE_URL = "https://iguoiyslhyqpvlfjxksh.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsImJhdCI6IjE3ODcyMDU3NTcsImV4cCI6MjEwMjc4MTc1N30.5Zh2MPcH3TpIJ--M2m-vN4pSICu5-5Ja8-zbgiRipyM"

CHECKOUT_FUNCTION_URL = f"{SUPABASE_URL}/functions/v1/create-yoco-checkout"
APP_BASE_URL = "https://8b6gr3mtlfbcjfc6kzuuds.streamlit.app"

PLAN_LABELS = {
    "starter": "Starter — R350/mo",
    "professional": "Professional — R1,500/mo",
    "enterprise": "Enterprise — custom pricing",
}

st.set_page_config(
    page_title="Gonnie Fleet Intelligence D.O.W",
    page_icon="🚚",
    layout="wide",
)

st.markdown("""
<style>
.main { background-color:#f8f9fa; }
div[data-testid="stMetric"] { border-radius:10px; padding:8px; }
</style>
""", unsafe_allow_html=True)


# =========================================================
# CLIENTS / AUTH
# =========================================================
@st.cache_resource
def get_base_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_authed_client() -> Client:
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    session = st.session_state.get("session")
    if session:
        client.auth.set_session(session.access_token, session.refresh_token)
    return client


def logout():
    try:
        get_authed_client().auth.sign_out()
    except Exception:
        pass
    for key in ("session", "user"):
        st.session_state.pop(key, None)
    st.rerun()


# =========================================================
# AUTH SCREENS
# =========================================================
def show_login():
    st.title("🚚 Gonnie Fleet Intelligence D.O.W")
    st.caption("Diesel on Wheels — Multi-Fleet Intelligence Platform")

    tab_login, tab_signup = st.tabs(["Log In", "Sign Up"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Log In", use_container_width=True):
                try:
                    res = get_base_client().auth.sign_in_with_password(
                        {"email": email.strip(), "password": password}
                    )
                    st.session_state["session"] = res.session
                    st.session_state["user"] = res.user
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

    with tab_signup:
        st.markdown(
            "New company? Create your account — you will receive an isolated workspace."
        )
        with st.form("signup_form"):
            company_name = st.text_input("Company Name")
            full_name = st.text_input("Your Full Name")
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password", type="password", key="signup_password")
            if st.form_submit_button("Create Account", use_container_width=True):
                if not company_name.strip() or not full_name.strip():
                    st.error("Company Name and Full Name are required.")
                else:
                    try:
                        get_base_client().auth.sign_up({
                            "email": email.strip(),
                            "password": password,
                            "options": {
                                "data": {
                                    "company_name": company_name.strip(),
                                    "full_name": full_name.strip(),
                                }
                            },
                        })
                        st.success("Account created. Check your email to confirm, then log in.")
                    except Exception as e:
                        st.error(f"Sign up failed: {e}")


# =========================================================
# HELPERS
# =========================================================
def get_profile(client: Client, user_id: str):
    try:
        res = client.table("profiles").select("*").eq("id", user_id).single().execute()
        return res.data
    except Exception:
        return None


def fetch_df(client: Client, table_name: str, tenant_filter=None) -> pd.DataFrame:
    q = client.table(table_name).select("*")
    if tenant_filter:
        q = q.eq("tenant_id", tenant_filter)
    try:
        res = q.execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def resolve_tenant_id(client, profile, user_id):
    existing = profile.get("tenant_id")
    if existing:
        return existing

    tenants = client.table("tenants").select("id,name").order("name").execute().data or []
    if len(tenants) == 1:
        tenant_id = tenants[0]["id"]
        client.table("profiles").update({"tenant_id": tenant_id}).eq("id", user_id).execute()
        profile["tenant_id"] = tenant_id
        return tenant_id

    if not tenants:
        raise RuntimeError("No workspace exists for this account.")

    raise RuntimeError(
        "Your account has no workspace assigned. A Master Admin must assign one."
    )


def tenant_payload(payload, is_master, tenant_filter, profile):
    if is_master and tenant_filter:
        payload["tenant_id"] = tenant_filter
    elif not is_master:
        tenant_id = profile.get("tenant_id")
        if not tenant_id:
            raise RuntimeError("No tenant is assigned to this user.")
        payload["tenant_id"] = tenant_id
    return payload


def compute_trip_fields(row, vehicle_row=None):
    distance = row.get("distance_km") or 0
    fuel = row.get("fuel_used_liters") or 0
    price = row.get("cost_per_liter") or 0
    revenue = row.get("revenue") or 0
    fixed = row.get("fixed_cost") or 0
    variable = row.get("variable_cost") or fuel * price

    km_l = round(distance / fuel, 2) if fuel else 0
    fuel_cost = round(fuel * price, 2)

    expected = 2.0
    if vehicle_row is not None:
        try:
            expected = vehicle_row.get("expected_km_l", 2.0)
            if pd.isna(expected) or expected <= 0:
                expected = 2.0
        except Exception:
            expected = 2.0

    variance = round(((km_l - expected) / expected) * 100, 1) if expected else 0
    theft = variance <= -20
    profit = round(revenue - fixed - variable, 2)
    margin = round((profit / revenue) * 100, 1) if revenue else 0
    cost_km = round((fixed + variable) / distance, 2) if distance else 0

    return {
        "km_per_l": km_l,
        "fuel_cost": fuel_cost,
        "expected_km_l": expected,
        "fuel_variance_pct": variance,
        "theft_alert": theft,
        "net_profit": profit,
        "profit_margin": margin,
        "cost_per_km": cost_km,
    }


def compliance_status(expiry):
    if not expiry:
        return "⚪ UNKNOWN", None
    try:
        days = (pd.to_datetime(expiry).date() - date.today()).days
    except Exception:
        return "⚪ UNKNOWN", None
    if days < 0:
        return "🔴 EXPIRED", days
    if days <= 7:
        return "🟠 URGENT", days
    if days <= 30:
        return "🟡 EXPIRING SOON", days
    return "🟢 COMPLIANT", days


# =========================================================
# MASTER ADMIN / AUDIT HELPERS
# =========================================================
def write_audit(client, user, profile, action, table_name=None,
                record_id=None, tenant_id=None, old_data=None, new_data=None):
    """Writes to the EXISTING public.audit_logs schema."""
    try:
        payload = {
            "actor_user_id": str(user.id) if user else None,
            "actor_role": profile.get("role") if profile else None,
            "tenant_id": tenant_id,
            "table_name": table_name,
            "record_id": str(record_id) if record_id else None,
            "action": action,
            "old_data": old_data,
            "new_data": new_data,
        }
        client.table("audit_logs").insert(payload).execute()
    except Exception:
        # Audit failure must never crash the operational app.
        pass


def master_update_profile(client, user, profile, user_id, fields):
    old = client.table("profiles").select("*").eq("id", user_id).single().execute().data
    result = client.table("profiles").update(fields).eq("id", user_id).execute()
    new_rows = result.data or []
    write_audit(
        client, user, profile, "MASTER_UPDATE_PROFILE",
        "profiles", user_id,
        fields.get("tenant_id", old.get("tenant_id") if old else None),
        old, new_rows[0] if new_rows else fields
    )


def show_platform_control_centre(client, user, profile):
    st.title("👑 Gonnie Platform Control Centre")
    st.caption(
        "Master Admin only — complete platform oversight, tenant management, "
        "user administration, subscriptions and audit history."
    )

    tenants_df = fetch_df(client, "tenants")
    profiles_df = fetch_df(client, "profiles")
    trips_df = fetch_df(client, "trips")
    vehicles_df = fetch_df(client, "vehicles")
    drivers_df = fetch_df(client, "drivers")
    subs_df = fetch_df(client, "billing_subscriptions")
    audit_df = fetch_df(client, "audit_logs")

    # ---------- PLATFORM KPIs ----------
    active_subs = (
        int((subs_df["status"].astype(str).str.lower() == "active").sum())
        if not subs_df.empty and "status" in subs_df else 0
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🏢 Tenants", len(tenants_df))
    c2.metric("👤 Users", len(profiles_df))
    c3.metric("🚚 Vehicles", len(vehicles_df))
    c4.metric("🗺️ Trips", len(trips_df))
    c5.metric("💳 Active Subscriptions", active_subs)

    st.markdown("---")

    # ---------- TENANT MANAGEMENT ----------
    st.subheader("🏢 Tenant Management")

    if not tenants_df.empty:
        tenant_view = tenants_df.copy()
        if not profiles_df.empty and "tenant_id" in profiles_df:
            counts = profiles_df.groupby("tenant_id").size().rename("Users")
            tenant_view = tenant_view.merge(
                counts, left_on="id", right_index=True, how="left"
            )
            tenant_view["Users"] = tenant_view["Users"].fillna(0).astype(int)

        if not trips_df.empty and "tenant_id" in trips_df:
            counts = trips_df.groupby("tenant_id").size().rename("Trips")
            tenant_view = tenant_view.merge(
                counts, left_on="id", right_index=True, how="left"
            )
            tenant_view["Trips"] = tenant_view["Trips"].fillna(0).astype(int)

        st.dataframe(tenant_view, use_container_width=True)

    with st.expander("➕ Create a tenant/workspace"):
        with st.form("create_tenant"):
            tenant_name = st.text_input("Company / Workspace Name")
            if st.form_submit_button("Create Tenant"):
                if not tenant_name.strip():
                    st.error("Tenant name is required.")
                else:
                    try:
                        res = client.table("tenants").insert(
                            {"name": tenant_name.strip()}
                        ).execute()
                        created = res.data[0] if res.data else None
                        write_audit(
                            client, user, profile, "MASTER_CREATE_TENANT",
                            "tenants",
                            created.get("id") if created else None,
                            created.get("id") if created else None,
                            None, created
                        )
                        st.success("Tenant created.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not create tenant: {e}")

    # ---------- USER MANAGEMENT ----------
    st.markdown("---")
    st.subheader("👤 User Administration")

    if not profiles_df.empty:
        display_profiles = profiles_df.copy()

        if not tenants_df.empty and "tenant_id" in display_profiles:
            tenant_names = tenants_df.set_index("id")["name"].to_dict()
            display_profiles["tenant_name"] = display_profiles["tenant_id"].map(tenant_names)

        st.dataframe(display_profiles, use_container_width=True)

        user_options = {}
        for _, row in profiles_df.iterrows():
            uid = row.get("id")
            label = f"{row.get('full_name') or 'Unnamed'} • {row.get('role')} • {uid}"
            user_options[label] = uid

        with st.expander("🔐 Change User Role / Workspace"):
            selected_label = st.selectbox("Select User", list(user_options.keys()))
            selected_id = user_options[selected_label]
            selected_row = profiles_df[profiles_df["id"].astype(str) == str(selected_id)].iloc[0]

            role_options = ["master_admin", "tenant_admin", "driver", "viewer"]
            current_role = selected_row.get("role")
            new_role = st.selectbox(
                "Role",
                role_options,
                index=role_options.index(current_role)
                if current_role in role_options else 1,
            )

            tenant_options = {"— No tenant —": None}
            for _, t in tenants_df.iterrows():
                tenant_options[str(t["name"])] = t["id"]

            current_tenant = selected_row.get("tenant_id")
            tenant_labels = list(tenant_options.keys())
            default_idx = 0
            for i, label in enumerate(tenant_labels):
                if tenant_options[label] == current_tenant:
                    default_idx = i
                    break

            tenant_label = st.selectbox(
                "Workspace",
                tenant_labels,
                index=default_idx,
            )

            if st.button("💾 Save User Administration", type="primary"):
                try:
                    fields = {
                        "role": new_role,
                        "tenant_id": tenant_options[tenant_label],
                    }
                    master_update_profile(
                        client, user, profile, selected_id, fields
                    )
                    st.success("User role/workspace updated.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not update user: {e}")

    # ---------- TENANT DATA VIEW ----------
    st.markdown("---")
    st.subheader("🔎 Tenant Intelligence")

    if not tenants_df.empty:
        tenant_map = {str(r["name"]): r["id"] for _, r in tenants_df.iterrows()}
        selected_tenant_name = st.selectbox(
            "Inspect Tenant",
            list(tenant_map.keys()),
            key="master_inspect_tenant",
        )
        selected_tenant_id = tenant_map[selected_tenant_name]

        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric(
            "Users",
            int((profiles_df["tenant_id"] == selected_tenant_id).sum())
            if not profiles_df.empty and "tenant_id" in profiles_df else 0
        )
        tc2.metric(
            "Vehicles",
            int((vehicles_df["tenant_id"] == selected_tenant_id).sum())
            if not vehicles_df.empty and "tenant_id" in vehicles_df else 0
        )
        tc3.metric(
            "Drivers",
            int((drivers_df["tenant_id"] == selected_tenant_id).sum())
            if not drivers_df.empty and "tenant_id" in drivers_df else 0
        )
        tc4.metric(
            "Trips",
            int((trips_df["tenant_id"] == selected_tenant_id).sum())
            if not trips_df.empty and "tenant_id" in trips_df else 0
        )

    # ---------- BILLING ----------
    st.markdown("---")
    st.subheader("💳 Platform Billing")

    if not subs_df.empty:
        billing = subs_df.copy()
        if not tenants_df.empty and "tenant_id" in billing:
            names = tenants_df.set_index("id")["name"].to_dict()
            billing["tenant_name"] = billing["tenant_id"].map(names)

        if "amount_cents" in billing:
            billing["amount_R"] = billing["amount_cents"].fillna(0) / 100

        st.dataframe(billing, use_container_width=True)

    # ---------- AUDIT ----------
    st.markdown("---")
    st.subheader("🛡️ Audit Trail")

    if not audit_df.empty:
        audit_view = audit_df.copy()
        if "created_at" in audit_view:
            audit_view = audit_view.sort_values("created_at", ascending=False)

        limit = st.selectbox("Audit records to display", [25, 50, 100, 250], index=1)
        st.dataframe(audit_view.head(limit), use_container_width=True)
    else:
        st.info("No audit events recorded yet.")


# =========================================================
# MAIN APP
# =========================================================
def show_app():
    client = get_authed_client()
    user = st.session_state["user"]
    profile = get_profile(client, user.id)

    if not profile:
        st.error("No profile found for this account.")
        st.stop()

    is_master = profile.get("role") == "master_admin"

    if not is_master:
        try:
            resolve_tenant_id(client, profile, user.id)
        except Exception as e:
            st.error(f"Workspace assignment required: {e}")
            st.stop()

    st.sidebar.title("🚚 Gonnie Fleet Intelligence")
    st.sidebar.markdown(f"**{user.email}**")
    st.sidebar.markdown(f"Role: `{profile.get('role')}`")

    if st.sidebar.button("Log Out"):
        logout()

    st.sidebar.markdown("---")

    tenant_filter = None

    if is_master:
        tenants_res = client.table("tenants").select("id,name").order("name").execute()
        tenant_options = {"🌐 All Tenants (Master View)": None}
        tenant_options.update({
            t["name"]: t["id"] for t in (tenants_res.data or [])
        })
        chosen = st.sidebar.selectbox(
            "Viewing Tenant",
            list(tenant_options.keys()),
        )
        tenant_filter = tenant_options[chosen]

    nav = [
        "📊 Executive Dashboard",
        "🗺️ Trip Log",
        "🚗 Vehicle Register",
        "👤 Driver Register",
        "📅 Compliance & Documents",
        "⛽ Fuel Consumption Analysis",
        "🔧 Maintenance Log",
        "💰 Financial Forecast",
        "🧮 Job Profitability Estimator",
        "🛰️ GPS Tracker Log",
        "💳 Billing & Subscription",
    ]

    if is_master:
        nav.append("👑 Gonnie Platform Control Centre")

    app_mode = st.sidebar.selectbox("Choose Navigation", nav)

    # =====================================================
    # MASTER CONTROL CENTRE
    # =====================================================
    if app_mode == "👑 Gonnie Platform Control Centre":
        show_platform_control_centre(client, user, profile)
        return

    trips_df = fetch_df(client, "trips", tenant_filter)
    vehicles_df = fetch_df(client, "vehicles", tenant_filter)
    drivers_df = fetch_df(client, "drivers", tenant_filter)

    # =====================================================
    # EXECUTIVE DASHBOARD
    # =====================================================
    if app_mode == "📊 Executive Dashboard":
        st.title("📊 Fleet Executive Dashboard")
        st.markdown("**GONNIE FLEET MANAGEMENT SYSTEM** ⬥ Multi-Fleet Intelligence Dashboard")

        if trips_df.empty:
            st.info("No trip data yet. Add trips from Trip Log.")
        else:
            total_trips = len(trips_df)
            total_distance = trips_df.get("distance_km", pd.Series(dtype=float)).fillna(0).sum()
            total_revenue = trips_df.get("revenue", pd.Series(dtype=float)).fillna(0).sum()
            fuel = trips_df.get("fuel_used_liters", pd.Series(dtype=float)).fillna(0)
            price = trips_df.get("cost_per_liter", pd.Series(dtype=float)).fillna(0)
            fuel_cost = (fuel * price).sum()
            fixed = trips_df.get("fixed_cost", pd.Series(dtype=float)).fillna(0).sum()
            variable = trips_df.get("variable_cost", pd.Series(dtype=float)).fillna(0).sum()
            net = trips_df.get("net_profit", pd.Series(dtype=float)).fillna(0).sum()
            if "net_profit" not in trips_df:
                net = total_revenue - fixed - variable

            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total Trips", f"{total_trips}")
            c2.metric("Revenue", f"R{total_revenue:,.2f}")
            c3.metric("Distance", f"{total_distance:,.0f} km")
            c4.metric("Fuel Cost", f"R{fuel_cost:,.2f}")

            c5,c6,c7,c8 = st.columns(4)
            c5.metric("Net Profit", f"R{net:,.2f}")
            c6.metric("Avg Revenue/KM", f"R{total_revenue/total_distance:,.2f}" if total_distance else "R0.00")
            c7.metric("Profit Margin", f"{net/total_revenue*100:.1f}%" if total_revenue else "0.0%")
            c8.metric("Avg Cost/KM", f"R{(fixed+variable)/total_distance:,.2f}" if total_distance else "R0.00")

            st.markdown("---")

            if "registration" in trips_df:
                st.subheader("🚛 Vehicle Performance")
                group_cols = {
                    "Trips": ("trip_id","count"),
                    "Distance_KM": ("distance_km","sum"),
                    "Revenue_R": ("revenue","sum"),
                    "Net_Profit_R": ("net_profit","sum"),
                }
                available = {k:v for k,v in group_cols.items() if v[0] in trips_df.columns}
                if available:
                    perf = trips_df.groupby("registration").agg(**available).reset_index()
                    st.dataframe(perf, use_container_width=True)

            if "driver_name" in trips_df:
                st.subheader("👤 Driver Performance")
                perf = trips_df.groupby("driver_name").agg(
                    Trips=("trip_id","count"),
                    Revenue_R=("revenue","sum"),
                    Net_Profit_R=("net_profit","sum"),
                ).reset_index()
                st.dataframe(perf, use_container_width=True)

            if "trip_date" in trips_df:
                st.subheader("📅 Monthly Performance")
                tmp = trips_df.copy()
                tmp["_month"] = pd.to_datetime(tmp["trip_date"], errors="coerce").dt.to_period("M").astype(str)
                monthly = tmp.groupby("_month").agg(
                    Revenue_R=("revenue","sum"),
                    Net_Profit_R=("net_profit","sum"),
                )
                st.line_chart(monthly)

    # =====================================================
    # TRIP LOG
    # =====================================================
    elif app_mode == "🗺️ Trip Log":
        st.title("🚚 GONNIE FLEET — TRIP LOG")
        st.caption("KM/L, fuel variance and profit auto-calculate.")

        veh_lookup = {
            v["registration"]: v
            for _, v in vehicles_df.iterrows()
        } if not vehicles_df.empty else {}

        with st.expander("➕ Log a new trip", expanded=trips_df.empty):
            with st.form("new_trip"):
                c1,c2,c3 = st.columns(3)
                trip_id = c1.text_input("Trip ID")
                fleet_no = c2.text_input("Fleet No")
                registration = c3.selectbox("Registration", list(veh_lookup.keys()) or ["(add vehicle first)"])

                c4,c5,c6 = st.columns(3)
                driver_name = c4.selectbox("Driver Name", list(drivers_df["driver_name"]) if not drivers_df.empty else ["(add driver first)"])
                driver_phone = c5.text_input("Driver Phone")
                trip_date = c6.date_input("Trip Date")

                c7,c8 = st.columns(2)
                origin = c7.text_input("Destination Start", "D.O.W DEPOT")
                destination = c8.text_input("Destination End")

                c9,c10,c11 = st.columns(3)
                odo_start = c9.number_input("Odo Start", min_value=0.0)
                odo_end = c10.number_input("Odo End", min_value=0.0)
                distance_km = c11.number_input("Distance KM", min_value=0.0)

                c12,c13 = st.columns(2)
                fuel_used = c12.number_input("Fuel Used (L)", min_value=0.0)
                price = c13.number_input("Cost/Litre (R)", min_value=0.0, value=25.31)

                c14,c15,c16 = st.columns(3)
                revenue = c14.number_input("Revenue (R)", min_value=0.0)
                fixed_cost = c15.number_input("Fixed Cost (R)", min_value=0.0)
                variable_cost = c16.number_input("Variable Cost (R)", min_value=0.0)

                c17,c18,c19 = st.columns(3)
                customer = c17.text_input("Customer")
                cargo = c18.text_input("Cargo Type")
                load_kg = c19.number_input("Load KG", min_value=0.0)

                c20,c21,c22 = st.columns(3)
                station = c20.text_input("Fuel Station")
                gps = c21.checkbox("GPS Verified")
                score = c22.number_input("Driver Score", min_value=0.0, max_value=100.0, value=95.0)

                c23,c24 = st.columns(2)
                maint = c23.selectbox("Maint Flag", ["None","SERVICE DUE","OVERDUE"])
                paid = c24.selectbox("Paid Status", ["unpaid","paid"])

                manager = st.text_input("Manager Name")
                manager_phone = st.text_input("Manager Phone")
                notes = st.text_area("Trip Notes")

                if st.form_submit_button("Save Trip"):
                    auto_distance = odo_end - odo_start if odo_end > odo_start else distance_km
                    calc = compute_trip_fields({
                        "distance_km": auto_distance,
                        "fuel_used_liters": fuel_used,
                        "cost_per_liter": price,
                        "revenue": revenue,
                        "fixed_cost": fixed_cost,
                        "variable_cost": variable_cost or fuel_used * price,
                    }, veh_lookup.get(registration))

                    payload = {
                        "trip_id": trip_id,
                        "fleet_no": fleet_no,
                        "registration": registration,
                        "driver_name": driver_name,
                        "driver_phone": driver_phone,
                        "trip_date": str(trip_date),
                        "origin": origin,
                        "destination": destination,
                        "odo_start": odo_start,
                        "odo_end": odo_end,
                        "distance_km": auto_distance,
                        "fuel_used_liters": fuel_used,
                        "cost_per_liter": price,
                        "revenue": revenue,
                        "fixed_cost": fixed_cost,
                        "variable_cost": variable_cost or fuel_used * price,
                        "net_profit": calc["net_profit"],
                        "customer_name": customer,
                        "cargo_type": cargo,
                        "load_kg": load_kg,
                        "fuel_station": station,
                        "gps_verified": gps,
                        "driver_score": score,
                        "maint_flag": maint,
                        "paid_status": paid,
                        "manager_name": manager,
                        "manager_phone": manager_phone,
                        "trip_notes": notes,
                    }

                    try:
                        payload = tenant_payload(payload, is_master, tenant_filter, profile)
                        result = client.table("trips").insert(payload).execute()
                        record = result.data[0] if result.data else None
                        write_audit(client,user,profile,"CREATE","trips",
                                    record.get("id") if record else None,
                                    payload.get("tenant_id"),None,record)
                        if calc["theft_alert"]:
                            st.warning(f"🚨 Theft Alert: KM/L is {calc['fuel_variance_pct']}% below expected.")
                        st.success(f"Trip saved. KM/L {calc['km_per_l']} | Profit R{calc['net_profit']:,.2f}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save trip: {e}")

        if not trips_df.empty:
            st.dataframe(trips_df, use_container_width=True)

            can_delete = is_master or profile.get("role") in ("master_admin","tenant_admin","workspace_admin","admin")
            if can_delete and "id" in trips_df:
                st.markdown("---")
                st.subheader("🗑️ Delete Trip")
                options = {}
                for _, r in trips_df.iterrows():
                    options[
                        f"{r.get('trip_id','')} • {r.get('trip_date','')} • {r.get('registration','')}"
                    ] = r["id"]

                selected = st.selectbox("Trip", list(options.keys()))
                confirm = st.checkbox("I understand this permanently deletes the selected trip.")
                if st.button("🗑️ Delete Selected Trip", disabled=not confirm):
                    rid = options[selected]
                    try:
                        q = client.table("trips").delete().eq("id", rid)
                        if tenant_filter:
                            q = q.eq("tenant_id", tenant_filter)
                        elif not is_master:
                            q = q.eq("tenant_id", profile["tenant_id"])
                        old = trips_df[trips_df["id"] == rid].iloc[0].to_dict()
                        res = q.execute()
                        if res.data:
                            write_audit(client,user,profile,"DELETE","trips",rid,
                                        old.get("tenant_id"),old,None)
                            st.success("Trip deleted.")
                            st.rerun()
                        else:
                            st.warning("Trip was not deleted.")
                    except Exception as e:
                        st.error(f"Could not delete trip: {e}")

    # =====================================================
    # VEHICLE REGISTER
    # =====================================================
    elif app_mode == "🚗 Vehicle Register":
        st.title("🚗 VEHICLE REGISTER")

        with st.expander("➕ Add a vehicle", expanded=vehicles_df.empty):
            with st.form("new_vehicle"):
                c1,c2,c3 = st.columns(3)
                registration = c1.text_input("Registration")
                fleet_no = c2.text_input("Fleet No")
                make = c3.text_input("Make")
                c4,c5,c6 = st.columns(3)
                model = c4.text_input("Model")
                year = c5.number_input("Year", min_value=1980, max_value=2100, value=2020)
                vin = c6.text_input("VIN / Engine No")
                c7,c8,c9 = st.columns(3)
                status = c7.selectbox("Status", ["Active","In Maintenance","Inactive"])
                expected = c8.number_input("Expected KM/L", min_value=0.0, value=2.0)
                service_cost = c9.number_input("Service Cost/KM", min_value=0.0, value=1.0)
                c10,c11,c12 = st.columns(3)
                insurance = c10.number_input("Monthly Insurance (R)", min_value=0.0)
                next_service = c11.number_input("Next Service KM", min_value=0.0)
                avg_daily = c12.number_input("Avg Daily KM", min_value=0.0)
                c13,c14 = st.columns(2)
                odo = c13.number_input("Current Odometer", min_value=0.0)
                license_cost = c14.number_input("Annual License Cost", min_value=0.0)

                if st.form_submit_button("Save Vehicle"):
                    payload = {
                        "registration":registration,"fleet_no":fleet_no,"make":make,
                        "model":model,"year":int(year),"vin_engine_no":vin,
                        "status":status,"expected_km_l":expected,
                        "service_cost_per_km":service_cost,
                        "monthly_insurance":insurance,"next_service_km":next_service,
                        "avg_daily_km":avg_daily,"fleet_health_score":100,
                        "current_odometer":odo,"annual_license_cost":license_cost,
                    }
                    try:
                        payload = tenant_payload(payload,is_master,tenant_filter,profile)
                        res = client.table("vehicles").insert(payload).execute()
                        record = res.data[0] if res.data else None
                        write_audit(client,user,profile,"CREATE","vehicles",
                                    record.get("id") if record else None,
                                    payload.get("tenant_id"),None,record)
                        st.success("Vehicle saved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save vehicle: {e}")

        if not vehicles_df.empty:
            st.dataframe(vehicles_df, use_container_width=True)

    # =====================================================
    # DRIVER REGISTER
    # =====================================================
    elif app_mode == "👤 Driver Register":
        st.title("👤 DRIVER REGISTER")

        with st.expander("➕ Add a driver", expanded=drivers_df.empty):
            with st.form("new_driver"):
                c1,c2,c3 = st.columns(3)
                name = c1.text_input("Driver Name")
                phone = c2.text_input("Phone")
                license_no = c3.text_input("License No")
                c4,c5 = st.columns(2)
                license_expiry = c4.date_input("License Expiry")
                prdp_expiry = c5.date_input("PrDP Expiry")
                c6,c7,c8 = st.columns(3)
                supervisor = c6.text_input("Supervisor")
                rating = c7.number_input("Supervisor Rating",1.0,5.0,5.0)
                avg_score = c8.number_input("Avg Driver Score",0.0,100.0,100.0)
                c9,c10 = st.columns(2)
                accidents = c9.number_input("Accidents",0)
                fines = c10.number_input("Fines",0)

                if st.form_submit_button("Save Driver"):
                    payload = {
                        "driver_name":name,"driver_phone":phone,
                        "license_number":license_no,"license_expiry":str(license_expiry),
                        "prdp_expiry":str(prdp_expiry),"supervisor":supervisor,
                        "rating":rating,"avg_driver_score":avg_score,
                        "accidents":int(accidents),"fines":int(fines),"status":"active",
                    }
                    try:
                        payload = tenant_payload(payload,is_master,tenant_filter,profile)
                        res = client.table("drivers").insert(payload).execute()
                        record = res.data[0] if res.data else None
                        write_audit(client,user,profile,"CREATE","drivers",
                                    record.get("id") if record else None,
                                    payload.get("tenant_id"),None,record)
                        st.success("Driver saved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save driver: {e}")

        if not drivers_df.empty:
            st.dataframe(drivers_df, use_container_width=True)

    # =====================================================
    # COMPLIANCE
    # =====================================================
    elif app_mode == "📅 Compliance & Documents":
        st.title("📅 COMPLIANCE & DOCUMENT TRACKER")

        if drivers_df.empty:
            st.info("Add drivers to populate compliance tracking.")
        else:
            rows = []
            for _, d in drivers_df.iterrows():
                ls, ld = compliance_status(d.get("license_expiry"))
                ps, pdays = compliance_status(d.get("prdp_expiry"))
                vals = [x for x in (ld,pdays) if x is not None]
                worst = min(vals) if vals else None
                action = "No action needed"
                if worst is not None and worst <= 7: action = "Renew immediately"
                elif worst is not None and worst <= 30: action = "Schedule renewal"
                rows.append({
                    "Driver Name":d.get("driver_name"),
                    "License Expiry":d.get("license_expiry"),
                    "License Status":ls,
                    "PrDP Expiry":d.get("prdp_expiry"),
                    "PrDP Status":ps,
                    "Days to Expiry":worst,
                    "Action Required":action,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # =====================================================
    # FUEL
    # =====================================================
    elif app_mode == "⛽ Fuel Consumption Analysis":
        st.title("⛽ FUEL CONSUMPTION ANALYSIS")

        if trips_df.empty:
            st.info("No fuel data yet.")
        else:
            df = trips_df.copy()
            df["_month"] = pd.to_datetime(df["trip_date"],errors="coerce").dt.to_period("M").astype(str)
            df["fuel_cost"] = df["fuel_used_liters"].fillna(0) * df["cost_per_liter"].fillna(0)
            monthly = df.groupby("_month").agg(
                Total_Trips=("trip_id","count"),
                Total_KM=("distance_km","sum"),
                Total_Fuel_L=("fuel_used_liters","sum"),
                Total_Cost_R=("fuel_cost","sum"),
            ).reset_index()
            monthly["Avg_KM_L"] = np.where(
                monthly["Total_Fuel_L"] > 0,
                (monthly["Total_KM"]/monthly["Total_Fuel_L"]).round(2),0
            )
            st.dataframe(monthly,use_container_width=True)
            st.line_chart(monthly.set_index("_month")[["Total_Cost_R","Avg_KM_L"]])

            lookup = {
                v["registration"]:v.get("expected_km_l",2.0)
                for _,v in vehicles_df.iterrows()
            } if not vehicles_df.empty else {}
            df["expected_km_l"] = df["registration"].map(lookup).fillna(2.0)
            df["actual_km_l"] = np.where(df["fuel_used_liters"]>0,
                                         df["distance_km"]/df["fuel_used_liters"],0)
            df["variance_pct"] = ((df["actual_km_l"]-df["expected_km_l"])
                                  /df["expected_km_l"]*100).round(1)
            alerts = df[df["variance_pct"] <= -20]
            if alerts.empty:
                st.success("No theft alerts.")
            else:
                st.warning(f"🚨 {len(alerts)} fuel-efficiency alerts detected.")
                st.dataframe(alerts,use_container_width=True)

    # =====================================================
    # MAINTENANCE
    # =====================================================
    elif app_mode == "🔧 Maintenance Log":
        st.title("🔧 MAINTENANCE LOG")
        options = list(vehicles_df["registration"]) if not vehicles_df.empty else ["(add vehicle first)"]

        with st.expander("➕ Log a service event"):
            with st.form("new_maintenance"):
                c1,c2 = st.columns(2)
                service_date = c1.date_input("Service Date")
                registration = c2.selectbox("Registration",options)
                c3,c4 = st.columns(2)
                fleet_no = c3.text_input("Fleet No")
                service_type = c4.selectbox("Service Type",["Scheduled","Unscheduled"])
                c5,c6 = st.columns(2)
                odo_service = c5.number_input("Odo at Service",min_value=0.0)
                next_service = c6.number_input("Next Service KM",min_value=0.0)
                c7,c8 = st.columns(2)
                cost = c7.number_input("Cost (R)",min_value=0.0)
                workshop = c8.text_input("Workshop")
                notes = st.text_area("Notes")

                if st.form_submit_button("Save Service Event"):
                    payload = {
                        "service_date":str(service_date),"registration":registration,
                        "fleet_no":fleet_no,"service_type":service_type,
                        "odo_at_service":odo_service,"next_service_km":next_service,
                        "cost":cost,"workshop":workshop,"notes":notes,
                    }
                    try:
                        payload = tenant_payload(payload,is_master,tenant_filter,profile)
                        res = client.table("maintenance_log").insert(payload).execute()
                        record = res.data[0] if res.data else None
                        write_audit(client,user,profile,"CREATE","maintenance_log",
                                    record.get("id") if record else None,
                                    payload.get("tenant_id"),None,record)
                        st.success("Service event logged.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save: {e}")

        maint_df = fetch_df(client,"maintenance_log",tenant_filter)
        if not maint_df.empty:
            st.dataframe(maint_df,use_container_width=True)
        else:
            st.info("No maintenance events logged yet.")

    # =====================================================
    # FINANCIAL FORECAST
    # =====================================================
    elif app_mode == "💰 Financial Forecast":
        st.title("💰 FINANCIAL FORECAST")
        today = date.today()
        end = today + pd.Timedelta(days=30)

        rows=[]
        total_spend=0
        urgent=0
        impacted=set()

        for _,v in vehicles_df.iterrows():
            next_service=v.get("next_service_km")
            avg=v.get("avg_daily_km") or 0
            odo=v.get("current_odometer") or 0
            if next_service and avg:
                days=int((next_service-odo)/avg)
                if days <= 30:
                    rows.append({
                        "Vehicle":v.get("registration"),
                        "Event":"Service Due",
                        "Days Away":days,
                        "Priority":"URGENT" if days<=7 else "PLAN",
                    })
                    if days<=7: urgent+=1
                    impacted.add(v.get("registration"))
            total_spend += (v.get("annual_license_cost") or 0)/12

        for _,d in drivers_df.iterrows():
            for field,label in [("license_expiry","License Renewal"),("prdp_expiry","PrDP Renewal")]:
                _,days=compliance_status(d.get(field))
                if days is not None and 0<=days<=30:
                    rows.append({
                        "Vehicle":"-","Driver":d.get("driver_name"),
                        "Event":label,"Days Away":days,
                        "Priority":"URGENT" if days<=7 else "PLAN",
                    })
                    if days<=7: urgent+=1

        c1,c2,c3,c4=st.columns(4)
        c1.metric("Forecast Spend",f"R{total_spend:,.2f}")
        c2.metric("Urgent Items",urgent)
        c3.metric("Vehicles Impacted",len(impacted))
        c4.metric("Events",len(rows))
        st.dataframe(pd.DataFrame(rows),use_container_width=True) if rows else st.success("No upcoming events.")

    # =====================================================
    # JOB PROFITABILITY
    # =====================================================
    elif app_mode == "🧮 Job Profitability Estimator":
        st.title("🧮 JOB PROFITABILITY ESTIMATOR")

        c1,c2=st.columns(2)
        distance=c1.number_input("Estimated Distance (km, one-way)",1.0, value=500.0)
        return_trip=c2.selectbox("Return Trip?",["YES","NO"])
        c3,c4=st.columns(2)
        revenue=c3.number_input("Revenue / Quote (R)",0.0,value=15000.0)
        fuel_price=c4.number_input("Fuel Cost per Litre (R)",0.0,value=25.31)
        c5,c6=st.columns(2)
        km_l=c5.number_input("Vehicle KM/L",0.1,value=2.0)
        driver_cost=c6.number_input("Driver Cost (R)",0.0,value=1500.0)
        c7,c8=st.columns(2)
        toll=c7.number_input("Toll Costs (R)",0.0,value=50.0)
        other=c8.number_input("Other Fixed Costs (R)",0.0)
        c9,c10,c11=st.columns(3)
        maint=c9.number_input("Maintenance Alloc/KM",0.0,value=0.45)
        ins=c10.number_input("Insurance Alloc/KM",0.0,value=0.25)
        lic=c11.number_input("License Alloc/KM",0.0,value=0.022)

        mult=2 if return_trip=="YES" else 1
        total_km=distance*mult
        fuel=total_km/km_l
        fuel_cost=fuel*fuel_price
        total_cost=fuel_cost+driver_cost+toll+(maint+ins+lic)*total_km+other
        profit=revenue-total_cost
        margin=profit/revenue*100 if revenue else 0
        st.metric("Total Cost",f"R{total_cost:,.2f}")
        st.metric("Net Profit",f"R{profit:,.2f}")
        st.metric("Profit Margin",f"{margin:.1f}%")
        if margin>=15: st.success("✅ TAKE THE JOB")
        elif margin>=5: st.warning("⚠️ MARGINAL")
        else: st.error("❌ DO NOT TAKE")

    # =====================================================
    # GPS
    # =====================================================
    elif app_mode == "🛰️ GPS Tracker Log":
        st.title("🛰️ GPS TRACKER LOG")

        with st.expander("➕ Log a GPS trip record"):
            with st.form("new_gps"):
                c1,c2,c3=st.columns(3)
                log_date=c1.date_input("Date")
                registration=c2.text_input("Registration")
                fleet_no=c3.text_input("Fleet No")
                c4,c5=st.columns(2)
                driver=c4.text_input("Driver Name")
                location=c5.text_input("Location (Lat, Long)")
                c6,c7=st.columns(2)
                ignition_on=c6.time_input("Ignition ON")
                ignition_off=c7.time_input("Ignition OFF")
                c8,c9=st.columns(2)
                odo_start=c8.number_input("Odo Start",0.0)
                odo_end=c9.number_input("Odo End",0.0)
                c10,c11,c12=st.columns(3)
                idle=c10.number_input("Idle Time (min)",0.0)
                fuel_start=c11.number_input("Fuel Start (%)",0.0,100.0,100.0)
                fuel_end=c12.number_input("Fuel End (%)",0.0,100.0,0.0)
                trip_distance=st.number_input("Trip Log Distance",0.0)

                if st.form_submit_button("Save GPS Record"):
                    payload={
                        "log_date":str(log_date),"registration":registration,
                        "fleet_no":fleet_no,"driver_name":driver,
                        "ignition_on":str(ignition_on),"ignition_off":str(ignition_off),
                        "odo_start":odo_start,"odo_end":odo_end,
                        "idle_time_min":idle,"fuel_level_start":fuel_start,
                        "fuel_level_end":fuel_end,"location":location,
                        "trip_log_distance":trip_distance,
                    }
                    try:
                        payload=tenant_payload(payload,is_master,tenant_filter,profile)
                        res=client.table("gps_tracker_log").insert(payload).execute()
                        record=res.data[0] if res.data else None
                        write_audit(client,user,profile,"CREATE","gps_tracker_log",
                                    record.get("id") if record else None,
                                    payload.get("tenant_id"),None,record)
                        st.success("GPS record saved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save: {e}")

        gps=fetch_df(client,"gps_tracker_log",tenant_filter)
        if not gps.empty:
            gps["gps_distance_km"]=gps["odo_end"].fillna(0)-gps["odo_start"].fillna(0)
            gps["variance_pct"]=np.where(
                gps["trip_log_distance"]>0,
                ((gps["gps_distance_km"]-gps["trip_log_distance"])/gps["trip_log_distance"]*100).round(1),0
            )
            gps["flag"]=np.where(gps["variance_pct"].abs()>=10,"🚩 MISMATCH","OK")
            st.dataframe(gps,use_container_width=True)
        else:
            st.info("No GPS records yet.")

    # =====================================================
    # BILLING
    # =====================================================
    elif app_mode == "💳 Billing & Subscription":
        st.title("💳 BILLING & SUBSCRIPTION")

        billing_tenant_id = tenant_filter if is_master and tenant_filter else profile.get("tenant_id")

        if not billing_tenant_id:
            st.info("Select a specific tenant from the Master Admin tenant selector.")
        else:
            sub = client.table("billing_subscriptions").select("*").eq(
                "tenant_id",billing_tenant_id
            ).order("created_at",desc=True).limit(1).execute().data
            current=sub[0] if sub else None

            if current:
                c1,c2,c3=st.columns(3)
                c1.metric("Plan",PLAN_LABELS.get(current["plan"],current["plan"]))
                c2.metric("Status",str(current["status"]).upper())
                c3.metric("Amount",f"R{(current.get('amount_cents') or 0)/100:,.2f}")
            else:
                st.warning("No subscription on record.")

            plan=st.selectbox("Choose a plan",["starter","professional","enterprise"],
                              format_func=lambda p:PLAN_LABELS[p])
            amount=None
            if plan=="enterprise":
                amount=int(st.number_input("Enterprise monthly amount (R)",0.0,step=100.0)*100)

            if st.button("Proceed to Payment",type="primary"):
                if plan=="enterprise" and not amount:
                    st.error("Enter the enterprise amount.")
                else:
                    try:
                        token=st.session_state["session"].access_token
                        payload={
                            "plan":plan,
                            "success_url":f"{APP_BASE_URL}/?billing=success",
                            "cancel_url":f"{APP_BASE_URL}/?billing=cancelled",
                            "failure_url":f"{APP_BASE_URL}/?billing=failed",
                        }
                        if plan=="enterprise":
                            payload["amount_cents"]=amount
                        resp=requests.post(
                            CHECKOUT_FUNCTION_URL,
                            headers={
                                "Authorization":f"Bearer {token}",
                                "Content-Type":"application/json",
                                "apikey":SUPABASE_ANON_KEY,
                            },
                            json=payload,timeout=30
                        )
                        data=resp.json()
                        if resp.ok and data.get("redirectUrl"):
                            st.link_button("💳 Pay with Yoco",data["redirectUrl"],type="primary")
                        else:
                            st.error(data.get("error",resp.text))
                    except Exception as e:
                        st.error(f"Checkout request failed: {e}")

            hist=client.table("billing_subscriptions").select("*").eq(
                "tenant_id",billing_tenant_id
            ).order("created_at",desc=True).execute().data or []
            if hist:
                st.subheader("Subscription History")
                st.dataframe(pd.DataFrame(hist),use_container_width=True)


# =========================================================
# ENTRYPOINT
# =========================================================
if "session" not in st.session_state:
    show_login()
else:
    show_app() 
