# Gonnie Fleet Intelligence — Multi-Tenant Setup Guide

## What's been built

**Backend:** A Supabase project (`gonnie-fleet-intelligence`, free tier — $0/month) with:
- `tenants` table — one row per company using the platform
- `profiles` table — links each login to a tenant and a role (`master_admin`, `tenant_admin`, `driver`, `viewer`)
- Six fleet tables (`trips`, `vehicles`, `drivers`, `fuel_analysis`, `financial_forecast`, `compliance`), all tagged by `tenant_id`
- Row-Level Security on every table: each company only ever sees its own data — **except** you.
- Your email, `gerswilledavids@gmail.com`, is hard-coded as the auto-promoted **master admin** the moment you sign up with it. Master admin can see and manage *all* tenants.

**Frontend:** `app.py`, a rebuilt version of your Streamlit dashboard with:
- Login / Sign-up screens (Supabase Auth)
- New companies self-signup and automatically get their own isolated workspace
- A tenant switcher in the sidebar (master admin only) to view any single tenant or all combined
- All your original pages — Executive Dashboard, Trip & GPS Logs, Fuel Analysis, Financial Forecast, Compliance, Job Estimator — now reading/writing live from the database instead of CSVs
- A **Master Admin Console** page to view every tenant/user and change roles

## Step 1 — Run it locally (to test)

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Step 2 — Create your master admin account

1. Open the app, go to the **Sign Up** tab
2. Use email **gerswilledavids@gmail.com** exactly — this is the only email wired to auto-become master admin
3. Set a password, submit
4. By default Supabase requires email confirmation — check your inbox for a confirmation link, then log in

If you'd rather skip email confirmation for testing, I can turn it off — just ask.

## Step 3 — Deploy it for free so others can use it

1. Push `app.py` and `requirements.txt` to a GitHub repo
2. Go to [share.streamlit.io](https://share.streamlit.io) (Streamlit Community Cloud — free)
3. Connect your GitHub repo and deploy
4. Your app gets a public URL — any company can visit it and sign up, automatically landing in their own isolated tenant

## Notes & honest caveats

- **Free tier limits:** Supabase pauses inactive free projects after ~1 week of no activity (just needs a visit to wake it back up), and caps you at 500MB database / 50k monthly active users. Fine for starting out, not for scale.
- **Security:** Data isolation is enforced at the database level (Row-Level Security), not just in app code — even if someone found a way around the UI, they still couldn't read another tenant's rows.
- **Master admin email is hard-coded** in the database trigger. If you want to add more master admins later, promote them from the Master Admin Console page once you're logged in.
