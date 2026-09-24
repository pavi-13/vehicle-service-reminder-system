"""VehicleCare - production-ready FastAPI + Supabase service workflow."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from supabase import create_client

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SECRET = os.getenv("APP_SECRET", "change-this-before-production")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    # The app can still import locally, but API calls will clearly explain the issue.
    print("WARNING: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not configured.")

app = FastAPI(title="VehicleCare Service Reminder")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

STAGES = [
    "Received",
    "Inspection",
    "Estimate Approved",
    "In Service",
    "Washing",
    "Engine Oil Change",
    "Repair / Parts",
    "Quality Check",
    "Ready for Pickup",
    "Completed",
]

SERVICE_TYPES = [
    "General Service",
    "Damage Repair",
    "Insurance Claim",
    "Accident Repair",
    "Engine / Mechanical",
    "Body & Paint",
    "AC / Electrical",
]

PAYMENT_METHODS = ["Pending", "Cash", "Online"]
PAYMENT_STATUSES = ["Pending", "Paid", "Failed"]


def sb():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(500, "Supabase environment variables are missing")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def now():
    return datetime.now(timezone.utc).isoformat()


def row(data):
    return data[0] if data else None


def hash_password(password: str, salt: Optional[str] = None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 310000)
    return f"{salt}${digest.hex()}"


def check_password(password: str, stored: str):
    try:
        return hmac.compare_digest(hash_password(password, stored.split("$", 1)[0]), stored)
    except Exception:
        return False


def token_for(user):
    payload = {
        "id": user["id"],
        "role": user["role"],
        "exp": (datetime.now(timezone.utc) + timedelta(days=7)).timestamp(),
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


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
        data = sb().table("users").select("id,name,email,phone,role").eq("id", payload["id"]).limit(1).execute().data
        user = row(data)
        if not user:
            raise ValueError()
        return user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Your login has expired. Please login again.")


def admin_only(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def send_email(recipient, subject, message):
    if not recipient or not os.getenv("SMTP_HOST") or not os.getenv("SMTP_USER"):
        return
    sender = os.getenv("EMAIL_FROM", os.getenv("SMTP_USER"))
    content = (
        f"From: {sender}\r\nTo: {recipient}\r\nSubject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n" + message
    )
    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "465")), timeout=12) as smtp:
        smtp.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
        smtp.sendmail(sender, [recipient], content.encode("utf-8"))


def send_sms(phone, message):
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth = os.getenv("TWILIO_AUTH_TOKEN")
    sender = os.getenv("TWILIO_FROM")
    if not phone or not (sid and auth and sender):
        return
    body = urllib.parse.urlencode({"To": phone, "From": sender, "Body": message}).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=body,
        method="POST",
    )
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{auth}".encode()).decode())
    with urllib.request.urlopen(req, timeout=12):
        pass


def notify(user_id, subject, message, channels="email,sms"):
    client = sb()
    created = now()
    client.table("notifications").insert({
        "user_id": user_id,
        "subject": subject,
        "message": message,
        "channels": channels,
        "created_at": created,
    }).execute()

    user = row(client.table("users").select("email,phone").eq("id", user_id).limit(1).execute().data)
    if not user:
        return
    try:
        send_email(user.get("email"), subject, message)
        send_sms(user.get("phone"), f"VehicleCare: {message}")
    except Exception:
        pass


def generate_token():
    return f"VC-{datetime.now().strftime('%y%m%d')}-{secrets.randbelow(9000)+1000}"


def get_job(job_id: int):
    client = sb()
    jobs = client.table("service_jobs").select(
        "*, vehicles!inner(id,owner_id,type,brand,model,registration_no,year), "
        "users!vehicles_owner_id_fkey(id,name,email,phone)"
    ).eq("id", job_id).limit(1).execute().data
    if jobs:
        return jobs[0]
    # Fallback if a generated FK relationship name differs.
    job = row(client.table("service_jobs").select("*").eq("id", job_id).limit(1).execute().data)
    if not job:
        return None
    vehicle = row(client.table("vehicles").select("*").eq("id", job["vehicle_id"]).limit(1).execute().data)
    owner = row(client.table("users").select("id,name,email,phone").eq("id", vehicle["owner_id"]).limit(1).execute().data) if vehicle else None
    job["vehicle"] = vehicle
    job["owner"] = owner
    return job


def enrich_job(job):
    if "vehicles" in job:
        vehicle = job["vehicles"]
        job["brand"] = vehicle.get("brand")
        job["model"] = vehicle.get("model")
        job["type"] = vehicle.get("type")
        job["registration_no"] = vehicle.get("registration_no")
        job["owner_id"] = vehicle.get("owner_id")
        job["owner_name"] = (job.get("users") or {}).get("name")
    elif job.get("vehicle"):
        vehicle = job["vehicle"]
        owner = job.get("owner") or {}
        job["brand"] = vehicle.get("brand")
        job["model"] = vehicle.get("model")
        job["type"] = vehicle.get("type")
        job["registration_no"] = vehicle.get("registration_no")
        job["owner_id"] = vehicle.get("owner_id")
        job["owner_name"] = owner.get("name")
    return job


def timeline_for(job_id: int):
    client = sb()
    data = client.table("service_timeline").select("*").eq("job_id", job_id).order("stage_order").execute().data
    return data or []


def build_job_response(job):
    job = enrich_job(job)
    job["timeline"] = timeline_for(job["id"])
    return job


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    identifier: str
    password: str


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
    check_in_date: str = Field(default_factory=lambda: date.today().isoformat())
    expected_delivery_date: Optional[str] = None
    service_type: str = "General Service"
    complaint: Optional[str] = None
    damage_details: Optional[str] = None
    insurance_details: Optional[str] = None
    estimate_amount: float = 0
    odometer: Optional[int] = None
    assigned_executive: Optional[str] = None


class StatusIn(BaseModel):
    status: str
    technician_notes: Optional[str] = None
    work_done: Optional[str] = None
    bill_amount: Optional[float] = None
    next_service_date: Optional[str] = None
    payment_method: Optional[str] = None
    payment_status: Optional[str] = None


class FeedbackIn(BaseModel):
    job_id: Optional[int] = None
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default="", max_length=1000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1500)


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "time": now(), "database": "supabase"}


@app.post("/api/auth/register")
def register(data: RegisterIn):
    if not data.email and not data.phone:
        raise HTTPException(400, "Enter an email address or mobile number")

    client = sb()
    email = data.email.lower().strip() if data.email else None
    phone = data.phone.strip() if data.phone else None

    if email and client.table("users").select("id").eq("email", email).limit(1).execute().data:
        raise HTTPException(409, "This email is already registered")
    if phone and client.table("users").select("id").eq("phone", phone).limit(1).execute().data:
        raise HTTPException(409, "This mobile number is already registered")

    created = client.table("users").insert({
        "name": data.name.strip(),
        "email": email,
        "phone": phone,
        "password_hash": hash_password(data.password),
        "role": "customer",
    }).execute().data
    user = row(created)
    if not user:
        raise HTTPException(500, "Could not create account")

    try:
        notify(user["id"], "Welcome to VehicleCare", "Your account is ready. Add your vehicle to begin.")
    except Exception:
        pass
    return {"token": token_for(user), "user": {k: user.get(k) for k in ("id","name","email","phone","role")}}


@app.post("/api/auth/login")
def login(data: LoginIn):
    identifier = data.identifier.strip()
    client = sb()
    by_email = client.table("users").select("*").ilike("email", identifier).limit(1).execute().data if "@" in identifier else []
    user = row(by_email)
    if not user:
        user = row(client.table("users").select("*").eq("phone", identifier).limit(1).execute().data)
    if not user or not check_password(data.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid email/mobile number or password")
    public = {k: user.get(k) for k in ("id","name","email","phone","role")}
    return {"token": token_for(public), "user": public}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


@app.get("/api/vehicles")
def vehicles(user=Depends(current_user)):
    client = sb()
    query = client.table("vehicles").select("*")
    if user["role"] != "admin":
        query = query.eq("owner_id", user["id"])
    data = query.order("id", desc=True).execute().data or []

    for v in data:
        jobs = client.table("service_jobs").select("id,status,service_type,token_number,check_in_date,bill_amount,payment_status").eq("vehicle_id", v["id"]).order("id", desc=True).execute().data or []
        v["service_count"] = len(jobs)
        v["current_job"] = jobs[0] if jobs and jobs[0].get("status") != "Completed" else None
        v["last_job"] = jobs[0] if jobs else None
    return data


@app.get("/api/vehicles/{vehicle_id}")
def vehicle_detail(vehicle_id: int, user=Depends(current_user)):
    client = sb()
    vehicle = row(client.table("vehicles").select("*").eq("id", vehicle_id).limit(1).execute().data)
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")
    if user["role"] != "admin" and vehicle["owner_id"] != user["id"]:
        raise HTTPException(404, "Vehicle not found")

    owner = row(client.table("users").select("id,name,email,phone").eq("id", vehicle["owner_id"]).limit(1).execute().data)
    jobs = client.table("service_jobs").select("*").eq("vehicle_id", vehicle_id).order("id", desc=True).execute().data or []
    for j in jobs:
        j["timeline"] = timeline_for(j["id"])
    return {"vehicle": vehicle, "owner": owner, "service_count": len(jobs), "history": jobs}


@app.post("/api/vehicles")
def add_vehicle(data: VehicleIn, user=Depends(current_user)):
    client = sb()
    registration = data.registration_no.strip().upper()
    existing = client.table("vehicles").select("id").eq("registration_no", registration).limit(1).execute().data
    if existing:
        raise HTTPException(409, "This registration number is already registered")
    created = client.table("vehicles").insert({
        "owner_id": user["id"],
        "type": data.type,
        "brand": data.brand.strip(),
        "model": data.model.strip(),
        "registration_no": registration,
        "year": data.year,
        "last_service_date": data.last_service_date,
        "next_service_date": data.next_service_date,
        "notes": data.notes,
    }).execute().data
    return row(created)


@app.delete("/api/vehicles/{vehicle_id}")
def delete_vehicle(vehicle_id: int, user=Depends(current_user)):
    client = sb()
    vehicle = row(client.table("vehicles").select("*").eq("id", vehicle_id).limit(1).execute().data)
    if not vehicle or (user["role"] != "admin" and vehicle["owner_id"] != user["id"]):
        raise HTTPException(404, "Vehicle not found")
    client.table("vehicles").delete().eq("id", vehicle_id).execute()
    return {"ok": True}


@app.get("/api/jobs")
def jobs(user=Depends(current_user)):
    client = sb()
    vehicles_query = client.table("vehicles").select("*")
    if user["role"] != "admin":
        vehicles_query = vehicles_query.eq("owner_id", user["id"])
    vs = vehicles_query.execute().data or []
    vehicle_map = {v["id"]: v for v in vs}
    if not vehicle_map:
        return []

    ids = list(vehicle_map.keys())
    data = client.table("service_jobs").select("*").in_("vehicle_id", ids).order("id", desc=True).execute().data or []
    owners = {}
    for v in vs:
        owners[v["owner_id"]] = v
    result = []
    for j in data:
        v = vehicle_map.get(j["vehicle_id"], {})
        j.update({
            "brand": v.get("brand"),
            "model": v.get("model"),
            "type": v.get("type"),
            "registration_no": v.get("registration_no"),
            "owner_id": v.get("owner_id"),
        })
        owner = row(client.table("users").select("id,name,email,phone").eq("id", v.get("owner_id")).limit(1).execute().data)
        j["owner_name"] = owner.get("name") if owner else "Customer"
        j["timeline"] = timeline_for(j["id"])
        result.append(j)
    return result


@app.post("/api/jobs")
def create_job(data: JobIn, admin=Depends(admin_only)):
    if data.service_type not in SERVICE_TYPES:
        raise HTTPException(400, "Invalid service type")

    client = sb()
    vehicle = row(client.table("vehicles").select("*").eq("id", data.vehicle_id).limit(1).execute().data)
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    active = client.table("service_jobs").select("id,status").eq("vehicle_id", data.vehicle_id).neq("status", "Completed").limit(1).execute().data
    if active:
        raise HTTPException(409, "This vehicle already has an active service job")

    token_number = generate_token()
    payload = {
        "vehicle_id": data.vehicle_id,
        "token_number": token_number,
        "status": "Received",
        "check_in_date": data.check_in_date,
        "expected_delivery_date": data.expected_delivery_date,
        "service_type": data.service_type,
        "complaint": data.complaint,
        "damage_details": data.damage_details,
        "insurance_details": data.insurance_details,
        "estimate_amount": data.estimate_amount,
        "odometer": data.odometer,
        "assigned_executive": data.assigned_executive,
        "bill_amount": 0,
        "payment_method": "Pending",
        "payment_status": "Pending",
        "created_at": now(),
    }
    created = client.table("service_jobs").insert(payload).execute().data
    job = row(created)
    if not job:
        raise HTTPException(500, "Could not create service job")

    timeline_rows = []
    for i, stage in enumerate(STAGES):
        timeline_rows.append({
            "job_id": job["id"],
            "stage": stage,
            "stage_order": i,
            "status": "Current" if i == 0 else "Pending",
            "notes": "Vehicle checked in" if i == 0 else None,
            "updated_at": now() if i == 0 else None,
        })
    client.table("service_timeline").insert(timeline_rows).execute()

    message = (
        f"Your {vehicle['brand']} {vehicle['model']} ({vehicle['registration_no']}) "
        f"is checked in. Token: {token_number}. Service: {data.service_type}. "
        "Current status: Received."
    )
    try:
        notify(vehicle["owner_id"], "Vehicle checked in", message)
    except Exception:
        pass
    return build_job_response(job)


@app.patch("/api/jobs/{job_id}")
def update_job(job_id: int, data: StatusIn, admin=Depends(admin_only)):
    if data.status not in STAGES:
        raise HTTPException(400, "Invalid service status")
    if data.payment_method and data.payment_method not in PAYMENT_METHODS:
        raise HTTPException(400, "Invalid payment method")
    if data.payment_status and data.payment_status not in PAYMENT_STATUSES:
        raise HTTPException(400, "Invalid payment status")

    client = sb()
    job = row(client.table("service_jobs").select("*").eq("id", job_id).limit(1).execute().data)
    if not job:
        raise HTTPException(404, "Service job not found")
    vehicle = row(client.table("vehicles").select("*").eq("id", job["vehicle_id"]).limit(1).execute().data)
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    update = {
        "status": data.status,
        "updated_at": now(),
    }
    for key in ("technician_notes", "work_done", "bill_amount", "next_service_date", "payment_method", "payment_status"):
        value = getattr(data, key)
        if value is not None:
            update[key] = value
    if data.status == "Completed":
        update["completed_at"] = now()

    updated = row(client.table("service_jobs").update(update).eq("id", job_id).execute().data)

    # Mark timeline stages.
    current_index = STAGES.index(data.status)
    for i, stage in enumerate(STAGES):
        if i < current_index:
            stage_status = "Completed"
        elif i == current_index:
            stage_status = "Current" if data.status != "Completed" else "Completed"
        else:
            stage_status = "Pending"
        client.table("service_timeline").update({
            "status": stage_status,
            "updated_at": now() if i <= current_index else None,
        }).eq("job_id", job_id).eq("stage_order", i).execute()

    if data.next_service_date:
        client.table("vehicles").update({
            "last_service_date": date.today().isoformat(),
            "next_service_date": data.next_service_date,
        }).eq("id", vehicle["id"]).execute()

    message = f"{vehicle['brand']} {vehicle['model']} ({vehicle['registration_no']}) status updated to {data.status}."
    if data.status == "Completed":
        message += (
            f" Bill: ₹{float(update.get('bill_amount', job.get('bill_amount') or 0)):.2f}."
            f" Payment: {update.get('payment_method', job.get('payment_method') or 'Pending')}."
            f" Report: {update.get('work_done', job.get('work_done') or 'Service completed')}."
        )
    try:
        notify(vehicle["owner_id"], "Service update", message)
    except Exception:
        pass

    return {"ok": True, "message": message, "job": build_job_response(updated or job)}


@app.get("/api/notifications")
def notifications(user=Depends(current_user)):
    return sb().table("notifications").select("*").eq("user_id", user["id"]).order("id", desc=True).limit(50).execute().data or []

@app.post("/api/notifications/read")
def mark_notifications_read(user=Depends(current_user)):
    client = sb()

    client.table("notifications").update({
        "read_at": now()
    }).eq(
        "user_id",
        user["id"]
    ).is_(
        "read_at",
        "null"
    ).execute()

    return {
        "ok": True,
        "message": "Notifications marked as read"
    }

@app.get("/api/dashboard")
def dashboard(user=Depends(current_user)):
    client = sb()
    if user["role"] == "admin":
        vehicles = client.table("vehicles").select("id", count="exact").execute()
        jobs = client.table("service_jobs").select("id,status").execute().data or []
        due = client.table("vehicles").select("id").lte("next_service_date", date.today().isoformat()).execute().data or []
    else:
        vehicles = client.table("vehicles").select("id", count="exact").eq("owner_id", user["id"]).execute()
        vs = client.table("vehicles").select("id").eq("owner_id", user["id"]).execute().data or []
        ids = [v["id"] for v in vs]
        jobs = client.table("service_jobs").select("id,status").in_("vehicle_id", ids).execute().data if ids else []
        jobs = jobs.data if hasattr(jobs, "data") else (jobs or [])
        due = client.table("vehicles").select("id").eq("owner_id", user["id"]).lte("next_service_date", date.today().isoformat()).execute().data or []

    return {
        "vehicles": vehicles.count or 0,
        "active_jobs": sum(1 for j in jobs if j["status"] != "Completed"),
        "completed_jobs": sum(1 for j in jobs if j["status"] == "Completed"),
        "due_services": len(due),
    }


@app.post("/api/feedback")
def leave_feedback(data: FeedbackIn, user=Depends(current_user)):
    payload = {
        "user_id": user["id"],
        "job_id": data.job_id,
        "rating": data.rating,
        "comment": data.comment,
        "created_at": now(),
    }
    sb().table("feedback").insert(payload).execute()
    return {"ok": True, "message": "Thank you for your feedback!"}


@app.get("/api/feedback")
def list_feedback(admin=Depends(admin_only)):
    data = sb().table("feedback").select("*").order("id", desc=True).limit(50).execute().data or []
    client = sb()
    for f in data:
        u = row(client.table("users").select("name").eq("id", f["user_id"]).limit(1).execute().data)
        f["customer_name"] = u["name"] if u else "Customer"
    return data


@app.get("/api/feedback/my")
def my_feedback(job_id: Optional[int] = None, user=Depends(current_user)):
    """Feedback submitted by the logged-in customer (optionally for one service job)."""
    query = sb().table("feedback").select("*").eq("user_id", user["id"])
    if job_id is not None:
        query = query.eq("job_id", job_id)
    return query.order("id", desc=True).limit(20).execute().data or []


@app.get("/api/admin/vehicle-search")
def vehicle_search(q: str = "", admin=Depends(admin_only)):
    q = q.strip().upper()
    if not q:
        return []
    client = sb()
    data = client.table("vehicles").select("*").ilike("registration_no", f"%{q}%").limit(10).execute().data or []
    for v in data:
        owner = row(client.table("users").select("name,email,phone").eq("id", v["owner_id"]).limit(1).execute().data)
        v["owner_name"] = owner.get("name") if owner else "Customer"
        active = client.table("service_jobs").select("id,status,token_number,service_type").eq("vehicle_id", v["id"]).neq("status", "Completed").limit(1).execute().data
        v["active_job"] = row(active)
    return data


@app.get("/api/admin/vehicle/{vehicle_id}/history")
def admin_vehicle_history(vehicle_id: int, admin=Depends(admin_only)):
    return vehicle_detail(vehicle_id, admin)


@app.get("/api/service-types")
def service_types(admin=Depends(admin_only)):
    return {"service_types": SERVICE_TYPES, "stages": STAGES}


def local_help(message: str):
    m = message.lower()
    if "status" in m or "service" in m:
        return "Open My Service to see the vehicle's current stage and complete timeline."
    if "bill" in m or "payment" in m or "report" in m:
        return "After completion, the service card shows the bill, payment method and service report."
    if "history" in m:
        return "Open My Vehicles and click a vehicle to see all previous services."
    return "I can help with vehicle status, service history, bills, reports, reminders and service updates."


@app.post("/api/chat")
def chat(data: ChatIn, user=Depends(current_user)):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"reply": local_help(data.message), "mode": "built-in help"}
    return {"reply": local_help(data.message), "mode": "built-in help"}


@app.get("/api/realtime-config")
def realtime_config(user=Depends(current_user)):
    # Browser-safe key only. Never expose the service-role key.
    key = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_PUBLISHABLE_KEY")
    return {"enabled": bool(SUPABASE_URL and key), "url": SUPABASE_URL if key else None, "anon_key": key if key else None}


@app.get("/api/cron/send-reminders")
def send_reminders(request: Request):
    secret = os.getenv("CRON_SECRET")
    if secret and request.headers.get("Authorization") != f"Bearer {secret}":
        raise HTTPException(401, "Invalid cron authorization")

    client = sb()
    limit = (date.today() + timedelta(days=30)).isoformat()
    due = client.table("vehicles").select(
        "id,owner_id,brand,model,registration_no,next_service_date"
    ).not_.is_("next_service_date", "null").lte("next_service_date", limit).execute().data or []

    sent = 0
    for vehicle in due:
        # Avoid duplicate reminder on the same date.
        start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc).isoformat()
        already = client.table("notifications").select("id").eq(
            "user_id", vehicle["owner_id"]
        ).eq("subject", "Service reminder").gte("created_at", start).limit(1).execute().data
        if already:
            continue
        overdue = vehicle["next_service_date"] < date.today().isoformat()
        msg = (
            f"Your {vehicle['brand']} {vehicle['model']} ({vehicle['registration_no']}) "
            f"service is {'overdue' if overdue else 'due on ' + vehicle['next_service_date']}."
        )
        try:
            notify(vehicle["owner_id"], "Service reminder", msg)
            sent += 1
        except Exception:
            pass
    return {"ok": True, "reminders_sent": sent}