import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import date, datetime
from supabase import create_client, Client

st.set_page_config(
    page_title="Gonnie Fleet Intelligence D.O.W",
    page_icon="🚚",
    layout="wide",
)

SUPABASE_URL = "https://sruqcdkjmhrgrgzzvcot.supabase.co"
SUPABASE_CLIENT_KEY = "sb_publishable_SVw4CNRyLGMZjTxB_3ewhg_9CnV1Osy"

APP_BASE_URL = "https://8b6gr3mtlfbcjfc6kzuuds.streamlit.app"

CHECKOUT_FUNCTION_URL = (
    f"{SUPABASE_URL}/functions/v1/create-yoco-checkout"
)

PLAN_LABELS = {
    "starter": "Starter — R350/mo",
    "professional": "Professional — R1,500/mo",
    "enterprise": "Enterprise — custom pricing",
}

st.markdown("""
<style>
.main {
    background-color:#f8f9fa;
}

div[data-testid="stMetric"] {
    border-radius:10px;
    padding:8px;
}
</style>
""", unsafe_allow_html=True)


def numeric_series(df, column):
    """Return a safe numeric Series for calculations."""
    if column not in df.columns:
        return pd.Series(0.0, index=df.index)

    return pd.to_numeric(
        df[column],
        errors="coerce"
    ).fillna(0.0)


def numeric_value(value, default=0.0):
    """Convert an individual value safely to float."""
    try:
        if value is None or pd.isna(value):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


@st.cache_resource
def get_base_client() -> Client:
    return create_client(
        SUPABASE_URL,
        SUPABASE_CLIENT_KEY
    )


def get_authed_client() -> Client:
    client = create_client(
        SUPABASE_URL,
        SUPABASE_CLIENT_KEY
    )

    session = st.session_state.get("session")

    if session:
        try:
            client.auth.set_session(
                session.access_token,
                session.refresh_token
            )
        except Exception:
            # Stale/invalid refresh token (expired, revoked, or the
            # project's auth keys changed). This used to propagate
            # uncaught and crash the entire app on every rerun.
            for key in ("session", "user"):
                st.session_state.pop(key, None)
            st.error("Your session expired. Please log in again.")
            st.rerun()

    return client


def logout():
    try:
        get_authed_client().auth.sign_out()
    except Exception:
        pass

    for key in ("session", "user"):
        st.session_state.pop(key, None)

    st.rerun()


def show_login():
    st.title("🚚 Gonnie Fleet Intelligence D.O.W")
    st.caption(
        "Diesel on Wheels — Multi-Fleet Intelligence Platform"
    )

    tab_login, tab_signup = st.tabs(
        ["Log In", "Sign Up"]
    )

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input(
                "Password",
                type="password"
            )

            if st.form_submit_button(
                "Log In",
                width="stretch"
            ):
                try:
                    res = get_base_client().auth.sign_in_with_password(
                        {
                            "email": email.strip(),
                            "password": password,
                        }
                    )

                    if not res.session:
                        raise RuntimeError(
                            "Authentication succeeded but no session was returned."
                        )

                    st.session_state["session"] = res.session
                    st.session_state["user"] = res.user

                    st.rerun()

                except Exception as e:
                    st.error(f"Login failed: {e}")

    with tab_signup:
        st.markdown(
            "New company? Create your account — "
            "you will receive an isolated workspace."
        )

        with st.form("signup_form"):
            company_name = st.text_input(
                "Company Name"
            )

            full_name = st.text_input(
                "Your Full Name"
            )

            email = st.text_input(
                "Email",
                key="signup_email"
            )

            password = st.text_input(
                "Password",
                type="password",
                key="signup_password"
            )

            if st.form_submit_button(
                "Create Account",
                width="stretch"
            ):
                if (
                    not company_name.strip()
                    or not full_name.strip()
                ):
                    st.error(
                        "Company Name and Full Name are required."
                    )

                elif not email.strip():
                    st.error("Email is required.")

                elif len(password) < 6:
                    st.error(
                        "Password must contain at least 6 characters."
                    )

                else:
                    try:
                        get_base_client().auth.sign_up(
                            {
                                "email": email.strip(),
                                "password": password,
                                "options": {
                                    "data": {
                                        "company_name":
                                            company_name.strip(),
                                        "full_name":
                                            full_name.strip(),
                                    }
                                },
                            }
                        )

                        st.success(
                            "Account created. "
                            "Check your email to confirm, then log in."
                        )

                    except Exception as e:
                        st.error(
                            f"Sign up failed: {e}"
                        )


def get_profile(
    client: Client,
    user_id: str
):
    try:
        res = (
            client.table("profiles")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        )

        return res.data

    except Exception:
        return None


def fetch_df(
    client: Client,
    table_name: str,
    tenant_filter=None
) -> pd.DataFrame:

    q = client.table(table_name).select("*")

    if tenant_filter:
        q = q.eq(
            "tenant_id",
            tenant_filter
        )

    try:
        res = q.execute()

        if not res.data:
            return pd.DataFrame()

        return pd.DataFrame(res.data)

    except Exception:
        return pd.DataFrame()


def resolve_tenant_id(
    client,
    profile,
    user_id
):
    existing = profile.get("tenant_id")

    if existing:
        return existing

    tenants = (
        client.table("tenants")
        .select("id,name")
        .order("name")
        .execute()
        .data
        or []
    )

    if len(tenants) == 1:
        tenant_id = tenants[0]["id"]

        (
            client.table("profiles")
            .update(
                {"tenant_id": tenant_id}
            )
            .eq("id", user_id)
            .execute()
        )

        profile["tenant_id"] = tenant_id

        return tenant_id

    if not tenants:
        raise RuntimeError(
            "No workspace exists for this account."
        )

    raise RuntimeError(
        "Your account has no workspace assigned. "
        "A Master Admin must assign one."
    )


def tenant_payload(
    payload,
    is_master,
    tenant_filter,
    profile
):
    if is_master:
        if not tenant_filter:
            raise RuntimeError(
                "Select a specific tenant/workspace "
                "before creating a record."
            )

        payload["tenant_id"] = tenant_filter

    else:
        tenant_id = profile.get("tenant_id")

        if not tenant_id:
            raise RuntimeError(
                "No tenant is assigned to this user."
            )

        payload["tenant_id"] = tenant_id

    return payload


def compute_trip_fields(
    row,
    vehicle_row=None
):
    distance = numeric_value(
        row.get("distance_km")
    )

    fuel = numeric_value(
        row.get("fuel_used_liters")
    )

    price = numeric_value(
        row.get("cost_per_liter")
    )

    revenue = numeric_value(
        row.get("revenue")
    )

    fixed = numeric_value(
        row.get("fixed_cost")
    )

    variable_raw = row.get(
        "variable_cost"
    )

    if variable_raw is None or (
        isinstance(variable_raw, float)
        and pd.isna(variable_raw)
    ):
        variable = fuel * price
    else:
        variable = numeric_value(
            variable_raw
        )

    km_l = (
        round(distance / fuel, 2)
        if fuel > 0
        else 0
    )

    fuel_cost = round(
        fuel * price,
        2
    )

    expected = 2.0

    if vehicle_row is not None:
        expected = numeric_value(
            vehicle_row.get(
                "expected_km_l",
                2.0
            ),
            2.0
        )

        if expected <= 0:
            expected = 2.0

    variance = (
        round(
            ((km_l - expected) / expected)
            * 100,
            1
        )
        if expected > 0
        else 0
    )

    theft = variance <= -20

    profit = round(
        revenue - fixed - variable,
        2
    )

    margin = (
        round(
            (profit / revenue) * 100,
            1
        )
        if revenue > 0
        else 0
    )

    cost_km = (
        round(
            (fixed + variable) / distance,
            2
        )
        if distance > 0
        else 0
    )

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


def write_audit(
    client,
    user,
    profile,
    action,
    table_name=None,
    record_id=None,
    tenant_id=None,
    old_data=None,
    new_data=None
):
    try:
        payload = {
            "actor_user_id":
                str(user.id) if user else None,

            "actor_role":
                profile.get("role")
                if profile
                else None,

            "tenant_id":
                tenant_id,

            "table_name":
                table_name,

            "record_id":
                str(record_id)
                if record_id
                else None,

            "action":
                action,

            "old_data":
                old_data,

            "new_data":
                new_data,
        }

        (
            client.table("audit_logs")
            .insert(payload)
            .execute()
        )

    except Exception:
        pass


def update_scoped_record(
    client,
    user,
    profile,
    table_name,
    record_id,
    fields,
    tenant_id=None
):
    """Safely update a record that belongs to a tenant-scoped table.

    Mirrors delete_scoped_record's safety checks: confirms the record
    exists (and is visible under RLS / the given tenant scope), applies
    the update scoped to that tenant, verifies the change stuck, and
    writes an audit log entry with before/after data.
    """
    if not record_id:
        raise ValueError(
            "A record ID is required."
        )

    is_master = (
        profile.get("role")
        == "master_admin"
    )

    if (
        not is_master
        and not profile.get("tenant_id")
    ):
        raise PermissionError(
            "No tenant is assigned to this user."
        )

    effective_tenant = (
        tenant_id
        if is_master
        else profile.get("tenant_id")
    )

    lookup = (
        client.table(table_name)
        .select("*")
        .eq("id", record_id)
        .limit(1)
    )

    if effective_tenant:
        lookup = lookup.eq(
            "tenant_id",
            effective_tenant
        )

    rows = lookup.execute().data or []

    if not rows:
        raise RuntimeError(
            "The record no longer exists, "
            "belongs to another tenant, "
            "or RLS blocked access."
        )

    old = rows[0]

    # Never let an edit form silently move a record to another tenant.
    safe_fields = {
        k: v
        for k, v in fields.items()
        if k not in ("id", "tenant_id")
    }

    update_query = (
        client.table(table_name)
        .update(safe_fields)
        .eq("id", record_id)
    )

    if effective_tenant:
        update_query = update_query.eq(
            "tenant_id",
            effective_tenant
        )

    result = update_query.execute()

    updated_rows = result.data or []

    if not updated_rows:
        raise RuntimeError(
            "The record was not updated. "
            "RLS or database permissions may have blocked the operation."
        )

    new = updated_rows[0]

    write_audit(
        client,
        user,
        profile,
        "UPDATE",
        table_name,
        record_id,
        old.get("tenant_id")
        if isinstance(old, dict)
        else effective_tenant,
        old,
        new
    )

    return new


def delete_scoped_record(
    client,
    user,
    profile,
    table_name,
    record_id,
    tenant_id=None
):
    if not record_id:
        raise ValueError(
            "A record ID is required."
        )

    is_master = (
        profile.get("role")
        == "master_admin"
    )

    if (
        not is_master
        and not profile.get("tenant_id")
    ):
        raise PermissionError(
            "No tenant is assigned to this user."
        )

    effective_tenant = (
        tenant_id
        if is_master
        else profile.get("tenant_id")
    )

    lookup = (
        client.table(table_name)
        .select("*")
        .eq("id", record_id)
        .limit(1)
    )

    if effective_tenant:
        lookup = lookup.eq(
            "tenant_id",
            effective_tenant
        )

    rows = lookup.execute().data or []

    if not rows:
        raise RuntimeError(
            "The record no longer exists, "
            "belongs to another tenant, "
            "or RLS blocked access."
        )

    old = rows[0]

    delete_query = (
        client.table(table_name)
        .delete()
        .eq("id", record_id)
    )

    if effective_tenant:
        delete_query = delete_query.eq(
            "tenant_id",
            effective_tenant
        )

    result = delete_query.execute()

    deleted_rows = result.data or []

    verify = (
        client.table(table_name)
        .select("id")
        .eq("id", record_id)
        .limit(1)
        .execute()
        .data
        or []
    )

    if verify:
        raise RuntimeError(
            "The record was not deleted. "
            "RLS or database permissions may have blocked the operation."
        )

    write_audit(
        client,
        user,
        profile,
        "DELETE",
        table_name,
        record_id,
        old.get("tenant_id")
        if isinstance(old, dict)
        else effective_tenant,
        old,
        None
    )

    return old


def delete_tenant_permanently(
    client,
    user,
    profile,
    tenant_id,
    tenant_name
):
    if profile.get("role") != "master_admin":
        raise PermissionError(
            "Master Admin access is required."
        )

    if not tenant_id:
        raise ValueError(
            "A tenant ID is required."
        )

    tenant_rows = (
        client.table("tenants")
        .select("id,name")
        .eq("id", tenant_id)
        .limit(1)
        .execute()
        .data
        or []
    )

    if not tenant_rows:
        raise RuntimeError(
            "Tenant no longer exists."
        )

    live_tenant = tenant_rows[0]

    if str(
        live_tenant.get("name", "")
    ) != str(tenant_name):
        raise RuntimeError(
            "Tenant changed since this deletion screen "
            "was loaded. Refresh and try again."
        )

    billing_rows = (
        client.table("billing_subscriptions")
        .select("*")
        .eq("tenant_id", tenant_id)
        .execute()
        .data
        or []
    )

    (
        client.table("billing_subscriptions")
        .delete()
        .eq("tenant_id", tenant_id)
        .execute()
    )

    try:
        result = (
            client.table("tenants")
            .delete()
            .eq("id", tenant_id)
            .execute()
        )

    except Exception:
        if billing_rows:
            (
                client.table("billing_subscriptions")
                .insert(billing_rows)
                .execute()
            )

        raise

    deleted = result.data or []

    if not deleted:
        if billing_rows:
            (
                client.table("billing_subscriptions")
                .insert(billing_rows)
                .execute()
            )

        raise RuntimeError(
            "Tenant was not deleted. "
            "Billing rows were restored. "
            "Check RLS/permissions and try again."
        )

    write_audit(
        client,
        user,
        profile,
        "MASTER_DELETE_TENANT",
        "tenants",
        tenant_id,
        tenant_id,
        live_tenant,
        None
    )

    return live_tenant


def compliance_status(expiry):
    if not expiry:
        return "⚪ UNKNOWN", None

    try:
        days = (
            pd.to_datetime(expiry).date()
            - date.today()
        ).days

    except Exception:
        return "⚪ UNKNOWN", None

    if days < 0:
        return "🔴 EXPIRED", days

    if days <= 7:
        return "🟠 URGENT", days

    if days <= 30:
        return "🟡 EXPIRING SOON", days

    return "🟢 COMPLIANT", days


def _masked_secret_status(value):
    if not value:
        return "NOT PRESENT"

    return "PRESENT (hidden)"


def check_supabase_health():
    started = time.perf_counter()

    url = (
        f"{SUPABASE_URL}/auth/v1/settings"
    )

    try:
        resp = requests.get(
            url,
            headers={
                "apikey":
                    SUPABASE_CLIENT_KEY
            },
            timeout=8,
        )

        latency_ms = round(
            (
                time.perf_counter()
                - started
            ) * 1000
        )

        return {
            "ok":
                200 <= resp.status_code < 300,

            "reachable":
                resp.status_code < 500,

            "status_code":
                resp.status_code,

            "latency_ms":
                latency_ms,

            "message":
                (
                    "Supabase Auth/API responding."
                    if 200 <= resp.status_code < 300
                    else
                    f"Supabase returned HTTP "
                    f"{resp.status_code}."
                ),
        }

    except Exception as exc:
        latency_ms = round(
            (
                time.perf_counter()
                - started
            ) * 1000
        )

        return {
            "ok": False,
            "reachable": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "message":
                f"Supabase API check failed: "
                f"{type(exc).__name__}",
        }


def check_yoco_endpoint_health():
    started = time.perf_counter()

    try:
        resp = requests.options(
            CHECKOUT_FUNCTION_URL,
            headers={
                "apikey":
                    SUPABASE_CLIENT_KEY
            },
            timeout=8,
        )

        latency_ms = round(
            (
                time.perf_counter()
                - started
            ) * 1000
        )

        reachable = (
            resp.status_code < 500
        )

        return {
            "ok":
                reachable,

            "reachable":
                reachable,

            "status_code":
                resp.status_code,

            "latency_ms":
                latency_ms,

            "message":
                (
                    "Yoco checkout Edge Function "
                    "is reachable. Secret is protected "
                    "in Supabase."
                    if reachable
                    else
                    f"Yoco Edge Function returned "
                    f"HTTP {resp.status_code}."
                ),
        }

    except Exception as exc:
        latency_ms = round(
            (
                time.perf_counter()
                - started
            ) * 1000
        )

        return {
            "ok": False,
            "reachable": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "message":
                f"Yoco Edge Function check failed: "
                f"{type(exc).__name__}",
        }


def check_deployment_health():
    started = time.perf_counter()

    try:
        resp = requests.get(
            APP_BASE_URL,
            timeout=10,
            allow_redirects=True,
        )

        latency_ms = round(
            (
                time.perf_counter()
                - started
            ) * 1000
        )

        return {
            "ok":
                200 <= resp.status_code < 400,

            "status_code":
                resp.status_code,

            "latency_ms":
                latency_ms,

            "message":
                (
                    "Public app URL is responding."
                    if resp.status_code < 400
                    else
                    f"Public app returned HTTP "
                    f"{resp.status_code}."
                ),
        }

    except Exception as exc:
        latency_ms = round(
            (
                time.perf_counter()
                - started
            ) * 1000
        )

        return {
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "message":
                f"Deployment health check failed: "
                f"{type(exc).__name__}",
        }


def get_yoco_secret_status(
    client: Client
) -> str:
    try:
        result = client.rpc(
            "get_yoco_secret_status_for_master_admin"
        ).execute()

        return str(
            result.data or "UNKNOWN"
        ).upper()

    except Exception:
        return "UNKNOWN"


def save_yoco_secret(
    client: Client,
    secret: str
) -> bool:

    value = (
        secret or ""
    ).strip()

    if not value:
        raise ValueError(
            "Enter the Yoco SECRET key."
        )

    if not value.startswith(
        ("sk_test_", "sk_live_")
    ):
        raise ValueError(
            "Use the Yoco SECRET key beginning "
            "with sk_test_ or sk_live_."
        )

    result = client.rpc(
        "set_yoco_secret_for_master_admin",
        {
            "p_secret": value
        }
    ).execute()

    return bool(result.data)


def show_system_configuration():
    st.title("⚙️ System Configuration")

    st.caption(
        "Master Admin only — live infrastructure diagnostics "
        "for Supabase, Yoco, the public deployment and "
        "the application API. No secret values are shown."
    )

    if st.button(
        "🔄 Run Live System Diagnostics",
        type="primary",
        width="stretch"
    ):
        st.session_state[
            "system_diag_nonce"
        ] = time.time()

    st.markdown("---")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Supabase URL",
        "Configured"
        if SUPABASE_URL
        else "Missing"
    )

    c2.metric(
        "Supabase Client Key",
        _masked_secret_status(
            SUPABASE_CLIENT_KEY
        )
    )

    c3.metric(
        "Yoco Function URL",
        "Configured"
        if CHECKOUT_FUNCTION_URL
        else "Missing"
    )

    c4.metric(
        "App Base URL",
        "Configured"
        if APP_BASE_URL
        else "Missing"
    )

    st.markdown(
        "### 🔐 Secret Protection"
    )

    st.info(
        "The Yoco secret key is intentionally NOT stored "
        "or displayed in this Streamlit application. "
        "It must remain inside the Supabase Edge Function "
        "secret store/Vault."
    )

    st.markdown(
        "### 🔐 Yoco Payment Secret"
    )

    st.info(
        "Paste the Yoco SECRET key here once. "
        "It is sent to a Master-Admin-only Supabase RPC "
        "and stored securely. The key is never displayed "
        "or written into app.py."
    )

    secret_status = get_yoco_secret_status(
        get_authed_client()
    )

    if secret_status == "PRESENT":
        st.success(
            "🟢 Yoco SECRET is installed "
            "in Supabase Vault."
        )

    elif secret_status == "MISSING":
        st.error(
            "🔴 Yoco SECRET is not installed yet."
        )

    else:
        st.warning(
            "🟠 Could not determine Yoco secret status."
        )

    with st.form(
        "master_yoco_secret_form"
    ):
        yoco_secret_input = st.text_input(
            "Yoco SECRET key",
            type="password",
            placeholder="sk_test_... or sk_live_...",
            help=(
                "Use the Yoco SECRET key, "
                "not the Yoco public key."
            ),
        )

        if st.form_submit_button(
            "🔒 Save Yoco SECRET to Supabase Vault",
            type="primary",
            width="stretch"
        ):
            try:
                if save_yoco_secret(
                    get_authed_client(),
                    yoco_secret_input
                ):
                    st.success(
                        "Yoco SECRET saved securely."
                    )

                    st.rerun()

            except Exception as exc:
                st.error(
                    f"Could not save Yoco SECRET: {exc}"
                )

    st.markdown(
        "### 🟢 Live Health Checks"
    )

    if not st.session_state.get(
        "system_diag_nonce"
    ):
        st.info(
            "Click '🔄 Run Live System Diagnostics' "
            "above to check Supabase, Yoco and deployment."
        )

    else:
        supabase = check_supabase_health()
        yoco = check_yoco_endpoint_health()
        deployment = check_deployment_health()

        def health_badge(result):
            if result.get("ok"):
                return "🟢 HEALTHY"

            if result.get("reachable"):
                return "🟠 REACHABLE / CHECK RESPONSE"

            return "🔴 DOWN / ERROR"

        h1, h2, h3 = st.columns(3)

        with h1:
            st.subheader("Supabase")

            st.metric(
                "Status",
                health_badge(supabase)
            )

            st.write(
                f"HTTP: "
                f"{supabase.get('status_code') or '—'}"
            )

            st.write(
                f"Latency: "
                f"{supabase.get('latency_ms', '—')} ms"
            )

            st.caption(
                supabase.get(
                    "message",
                    ""
                )
            )

        with h2:
            st.subheader("Yoco Checkout")

            st.metric(
                "Endpoint",
                health_badge(yoco)
            )

            st.write(
                f"HTTP: "
                f"{yoco.get('status_code') or '—'}"
            )

            st.write(
                f"Latency: "
                f"{yoco.get('latency_ms', '—')} ms"
            )

            st.caption(
                yoco.get(
                    "message",
                    ""
                )
            )

        with h3:
            st.subheader("Public Deployment")

            st.metric(
                "Status",
                health_badge(deployment)
            )

            st.write(
                f"HTTP: "
                f"{deployment.get('status_code') or '—'}"
            )

            st.write(
                f"Latency: "
                f"{deployment.get('latency_ms', '—')} ms"
            )

            st.caption(
                deployment.get(
                    "message",
                    ""
                )
            )

        st.markdown(
            "### 🧪 Application API"
        )

        api_checks = []

        started = time.perf_counter()

        try:
            get_authed_client() \
                .table("profiles") \
                .select("id") \
                .limit(1) \
                .execute()

            api_checks.append({
                "Service":
                    "Supabase Database API",

                "Status":
                    "🟢 OK",

                "HTTP":
                    "—",

                "Latency (ms)":
                    str(round(
                        (
                            time.perf_counter()
                            - started
                        ) * 1000
                    )),

                "Detail":
                    "Authenticated database query completed.",
            })

        except Exception as exc:
            api_checks.append({
                "Service":
                    "Supabase Database API",

                "Status":
                    "🔴 ERROR",

                "HTTP":
                    "—",

                "Latency (ms)":
                    str(round(
                        (
                            time.perf_counter()
                            - started
                        ) * 1000
                    )),

                "Detail":
                    f"Database probe failed: "
                    f"{type(exc).__name__}",
            })

        api_checks.append({
            "Service":
                "Supabase Publishable Key",

            "Status":
                "🟢 PRESENT"
                if SUPABASE_CLIENT_KEY
                else "🔴 MISSING",

            "HTTP":
                "—",

            "Latency (ms)":
                "—",

            "Detail":
                "Value hidden by design.",
        })

        st.dataframe(
            pd.DataFrame(api_checks),
            width="stretch",
            hide_index=True,
        )

    st.markdown(
        "### 📋 Current Runtime"
    )

    runtime = {
        "Application":
            "Gonnie Fleet Intelligence D.O.W",

        "Role":
            "Master Admin",

        "Python Runtime":
            ".".join(
                map(
                    str,
                    __import__(
                        "sys"
                    ).version_info[:3]
                )
            ),

        "Diagnostic Time":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "Supabase Project":
            SUPABASE_URL
            .split("//", 1)[-1]
            .split(".", 1)[0],

        "Yoco Secret":
            "HIDDEN — Supabase Edge Function secret store",
    }

    st.dataframe(
        pd.DataFrame([runtime]),
        width="stretch",
        hide_index=True,
    )


def master_update_profile(
    client,
    user,
    profile,
    user_id,
    fields
):
    old = (
        client.table("profiles")
        .select("*")
        .eq("id", user_id)
        .single()
        .execute()
        .data
    )

    result = (
        client.table("profiles")
        .update(fields)
        .eq("id", user_id)
        .execute()
    )

    new_rows = result.data or []

    write_audit(
        client,
        user,
        profile,
        "MASTER_UPDATE_PROFILE",
        "profiles",
        user_id,
        fields.get(
            "tenant_id",
            old.get("tenant_id")
            if old
            else None
        ),
        old,
        new_rows[0]
        if new_rows
        else fields
    )


def show_platform_control_centre(
    client,
    user,
    profile
):
    st.title(
        "👑 Gonnie Platform Control Centre"
    )

    st.caption(
        "Master Admin only — complete platform oversight, "
        "tenant management, user administration, "
        "subscriptions and audit history."
    )

    tenants_df = fetch_df(
        client,
        "tenants"
    )

    profiles_df = fetch_df(
        client,
        "profiles"
    )

    trips_df = fetch_df(
        client,
        "trips"
    )

    vehicles_df = fetch_df(
        client,
        "vehicles"
    )

    drivers_df = fetch_df(
        client,
        "drivers"
    )

    subs_df = fetch_df(
        client,
        "billing_subscriptions"
    )

    audit_df = fetch_df(
        client,
        "audit_logs"
    )

    active_subs = 0

    if (
        not subs_df.empty
        and "status" in subs_df.columns
    ):
        active_subs = int(
            (
                subs_df["status"]
                .astype(str)
                .str.lower()
                == "active"
            ).sum()
        )

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric(
        "🏢 Tenants",
        len(tenants_df)
    )

    c2.metric(
        "👤 Users",
        len(profiles_df)
    )

    c3.metric(
        "🚚 Vehicles",
        len(vehicles_df)
    )

    c4.metric(
        "🗺️ Trips",
        len(trips_df)
    )

    c5.metric(
        "💳 Active Subscriptions",
        active_subs
    )

    st.markdown("---")

    st.subheader(
        "🏢 Tenant Management"
    )

    if not tenants_df.empty:
        tenant_view = tenants_df.copy()

        if (
            not profiles_df.empty
            and "tenant_id"
            in profiles_df.columns
        ):
            counts = (
                profiles_df
                .groupby("tenant_id")
                .size()
                .rename("Users")
            )

            tenant_view = tenant_view.merge(
                counts,
                left_on="id",
                right_index=True,
                how="left"
            )

            tenant_view["Users"] = (
                pd.to_numeric(
                    tenant_view["Users"],
                    errors="coerce"
                )
                .fillna(0)
                .astype(int)
            )

        if (
            not trips_df.empty
            and "tenant_id"
            in trips_df.columns
        ):
            counts = (
                trips_df
                .groupby("tenant_id")
                .size()
                .rename("Trips")
            )

            tenant_view = tenant_view.merge(
                counts,
                left_on="id",
                right_index=True,
                how="left"
            )

            tenant_view["Trips"] = (
                pd.to_numeric(
                    tenant_view["Trips"],
                    errors="coerce"
                )
                .fillna(0)
                .astype(int)
            )

        st.dataframe(
            tenant_view,
            width="stretch"
        )

    with st.expander(
        "➕ Create a tenant/workspace"
    ):
        with st.form(
            "create_tenant"
        ):
            tenant_name = st.text_input(
                "Company / Workspace Name"
            )

            if st.form_submit_button(
                "Create Tenant"
            ):
                if not tenant_name.strip():
                    st.error(
                        "Tenant name is required."
                    )

                else:
                    try:
                        res = (
                            client.table("tenants")
                            .insert(
                                {
                                    "name":
                                        tenant_name.strip()
                                }
                            )
                            .execute()
                        )

                        created = (
                            res.data[0]
                            if res.data
                            else None
                        )

                        write_audit(
                            client,
                            user,
                            profile,
                            "MASTER_CREATE_TENANT",
                            "tenants",
                            created.get("id")
                            if created
                            else None,
                            created.get("id")
                            if created
                            else None,
                            None,
                            created
                        )

                        st.success(
                            "Tenant created."
                        )

                        st.rerun()

                    except Exception as e:
                        st.error(
                            f"Could not create tenant: {e}"
                        )

    st.markdown("---")

    st.subheader(
        "👤 User Administration"
    )

    if not profiles_df.empty:
        display_profiles = profiles_df.copy()

        if (
            not tenants_df.empty
            and "tenant_id"
            in display_profiles.columns
        ):
            tenant_names = (
                tenants_df
                .set_index("id")["name"]
                .to_dict()
            )

            display_profiles[
                "tenant_name"
            ] = (
                display_profiles[
                    "tenant_id"
                ].map(tenant_names)
            )

        st.dataframe(
            display_profiles,
            width="stretch"
        )

        user_options = {}

        for _, row in profiles_df.iterrows():
            uid = row.get("id")

            label = (
                f"{row.get('full_name') or 'Unnamed'} "
                f"• {row.get('role')} "
                f"• {uid}"
            )

            user_options[label] = uid

        if user_options:
            with st.expander(
                "🔐 Change User Role / Workspace"
            ):
                selected_label = st.selectbox(
                    "Select User",
                    list(
                        user_options.keys()
                    )
                )

                selected_id = (
                    user_options[
                        selected_label
                    ]
                )

                selected_matches = (
                    profiles_df[
                        profiles_df["id"]
                        .astype(str)
                        == str(selected_id)
                    ]
                )

                if selected_matches.empty:
                    st.error(
                        "Selected user could not be found."
                    )
                else:
                    selected_row = (
                        selected_matches.iloc[0]
                    )

                    role_options = [
                        "master_admin",
                        "tenant_admin",
                        "driver",
                        "viewer",
                    ]

                    current_role = (
                        selected_row.get("role")
                    )

                    new_role = st.selectbox(
                        "Role",
                        role_options,
                        index=(
                            role_options.index(
                                current_role
                            )
                            if current_role
                            in role_options
                            else 1
                        )
                    )

                    tenant_options = {
                        "— No tenant —":
                            None
                    }

                    for _, t in tenants_df.iterrows():
                        tenant_options[
                            str(t["name"])
                        ] = t["id"]

                    current_tenant = (
                        selected_row.get(
                            "tenant_id"
                        )
                    )

                    tenant_labels = list(
                        tenant_options.keys()
                    )

                    default_idx = 0

                    for i, label in enumerate(
                        tenant_labels
                    ):
                        if (
                            tenant_options[label]
                            == current_tenant
                        ):
                            default_idx = i
                            break

                    tenant_label = st.selectbox(
                        "Workspace",
                        tenant_labels,
                        index=default_idx
                    )

                    if st.button(
                        "💾 Save User Administration",
                        type="primary"
                    ):
                        try:
                            fields = {
                                "role":
                                    new_role,

                                "tenant_id":
                                    tenant_options[
                                        tenant_label
                                    ],
                            }

                            master_update_profile(
                                client,
                                user,
                                profile,
                                selected_id,
                                fields
                            )

                            st.success(
                                "User role/workspace updated."
                            )

                            st.rerun()

                        except Exception as e:
                            st.error(
                                f"Could not update user: {e}"
                            )

    st.markdown("---")

    st.subheader(
        "🔴 Permanently Delete Tenant"
    )

    st.warning(
        "This permanently removes the tenant workspace "
        "and its operational data. Billing records are "
        "removed first because that table is protected "
        "by a NO ACTION foreign key. Supabase Auth "
        "accounts are NOT deleted by this Streamlit client."
    )

    if not tenants_df.empty:
        delete_map = {
            str(r["name"]):
                r["id"]
            for _, r in tenants_df.iterrows()
        }

        delete_name = st.selectbox(
            "Tenant to permanently delete",
            list(delete_map.keys()),
            key="permanent_delete_tenant_name"
        )

        delete_id = delete_map[
            delete_name
        ]

        impact_tables = [
            "profiles",
            "trips",
            "vehicles",
            "drivers",
            "compliance",
            "fuel_analysis",
            "gps_tracker_log",
            "maintenance_log",
            "financial_forecast",
            "invite_codes",
            "billing_subscriptions",
        ]

        impact = {}

        for table in impact_tables:
            try:
                rows = (
                    client.table(table)
                    .select("id")
                    .eq(
                        "tenant_id",
                        delete_id
                    )
                    .execute()
                    .data
                    or []
                )

                impact[table] = len(rows)

            except Exception:
                impact[table] = "—"

        total_known = sum(
            value
            for value in impact.values()
            if isinstance(value, int)
        )

        st.metric(
            "Known records affected",
            total_known
        )

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Table": k,
                        "Records": v
                    }
                    for k, v in impact.items()
                ]
            ),
            width="stretch",
            hide_index=True
        )

        typed = st.text_input(
            "Type the exact tenant name to unlock permanent deletion",
            key="permanent_delete_tenant_typed"
        )

        confirm_1 = (
            typed.strip()
            == delete_name.strip()
        )

        confirm_2 = st.checkbox(
            "I understand this action is permanent and cannot be undone.",
            key="permanent_delete_tenant_confirm"
        )

        if st.button(
            "🔴 PERMANENTLY DELETE TENANT",
            type="primary",
            disabled=not (
                confirm_1
                and confirm_2
            ),
            key="permanent_delete_tenant_button"
        ):
            try:
                deleted_tenant = (
                    delete_tenant_permanently(
                        client,
                        user,
                        profile,
                        delete_id,
                        delete_name
                    )
                )

                st.success(
                    f"Tenant "
                    f"'{deleted_tenant.get('name', delete_name)}' "
                    f"and its workspace data were permanently deleted."
                )

                st.session_state.pop(
                    "permanent_delete_tenant_typed",
                    None
                )

                st.session_state.pop(
                    "permanent_delete_tenant_confirm",
                    None
                )

                st.rerun()

            except Exception as e:
                st.error(
                    f"Tenant deletion failed: {e}"
                )

    st.markdown("---")

    st.subheader(
        "🔎 Tenant Intelligence"
    )

    if not tenants_df.empty:
        tenant_map = {
            str(r["name"]):
                r["id"]
            for _, r in tenants_df.iterrows()
        }

        selected_tenant_name = st.selectbox(
            "Inspect Tenant",
            list(tenant_map.keys()),
            key="master_inspect_tenant"
        )

        selected_tenant_id = (
            tenant_map[
                selected_tenant_name
            ]
        )

        tc1, tc2, tc3, tc4 = st.columns(4)

        tc1.metric(
            "Users",
            int(
                (
                    profiles_df["tenant_id"]
                    == selected_tenant_id
                ).sum()
            )
            if (
                not profiles_df.empty
                and "tenant_id"
                in profiles_df.columns
            )
            else 0
        )

        tc2.metric(
            "Vehicles",
            int(
                (
                    vehicles_df["tenant_id"]
                    == selected_tenant_id
                ).sum()
            )
            if (
                not vehicles_df.empty
                and "tenant_id"
                in vehicles_df.columns
            )
            else 0
        )

        tc3.metric(
            "Drivers",
            int(
                (
                    drivers_df["tenant_id"]
                    == selected_tenant_id
                ).sum()
            )
            if (
                not drivers_df.empty
                and "tenant_id"
                in drivers_df.columns
            )
            else 0
        )

        tc4.metric(
            "Trips",
            int(
                (
                    trips_df["tenant_id"]
                    == selected_tenant_id
                ).sum()
            )
            if (
                not trips_df.empty
                and "tenant_id"
                in trips_df.columns
            )
            else 0
        )

    st.markdown("---")

    st.subheader(
        "💳 Platform Billing"
    )

    if not subs_df.empty:
        billing = subs_df.copy()

        if (
            not tenants_df.empty
            and "tenant_id"
            in billing.columns
        ):
            names = (
                tenants_df
                .set_index("id")["name"]
                .to_dict()
            )

            billing[
                "tenant_name"
            ] = (
                billing[
                    "tenant_id"
                ].map(names)
            )

        if "amount_cents" in billing.columns:
            billing[
                "amount_cents"
            ] = pd.to_numeric(
                billing["amount_cents"],
                errors="coerce"
            ).fillna(0)

            billing[
                "amount_R"
            ] = (
                billing["amount_cents"]
                / 100
            )

        st.dataframe(
            billing,
            width="stretch"
        )

    st.markdown("---")

    st.subheader(
        "🛡️ Audit Trail"
    )

    if not audit_df.empty:
        audit_view = audit_df.copy()

        if "created_at" in audit_view.columns:
            audit_view = (
                audit_view
                .sort_values(
                    "created_at",
                    ascending=False
                )
            )

        limit = st.selectbox(
            "Audit records to display",
            [25, 50, 100, 250],
            index=1
        )

        st.dataframe(
            audit_view.head(limit),
            width="stretch"
        )

    else:
        st.info(
            "No audit events recorded yet."
        )


def show_app():
    client = get_authed_client()

    user = st.session_state["user"]

    session = st.session_state.get(
        "session"
    )

    if (
        not session
        or not getattr(
            session,
            "access_token",
            None
        )
    ):
        for key in (
            "session",
            "user"
        ):
            st.session_state.pop(
                key,
                None
            )

        st.rerun()

    try:
        verified = (
            client.auth.get_user(
                session.access_token
            )
        )

        if (
            not verified
            or not verified.user
            or str(
                verified.user.id
            )
            != str(user.id)
        ):
            raise RuntimeError(
                "Session validation failed"
            )

        user = verified.user

        st.session_state[
            "user"
        ] = user

    except Exception:
        for key in (
            "session",
            "user"
        ):
            st.session_state.pop(
                key,
                None
            )

        st.warning(
            "Your session expired. "
            "Please log in again."
        )

        st.rerun()

    profile = get_profile(
        client,
        user.id
    )

    if not profile:
        st.error(
            "No profile found for this account."
        )
        st.stop()

    is_master = (
        profile.get("role")
        == "master_admin"
    )

    if not is_master:
        try:
            resolve_tenant_id(
                client,
                profile,
                user.id
            )

        except Exception as e:
            st.error(
                f"Workspace assignment required: {e}"
            )
            st.stop()

    st.sidebar.title(
        "🚚 Gonnie Fleet Intelligence"
    )

    st.sidebar.markdown(
        f"**{user.email}**"
    )

    st.sidebar.markdown(
        f"Role: `{profile.get('role')}`"
    )

    if st.sidebar.button(
        "Log Out"
    ):
        logout()

    st.sidebar.markdown("---")

    tenant_filter = None

    if is_master:
        tenants_res = (
            client.table("tenants")
            .select("id,name")
            .order("name")
            .execute()
        )

        tenant_options = {
            "🌐 All Tenants (Master View)":
                None
        }

        tenant_options.update({
            t["name"]: t["id"]
            for t in (
                tenants_res.data
                or []
            )
        })

        chosen = st.sidebar.selectbox(
            "Viewing Tenant",
            list(
                tenant_options.keys()
            )
        )

        tenant_filter = (
            tenant_options[chosen]
        )

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
        nav.append(
            "👑 Gonnie Platform Control Centre"
        )

        nav.append(
            "⚙️ System Configuration"
        )

    app_mode = st.sidebar.selectbox(
        "Choose Navigation",
        nav
    )

    if (
        app_mode
        == "👑 Gonnie Platform Control Centre"
    ):
        show_platform_control_centre(
            client,
            user,
            profile
        )
        return

    if (
        app_mode
        == "⚙️ System Configuration"
    ):
        if not is_master:
            st.error(
                "Master Admin access required."
            )
            st.stop()

        show_system_configuration()

        return

    trips_df = fetch_df(
        client,
        "trips",
        tenant_filter
    )

    vehicles_df = fetch_df(
        client,
        "vehicles",
        tenant_filter
    )

    drivers_df = fetch_df(
        client,
        "drivers",
        tenant_filter
    )

    if app_mode == "📊 Executive Dashboard":
        st.title(
            "📊 Fleet Executive Dashboard"
        )

        st.markdown(
            "**GONNIE FLEET MANAGEMENT SYSTEM** "
            "⬥ Multi-Fleet Intelligence Dashboard"
        )

        if trips_df.empty:
            st.info(
                "No trip data yet. Add trips from Trip Log."
            )

        else:
            total_trips = len(
                trips_df
            )

            total_distance = numeric_series(
                trips_df,
                "distance_km"
            ).sum()

            total_revenue = numeric_series(
                trips_df,
                "revenue"
            ).sum()

            fuel = numeric_series(
                trips_df,
                "fuel_used_liters"
            )

            price = numeric_series(
                trips_df,
                "cost_per_liter"
            )

            fixed = numeric_series(
                trips_df,
                "fixed_cost"
            ).sum()

            variable = numeric_series(
                trips_df,
                "variable_cost"
            ).sum()

            fuel_cost = (
                fuel * price
            ).sum()

            if "net_profit" in trips_df.columns:
                net = numeric_series(
                    trips_df,
                    "net_profit"
                ).sum()
            else:
                net = (
                    total_revenue
                    - fixed
                    - variable
                )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "Total Trips",
                f"{total_trips}"
            )

            c2.metric(
                "Revenue",
                f"R{total_revenue:,.2f}"
            )

            c3.metric(
                "Distance",
                f"{total_distance:,.0f} km"
            )

            c4.metric(
                "Fuel Cost",
                f"R{fuel_cost:,.2f}"
            )

            c5, c6, c7, c8 = st.columns(4)

            c5.metric(
                "Net Profit",
                f"R{net:,.2f}"
            )

            c6.metric(
                "Avg Revenue/KM",
                (
                    f"R{total_revenue / total_distance:,.2f}"
                    if total_distance
                    else "R0.00"
                )
            )

            c7.metric(
                "Profit Margin",
                (
                    f"{net / total_revenue * 100:.1f}%"
                    if total_revenue
                    else "0.0%"
                )
            )

            c8.metric(
                "Avg Cost/KM",
                (
                    f"R{(fixed + variable) / total_distance:,.2f}"
                    if total_distance
                    else "R0.00"
                )
            )

            st.markdown("---")

            if "registration" in trips_df.columns:
                st.subheader(
                    "🚛 Vehicle Performance"
                )

                group_kwargs = {}

                if "trip_id" in trips_df.columns:
                    group_kwargs[
                        "Trips"
                    ] = (
                        "trip_id",
                        "count"
                    )

                if "distance_km" in trips_df.columns:
                    group_kwargs[
                        "Distance_KM"
                    ] = (
                        "distance_km",
                        "sum"
                    )

                if "revenue" in trips_df.columns:
                    group_kwargs[
                        "Revenue_R"
                    ] = (
                        "revenue",
                        "sum"
                    )

                if "net_profit" in trips_df.columns:
                    group_kwargs[
                        "Net_Profit_R"
                    ] = (
                        "net_profit",
                        "sum"
                    )

                if group_kwargs:
                    perf_df = trips_df.copy()

                    for col in [
                        "distance_km",
                        "revenue",
                        "net_profit"
                    ]:
                        if col in perf_df.columns:
                            perf_df[col] = pd.to_numeric(
                                perf_df[col],
                                errors="coerce"
                            ).fillna(0)

                    perf = (
                        perf_df
                        .groupby("registration")
                        .agg(**group_kwargs)
                        .reset_index()
                    )

                    st.dataframe(
                        perf,
                        width="stretch"
                    )

            if (
                "driver_name"
                in trips_df.columns
            ):
                st.subheader(
                    "👤 Driver Performance"
                )

                perf_df = trips_df.copy()

                for col in [
                    "revenue",
                    "net_profit"
                ]:
                    if col in perf_df.columns:
                        perf_df[col] = pd.to_numeric(
                            perf_df[col],
                            errors="coerce"
                        ).fillna(0)

                group_kwargs = {}

                if "trip_id" in perf_df.columns:
                    group_kwargs[
                        "Trips"
                    ] = (
                        "trip_id",
                        "count"
                    )

                if "revenue" in perf_df.columns:
                    group_kwargs[
                        "Revenue_R"
                    ] = (
                        "revenue",
                        "sum"
                    )

                if "net_profit" in perf_df.columns:
                    group_kwargs[
                        "Net_Profit_R"
                    ] = (
                        "net_profit",
                        "sum"
                    )

                if group_kwargs:
                    perf = (
                        perf_df
                        .groupby("driver_name")
                        .agg(**group_kwargs)
                        .reset_index()
                    )

                    st.dataframe(
                        perf,
                        width="stretch"
                    )

            if (
                "trip_date"
                in trips_df.columns
            ):
                st.subheader(
                    "📅 Monthly Performance"
                )

                tmp = trips_df.copy()

                tmp["_month"] = (
                    pd.to_datetime(
                        tmp["trip_date"],
                        errors="coerce"
                    )
                    .dt.to_period("M")
                    .astype(str)
                )

                monthly_data = {}

                if "revenue" in tmp.columns:
                    tmp["revenue"] = pd.to_numeric(
                        tmp["revenue"],
                        errors="coerce"
                    ).fillna(0)

                    monthly_data[
                        "Revenue_R"
                    ] = (
                        "revenue",
                        "sum"
                    )

                if "net_profit" in tmp.columns:
                    tmp["net_profit"] = pd.to_numeric(
                        tmp["net_profit"],
                        errors="coerce"
                    ).fillna(0)

                    monthly_data[
                        "Net_Profit_R"
                    ] = (
                        "net_profit",
                        "sum"
                    )

                if monthly_data:
                    monthly = (
                        tmp
                        .groupby("_month")
                        .agg(**monthly_data)
                    )

                    monthly = monthly[
                        monthly.index != "NaT"
                    ]

                    if not monthly.empty:
                        st.line_chart(
                            monthly
                        )

    elif app_mode == "🗺️ Trip Log":
        st.title(
            "🚚 GONNIE FLEET — TRIP LOG"
        )

        st.caption(
            "KM/L, fuel variance and profit auto-calculate."
        )

        if (
            not vehicles_df.empty
            and "registration"
            in vehicles_df.columns
        ):
            veh_lookup = {
                v["registration"]: v
                for _, v
                in vehicles_df.iterrows()
            }

        else:
            veh_lookup = {}

        with st.expander(
            "➕ Log a new trip",
            expanded=trips_df.empty
        ):
            with st.form(
                "new_trip"
            ):
                c1, c2, c3 = st.columns(3)

                trip_id = c1.text_input(
                    "Trip ID"
                )

                fleet_no = c2.text_input(
                    "Fleet No"
                )

                registration = c3.selectbox(
                    "Registration",
                    list(
                        veh_lookup.keys()
                    )
                    or [
                        "(add vehicle first)"
                    ]
                )

                c4, c5, c6 = st.columns(3)

                if (
                    not drivers_df.empty
                    and "driver_name"
                    in drivers_df.columns
                ):
                    driver_options = list(
                        drivers_df[
                            "driver_name"
                        ]
                    )
                else:
                    driver_options = [
                        "(add driver first)"
                    ]

                driver_name = c4.selectbox(
                    "Driver Name",
                    driver_options
                )

                driver_phone = c5.text_input(
                    "Driver Phone"
                )

                trip_date = c6.date_input(
                    "Trip Date"
                )

                c7, c8 = st.columns(2)

                origin = c7.text_input(
                    "Destination Start",
                    "D.O.W DEPOT"
                )

                destination = c8.text_input(
                    "Destination End"
                )

                c9, c10, c11 = st.columns(3)

                odo_start = c9.number_input(
                    "Odo Start",
                    min_value=0.0
                )

                odo_end = c10.number_input(
                    "Odo End",
                    min_value=0.0
                )

                distance_km = c11.number_input(
                    "Distance KM",
                    min_value=0.0
                )

                c12, c13 = st.columns(2)

                fuel_used = c12.number_input(
                    "Fuel Used (L)",
                    min_value=0.0
                )

                price = c13.number_input(
                    "Cost/Litre (R)",
                    min_value=0.0,
                    value=25.31
                )

                c14, c15, c16 = st.columns(3)

                revenue = c14.number_input(
                    "Revenue (R)",
                    min_value=0.0
                )

                fixed_cost = c15.number_input(
                    "Fixed Cost (R)",
                    min_value=0.0
                )

                auto_variable_cost = (
                    c16.checkbox(
                        "Auto-calculate Variable Cost from fuel",
                        value=True
                    )
                )

                variable_cost = c16.number_input(
                    "Variable Cost (R)",
                    min_value=0.0,
                    disabled=auto_variable_cost,
                    help=(
                        "Uncheck Auto-calculate "
                        "to enter this manually, "
                        "including R0."
                    )
                )

                c17, c18, c19 = st.columns(3)

                customer = c17.text_input(
                    "Customer"
                )

                cargo = c18.text_input(
                    "Cargo Type"
                )

                load_kg = c19.number_input(
                    "Load KG",
                    min_value=0.0
                )

                c20, c21, c22 = st.columns(3)

                station = c20.text_input(
                    "Fuel Station"
                )

                gps = c21.checkbox(
                    "GPS Verified"
                )

                score = c22.number_input(
                    "Driver Score",
                    min_value=0.0,
                    max_value=100.0,
                    value=95.0
                )

                c23, c24 = st.columns(2)

                maint = c23.selectbox(
                    "Maint Flag",
                    [
                        "None",
                        "SERVICE DUE",
                        "OVERDUE"
                    ]
                )

                paid = c24.selectbox(
                    "Paid Status",
                    [
                        "unpaid",
                        "paid"
                    ]
                )

                manager = st.text_input(
                    "Manager Name"
                )

                manager_phone = st.text_input(
                    "Manager Phone"
                )

                notes = st.text_area(
                    "Trip Notes"
                )

                if st.form_submit_button(
                    "Save Trip"
                ):
                    if (
                        odo_end > 0
                        and odo_start > 0
                        and odo_end < odo_start
                    ):
                        st.error(
                            "Odo End is less than Odo Start — "
                            "check the readings before saving."
                        )

                    elif (
                        registration
                        == "(add vehicle first)"
                    ):
                        st.error(
                            "Add a vehicle before recording a trip."
                        )

                    elif (
                        driver_name
                        == "(add driver first)"
                    ):
                        st.error(
                            "Add a driver before recording a trip."
                        )

                    else:
                        auto_distance = (
                            odo_end - odo_start
                            if odo_end > odo_start
                            else distance_km
                        )

                        resolved_variable_cost = (
                            fuel_used * price
                            if auto_variable_cost
                            else variable_cost
                        )

                        calc = compute_trip_fields(
                            {
                                "distance_km":
                                    auto_distance,

                                "fuel_used_liters":
                                    fuel_used,

                                "cost_per_liter":
                                    price,

                                "revenue":
                                    revenue,

                                "fixed_cost":
                                    fixed_cost,

                                "variable_cost":
                                    resolved_variable_cost,
                            },
                            veh_lookup.get(
                                registration
                            )
                        )

                        payload = {
                            "trip_id":
                                trip_id,

                            "fleet_no":
                                fleet_no,

                            "registration":
                                registration,

                            "driver_name":
                                driver_name,

                            "driver_phone":
                                driver_phone,

                            "trip_date":
                                str(trip_date),

                            "origin":
                                origin,

                            "destination":
                                destination,

                            "odo_start":
                                odo_start,

                            "odo_end":
                                odo_end,

                            "distance_km":
                                auto_distance,

                            "fuel_used_liters":
                                fuel_used,

                            "cost_per_liter":
                                price,

                            "revenue":
                                revenue,

                            "fixed_cost":
                                fixed_cost,

                            "variable_cost":
                                resolved_variable_cost,

                            "net_profit":
                                calc["net_profit"],

                            "customer_name":
                                customer,

                            "cargo_type":
                                cargo,

                            "load_kg":
                                load_kg,

                            "fuel_station":
                                station,

                            "gps_verified":
                                gps,

                            "driver_score":
                                score,

                            "maint_flag":
                                maint,

                            "paid_status":
                                paid,

                            "manager_name":
                                manager,

                            "manager_phone":
                                manager_phone,

                            "trip_notes":
                                notes,
                        }

                        try:
                            payload = tenant_payload(
                                payload,
                                is_master,
                                tenant_filter,
                                profile
                            )

                            result = (
                                client.table("trips")
                                .insert(payload)
                                .execute()
                            )

                            record = (
                                result.data[0]
                                if result.data
                                else None
                            )

                            write_audit(
                                client,
                                user,
                                profile,
                                "CREATE",
                                "trips",
                                record.get("id")
                                if record
                                else None,
                                payload.get(
                                    "tenant_id"
                                ),
                                None,
                                record
                            )

                            if calc[
                                "theft_alert"
                            ]:
                                st.warning(
                                    "🚨 Theft Alert: "
                                    f"KM/L is "
                                    f"{calc['fuel_variance_pct']}% "
                                    "below expected."
                                )

                            st.success(
                                f"Trip saved. "
                                f"KM/L {calc['km_per_l']} "
                                f"| Profit "
                                f"R{calc['net_profit']:,.2f}"
                            )

                            st.rerun()

                        except Exception as e:
                            st.error(
                                f"Could not save trip: {e}"
                            )

        if not trips_df.empty:
            st.dataframe(
                trips_df,
                width="stretch"
            )

            can_delete = (
                is_master
                or profile.get("role")
                in (
                    "master_admin",
                    "tenant_admin",
                    "workspace_admin",
                    "admin"
                )
            )

            if (
                can_delete
                and "id"
                in trips_df.columns
            ):
                st.markdown("---")

                st.subheader(
                    "✏️ Edit Trip"
                )

                edit_options = {}

                for _, r in trips_df.iterrows():
                    edit_options[
                        f"{r.get('trip_id','')} "
                        f"• {r.get('trip_date','')} "
                        f"• {r.get('registration','')}"
                    ] = r["id"]

                edit_selected = st.selectbox(
                    "Trip",
                    list(edit_options.keys()),
                    key="edit_trip_select"
                )

                edit_id = edit_options[edit_selected]

                edit_matches = trips_df[
                    trips_df["id"] == edit_id
                ]

                if not edit_matches.empty:
                    er = edit_matches.iloc[0]

                    with st.form(
                        "edit_trip_form"
                    ):
                        c1, c2, c3 = st.columns(3)

                        e_trip_id = c1.text_input(
                            "Trip ID",
                            value=str(
                                er.get("trip_id") or ""
                            )
                        )

                        e_fleet_no = c2.text_input(
                            "Fleet No",
                            value=str(
                                er.get("fleet_no") or ""
                            )
                        )

                        reg_choices = (
                            list(veh_lookup.keys())
                            or [
                                str(
                                    er.get("registration")
                                    or ""
                                )
                            ]
                        )

                        current_reg = str(
                            er.get("registration") or ""
                        )

                        if current_reg not in reg_choices:
                            reg_choices = (
                                [current_reg] + reg_choices
                            )

                        e_registration = c3.selectbox(
                            "Registration",
                            reg_choices,
                            index=reg_choices.index(
                                current_reg
                            )
                        )

                        c4, c5, c6 = st.columns(3)

                        if (
                            not drivers_df.empty
                            and "driver_name"
                            in drivers_df.columns
                        ):
                            driver_choices = list(
                                drivers_df["driver_name"]
                            )
                        else:
                            driver_choices = []

                        current_driver = str(
                            er.get("driver_name") or ""
                        )

                        if (
                            current_driver
                            and current_driver
                            not in driver_choices
                        ):
                            driver_choices = (
                                [current_driver]
                                + driver_choices
                            )

                        if not driver_choices:
                            driver_choices = [
                                current_driver
                            ]

                        e_driver_name = c4.selectbox(
                            "Driver Name",
                            driver_choices,
                            index=driver_choices.index(
                                current_driver
                            )
                            if current_driver
                            in driver_choices
                            else 0
                        )

                        e_driver_phone = c5.text_input(
                            "Driver Phone",
                            value=str(
                                er.get("driver_phone") or ""
                            )
                        )

                        try:
                            default_trip_date = (
                                pd.to_datetime(
                                    er.get("trip_date")
                                ).date()
                            )
                        except Exception:
                            default_trip_date = date.today()

                        e_trip_date = c6.date_input(
                            "Trip Date",
                            value=default_trip_date
                        )

                        c7, c8 = st.columns(2)

                        e_origin = c7.text_input(
                            "Destination Start",
                            value=str(
                                er.get("origin")
                                or "D.O.W DEPOT"
                            )
                        )

                        e_destination = c8.text_input(
                            "Destination End",
                            value=str(
                                er.get("destination") or ""
                            )
                        )

                        c9, c10, c11 = st.columns(3)

                        e_odo_start = c9.number_input(
                            "Odo Start",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("odo_start")
                            )
                        )

                        e_odo_end = c10.number_input(
                            "Odo End",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("odo_end")
                            )
                        )

                        e_distance_km = c11.number_input(
                            "Distance KM",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("distance_km")
                            )
                        )

                        c12, c13 = st.columns(2)

                        e_fuel_used = c12.number_input(
                            "Fuel Used (L)",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("fuel_used_liters")
                            )
                        )

                        e_price = c13.number_input(
                            "Cost/Litre (R)",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("cost_per_liter"),
                                25.31
                            )
                        )

                        c14, c15, c16 = st.columns(3)

                        e_revenue = c14.number_input(
                            "Revenue (R)",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("revenue")
                            )
                        )

                        e_fixed_cost = c15.number_input(
                            "Fixed Cost (R)",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("fixed_cost")
                            )
                        )

                        e_auto_variable_cost = (
                            c16.checkbox(
                                "Auto-calculate Variable Cost from fuel",
                                value=False,
                                key="edit_trip_auto_variable"
                            )
                        )

                        e_variable_cost = c16.number_input(
                            "Variable Cost (R)",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("variable_cost")
                            ),
                            disabled=e_auto_variable_cost,
                            key="edit_trip_variable_cost"
                        )

                        c17, c18, c19 = st.columns(3)

                        e_customer = c17.text_input(
                            "Customer",
                            value=str(
                                er.get("customer_name") or ""
                            )
                        )

                        e_cargo = c18.text_input(
                            "Cargo Type",
                            value=str(
                                er.get("cargo_type") or ""
                            )
                        )

                        e_load_kg = c19.number_input(
                            "Load KG",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("load_kg")
                            )
                        )

                        c20, c21, c22 = st.columns(3)

                        e_station = c20.text_input(
                            "Fuel Station",
                            value=str(
                                er.get("fuel_station") or ""
                            )
                        )

                        e_gps = c21.checkbox(
                            "GPS Verified",
                            value=bool(
                                er.get("gps_verified")
                            )
                        )

                        e_score = c22.number_input(
                            "Driver Score",
                            min_value=0.0,
                            max_value=100.0,
                            value=numeric_value(
                                er.get("driver_score"),
                                95.0
                            )
                        )

                        c23, c24 = st.columns(2)

                        maint_options = [
                            "None",
                            "SERVICE DUE",
                            "OVERDUE"
                        ]

                        current_maint = str(
                            er.get("maint_flag")
                            or "None"
                        )

                        e_maint = c23.selectbox(
                            "Maint Flag",
                            maint_options,
                            index=maint_options.index(
                                current_maint
                            )
                            if current_maint
                            in maint_options
                            else 0
                        )

                        paid_options = [
                            "unpaid",
                            "paid"
                        ]

                        current_paid = str(
                            er.get("paid_status")
                            or "unpaid"
                        )

                        e_paid = c24.selectbox(
                            "Paid Status",
                            paid_options,
                            index=paid_options.index(
                                current_paid
                            )
                            if current_paid
                            in paid_options
                            else 0
                        )

                        e_manager = st.text_input(
                            "Manager Name",
                            value=str(
                                er.get("manager_name") or ""
                            )
                        )

                        e_manager_phone = st.text_input(
                            "Manager Phone",
                            value=str(
                                er.get("manager_phone") or ""
                            )
                        )

                        e_notes = st.text_area(
                            "Trip Notes",
                            value=str(
                                er.get("trip_notes") or ""
                            )
                        )

                        if st.form_submit_button(
                            "💾 Save Trip Changes"
                        ):
                            if (
                                e_odo_end > 0
                                and e_odo_start > 0
                                and e_odo_end < e_odo_start
                            ):
                                st.error(
                                    "Odo End is less than Odo Start — "
                                    "check the readings before saving."
                                )

                            else:
                                auto_distance = (
                                    e_odo_end - e_odo_start
                                    if e_odo_end > e_odo_start
                                    else e_distance_km
                                )

                                resolved_variable_cost = (
                                    e_fuel_used * e_price
                                    if e_auto_variable_cost
                                    else e_variable_cost
                                )

                                calc = compute_trip_fields(
                                    {
                                        "distance_km":
                                            auto_distance,

                                        "fuel_used_liters":
                                            e_fuel_used,

                                        "cost_per_liter":
                                            e_price,

                                        "revenue":
                                            e_revenue,

                                        "fixed_cost":
                                            e_fixed_cost,

                                        "variable_cost":
                                            resolved_variable_cost,
                                    },
                                    veh_lookup.get(
                                        e_registration
                                    )
                                )

                                fields = {
                                    "trip_id":
                                        e_trip_id,

                                    "fleet_no":
                                        e_fleet_no,

                                    "registration":
                                        e_registration,

                                    "driver_name":
                                        e_driver_name,

                                    "driver_phone":
                                        e_driver_phone,

                                    "trip_date":
                                        str(e_trip_date),

                                    "origin":
                                        e_origin,

                                    "destination":
                                        e_destination,

                                    "odo_start":
                                        e_odo_start,

                                    "odo_end":
                                        e_odo_end,

                                    "distance_km":
                                        auto_distance,

                                    "fuel_used_liters":
                                        e_fuel_used,

                                    "cost_per_liter":
                                        e_price,

                                    "revenue":
                                        e_revenue,

                                    "fixed_cost":
                                        e_fixed_cost,

                                    "variable_cost":
                                        resolved_variable_cost,

                                    "net_profit":
                                        calc["net_profit"],

                                    "customer_name":
                                        e_customer,

                                    "cargo_type":
                                        e_cargo,

                                    "load_kg":
                                        e_load_kg,

                                    "fuel_station":
                                        e_station,

                                    "gps_verified":
                                        e_gps,

                                    "driver_score":
                                        e_score,

                                    "maint_flag":
                                        e_maint,

                                    "paid_status":
                                        e_paid,

                                    "manager_name":
                                        e_manager,

                                    "manager_phone":
                                        e_manager_phone,

                                    "trip_notes":
                                        e_notes,
                                }

                                try:
                                    update_scoped_record(
                                        client,
                                        user,
                                        profile,
                                        "trips",
                                        edit_id,
                                        fields,
                                        (
                                            tenant_filter
                                            if is_master
                                            and tenant_filter
                                            else None
                                        )
                                    )

                                    if calc[
                                        "theft_alert"
                                    ]:
                                        st.warning(
                                            "🚨 Theft Alert: "
                                            f"KM/L is "
                                            f"{calc['fuel_variance_pct']}% "
                                            "below expected."
                                        )

                                    st.success(
                                        f"Trip updated. "
                                        f"KM/L {calc['km_per_l']} "
                                        f"| Profit "
                                        f"R{calc['net_profit']:,.2f}"
                                    )

                                    st.rerun()

                                except Exception as e:
                                    st.error(
                                        f"Could not update trip: {e}"
                                    )

            if (
                can_delete
                and "id"
                in trips_df.columns
            ):
                st.markdown("---")

                st.subheader(
                    "🗑️ Delete Trip"
                )

                options = {}

                for _, r in trips_df.iterrows():
                    options[
                        f"{r.get('trip_id','')} "
                        f"• {r.get('trip_date','')} "
                        f"• {r.get('registration','')}"
                    ] = r["id"]

                selected = st.selectbox(
                    "Trip",
                    list(options.keys()),
                    key="delete_trip_select"
                )

                confirm = st.checkbox(
                    "I understand this permanently deletes the selected trip.",
                    key="delete_trip_confirm"
                )

                if st.button(
                    "🗑️ Delete Selected Trip",
                    disabled=not confirm,
                    key="delete_trip_button"
                ):
                    try:
                        rid = options[selected]

                        old = delete_scoped_record(
                            client,
                            user,
                            profile,
                            "trips",
                            rid,
                            (
                                tenant_filter
                                if is_master
                                and tenant_filter
                                else None
                            )
                        )

                        st.success(
                            f"Trip "
                            f"{old.get('trip_id','')} "
                            "deleted."
                        )

                        st.rerun()

                    except Exception as e:
                        st.error(
                            f"Could not delete trip: {e}"
                        )

    elif app_mode == "🚗 Vehicle Register":
        st.title(
            "🚗 VEHICLE REGISTER"
        )

        with st.expander(
            "➕ Add a vehicle",
            expanded=vehicles_df.empty
        ):
            with st.form(
                "new_vehicle"
            ):
                c1, c2, c3 = st.columns(3)

                registration = c1.text_input(
                    "Registration"
                )

                fleet_no = c2.text_input(
                    "Fleet No"
                )

                make = c3.text_input(
                    "Make"
                )

                c4, c5, c6 = st.columns(3)

                model = c4.text_input(
                    "Model"
                )

                year = c5.number_input(
                    "Year",
                    min_value=1980,
                    max_value=2100,
                    value=2020
                )

                vin = c6.text_input(
                    "VIN / Engine No"
                )

                c7, c8, c9 = st.columns(3)

                status = c7.selectbox(
                    "Status",
                    [
                        "Active",
                        "In Maintenance",
                        "Inactive"
                    ]
                )

                expected = c8.number_input(
                    "Expected KM/L",
                    min_value=0.0,
                    value=2.0
                )

                service_cost = c9.number_input(
                    "Service Cost/KM",
                    min_value=0.0,
                    value=1.0
                )

                c10, c11, c12 = st.columns(3)

                insurance = c10.number_input(
                    "Monthly Insurance (R)",
                    min_value=0.0
                )

                next_service = c11.number_input(
                    "Next Service KM",
                    min_value=0.0
                )

                avg_daily = c12.number_input(
                    "Avg Daily KM",
                    min_value=0.0
                )

                c13, c14 = st.columns(2)

                odo = c13.number_input(
                    "Current Odometer",
                    min_value=0.0
                )

                license_cost = c14.number_input(
                    "Annual License Cost",
                    min_value=0.0
                )

                if st.form_submit_button(
                    "Save Vehicle"
                ):
                    if not registration.strip():
                        st.error(
                            "Registration is required."
                        )
                    else:
                        payload = {
                            "registration":
                                registration.strip(),

                            "fleet_no":
                                fleet_no,

                            "make":
                                make,

                            "model":
                                model,

                            "year":
                                int(year),

                            "vin_engine_no":
                                vin,

                            "status":
                                status,

                            "expected_km_l":
                                expected,

                            "service_cost_per_km":
                                service_cost,

                            "monthly_insurance":
                                insurance,

                            "next_service_km":
                                next_service,

                            "avg_daily_km":
                                avg_daily,

                            "fleet_health_score":
                                100,

                            "current_odometer":
                                odo,

                            "annual_license_cost":
                                license_cost,
                        }

                        try:
                            payload = tenant_payload(
                                payload,
                                is_master,
                                tenant_filter,
                                profile
                            )

                            res = (
                                client.table("vehicles")
                                .insert(payload)
                                .execute()
                            )

                            record = (
                                res.data[0]
                                if res.data
                                else None
                            )

                            write_audit(
                                client,
                                user,
                                profile,
                                "CREATE",
                                "vehicles",
                                record.get("id")
                                if record
                                else None,
                                payload.get(
                                    "tenant_id"
                                ),
                                None,
                                record
                            )

                            st.success(
                                "Vehicle saved."
                            )

                            st.rerun()

                        except Exception as e:
                            st.error(
                                f"Could not save vehicle: {e}"
                            )

        if not vehicles_df.empty:
            st.dataframe(
                vehicles_df,
                width="stretch"
            )

            can_delete = (
                is_master
                or profile.get("role")
                in (
                    "tenant_admin",
                    "workspace_admin",
                    "admin"
                )
            )

            if (
                can_delete
                and "id"
                in vehicles_df.columns
            ):
                st.markdown("---")

                st.subheader(
                    "✏️ Edit Vehicle"
                )

                edit_options = {
                    f"{r.get('registration','')} "
                    f"• Fleet {r.get('fleet_no','')} "
                    f"• {r.get('make','')} "
                    f"{r.get('model','')}":
                        r["id"]
                    for _, r
                    in vehicles_df.iterrows()
                }

                edit_selected = st.selectbox(
                    "Vehicle",
                    list(edit_options.keys()),
                    key="edit_vehicle_select"
                )

                edit_id = edit_options[
                    edit_selected
                ]

                edit_matches = vehicles_df[
                    vehicles_df["id"] == edit_id
                ]

                if not edit_matches.empty:
                    er = edit_matches.iloc[0]

                    status_options = [
                        "Active",
                        "In Maintenance",
                        "Inactive"
                    ]

                    current_status = str(
                        er.get("status")
                        or "Active"
                    )

                    with st.form(
                        "edit_vehicle_form"
                    ):
                        c1, c2, c3 = st.columns(3)

                        e_registration = c1.text_input(
                            "Registration",
                            value=str(
                                er.get("registration") or ""
                            )
                        )

                        e_fleet_no = c2.text_input(
                            "Fleet No",
                            value=str(
                                er.get("fleet_no") or ""
                            )
                        )

                        e_make = c3.text_input(
                            "Make",
                            value=str(
                                er.get("make") or ""
                            )
                        )

                        c4, c5, c6 = st.columns(3)

                        e_model = c4.text_input(
                            "Model",
                            value=str(
                                er.get("model") or ""
                            )
                        )

                        e_year = c5.number_input(
                            "Year",
                            min_value=1980,
                            max_value=2100,
                            value=int(
                                numeric_value(
                                    er.get("year"),
                                    2020
                                )
                            )
                        )

                        e_vin = c6.text_input(
                            "VIN / Engine No",
                            value=str(
                                er.get("vin_engine_no") or ""
                            )
                        )

                        c7, c8, c9 = st.columns(3)

                        e_status = c7.selectbox(
                            "Status",
                            status_options,
                            index=status_options.index(
                                current_status
                            )
                            if current_status
                            in status_options
                            else 0
                        )

                        e_expected = c8.number_input(
                            "Expected KM/L",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("expected_km_l"),
                                2.0
                            )
                        )

                        e_service_cost = c9.number_input(
                            "Service Cost/KM",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("service_cost_per_km"),
                                1.0
                            )
                        )

                        c10, c11, c12 = st.columns(3)

                        e_insurance = c10.number_input(
                            "Monthly Insurance (R)",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("monthly_insurance")
                            )
                        )

                        e_next_service = c11.number_input(
                            "Next Service KM",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("next_service_km")
                            )
                        )

                        e_avg_daily = c12.number_input(
                            "Avg Daily KM",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("avg_daily_km")
                            )
                        )

                        c13, c14 = st.columns(2)

                        e_odo = c13.number_input(
                            "Current Odometer",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("current_odometer")
                            )
                        )

                        e_license_cost = c14.number_input(
                            "Annual License Cost",
                            min_value=0.0,
                            value=numeric_value(
                                er.get("annual_license_cost")
                            )
                        )

                        if st.form_submit_button(
                            "💾 Save Vehicle Changes"
                        ):
                            if not e_registration.strip():
                                st.error(
                                    "Registration is required."
                                )
                            else:
                                fields = {
                                    "registration":
                                        e_registration.strip(),

                                    "fleet_no":
                                        e_fleet_no,

                                    "make":
                                        e_make,

                                    "model":
                                        e_model,

                                    "year":
                                        int(e_year),

                                    "vin_engine_no":
                                        e_vin,

                                    "status":
                                        e_status,

                                    "expected_km_l":
                                        e_expected,

                                    "service_cost_per_km":
                                        e_service_cost,

                                    "monthly_insurance":
                                        e_insurance,

                                    "next_service_km":
                                        e_next_service,

                                    "avg_daily_km":
                                        e_avg_daily,

                                    "current_odometer":
                                        e_odo,

                                    "annual_license_cost":
                                        e_license_cost,
                                }

                                try:
                                    update_scoped_record(
                                        client,
                                        user,
                                        profile,
                                        "vehicles",
                                        edit_id,
                                        fields,
                                        (
                                            tenant_filter
                                            if is_master
                                            and tenant_filter
                                            else None
                                        )
                                    )

                                    st.success(
                                        "Vehicle updated."
                                    )

                                    st.rerun()

                                except Exception as e:
                                    st.error(
                                        f"Could not update vehicle: {e}"
                                    )

            if (
                can_delete
                and "id"
                in vehicles_df.columns
            ):
                st.markdown("---")

                st.subheader(
                    "🗑️ Delete Vehicle"
                )

                options = {
                    f"{r.get('registration','')} "
                    f"• Fleet {r.get('fleet_no','')} "
                    f"• {r.get('make','')} "
                    f"{r.get('model','')}":
                        r["id"]
                    for _, r
                    in vehicles_df.iterrows()
                }

                selected = st.selectbox(
                    "Vehicle",
                    list(options.keys()),
                    key="delete_vehicle_select"
                )

                confirm = st.checkbox(
                    "I understand this permanently deletes the selected vehicle.",
                    key="delete_vehicle_confirm"
                )

                if st.button(
                    "🗑️ Delete Selected Vehicle",
                    disabled=not confirm,
                    key="delete_vehicle_button"
                ):
                    try:
                        old = delete_scoped_record(
                            client,
                            user,
                            profile,
                            "vehicles",
                            options[selected],
                            (
                                tenant_filter
                                if is_master
                                and tenant_filter
                                else None
                            )
                        )

                        st.success(
                            f"Vehicle "
                            f"{old.get('registration','')} "
                            "deleted."
                        )

                        st.rerun()

                    except Exception as e:
                        st.error(
                            f"Could not delete vehicle: {e}"
                        )

    elif app_mode == "👤 Driver Register":
        st.title(
            "👤 DRIVER REGISTER"
        )

        with st.expander(
            "➕ Add a driver",
            expanded=drivers_df.empty
        ):
            with st.form(
                "new_driver"
            ):
                c1, c2, c3 = st.columns(3)

                name = c1.text_input(
                    "Driver Name"
                )

                phone = c2.text_input(
                    "Phone"
                )

                license_no = c3.text_input(
                    "License No"
                )

                c4, c5 = st.columns(2)

                license_expiry = c4.date_input(
                    "License Expiry"
                )

                prdp_expiry = c5.date_input(
                    "PrDP Expiry"
                )

                c6, c7, c8 = st.columns(3)

                supervisor = c6.text_input(
                    "Supervisor"
                )

                rating = c7.number_input(
                    "Supervisor Rating",
                    1.0,
                    5.0,
                    5.0
                )

                avg_score = c8.number_input(
                    "Avg Driver Score",
                    0.0,
                    100.0,
                    100.0
                )

                c9, c10 = st.columns(2)

                accidents = c9.number_input(
                    "Accidents",
                    0
                )

                fines = c10.number_input(
                    "Fines",
                    0
                )

                if st.form_submit_button(
                    "Save Driver"
                ):
                    if not name.strip():
                        st.error(
                            "Driver Name is required."
                        )
                    else:
                        payload = {
                            "driver_name":
                                name.strip(),

                            "driver_phone":
                                phone,

                            "license_number":
                                license_no,

                            "license_expiry":
                                str(
                                    license_expiry
                                ),

                            "prdp_expiry":
                                str(
                                    prdp_expiry
                                ),

                            "supervisor":
                                supervisor,

                            "rating":
                                rating,

                            "avg_driver_score":
                                avg_score,

                            "accidents":
                                int(accidents),

                            "fines":
                                int(fines),

                            "status":
                                "active",
                        }

                        try:
                            payload = tenant_payload(
                                payload,
                                is_master,
                                tenant_filter,
                                profile
                            )

                            res = (
                                client.table("drivers")
                                .insert(payload)
                                .execute()
                            )

                            record = (
                                res.data[0]
                                if res.data
                                else None
                            )

                            write_audit(
                                client,
                                user,
                                profile,
                                "CREATE",
                                "drivers",
                                record.get("id")
                                if record
                                else None,
                                payload.get(
                                    "tenant_id"
                                ),
                                None,
                                record
                            )

                            st.success(
                                "Driver saved."
                            )

                            st.rerun()

                        except Exception as e:
                            st.error(
                                f"Could not save driver: {e}"
                            )

        if not drivers_df.empty:
            st.dataframe(
                drivers_df,
                width="stretch"
            )

            can_delete = (
                is_master
                or profile.get("role")
                in (
                    "tenant_admin",
                    "workspace_admin",
                    "admin"
                )
            )

            if (
                can_delete
                and "id"
                in drivers_df.columns
            ):
                st.markdown("---")

                st.subheader(
                    "✏️ Edit Driver"
                )

                edit_options = {
                    f"{r.get('driver_name','')} "
                    f"• {r.get('driver_phone','')} "
                    f"• License "
                    f"{r.get('license_number','')}":
                        r["id"]
                    for _, r
                    in drivers_df.iterrows()
                }

                edit_selected = st.selectbox(
                    "Driver",
                    list(edit_options.keys()),
                    key="edit_driver_select"
                )

                edit_id = edit_options[
                    edit_selected
                ]

                edit_matches = drivers_df[
                    drivers_df["id"] == edit_id
                ]

                if not edit_matches.empty:
                    er = edit_matches.iloc[0]

                    status_options = [
                        "active",
                        "inactive",
                        "suspended"
                    ]

                    current_status = str(
                        er.get("status")
                        or "active"
                    ).lower()

                    if current_status not in status_options:
                        status_options = (
                            [current_status]
                            + status_options
                        )

                    try:
                        default_license_expiry = (
                            pd.to_datetime(
                                er.get("license_expiry")
                            ).date()
                        )
                    except Exception:
                        default_license_expiry = date.today()

                    try:
                        default_prdp_expiry = (
                            pd.to_datetime(
                                er.get("prdp_expiry")
                            ).date()
                        )
                    except Exception:
                        default_prdp_expiry = date.today()

                    with st.form(
                        "edit_driver_form"
                    ):
                        c1, c2, c3 = st.columns(3)

                        e_name = c1.text_input(
                            "Driver Name",
                            value=str(
                                er.get("driver_name") or ""
                            )
                        )

                        e_phone = c2.text_input(
                            "Phone",
                            value=str(
                                er.get("driver_phone") or ""
                            )
                        )

                        e_license_no = c3.text_input(
                            "License No",
                            value=str(
                                er.get("license_number") or ""
                            )
                        )

                        c4, c5 = st.columns(2)

                        e_license_expiry = c4.date_input(
                            "License Expiry",
                            value=default_license_expiry
                        )

                        e_prdp_expiry = c5.date_input(
                            "PrDP Expiry",
                            value=default_prdp_expiry
                        )

                        c6, c7, c8 = st.columns(3)

                        e_supervisor = c6.text_input(
                            "Supervisor",
                            value=str(
                                er.get("supervisor") or ""
                            )
                        )

                        e_rating = c7.number_input(
                            "Supervisor Rating",
                            1.0,
                            5.0,
                            value=numeric_value(
                                er.get("rating"),
                                5.0
                            )
                        )

                        e_avg_score = c8.number_input(
                            "Avg Driver Score",
                            0.0,
                            100.0,
                            value=numeric_value(
                                er.get("avg_driver_score"),
                                100.0
                            )
                        )

                        c9, c10, c11 = st.columns(3)

                        e_accidents = c9.number_input(
                            "Accidents",
                            0,
                            value=int(
                                numeric_value(
                                    er.get("accidents")
                                )
                            )
                        )

                        e_fines = c10.number_input(
                            "Fines",
                            0,
                            value=int(
                                numeric_value(
                                    er.get("fines")
                                )
                            )
                        )

                        e_status = c11.selectbox(
                            "Status",
                            status_options,
                            index=status_options.index(
                                current_status
                            )
                        )

                        if st.form_submit_button(
                            "💾 Save Driver Changes"
                        ):
                            if not e_name.strip():
                                st.error(
                                    "Driver Name is required."
                                )
                            else:
                                fields = {
                                    "driver_name":
                                        e_name.strip(),

                                    "driver_phone":
                                        e_phone,

                                    "license_number":
                                        e_license_no,

                                    "license_expiry":
                                        str(e_license_expiry),

                                    "prdp_expiry":
                                        str(e_prdp_expiry),

                                    "supervisor":
                                        e_supervisor,

                                    "rating":
                                        e_rating,

                                    "avg_driver_score":
                                        e_avg_score,

                                    "accidents":
                                        int(e_accidents),

                                    "fines":
                                        int(e_fines),

                                    "status":
                                        e_status,
                                }

                                try:
                                    update_scoped_record(
                                        client,
                                        user,
                                        profile,
                                        "drivers",
                                        edit_id,
                                        fields,
                                        (
                                            tenant_filter
                                            if is_master
                                            and tenant_filter
                                            else None
                                        )
                                    )

                                    st.success(
                                        "Driver updated."
                                    )

                                    st.rerun()

                                except Exception as e:
                                    st.error(
                                        f"Could not update driver: {e}"
                                    )

            if (
                can_delete
                and "id"
                in drivers_df.columns

Preview truncated for large file