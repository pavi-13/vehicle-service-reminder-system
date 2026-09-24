# VehicleCare — Vehicle Service Reminder System

A fast Python/FastAPI web application for a car, bike, or multi-vehicle service centre. The responsive UI includes separate customer access and full admin access.

## Included features

- Customer account signup, password login, and one-time-password login flow.
- Add, view, and remove cars, bikes, scooters, and other vehicles.
- Admin service desk: check-in a vehicle, update live repair status, add technician notes, bill, service report, and next-service date.
- Automatic in-app notification history for every check-in and update.
- Real email through SMTP and real SMS through Twilio as soon as the corresponding environment variables are configured.
- Daily Vercel Cron endpoint that sends due/overdue service reminders up to 30 days ahead.
- Customer service report, delivery date, bill, next service date, feedback form, and 24/7 help chat.
- Optional OpenAI-powered chat using `gpt-6-astra`; no key means the app remains usable with the free built-in service-help assistant.

## Quick start (Windows PowerShell)

```powershell
cd E:\vehicle-service-reminder-system
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`.

Default admin login for local testing:

```text
Email: admin@vehiclecare.local
Password: Admin@123
```

Change the admin password and `APP_SECRET` before launch. In development mode, requested OTP is shown on screen to simplify testing; set `DEBUG=false` for production and configure a delivery provider.

## Vercel deployment

1. Put this folder in a GitHub repository and import it in Vercel, or run `vercel` from this folder.
2. Add `APP_SECRET` and `CRON_SECRET` in Vercel Project Settings → Environment Variables.
3. Optionally add SMTP, Twilio, and OpenAI environment variables from `.env.example`.
4. Deploy. The included `vercel.json` schedules `GET /api/cron/send-reminders` once each day.

### Important production database note

SQLite is intentionally used for a zero-setup local demo. Vercel functions have temporary storage, so vehicle records will not be durable there. Before opening this to customers, connect the same routes to a managed Postgres database (for example Supabase or Neon). Do not launch a customer-facing service centre on temporary SQLite storage.

## Environment variables

Copy `.env.example` to `.env` and replace only the values you need. Never commit `.env` or API keys to GitHub.
