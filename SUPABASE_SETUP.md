# Supabase Setup for MQS ChatPilot (1-time, 2 mins)

> Para hindi mabura accounts pag nag-deploy — persistent na.

## 1. Create Table
- Supabase Dashboard → SQL Editor → New Query → paste at Run:

```sql
create table if not exists mqs_users (
  id text primary key,
  email text unique not null,
  password text not null,
  name text,
  balsa_name text,
  gcash text,
  plan text default 'trial',
  created_at text,
  trial_end text,
  business jsonb default '{}'::jsonb,
  vacation jsonb default '{}'::jsonb,
  oauth text,
  page_id text,
  page_access_token text,
  page_name text
);
-- add missing columns if table already exists
alter table mqs_users add column if not exists page_id text;
alter table mqs_users add column if not exists page_access_token text;
alter table mqs_users add column if not exists page_name text;
-- enable anon access (service key will bypass, but allow anon for our simple REST)
alter table mqs_users enable row level security;
create policy "allow all for anon" on mqs_users for all using (true) with check (true);
```

## 2. Get Keys
- Supabase → Project Settings → API
- Copy: **Project URL** (https://xxxxx.supabase.co)
- Copy: **anon public key** (eyJ...)

## 3. Set on Render
- Render Dashboard → MQS ChatPilot → Environment → Add:
  - `SUPABASE_URL` = `https://xxxxx.supabase.co`
  - `SUPABASE_KEY` = `eyJ...` (anon key)
  - `FLASK_SECRET` = random string (e.g., `mqs_secret_change_me_2026`)
  - Keep `PAGE_TOKEN`, `GEMINI_KEY`, `VERIFY_TOKEN=mqs_verify_2026`, `SYNC_TOKEN=mqs_sync_2026`, `ADMIN_PASS=mqs_sync_2026`
- Save → Render auto-redeploy

## 4. Verify
- Register at https://mqs-chatpilot.onrender.com/register → check Supabase → Table Editor → mqs_users → may row na.
- `/mqs-admin` → login → makita users kahit mag-redeploy.

Fallback: If no SUPABASE_URL/KEY, it uses `users.json` file locally (so dev pa rin gumagana).
