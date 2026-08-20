import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime
from supabase import create_client, Client

# =========================================================
# CONFIG
# =========================================================
SUPABASE_URL = "https://iguoiyslhyqpvlfjxksh.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlndW9peXNsaHlxcHZsZmp4a3NoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODcyMDU3NTcsImV4cCI6MjEwMjc4MTc1N30.5Zh2MPcH3TpIJ--M2m-vN4pSICu5-5Ja8-zbgiRipyM"

st.set_page_config(page_title="Gonnie Fleet Intelligence D.O.W", page_icon="🚚", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .sidebar .sidebar-content { background-color: #2c3e50; }
    </style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_base_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_authed_client() -> Client:
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    if "session" in st.session_state:
        client.auth.set_session(
            st.session_state["session"].access_token,
            st.session_state["session"].refresh_token,
        )
    return client


# =========================================================
# AUTH SCREENS
# =========================================================
def show_login():
    st.title("🚚 Gonnie Fleet Intelligence D.O.W")
    st.caption("Diesel on Wheels — Multi-Fleet Intelligence Dashboard")

    tab_login, tab_signup = st.tabs(["Log In", "Sign Up"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log In", use_container_width=True)
            if submitted:
                try:
                    client = get_base_client()
                    res = client.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state["session"] = res.session
                    st.session_state["user"] = res.user
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

    with tab_signup:
        st.markdown("New company? Create your account — you'll automatically get your own isolated workspace.")
        with st.form("signup_form"):
            company_name = st.text_input("Company Name")
            full_name = st.text_input("Your Full Name")
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password", type="password", key="signup_password")
            submitted = st.form_submit_button("Create Account", use_container_width=True)
            if submitted:
                try:
                    client = get_base_client()
                    client.auth.sign_up({
                        "email": email,
                        "password": password,
                        "options": {"data": {"company_name": company_name, "full_name": full_name}},
                    })
                    st.success("Account created! Check your email to confirm, then log in.")
                except Exception as e:
                    st.error(f"Sign up failed: {e}")


# =========================================================
# HELPERS
# =========================================================
def get_profile(client: Client, user_id: str):
    res = client.table("profiles").select("*").eq("id", user_id).single().execute()
    return res.data


def fetch_df(client: Client, table_name: str, tenant_filter: str = None) -> pd.DataFrame:
    q = client.table(table_name).select("*")
    if tenant_filter:
        q = q.eq("tenant_id", tenant_filter)
    res = q.execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()


def tenant_payload(payload: dict, is_master: bool, tenant_filter, profile) -> dict:
    if is_master and tenant_filter:
        payload["tenant_id"] = tenant_filter
    elif not is_master:
        payload["tenant_id"] = profile["tenant_id"]
    return payload


def compute_trip_fields(row: dict, vehicle_row: dict = None) -> dict:
    """Auto-calculate KM/L, cost/km, fuel variance %, theft alert — mirrors the spreadsheet formulas."""
    distance = row.get("distance_km") or 0
    fuel_used = row.get("fuel_used_liters") or 0
    cost_per_liter = row.get("cost_per_liter") or 0
    revenue = row.get("revenue") or 0
    fixed_cost = row.get("fixed_cost") or 0
    variable_cost = row.get("variable_cost") or (fuel_used * cost_per_liter)

    km_per_l = round(distance / fuel_used, 2) if fuel_used else 0
    fuel_cost = round(fuel_used * cost_per_liter, 2)
    # vehicle_row is normally a pandas Series from iterrows().
    # Do NOT use `vehicle_row or {}` here because pandas Series cannot
    # be evaluated as a single True/False value.
    if vehicle_row is None:
        expected_km_l = 2.0
    else:
        expected_km_l = vehicle_row.get("expected_km_l", 2.0)
        if pd.isna(expected_km_l) or expected_km_l <= 0:
            expected_km_l = 2.0

    fuel_variance_pct = round(((km_per_l - expected_km_l) / expected_km_l) * 100, 1) if expected_km_l else 0
    theft_alert = fuel_variance_pct <= -20
    net_profit = round(revenue - fixed_cost - variable_cost, 2)
    profit_margin = round((net_profit / revenue) * 100, 1) if revenue else 0
    cost_per_km = round((fixed_cost + variable_cost) / distance, 2) if distance else 0

    return {
        "km_per_l": km_per_l,
        "fuel_cost": fuel_cost,
        "expected_km_l": expected_km_l,
        "fuel_variance_pct": fuel_variance_pct,
        "theft_alert": theft_alert,
        "net_profit": net_profit,
        "profit_margin": profit_margin,
        "cost_per_km": cost_per_km,
    }


def compliance_status(expiry: str):
    if not expiry:
        return "⚪ UNKNOWN", None
    try:
        exp_date = pd.to_datetime(expiry).date()
    except Exception:
        return "⚪ UNKNOWN", None
    days = (exp_date - date.today()).days
    if days < 0:
        return "🔴 EXPIRED", days
    elif days <= 7:
        return "🟠 URGENT", days
    elif days <= 30:
        return "🟡 EXPIRING SOON", days
    else:
        return "🟢 COMPLIANT", days


# =========================================================
# MAIN APP
# =========================================================
def show_app():
    client = get_authed_client()
    user = st.session_state["user"]
    profile = get_profile(client, user.id)

    if profile is None:
        st.error("No profile found for this user. Please contact support.")
        st.stop()

    is_master = profile["role"] == "master_admin"

    st.sidebar.title("🚚 Gonnie Fleet Intelligence")
    st.sidebar.markdown(f"**{user.email}**")
    st.sidebar.markdown(f"Role: `{profile['role']}`")
    if st.sidebar.button("Log Out"):
        client.auth.sign_out()
        for k in ("session", "user"):
            st.session_state.pop(k, None)
        st.rerun()
    st.sidebar.markdown("---")

    tenant_filter = None
    if is_master:
        tenants_res = client.table("tenants").select("id, name").order("name").execute()
        tenant_options = {"🌐 All Tenants (Master View)": None}
        tenant_options.update({t["name"]: t["id"] for t in tenants_res.data})
        chosen = st.sidebar.selectbox("Viewing Tenant", list(tenant_options.keys()))
        tenant_filter = tenant_options[chosen]
        st.sidebar.caption("As master admin, you can view any tenant's data or all combined.")

    app_mode = st.sidebar.selectbox("Choose Navigation", [
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
    ] + (["👑 Master Admin: Manage Tenants & Users"] if is_master else []))

    trips_df = fetch_df(client, "trips", tenant_filter)
    vehicles_df = fetch_df(client, "vehicles", tenant_filter)
    drivers_df = fetch_df(client, "drivers", tenant_filter)

    # -----------------------------------------------------
    # 1. EXECUTIVE DASHBOARD
    # -----------------------------------------------------
    if app_mode == "📊 Executive Dashboard":
        st.title("📊 Fleet Executive Dashboard")
        st.markdown("**GONNIE FLEET MANAGEMENT SYSTEM** ⬥ Multi-Fleet Intelligence Dashboard ⬥ Trip Log Powered")

        if not trips_df.empty:
            total_trips = len(trips_df)
            total_distance = trips_df['distance_km'].fillna(0).sum() if 'distance_km' in trips_df else 0
            total_revenue = trips_df['revenue'].fillna(0).sum() if 'revenue' in trips_df else 0
            total_fuel_cost = (trips_df.get('fuel_used_liters', pd.Series(dtype=float)).fillna(0) *
                                trips_df.get('cost_per_liter', pd.Series(dtype=float)).fillna(0)).sum()
            fixed_cost = trips_df.get('fixed_cost', pd.Series(dtype=float)).fillna(0).sum()
            variable_cost = trips_df.get('variable_cost', pd.Series(dtype=float)).fillna(0).sum()
            net_profit = trips_df['net_profit'].fillna(0).sum() if 'net_profit' in trips_df else (total_revenue - fixed_cost - variable_cost)
            avg_rev_km = round(total_revenue / total_distance, 2) if total_distance else 0
            profit_margin = round((net_profit / total_revenue) * 100, 1) if total_revenue else 0
            avg_cost_km = round((fixed_cost + variable_cost) / total_distance, 2) if total_distance else 0
            theft_alerts = int(trips_df.get('theft_alert', pd.Series(dtype=bool)).fillna(False).sum()) if 'theft_alert' in trips_df else 0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Trips", f"{total_trips}")
            c2.metric("Total Revenue (R)", f"{total_revenue:,.2f}")
            c3.metric("Total Distance (km)", f"{total_distance:,.0f}")
            c4.metric("Fuel Cost (R)", f"{total_fuel_cost:,.2f}")

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Net Profit (R)", f"{net_profit:,.2f}")
            c6.metric("Avg Revenue/KM", f"{avg_rev_km:,.2f}")
            c7.metric("Profit Margin %", f"{profit_margin}%")
            c8.metric("Avg Cost/KM", f"{avg_cost_km:,.2f}")

            c9, c10, c11 = st.columns(3)
            c9.metric("Fixed Cost (R)", f"{fixed_cost:,.2f}")
            c10.metric("Variable Cost (R)", f"{variable_cost:,.2f}")
            c11.metric("🚨 Theft Alerts", f"{theft_alerts}")

            st.markdown("---")

            st.subheader("🚛 Vehicle Performance")
            if 'registration' in trips_df.columns:
                veh_perf = trips_df.groupby('registration').agg(
                    Trips=('trip_id', 'count'),
                    Distance_KM=('distance_km', 'sum'),
                    Revenue_R=('revenue', 'sum'),
                    Net_Profit_R=('net_profit', 'sum'),
                ).reset_index()
                veh_perf['Margin_%'] = np.where(veh_perf['Revenue_R'] > 0,
                                                 (veh_perf['Net_Profit_R'] / veh_perf['Revenue_R'] * 100).round(1), 0)
                st.dataframe(veh_perf, use_container_width=True)

            st.subheader("👤 Driver Performance")
            if 'driver_name' in trips_df.columns:
                drv_perf = trips_df.groupby('driver_name').agg(
                    Trips=('trip_id', 'count'),
                    Revenue_R=('revenue', 'sum'),
                    Net_Profit_R=('net_profit', 'sum'),
                ).reset_index()
                drv_perf['Margin_%'] = np.where(drv_perf['Revenue_R'] > 0,
                                                 (drv_perf['Net_Profit_R'] / drv_perf['Revenue_R'] * 100).round(1), 0)
                st.dataframe(drv_perf, use_container_width=True)

            if 'customer_name' in trips_df.columns and trips_df['customer_name'].notna().any():
                st.subheader("🏢 Customer Performance")
                cust_perf = trips_df.groupby('customer_name').agg(
                    Trips=('trip_id', 'count'),
                    Revenue_R=('revenue', 'sum'),
                    Net_Profit_R=('net_profit', 'sum'),
                    Avg_KM=('distance_km', 'mean'),
                ).reset_index()
                st.dataframe(cust_perf, use_container_width=True)

            st.subheader("📅 Monthly Performance Trend")
            if 'trip_date' in trips_df.columns:
                trips_df['_month'] = pd.to_datetime(trips_df['trip_date'], errors='coerce').dt.to_period('M').astype(str)
                monthly = trips_df.groupby('_month').agg(
                    Trips=('trip_id', 'count'),
                    Distance_KM=('distance_km', 'sum'),
                    Revenue_R=('revenue', 'sum'),
                    Net_Profit_R=('net_profit', 'sum'),
                ).reset_index()
                st.line_chart(monthly.set_index('_month')[['Revenue_R', 'Net_Profit_R']])

            st.subheader("🏆 Top 10 Most Profitable Trips")
            top10 = trips_df.sort_values('net_profit', ascending=False).head(10)
            cols_show = [c for c in ['trip_id', 'trip_date', 'registration', 'driver_name',
                                      'customer_name', 'distance_km', 'revenue', 'net_profit'] if c in top10.columns]
            st.dataframe(top10[cols_show], use_container_width=True)

            st.subheader("⚠ Bottom 10 Least Profitable Trips")
            bottom10 = trips_df.sort_values('net_profit', ascending=True).head(10)
            st.dataframe(bottom10[cols_show], use_container_width=True)
        else:
            st.info("No trip data yet. Add trips from the 'Trip Log' page.")

    # -----------------------------------------------------
    # 2. TRIP LOG
    # -----------------------------------------------------
    elif app_mode == "🗺️ Trip Log":
        st.title("🚚 GONNIE FLEET — TRIP LOG")
        st.caption("Enter trip data below. KM/L, fuel variance, and profit auto-calculate.")

        veh_lookup = {v['registration']: v for _, v in vehicles_df.iterrows()} if not vehicles_df.empty else {}

        with st.expander("➕ Log a new trip", expanded=trips_df.empty):
            with st.form("new_trip"):
                c1, c2, c3 = st.columns(3)
                trip_id = c1.text_input("Trip ID")
                fleet_no = c2.text_input("Fleet No")
                registration = c3.selectbox("Registration", options=list(veh_lookup.keys()) or ["(add a vehicle first)"])

                c4, c5, c6 = st.columns(3)
                driver_name = c4.selectbox("Driver Name", options=list(drivers_df['driver_name']) if not drivers_df.empty else ["(add a driver first)"])
                driver_phone = c5.text_input("Driver Phone")
                trip_date = c6.date_input("Trip Date")

                c7, c8 = st.columns(2)
                origin = c7.text_input("Destination Start", value="D.O.W DEPOT")
                destination = c8.text_input("Destination End")

                c9, c10, c11 = st.columns(3)
                odo_start = c9.number_input("Odo Start", min_value=0.0, value=0.0)
                odo_end = c10.number_input("Odo End", min_value=0.0, value=0.0)
                distance_km = c11.number_input("Distance KM (auto if blank)", min_value=0.0, value=0.0)

                c12, c13 = st.columns(2)
                fuel_used_liters = c12.number_input("Fuel Used (L)", min_value=0.0, value=0.0)
                cost_per_liter = c13.number_input("Cost/Liter (R)", min_value=0.0, value=25.31)

                c14, c15, c16 = st.columns(3)
                revenue = c14.number_input("Revenue (R)", min_value=0.0, value=0.0)
                fixed_cost = c15.number_input("Fixed Cost (R)", min_value=0.0, value=0.0)
                variable_cost = c16.number_input("Variable Cost (R, blank = fuel cost)", min_value=0.0, value=0.0)

                c17, c18, c19 = st.columns(3)
                customer_name = c17.text_input("Customer")
                cargo_type = c18.text_input("Cargo Type")
                load_kg = c19.number_input("Load KG", min_value=0.0, value=0.0)

                c20, c21, c22 = st.columns(3)
                fuel_station = c20.text_input("Fuel Station")
                gps_verified = c21.checkbox("GPS Verified")
                driver_score = c22.number_input("Driver Score", min_value=0.0, max_value=100.0, value=95.0)

                c23, c24 = st.columns(2)
                maint_flag = c23.selectbox("Maint Flag", ["None", "SERVICE DUE", "OVERDUE"])
                paid_status = c24.selectbox("Paid Status", ["unpaid", "paid"])

                manager_name = st.text_input("Manager Name")
                manager_phone = st.text_input("Manager Phone")
                trip_notes = st.text_area("Trip Notes")

                if st.form_submit_button("Save Trip"):
                    auto_distance = (odo_end - odo_start) if (odo_end and odo_start and odo_end > odo_start) else distance_km
                    vehicle_row = veh_lookup.get(registration, {})
                    calc = compute_trip_fields({
                        "distance_km": auto_distance, "fuel_used_liters": fuel_used_liters,
                        "cost_per_liter": cost_per_liter, "revenue": revenue,
                        "fixed_cost": fixed_cost, "variable_cost": variable_cost or (fuel_used_liters * cost_per_liter),
                    }, vehicle_row)

                    payload = {
                        "trip_id": trip_id, "fleet_no": fleet_no, "registration": registration,
                        "driver_name": driver_name, "driver_phone": driver_phone,
                        "trip_date": str(trip_date), "origin": origin, "destination": destination,
                        "odo_start": odo_start, "odo_end": odo_end, "distance_km": auto_distance,
                        "fuel_used_liters": fuel_used_liters, "cost_per_liter": cost_per_liter,
                        "revenue": revenue, "fixed_cost": fixed_cost,
                        "variable_cost": variable_cost or (fuel_used_liters * cost_per_liter),
                        "net_profit": calc["net_profit"],
                        "customer_name": customer_name, "cargo_type": cargo_type, "load_kg": load_kg,
                        "fuel_station": fuel_station, "gps_verified": gps_verified, "driver_score": driver_score,
                        "maint_flag": maint_flag, "paid_status": paid_status,
                        "manager_name": manager_name, "manager_phone": manager_phone, "trip_notes": trip_notes,
                    }
                    payload = tenant_payload(payload, is_master, tenant_filter, profile)
                    try:
                        client.table("trips").insert(payload).execute()
                        if calc["theft_alert"]:
                            st.warning(f"🚨 Theft Alert: KM/L is {calc['fuel_variance_pct']}% below expected for this vehicle.")
                        st.success(f"Trip saved. KM/L: {calc['km_per_l']} | Net Profit: R{calc['net_profit']:,.2f}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save trip: {e}")

        if not trips_df.empty:
            search_reg = st.text_input("Filter by Registration or Driver", "")
            display_df = trips_df.copy()
            if search_reg:
                display_df = display_df[
                    display_df['registration'].astype(str).str.contains(search_reg, case=False, na=False) |
                    display_df['driver_name'].astype(str).str.contains(search_reg, case=False, na=False)
                ]
            if 'fuel_used_liters' in display_df.columns and 'distance_km' in display_df.columns:
                display_df['km_per_l'] = np.where(display_df['fuel_used_liters'] > 0,
                                                   (display_df['distance_km'] / display_df['fuel_used_liters']).round(2), 0)
            st.dataframe(display_df, use_container_width=True)
        else:
            st.info("No trips logged yet.")

    # -----------------------------------------------------
    # 3. VEHICLE REGISTER
    # -----------------------------------------------------
    elif app_mode == "🚗 Vehicle Register":
        st.title("🚗 VEHICLE REGISTER")
        st.caption("Formulas across the system reference these values (Expected KM/L, service intervals, health score).")

        with st.expander("➕ Add a vehicle", expanded=vehicles_df.empty):
            with st.form("new_vehicle"):
                c1, c2, c3 = st.columns(3)
                registration = c1.text_input("Registration")
                fleet_no = c2.text_input("Fleet No")
                make = c3.text_input("Make")
                c4, c5, c6 = st.columns(3)
                model = c4.text_input("Model")
                year = c5.number_input("Year", min_value=1980, max_value=2100, value=2020)
                vin_engine_no = c6.text_input("VIN / Engine No")
                c7, c8, c9 = st.columns(3)
                status = c7.selectbox("Status", ["Active", "In Maintenance", "Inactive"])
                expected_km_l = c8.number_input("Expected KM/L", min_value=0.0, value=2.0)
                service_cost_per_km = c9.number_input("Service Cost/KM (R)", min_value=0.0, value=1.0)
                c10, c11, c12 = st.columns(3)
                monthly_insurance = c10.number_input("Monthly Insurance (R)", min_value=0.0, value=0.0)
                next_service_km = c11.number_input("Next Service KM", min_value=0.0, value=0.0)
                avg_daily_km = c12.number_input("Avg Daily KM", min_value=0.0, value=0.0)
                c13, c14 = st.columns(2)
                current_odometer = c13.number_input("Current Odometer", min_value=0.0, value=0.0)
                annual_license_cost = c14.number_input("Annual License Cost (R)", min_value=0.0, value=0.0)

                if st.form_submit_button("Save Vehicle"):
                    payload = {
                        "registration": registration, "fleet_no": fleet_no, "make": make, "model": model,
                        "year": int(year), "vin_engine_no": vin_engine_no, "status": status,
                        "expected_km_l": expected_km_l, "service_cost_per_km": service_cost_per_km,
                        "monthly_insurance": monthly_insurance, "next_service_km": next_service_km,
                        "avg_daily_km": avg_daily_km, "fleet_health_score": 100,
                        "current_odometer": current_odometer, "annual_license_cost": annual_license_cost,
                    }
                    payload = tenant_payload(payload, is_master, tenant_filter, profile)
                    try:
                        client.table("vehicles").insert(payload).execute()
                        st.success("Vehicle saved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save vehicle: {e}")

        if not vehicles_df.empty:
            st.dataframe(vehicles_df, use_container_width=True)
        else:
            st.info("No vehicles registered yet.")

    # -----------------------------------------------------
    # 4. DRIVER REGISTER
    # -----------------------------------------------------
    elif app_mode == "👤 Driver Register":
        st.title("👤 DRIVER REGISTER")
        st.caption("License & PrDP expiry dates feed the Compliance tracker automatically.")

        with st.expander("➕ Add a driver", expanded=drivers_df.empty):
            with st.form("new_driver"):
                c1, c2, c3 = st.columns(3)
                driver_name = c1.text_input("Driver Name")
                driver_phone = c2.text_input("Phone")
                license_number = c3.text_input("License No")
                c4, c5 = st.columns(2)
                license_expiry = c4.date_input("License Expiry")
                prdp_expiry = c5.date_input("PrDP Expiry")
                c6, c7, c8 = st.columns(3)
                supervisor = c6.text_input("Supervisor")
                rating = c7.number_input("Supervisor Rating (1-5)", min_value=1.0, max_value=5.0, value=5.0)
                avg_driver_score = c8.number_input("Avg Driver Score", min_value=0.0, max_value=100.0, value=100.0)
                c9, c10 = st.columns(2)
                accidents = c9.number_input("Accidents", min_value=0, value=0)
                fines = c10.number_input("Fines", min_value=0, value=0)

                if st.form_submit_button("Save Driver"):
                    payload = {
                        "driver_name": driver_name, "driver_phone": driver_phone,
                        "license_number": license_number, "license_expiry": str(license_expiry),
                        "prdp_expiry": str(prdp_expiry), "supervisor": supervisor, "rating": rating,
                        "avg_driver_score": avg_driver_score, "accidents": int(accidents), "fines": int(fines),
                        "status": "active",
                    }
                    payload = tenant_payload(payload, is_master, tenant_filter, profile)
                    try:
                        client.table("drivers").insert(payload).execute()
                        st.success("Driver saved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save driver: {e}")

        if not drivers_df.empty:
            st.dataframe(drivers_df, use_container_width=True)
        else:
            st.info("No drivers registered yet.")

    # -----------------------------------------------------
    # 5. COMPLIANCE & DOCUMENTS
    # -----------------------------------------------------
    elif app_mode == "📅 Compliance & Documents":
        st.title("📅 COMPLIANCE & DOCUMENT TRACKER")
        st.caption("Auto-links from Driver Register. Colour-coded by urgency.")

        if not drivers_df.empty:
            rows = []
            for _, d in drivers_df.iterrows():
                lic_status, lic_days = compliance_status(d.get("license_expiry"))
                prdp_status, prdp_days = compliance_status(d.get("prdp_expiry"))
                worst_days = min([x for x in [lic_days, prdp_days] if x is not None], default=None)
                action = "No action needed"
                if worst_days is not None and worst_days <= 7:
                    action = "Renew immediately"
                elif worst_days is not None and worst_days <= 30:
                    action = "Schedule renewal"
                rows.append({
                    "Driver Name": d.get("driver_name"),
                    "License Expiry": d.get("license_expiry"),
                    "License Status": lic_status,
                    "PrDP Expiry": d.get("prdp_expiry"),
                    "PrDP Status": prdp_status,
                    "Days to Expiry": worst_days,
                    "Action Required": action,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("Add drivers with license/PrDP expiry dates to populate compliance tracking.")

    # -----------------------------------------------------
    # 6. FUEL CONSUMPTION ANALYSIS
    # -----------------------------------------------------
    elif app_mode == "⛽ Fuel Consumption Analysis":
        st.title("⛽ FUEL CONSUMPTION ANALYSIS")
        st.caption("Auto-aggregated monthly from Trip Log.")

        if not trips_df.empty and 'fuel_used_liters' in trips_df.columns:
            df = trips_df.copy()
            df['_month'] = pd.to_datetime(df['trip_date'], errors='coerce').dt.to_period('M').astype(str)
            df['fuel_cost'] = df['fuel_used_liters'].fillna(0) * df['cost_per_liter'].fillna(0)
            monthly = df.groupby('_month').agg(
                Total_Trips=('trip_id', 'count'),
                Total_KM=('distance_km', 'sum'),
                Total_Fuel_L=('fuel_used_liters', 'sum'),
                Total_Cost_R=('fuel_cost', 'sum'),
            ).reset_index()
            monthly['Avg_KM_L'] = np.where(monthly['Total_Fuel_L'] > 0,
                                            (monthly['Total_KM'] / monthly['Total_Fuel_L']).round(2), 0)
            monthly['Avg_Cost_KM'] = np.where(monthly['Total_KM'] > 0,
                                               (monthly['Total_Cost_R'] / monthly['Total_KM']).round(2), 0)
            st.dataframe(monthly, use_container_width=True)

            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("Monthly Fuel Cost Trend")
                st.line_chart(monthly.set_index('_month')['Total_Cost_R'])
            with col_b:
                st.subheader("KM/L Efficiency Trend")
                st.line_chart(monthly.set_index('_month')['Avg_KM_L'])

            st.subheader("Theft Alerts (KM/L drop > 20% below vehicle baseline)")
            veh_lookup = {v['registration']: v.get('expected_km_l', 2.0) for _, v in vehicles_df.iterrows()} if not vehicles_df.empty else {}
            df['expected_km_l'] = df['registration'].map(veh_lookup).fillna(2.0)
            df['actual_km_l'] = np.where(df['fuel_used_liters'] > 0, df['distance_km'] / df['fuel_used_liters'], 0)
            df['variance_pct'] = np.where(df['expected_km_l'] > 0,
                                           ((df['actual_km_l'] - df['expected_km_l']) / df['expected_km_l'] * 100).round(1), 0)
            alerts = df[df['variance_pct'] <= -20]
            if not alerts.empty:
                st.dataframe(alerts[['trip_id', 'trip_date', 'registration', 'driver_name', 'actual_km_l',
                                      'expected_km_l', 'variance_pct']], use_container_width=True)
            else:
                st.success("No theft alerts — all vehicles within expected fuel efficiency range.")
        else:
            st.info("No fuel data yet — log trips with fuel used to populate this page.")

    # -----------------------------------------------------
    # 7. MAINTENANCE LOG
    # -----------------------------------------------------
    elif app_mode == "🔧 Maintenance Log":
        st.title("🔧 MAINTENANCE LOG")
        st.caption("Log ALL service events. Type = Scheduled or Unscheduled (affects Health Score).")

        veh_options = list(vehicles_df['registration']) if not vehicles_df.empty else []

        with st.expander("➕ Log a service event"):
            with st.form("new_maintenance"):
                c1, c2 = st.columns(2)
                service_date = c1.date_input("Service Date")
                registration = c2.selectbox("Registration", options=veh_options or ["(add a vehicle first)"])
                c3, c4 = st.columns(2)
                fleet_no = c3.text_input("Fleet No")
                service_type = c4.selectbox("Service Type", ["Scheduled", "Unscheduled"])
                c5, c6 = st.columns(2)
                odo_at_service = c5.number_input("Odo at Service", min_value=0.0, value=0.0)
                next_service_km = c6.number_input("Next Service KM", min_value=0.0, value=0.0)
                c7, c8 = st.columns(2)
                cost = c7.number_input("Cost (R)", min_value=0.0, value=0.0)
                workshop = c8.text_input("Workshop")
                notes = st.text_area("Notes")

                if st.form_submit_button("Save Service Event"):
                    payload = {
                        "service_date": str(service_date), "registration": registration, "fleet_no": fleet_no,
                        "service_type": service_type, "odo_at_service": odo_at_service,
                        "next_service_km": next_service_km, "cost": cost, "workshop": workshop, "notes": notes,
                    }
                    payload = tenant_payload(payload, is_master, tenant_filter, profile)
                    try:
                        client.table("maintenance_log").insert(payload).execute()
                        if service_type == "Unscheduled" and not vehicles_df.empty:
                            veh_row = vehicles_df[vehicles_df['registration'] == registration]
                            if not veh_row.empty:
                                new_score = max(0, (veh_row.iloc[0].get('fleet_health_score', 100) or 100) - 5)
                                client.table("vehicles").update({"fleet_health_score": new_score,
                                                                  "next_service_km": next_service_km}).eq(
                                    "id", veh_row.iloc[0]['id']).execute()
                        st.success("Service event logged.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save: {e}")

        maint_df = fetch_df(client, "maintenance_log", tenant_filter)
        if not maint_df.empty:
            st.dataframe(maint_df, use_container_width=True)
        else:
            st.info("No maintenance events logged yet.")

    # -----------------------------------------------------
    # 8. FINANCIAL FORECAST
    # -----------------------------------------------------
    elif app_mode == "💰 Financial Forecast":
        st.title("💰 FINANCIAL FORECAST")
        st.caption("Predictive 30-day cash-flow planner — auto-calculated from Vehicle Register + Compliance.")

        today = date.today()
        forecast_end = today + pd.Timedelta(days=30)
        st.subheader(f"Forecast Period: {today.strftime('%d %b')} — {forecast_end.strftime('%d %b %Y')}")

        rows = []
        total_spend = 0
        urgent_count = 0
        vehicles_impacted = set()

        if not vehicles_df.empty:
            for _, v in vehicles_df.iterrows():
                next_service = v.get('next_service_km')
                avg_daily = v.get('avg_daily_km') or 0
                current_odo = v.get('current_odometer') or 0
                if next_service and avg_daily:
                    km_remaining = next_service - current_odo
                    days_away = int(km_remaining / avg_daily) if avg_daily else None
                    if days_away is not None and days_away <= 30:
                        priority = "URGENT" if days_away <= 7 else "PLAN"
                        rows.append({
                            "Vehicle": v.get('registration'), "Event": "Service Due",
                            "Days Away": days_away, "Priority": priority, "Source": "Vehicle Register",
                        })
                        if days_away <= 7:
                            urgent_count += 1
                        vehicles_impacted.add(v.get('registration'))
                if v.get('annual_license_cost'):
                    total_spend += (v.get('annual_license_cost') or 0) / 12

        if not drivers_df.empty:
            for _, d in drivers_df.iterrows():
                for field, label in [("license_expiry", "License Renewal"), ("prdp_expiry", "PrDP Renewal")]:
                    _, days = compliance_status(d.get(field))
                    if days is not None and 0 <= days <= 30:
                        priority = "URGENT" if days <= 7 else "PLAN"
                        rows.append({
                            "Vehicle": "-", "Driver": d.get("driver_name"), "Event": label,
                            "Days Away": days, "Priority": priority, "Source": "Compliance",
                        })
                        if days <= 7:
                            urgent_count += 1

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Forecast Spend (30d)", f"R{total_spend:,.2f}")
        c2.metric("Urgent Items (≤7 days)", urgent_count)
        c3.metric("Vehicles Impacted", len(vehicles_impacted))
        c4.metric("Events in Next 30 Days", len(rows))

        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.success("No upcoming service or compliance events in the next 30 days.")

    # -----------------------------------------------------
    # 9. JOB PROFITABILITY ESTIMATOR
    # -----------------------------------------------------
    elif app_mode == "🧮 Job Profitability Estimator":
        st.title("🧮 JOB PROFITABILITY ESTIMATOR")
        st.markdown("Enter the job details below — profitability calculates **before** you accept the trip.")

        c1, c2 = st.columns(2)
        distance = c1.number_input("Estimated Distance (km, one-way)", min_value=1.0, value=500.0)
        return_trip = c2.selectbox("Return Trip?", ["YES", "NO"])

        c3, c4 = st.columns(2)
        revenue = c3.number_input("Revenue / Quote (R)", min_value=0.0, value=15000.0)
        fuel_price = c4.number_input("Fuel Cost per Litre (R)", min_value=0.0, value=25.31)

        c5, c6 = st.columns(2)
        km_per_liter = c5.number_input("Vehicle KM/L (Expected)", min_value=0.1, value=2.0)
        driver_cost = c6.number_input("Driver Cost per Trip (R)", min_value=0.0, value=1500.0)

        c7, c8 = st.columns(2)
        toll_costs = c7.number_input("Toll Costs (R)", min_value=0.0, value=50.0)
        other_fixed = c8.number_input("Other Fixed Costs (R)", min_value=0.0, value=0.0)

        c9, c10, c11 = st.columns(3)
        maint_alloc_km = c9.number_input("Maintenance Alloc per KM (R)", min_value=0.0, value=0.45)
        insur_alloc_km = c10.number_input("Insurance Alloc per KM (R)", min_value=0.0, value=0.25)
        license_alloc_km = c11.number_input("License Alloc per KM (R)", min_value=0.0, value=0.022)

        multiplier = 2 if return_trip == "YES" else 1
        total_km = distance * multiplier
        fuel_used = total_km / km_per_liter
        fuel_cost = fuel_used * fuel_price
        maint_alloc = maint_alloc_km * total_km
        insur_alloc = insur_alloc_km * total_km
        license_alloc = license_alloc_km * total_km
        total_cost = fuel_cost + driver_cost + toll_costs + maint_alloc + insur_alloc + license_alloc + other_fixed
        net_profit = revenue - total_cost
        profit_margin = (net_profit / revenue * 100) if revenue else 0
        cost_per_km = total_cost / total_km if total_km else 0
        revenue_per_km = revenue / total_km if total_km else 0
        profit_per_km = net_profit / total_km if total_km else 0
        breakeven_rate = total_cost
        recommended_rate = total_cost * 1.15

        st.markdown("---")
        st.subheader("📊 Profitability Analysis")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Distance (km)", f"{total_km:,.0f}")
        c2.metric("Fuel Used (L)", f"{fuel_used:,.1f}")
        c3.metric("Fuel Cost (R)", f"{fuel_cost:,.2f}")

        c4, c5, c6 = st.columns(3)
        c4.metric("Total Cost (R)", f"{total_cost:,.2f}")
        c5.metric("Net Profit (R)", f"{net_profit:,.2f}")
        c6.metric("Profit Margin %", f"{profit_margin:.1f}%")

        c7, c8, c9 = st.columns(3)
        c7.metric("Cost per KM", f"R{cost_per_km:,.2f}")
        c8.metric("Revenue per KM", f"R{revenue_per_km:,.2f}")
        c9.metric("Profit per KM", f"R{profit_per_km:,.2f}")

        st.markdown("---")
        if profit_margin >= 15:
            st.success(f"✅ TAKE THE JOB — Strong margin {profit_margin:.1f}%")
        elif profit_margin >= 5:
            st.warning(f"⚠️ MARGINAL — {profit_margin:.1f}% margin, proceed with caution")
        else:
            st.error(f"❌ DO NOT TAKE — Margin too low ({profit_margin:.1f}%)")

        st.caption(f"Break-even rate: R{breakeven_rate:,.2f} | Recommended rate (15% margin): R{recommended_rate:,.2f}")

    # -----------------------------------------------------
    # 10. GPS TRACKER LOG
    # -----------------------------------------------------
    elif app_mode == "🛰️ GPS Tracker Log":
        st.title("🛰️ GPS TRACKER LOG")
        st.caption("Manual entry for now. Live tracker sync (Traccar/Wialon/Cartrack) needs a separate hardware + API integration — ask if you'd like that built as a next step.")

        with st.expander("➕ Log a GPS trip record"):
            with st.form("new_gps_log"):
                c1, c2, c3 = st.columns(3)
                log_date = c1.date_input("Date")
                registration = c2.text_input("Registration")
                fleet_no = c3.text_input("Fleet No")
                c4, c5 = st.columns(2)
                driver_name = c4.text_input("Driver Name")
                location = c5.text_input("Location (Lat, Long)")
                c6, c7 = st.columns(2)
                ignition_on = c6.time_input("Ignition ON Time")
                ignition_off = c7.time_input("Ignition OFF Time")
                c8, c9 = st.columns(2)
                odo_start = c8.number_input("Odo Start (km)", min_value=0.0, value=0.0)
                odo_end = c9.number_input("Odo End (km)", min_value=0.0, value=0.0)
                c10, c11, c12 = st.columns(3)
                idle_time_min = c10.number_input("Idle Time (min)", min_value=0.0, value=0.0)
                fuel_level_start = c11.number_input("Fuel Level Start (%)", min_value=0.0, max_value=100.0, value=100.0)
                fuel_level_end = c12.number_input("Fuel Level End (%)", min_value=0.0, max_value=100.0, value=0.0)
                trip_log_distance = st.number_input("Trip Log Distance (km, for variance check)", min_value=0.0, value=0.0)

                if st.form_submit_button("Save GPS Record"):
                    gps_distance = odo_end - odo_start
                    payload = {
                        "log_date": str(log_date), "registration": registration, "fleet_no": fleet_no,
                        "driver_name": driver_name, "ignition_on": str(ignition_on), "ignition_off": str(ignition_off),
                        "odo_start": odo_start, "odo_end": odo_end, "idle_time_min": idle_time_min,
                        "fuel_level_start": fuel_level_start, "fuel_level_end": fuel_level_end,
                        "location": location, "trip_log_distance": trip_log_distance,
                    }
                    payload = tenant_payload(payload, is_master, tenant_filter, profile)
                    try:
                        client.table("gps_tracker_log").insert(payload).execute()
                        if trip_log_distance:
                            variance = (gps_distance - trip_log_distance) / trip_log_distance * 100
                            if abs(variance) >= 10:
                                st.warning(f"🚩 MISMATCH — GPS distance vs trip log distance varies by {variance:.1f}%")
                        st.success(f"GPS record saved. Distance: {gps_distance:.0f} km")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save: {e}")

        gps_df = fetch_df(client, "gps_tracker_log", tenant_filter)
        if not gps_df.empty:
            gps_df['gps_distance_km'] = gps_df['odo_end'].fillna(0) - gps_df['odo_start'].fillna(0)
            gps_df['variance_pct'] = np.where(gps_df['trip_log_distance'] > 0,
                                               ((gps_df['gps_distance_km'] - gps_df['trip_log_distance']) /
                                                gps_df['trip_log_distance'] * 100).round(1), 0)
            gps_df['flag'] = np.where(gps_df['variance_pct'].abs() >= 10, "🚩 MISMATCH", "OK")
            st.dataframe(gps_df, use_container_width=True)
        else:
            st.info("No GPS tracker records yet.")

    # -----------------------------------------------------
    # 11. MASTER ADMIN
    # -----------------------------------------------------
    elif app_mode == "👑 Master Admin: Manage Tenants & Users":
        st.title("👑 Master Admin Console")
        st.markdown("Manage every tenant company and user on the platform.")

        st.subheader("All Tenants")
        tenants_df = fetch_df(client, "tenants")
        st.dataframe(tenants_df, use_container_width=True)

        st.subheader("All Users / Profiles")
        profiles_df = fetch_df(client, "profiles")
        st.dataframe(profiles_df, use_container_width=True)

        st.subheader("Promote / Change a User's Role")
        if not profiles_df.empty:
            with st.form("change_role"):
                user_id = st.selectbox("User ID", profiles_df["id"].tolist())
                new_role = st.selectbox("New Role", ["master_admin", "tenant_admin", "driver", "viewer"])
                if st.form_submit_button("Update Role"):
                    try:
                        client.table("profiles").update({"role": new_role}).eq("id", user_id).execute()
                        st.success("Role updated.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not update role: {e}")


# =========================================================
# ENTRYPOINT
# =========================================================
if "session" not in st.session_state:
    show_login()
else:
    show_app()
