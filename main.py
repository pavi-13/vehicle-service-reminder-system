"""VehicleCare - a lightweight vehicle service reminder web application."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from supabase import create_client, Client

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SECRET = os.getenv("APP_SECRET", "change-this-before-production")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

app = FastAPI(title="VehicleCare Service Reminder")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def realtime_client():
    """Return a server-only Supabase client when Realtime is configured."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key) if url and key else None


def publish_realtime_notification(user_id, subject, message, channels, created_at):
    """Mirror local notifications to Supabase Realtime table when configured."""
    client = realtime_client()
    if not client:
        return
    try:
        client.table("realtime_notifications").insert({
            "recipient_id": user_id,
            "subject": subject,
            "message": message,
            "channels": channels,
            "created_at": created_at,
        }).execute()
    except Exception:
        pass


def now():
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str, salt: Optional[str] = None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000)
    return f"{salt}${digest.hex()}"


def check_password(password: str, stored: str):
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def token_for(user):
    body = base64.urlsafe_b64encode(
        json.dumps({
            "id": user["id"],
            "role": user["role"],
            "exp": (datetime.now(timezone.utc) + timedelta(days=7)).timestamp(),
        }).encode()
    ).decode().rstrip("=")
    signature = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def get_user_by_id(user_id):
    result = (
        supabase.table("users")
        .select("id,name,email,phone,role")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_user_by_identifier(identifier):
    identifier = identifier.strip()
    result = (
        supabase.table("users")
        .select("*")
        .eq("email", identifier.lower())
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]

    result = (
        supabase.table("users")
        .select("*")
        .eq("phone", identifier)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def current_user(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Please login first")
    try:
        body, signature = auth[7:].split(".", 1)
        expected = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(body + "=="))
        if payload["exp"] < datetime.now(timezone.utc).timestamp():
            raise ValueError()

        user = get_user_by_id(payload["id"])
        if not user:
            raise ValueError()
        return user
    except Exception:
        raise HTTPException(401, "Your login has expired. Please login again.")


def admin_only(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def send_email(recipient, subject, message):
    """Send via any SMTP provider when SMTP_HOST and SMTP_USER are configured."""
    if not recipient or not os.getenv("SMTP_HOST") or not os.getenv("SMTP_USER"):
        return
    from_addr = os.getenv("EMAIL_FROM", os.getenv("SMTP_USER"))
    email = (
        f"From: {from_addr}\r\n"
        f"To: {recipient}\r\n"
        f"Subject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{message}"
    )
    with smtplib.SMTP_SSL(
        os.getenv("SMTP_HOST"),
        int(os.getenv("SMTP_PORT", "465")),
        timeout=12,
    ) as smtp:
        smtp.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
        smtp.sendmail(from_addr, [recipient], email.encode("utf-8"))


def send_sms(phone, message):
    """Send with Twilio when TWILIO_* variables are configured."""
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth = os.getenv("TWILIO_AUTH_TOKEN")
    sender = os.getenv("TWILIO_FROM")
    if not phone or not (sid and auth and sender):
        return
    body = urllib.parse.urlencode({
        "To": phone,
        "From": sender,
        "Body": message,
    }).encode()
    request = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=body,
        method="POST",
    )
    request.add_header(
        "Authorization",
        "Basic " + base64.b64encode(f"{sid}:{auth}".encode()).decode(),
    )
    with urllib.request.urlopen(request, timeout=12):
        pass


def notify(user_id, subject, message, channels="email,sms"):
    """Save a notification and deliver email/SMS when providers are configured."""
    created_at = now()
    supabase.table("notifications").insert({
        "user_id": user_id,
        "subject": subject,
        "message": message,
        "channels": channels,
        "created_at": created_at,
    }).execute()

    publish_realtime_notification(user_id, subject, message, channels, created_at)

    user = get_user_by_id(user_id)
    if not user:
        return

    try:
        send_email(user.get("email"), subject, message)
        send_sms(user.get("phone"), f"VehicleCare: {message}")
    except Exception:
        pass


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    identifier: str
    password: str


class OTPIn(BaseModel):
    identifier: str


class VerifyOTPIn(OTPIn):
    code: str


class VehicleIn(BaseModel):
    type: str
    brand: str
    model: str
    registration_no: str
    year: Optional[int] = None
    last_service_date: Optional[str] = None
    next_service_date: Optional[str] = None
    notes: Optional[str] = None


class JobIn(BaseModel):
    vehicle_id: int
    status: str = "Received"
    check_in_date: str = Field(default_factory=lambda: date.today().isoformat())
    expected_delivery_date: Optional[str] = None
    odometer: Optional[int] = None
    complaint: Optional[str] = None
    work_done: Optional[str] = None
    technician_notes: Optional[str] = None
    bill_amount: float = 0
    next_service_date: Optional[str] = None


class StatusIn(BaseModel):
    status: str
    work_done: Optional[str] = None
    technician_notes: Optional[str] = None
    bill_amount: Optional[float] = None
    next_service_date: Optional[str] = None


class FeedbackIn(BaseModel):
    job_id: Optional[int] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default="", max_length=1000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1500)


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/api/auth/register")
def register(data: RegisterIn):
    if not data.email and not data.phone:
        raise HTTPException(400, "Enter an email address or mobile number")

    email = data.email.lower().strip() if data.email else None
    phone = data.phone.strip() if data.phone else None

    try:
        existing = None
        if email:
            existing = (
                supabase.table("users")
                .select("id")
                .eq("email", email)
                .limit(1)
                .execute()
            ).data
        if not existing and phone:
            existing = (
                supabase.table("users")
                .select("id")
                .eq("phone", phone)
                .limit(1)
                .execute()
            ).data

        if existing:
            raise HTTPException(409, "This email or mobile number is already registered")

        result = supabase.table("users").insert({
            "name": data.name.strip(),
            "email": email,
            "phone": phone,
            "password_hash": hash_password(data.password),
            "role": "customer",
            "created_at": now(),
        }).execute()

        if not result.data:
            raise HTTPException(500, "Could not create account")

        user = {
            k: result.data[0].get(k)
            for k in ("id", "name", "email", "phone", "role")
        }
        notify(
            user["id"],
            "Welcome to VehicleCare",
            "Your account is ready. Add your vehicle to receive service reminders.",
        )
        return {"token": token_for(user), "user": user}

    except HTTPException:
        raise
    except Exception as exc:
        message = str(exc).lower()
        if "duplicate" in message or "unique" in message:
            raise HTTPException(409, "This email or mobile number is already registered")
        raise HTTPException(500, f"Account creation failed: {exc}")


@app.post("/api/auth/login")
def login(data: LoginIn):
    user = get_user_by_identifier(data.identifier)
    if not user or not check_password(data.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid email/mobile number or password")

    public_user = {
        k: user.get(k)
        for k in ("id", "name", "email", "phone", "role")
    }
    return {"token": token_for(public_user), "user": public_user}


# OTP is intentionally kept separate for the later real SMS/email OTP migration.
# The current production database migration does not activate real OTP delivery yet.
@app.post("/api/auth/request-otp")
def request_otp(data: OTPIn):
    raise HTTPException(501, "Real OTP will be connected later")


@app.post("/api/auth/verify-otp")
def verify_otp(data: VerifyOTPIn):
    raise HTTPException(501, "Real OTP will be connected later")


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


@app.get("/api/vehicles")
def vehicles(user=Depends(current_user)):
    query = (
        supabase.table("vehicles")
        .select("*, users!vehicles_owner_id_fkey(name)")
    )
    if user["role"] != "admin":
        result = query.eq("owner_id", user["id"]).order("id", desc=True).execute()
    else:
        result = query.order("id", desc=True).execute()

    output = []
    for item in result.data or []:
        owner = item.pop("users", None) or {}
        item["owner_name"] = owner.get("name")
        output.append(item)
    return output


@app.post("/api/vehicles")
def add_vehicle(data: VehicleIn, user=Depends(current_user)):
    result = supabase.table("vehicles").insert({
        "owner_id": user["id"],
        "type": data.type,
        "brand": data.brand,
        "model": data.model,
        "registration_no": data.registration_no.upper(),
        "year": data.year,
        "last_service_date": data.last_service_date,
        "next_service_date": data.next_service_date,
        "notes": data.notes,
        "created_at": now(),
    }).execute()

    if not result.data:
        raise HTTPException(500, "Could not add vehicle")
    return result.data[0]


@app.delete("/api/vehicles/{vehicle_id}")
def delete_vehicle(vehicle_id: int, user=Depends(current_user)):
    result = (
        supabase.table("vehicles")
        .select("*")
        .eq("id", vehicle_id)
        .limit(1)
        .execute()
    )
    vehicle = result.data[0] if result.data else None

    if not vehicle or (user["role"] != "admin" and vehicle["owner_id"] != user["id"]):
        raise HTTPException(404, "Vehicle not found")

    supabase.table("vehicles").delete().eq("id", vehicle_id).execute()
    return {"ok": True}


@app.get("/api/jobs")
def jobs(user=Depends(current_user)):
    vehicles_result = supabase.table("vehicles").select("*").execute()
    vehicles_by_id = {
        v["id"]: v for v in (vehicles_result.data or [])
        if user["role"] == "admin" or v["owner_id"] == user["id"]
    }

    jobs_result = supabase.table("service_jobs").select("*").order("id", desc=True).execute()
    users_result = supabase.table("users").select("id,name,email,phone").execute()
    users_by_id = {u["id"]: u for u in (users_result.data or [])}

    output = []
    for job in jobs_result.data or []:
        vehicle = vehicles_by_id.get(job["vehicle_id"])
        if not vehicle:
            continue
        owner = users_by_id.get(vehicle["owner_id"], {})
        item = dict(job)
        item.update({
            "brand": vehicle["brand"],
            "model": vehicle["model"],
            "type": vehicle["type"],
            "registration_no": vehicle["registration_no"],
            "owner_id": vehicle["owner_id"],
            "owner_name": owner.get("name"),
            "owner_email": owner.get("email"),
            "owner_phone": owner.get("phone"),
        })
        output.append(item)
    return output


@app.post("/api/jobs")
def create_job(data: JobIn, admin=Depends(admin_only)):
    vehicle_result = (
        supabase.table("vehicles")
        .select("*")
        .eq("id", data.vehicle_id)
        .limit(1)
        .execute()
    )
    vehicle = vehicle_result.data[0] if vehicle_result.data else None

    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    result = supabase.table("service_jobs").insert({
        "vehicle_id": data.vehicle_id,
        "status": data.status,
        "check_in_date": data.check_in_date,
        "expected_delivery_date": data.expected_delivery_date,
        "odometer": data.odometer,
        "complaint": data.complaint,
        "work_done": data.work_done,
        "technician_notes": data.technician_notes,
        "bill_amount": data.bill_amount,
        "next_service_date": data.next_service_date,
        "created_at": now(),
    }).execute()

    if not result.data:
        raise HTTPException(500, "Could not create service job")

    notify(
        vehicle["owner_id"],
        "Vehicle received",
        f"Your {vehicle['brand']} {vehicle['model']} ({vehicle['registration_no']}) "
        f"is checked in. Status: {data.status}.",
    )
    return result.data[0]


@app.patch("/api/jobs/{job_id}")
def update_job(job_id: int, data: StatusIn, admin=Depends(admin_only)):
    allowed = {
        "Received",
        "Inspection",
        "In Service",
        "Waiting for Parts",
        "Quality Check",
        "Ready for Pickup",
        "Completed",
    }
    if data.status not in allowed:
        raise HTTPException(400, "Invalid service status")

    job_result = (
        supabase.table("service_jobs")
        .select("*")
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    job = job_result.data[0] if job_result.data else None
    if not job:
        raise HTTPException(404, "Job not found")

    vehicle_result = (
        supabase.table("vehicles")
        .select("*")
        .eq("id", job["vehicle_id"])
        .limit(1)
        .execute()
    )
    vehicle = vehicle_result.data[0] if vehicle_result.data else None
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    completed = now() if data.status == "Completed" else job.get("completed_at")
    work_done = data.work_done if data.work_done is not None else job.get("work_done")
    notes = (
        data.technician_notes
        if data.technician_notes is not None
        else job.get("technician_notes")
    )
    bill = data.bill_amount if data.bill_amount is not None else job.get("bill_amount", 0)
    next_date = (
        data.next_service_date
        if data.next_service_date is not None
        else job.get("next_service_date")
    )

    supabase.table("service_jobs").update({
        "status": data.status,
        "work_done": work_done,
        "technician_notes": notes,
        "bill_amount": bill,
        "next_service_date": next_date,
        "completed_at": completed,
    }).eq("id", job_id).execute()

    if next_date:
        supabase.table("vehicles").update({
            "last_service_date": date.today().isoformat(),
            "next_service_date": next_date,
        }).eq("id", job["vehicle_id"]).execute()

    msg = f"{vehicle['brand']} {vehicle['model']} ({vehicle['registration_no']}) status: {data.status}."
    if data.status == "Completed":
        msg += (
            f" Service report: {work_done or 'completed'}."
            f" Bill: ₹{bill:.2f}."
            f" Next service: {next_date or 'contact service centre'}."
        )

    notify(vehicle["owner_id"], "Service update", msg)
    return {"ok": True, "message": msg}


@app.get("/api/notifications")
def notifications(user=Depends(current_user)):
    result = (
        supabase.table("notifications")
        .select("*")
        .eq("user_id", user["id"])
        .order("id", desc=True)
        .limit(30)
        .execute()
    )
    return result.data or []


@app.get("/api/dashboard")
def dashboard(user=Depends(current_user)):
    today = date.today().isoformat()

    vehicles_result = supabase.table("vehicles").select("*").execute()
    jobs_result = supabase.table("service_jobs").select("*").execute()

    vehicles_data = vehicles_result.data or []
    jobs_data = jobs_result.data or []

    if user["role"] == "admin":
        my_vehicles = vehicles_data
        my_jobs = jobs_data
    else:
        my_vehicles = [v for v in vehicles_data if v["owner_id"] == user["id"]]
        my_vehicle_ids = {v["id"] for v in my_vehicles}
        my_jobs = [j for j in jobs_data if j["vehicle_id"] in my_vehicle_ids]

    return {
        "vehicles": len(my_vehicles),
        "active_jobs": sum(1 for j in my_jobs if j["status"] != "Completed"),
        "completed_jobs": sum(1 for j in my_jobs if j["status"] == "Completed"),
        "due_services": sum(
            1 for v in my_vehicles
            if v.get("next_service_date") and v["next_service_date"] <= today
        ),
    }


@app.post("/api/feedback")
def leave_feedback(data: FeedbackIn, user=Depends(current_user)):
    result = supabase.table("feedback").insert({
        "user_id": user["id"],
        "job_id": data.job_id,
        "rating": data.rating,
        "comment": data.comment,
        "created_at": now(),
    }).execute()

    if not result.data:
        raise HTTPException(500, "Could not save feedback")
    return {"ok": True, "message": "Thank you for your feedback!"}


@app.get("/api/feedback")
def list_feedback(admin=Depends(admin_only)):
    feedback_result = (
        supabase.table("feedback")
        .select("*")
        .order("id", desc=True)
        .execute()
    )
    users_result = supabase.table("users").select("id,name").execute()
    users_by_id = {u["id"]: u for u in (users_result.data or [])}

    output = []
    for item in feedback_result.data or []:
        item = dict(item)
        item["customer_name"] = users_by_id.get(item["user_id"], {}).get("name")
        output.append(item)
    return output


def local_help(message: str):
    message = message.lower()
    if any(word in message for word in ("status", "service", "repair")):
        return "Open My Service to see your live vehicle status. If the job is completed, its report and bill appear there."
    if any(word in message for word in ("due", "reminder", "next")):
        return "Your next-service date is shown in My Vehicles. We will also create a reminder notification when a service is updated."
    if any(word in message for word in ("bill", "payment", "report")):
        return "After service completion, the service report, bill amount and next-service date are available in My Service."
    return "I can help with vehicles, live service status, service due dates, bills, reports and feedback. What do you need?"


@app.post("/api/chat")
def chat(data: ChatIn, user=Depends(current_user)):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"reply": local_help(data.message), "mode": "built-in help"}

    prompt = (
        "You are VehicleCare's concise, friendly 24/7 service assistant. "
        "Answer only vehicle-service app questions. Do not invent a booking, "
        "price, status, or policy. User says: " + data.message
    )
    payload = json.dumps({
        "model": os.getenv("OPENAI_MODEL", "gpt-6-astra"),
        "input": prompt,
        "reasoning": {"effort": "low"},
    }).encode()

    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            answer = json.loads(response.read())
        return {
            "reply": answer.get("output_text", local_help(data.message)),
            "mode": "OpenAI",
        }
    except Exception:
        return {
            "reply": local_help(data.message),
            "mode": "built-in help (AI unavailable)",
        }


@app.get("/api/health")
def health():
    return {"status": "ok", "time": now()}


@app.get("/api/realtime-config")
def realtime_config(user=Depends(current_user)):
    """Expose only the browser-safe Supabase config to signed-in app users."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    return {
        "enabled": bool(url and key),
        "url": url if url and key else None,
        "anon_key": key if url and key else None,
    }


@app.get("/api/cron/send-reminders")
def send_reminders(request: Request):
    """Daily Vercel Cron target. Requires CRON_SECRET in production."""
    secret = os.getenv("CRON_SECRET")
    if secret and request.headers.get("Authorization") != f"Bearer {secret}":
        raise HTTPException(401, "Invalid cron authorization")

    today = date.today()
    limit = (today + timedelta(days=30)).isoformat()
    sent = 0

    vehicles_result = (
        supabase.table("vehicles")
        .select("id,owner_id,brand,model,registration_no,next_service_date")
        .not_.is_("next_service_date", "null")
        .lte("next_service_date", limit)
        .execute()
    )

    for vehicle in vehicles_result.data or []:
        notification_result = (
            supabase.table("notifications")
            .select("id")
            .eq("user_id", vehicle["owner_id"])
            .eq("subject", "Service reminder")
            .gte("created_at", today.isoformat())
            .limit(1)
            .execute()
        )
        if notification_result.data:
            continue

        overdue = vehicle["next_service_date"] < today.isoformat()
        message = (
            f"Your {vehicle['brand']} {vehicle['model']} "
            f"({vehicle['registration_no']}) service is "
            f"{'overdue' if overdue else 'due on ' + vehicle['next_service_date']}. "
            "Please contact your service centre."
        )
        notify(vehicle["owner_id"], "Service reminder", message)
        sent += 1

    return {"ok": True, "reminders_sent": sent}