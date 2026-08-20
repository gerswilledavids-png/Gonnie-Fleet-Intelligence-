import streamlit as st
import pandas as pd
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
    """Return a Supabase client with the current user's session attached,
    so every query is subject to Row Level Security as that user."""
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
    st.title("🚚 Gonnie Fleet Intelligence")
    st.caption("Multi-tenant fleet operations platform")

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
                    st.success("Account created! Check your email to confirm (if confirmation is enabled), then log in.")
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

    # Master admin gets a tenant switcher; everyone else is auto-scoped by RLS
    tenant_filter = None
    if is_master:
        tenants_res = client.table("tenants").select("id, name").order("name").execute()
        tenant_options = {"🌐 All Tenants (Master View)": None}
        tenant_options.update({t["name"]: t["id"] for t in tenants_res.data})
        chosen = st.sidebar.selectbox("Viewing Tenant", list(tenant_options.keys()))
        tenant_filter = tenant_options[chosen]
        st.sidebar.caption("As master admin, you can view any tenant's data or all of them combined.")

    app_mode = st.sidebar.selectbox("Choose Navigation", [
        "📊 Executive Dashboard",
        "🗺️ Trip & GPS Logs",
        "⛽ Fuel & Cost Analysis",
        "💰 Financial Forecast",
        "🛡️ Compliance & Maintenance",
        "🧮 Job Estimator",
    ] + (["👑 Master Admin: Manage Tenants & Users"] if is_master else []))

    # -----------------------------------------------------
    # 1. EXECUTIVE DASHBOARD
    # -----------------------------------------------------
    if app_mode == "📊 Executive Dashboard":
        st.title("📊 Fleet Executive Dashboard")
        st.markdown("Real-time operational overview for Diesel on Wheels (D.O.W).")

        trips_df = fetch_df(client, "trips", tenant_filter)

        if not trips_df.empty:
            total_trips = len(trips_df)
            total_distance = trips_df['distance_km'].sum() if 'distance_km' in trips_df.columns else 0
            total_revenue = trips_df['revenue'].sum() if 'revenue' in trips_df.columns else 0
            total_profit = trips_df['net_profit'].sum() if 'net_profit' in trips_df.columns else 0

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Trips Logged", f"{total_trips}")
            col2.metric("Total Distance (KM)", f"{total_distance:,.1f} km")
            col3.metric("Total Revenue", f"R {total_revenue:,.2f}")
            col4.metric("Net Profit", f"R {total_profit:,.2f}")

            st.markdown("---")

            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("Top Drivers by Distance")
                if 'driver_name' in trips_df.columns and 'distance_km' in trips_df.columns:
                    driver_dist = trips_df.groupby('driver_name')['distance_km'].sum().reset_index()
                    st.bar_chart(driver_dist.set_index('driver_name'))

            with col_b:
                st.subheader("Vehicle Performance (Net Profit)")
                if 'registration' in trips_df.columns and 'net_profit' in trips_df.columns:
                    veh_profit = trips_df.groupby('registration')['net_profit'].sum().reset_index()
                    st.bar_chart(veh_profit.set_index('registration'))
        else:
            st.info("No trip data yet. Add trips from the 'Trip & GPS Logs' page.")

    # -----------------------------------------------------
    # 2. TRIP & GPS LOGS
    # -----------------------------------------------------
    elif app_mode == "🗺️ Trip & GPS Logs":
        st.title("🗺️ Trip & GPS Tracking Logs")
        st.markdown("Detailed breakdown of vehicle routes, odometer readings, and telemetry.")

        with st.expander("➕ Log a new trip"):
            with st.form("new_trip"):
                c1, c2, c3 = st.columns(3)
                trip_id = c1.text_input("Trip ID")
                driver_name = c2.text_input("Driver Name")
                registration = c3.text_input("Vehicle Registration")
                c4, c5 = st.columns(2)
                origin = c4.text_input("Origin")
                destination = c5.text_input("Destination")
                c6, c7, c8 = st.columns(3)
                distance_km = c6.number_input("Distance (KM)", min_value=0.0, value=0.0)
                revenue = c7.number_input("Revenue (R)", min_value=0.0, value=0.0)
                net_profit = c8.number_input("Net Profit (R)", value=0.0)
                trip_date = st.date_input("Trip Date")
                if st.form_submit_button("Save Trip"):
                    payload = {
                        "trip_id": trip_id, "driver_name": driver_name, "registration": registration,
                        "origin": origin, "destination": destination, "distance_km": distance_km,
                        "revenue": revenue, "net_profit": net_profit, "trip_date": str(trip_date),
                    }
                    # Non-master users' tenant_id is auto-filled by RLS-safe default;
                    # we still set it explicitly for master admin writing to a chosen tenant.
                    if is_master and tenant_filter:
                        payload["tenant_id"] = tenant_filter
                    elif not is_master:
                        payload["tenant_id"] = profile["tenant_id"]
                    try:
                        client.table("trips").insert(payload).execute()
                        st.success("Trip saved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save trip: {e}")

        trips_df = fetch_df(client, "trips", tenant_filter)
        if not trips_df.empty:
            search_reg = st.text_input("Filter by Registration or Driver", "")
            if search_reg:
                filtered_trips = trips_df[
                    trips_df['registration'].str.contains(search_reg, case=False, na=False) |
                    trips_df['driver_name'].str.contains(search_reg, case=False, na=False)
                ]
            else:
                filtered_trips = trips_df
            st.dataframe(filtered_trips, use_container_width=True)
        else:
            st.info("No trips logged yet.")

    # -----------------------------------------------------
    # 3. FUEL & COST ANALYSIS
    # -----------------------------------------------------
    elif app_mode == "⛽ Fuel & Cost Analysis":
        st.title("⛽ Fuel Consumption & Efficiency Analysis")

        with st.expander("➕ Log fuel data"):
            with st.form("new_fuel"):
                c1, c2 = st.columns(2)
                month = c1.text_input("Month (e.g. 2026-08)")
                registration = c2.text_input("Vehicle Registration")
                c3, c4, c5 = st.columns(3)
                liters = c3.number_input("Liters", min_value=0.0, value=0.0)
                total_cost = c4.number_input("Total Cost (R)", min_value=0.0, value=0.0)
                km_per_liter = c5.number_input("KM per Liter", min_value=0.0, value=0.0)
                if st.form_submit_button("Save Fuel Record"):
                    payload = {"month": month, "registration": registration, "liters": liters,
                               "total_cost": total_cost, "km_per_liter": km_per_liter}
                    if is_master and tenant_filter:
                        payload["tenant_id"] = tenant_filter
                    elif not is_master:
                        payload["tenant_id"] = profile["tenant_id"]
                    try:
                        client.table("fuel_analysis").insert(payload).execute()
                        st.success("Fuel record saved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save record: {e}")

        fuel_df = fetch_df(client, "fuel_analysis", tenant_filter)
        if not fuel_df.empty:
            st.dataframe(fuel_df, use_container_width=True)
            st.subheader("Monthly Fuel Cost Trend")
            if 'month' in fuel_df.columns and 'total_cost' in fuel_df.columns:
                st.line_chart(fuel_df.groupby('month')['total_cost'].sum())
        else:
            st.info("No fuel data yet.")

    # -----------------------------------------------------
    # 4. FINANCIAL FORECAST
    # -----------------------------------------------------
    elif app_mode == "💰 Financial Forecast":
        st.title("💰 Financial Forecast & Maintenance Schedule")

        with st.expander("➕ Add forecast line"):
            with st.form("new_financial"):
                c1, c2 = st.columns(2)
                period = c1.text_input("Period (e.g. 2026-Q3)")
                category = c2.text_input("Category")
                c3, c4 = st.columns(2)
                projected_amount = c3.number_input("Projected Amount (R)", value=0.0)
                actual_amount = c4.number_input("Actual Amount (R)", value=0.0)
                notes = st.text_area("Notes")
                if st.form_submit_button("Save"):
                    payload = {"period": period, "category": category, "projected_amount": projected_amount,
                               "actual_amount": actual_amount, "notes": notes}
                    if is_master and tenant_filter:
                        payload["tenant_id"] = tenant_filter
                    elif not is_master:
                        payload["tenant_id"] = profile["tenant_id"]
                    try:
                        client.table("financial_forecast").insert(payload).execute()
                        st.success("Saved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save: {e}")

        financial_df = fetch_df(client, "financial_forecast", tenant_filter)
        if not financial_df.empty:
            st.dataframe(financial_df, use_container_width=True)
        else:
            st.info("No financial forecast data yet.")

    # -----------------------------------------------------
    # 5. COMPLIANCE & MAINTENANCE
    # -----------------------------------------------------
    elif app_mode == "🛡️ Compliance & Maintenance":
        st.title("🛡️ Fleet Compliance & Permits")

        with st.expander("➕ Add compliance record"):
            with st.form("new_compliance"):
                c1, c2 = st.columns(2)
                registration = c1.text_input("Vehicle Registration")
                document_type = c2.text_input("Document Type (e.g. Roadworthy, License Disc)")
                c3, c4 = st.columns(2)
                issue_date = c3.date_input("Issue Date")
                expiry_date = c4.date_input("Expiry Date")
                status = st.selectbox("Status", ["valid", "expiring_soon", "expired"])
                notes = st.text_area("Notes")
                if st.form_submit_button("Save"):
                    payload = {"registration": registration, "document_type": document_type,
                               "issue_date": str(issue_date), "expiry_date": str(expiry_date),
                               "status": status, "notes": notes}
                    if is_master and tenant_filter:
                        payload["tenant_id"] = tenant_filter
                    elif not is_master:
                        payload["tenant_id"] = profile["tenant_id"]
                    try:
                        client.table("compliance").insert(payload).execute()
                        st.success("Saved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save: {e}")

        compliance_df = fetch_df(client, "compliance", tenant_filter)
        if not compliance_df.empty:
            st.dataframe(compliance_df, use_container_width=True)
        else:
            st.info("No compliance records yet.")

    # -----------------------------------------------------
    # 6. JOB ESTIMATOR
    # -----------------------------------------------------
    elif app_mode == "🧮 Job Estimator":
        st.title("🧮 Instant Job Quoting Calculator")
        st.markdown("Calculate estimated transport costs and margins for new prospective jobs.")

        distance = st.number_input("Estimated Distance (one-way km)", min_value=1.0, value=500.0)
        return_trip = st.selectbox("Return Trip?", ["YES", "NO"])
        fuel_price = st.number_input("Current Fuel Price per Liter (R)", value=25.31)
        km_per_liter = st.number_input("Expected Vehicle Efficiency (KM/L)", value=2.0)
        cargo_weight = st.number_input("Cargo Weight (KG)", value=30000.0)

        multiplier = 2 if return_trip == "YES" else 1
        total_km = distance * multiplier
        estimated_fuel_used = total_km / km_per_liter
        estimated_fuel_cost = estimated_fuel_used * fuel_price

        st.markdown("---")
        st.subheader("Job Financial Estimate")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Route Distance", f"{total_km:,.1f} km")
        col2.metric("Estimated Fuel Needed", f"{estimated_fuel_used:,.1f} L")
        col3.metric("Estimated Fuel Cost", f"R {estimated_fuel_cost:,.2f}")

    # -----------------------------------------------------
    # 7. MASTER ADMIN: MANAGE TENANTS & USERS
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
