"""VehicleCare production service workflow.

Supabase Postgres is the source of truth. OTP is intentionally left for the later
Supabase Auth + SMS/email provider migration.
"""
import base64, hashlib, hmac, json, os, secrets, smtplib, urllib.request, urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from supabase import create_client, Client

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SECRET = os.getenv("APP_SECRET", "change-this-before-production")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
app = FastAPI(title="VehicleCare Service Reminder")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

STATUS_FLOW = ["Received","Inspection","Estimate Approved","In Service","Washing","Engine Oil Change","Repair / Parts","Quality Check","Ready for Pickup","Completed"]
SERVICE_TYPES = ["General Service","Damage Repair","Insurance Claim","Accident Repair","Engine / Mechanical","Body & Paint","AC / Electrical","Other"]
PROBLEM_TYPES = ["General service","Engine","Brake","Tyre / Wheel","Battery","AC","Electrical","Body damage","Accident damage","Insurance claim","Other"]

def now(): return datetime.now(timezone.utc).isoformat()
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 310000).hex()}"
def check_password(password, stored):
    try: salt, _ = stored.split("$",1)
    except ValueError: return False
    return hmac.compare_digest(hash_password(password,salt), stored)
def token_for(user):
    body=base64.urlsafe_b64encode(json.dumps({"id":user["id"],"role":user["role"],"exp":(datetime.now(timezone.utc)+timedelta(days=7)).timestamp()}).encode()).decode().rstrip("=")
    return body+"."+hmac.new(SECRET.encode(),body.encode(),hashlib.sha256).hexdigest()
def get_user_by_id(uid):
    r=supabase.table("users").select("id,name,email,phone,role").eq("id",uid).limit(1).execute()
    return r.data[0] if r.data else None
def get_user_by_identifier(x):
    x=x.strip()
    r=supabase.table("users").select("*").eq("email",x.lower()).limit(1).execute()
    if r.data:return r.data[0]
    r=supabase.table("users").select("*").eq("phone",x).limit(1).execute()
    return r.data[0] if r.data else None
def current_user(request:Request):
    auth=request.headers.get("Authorization","")
    if not auth.startswith("Bearer "): raise HTTPException(401,"Please login first")
    try:
        body,sig=auth[7:].split(".",1)
        if not hmac.compare_digest(sig,hmac.new(SECRET.encode(),body.encode(),hashlib.sha256).hexdigest()): raise ValueError()
        p=json.loads(base64.urlsafe_b64decode(body+"=="))
        if p["exp"]<datetime.now(timezone.utc).timestamp(): raise ValueError()
        u=get_user_by_id(p["id"])
        if not u: raise ValueError()
        return u
    except Exception: raise HTTPException(401,"Your login has expired. Please login again.")
def admin_only(user=Depends(current_user)):
    if user["role"]!="admin": raise HTTPException(403,"Admin access required")
    return user

def send_email(to,subject,message):
    if not to or not os.getenv("SMTP_HOST") or not os.getenv("SMTP_USER"): return False
    try:
        sender=os.getenv("EMAIL_FROM",os.getenv("SMTP_USER"))
        msg=f"From: {sender}\r\nTo: {to}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{message}"
        with smtplib.SMTP_SSL(os.getenv("SMTP_HOST"),int(os.getenv("SMTP_PORT","465")),timeout=12) as s:
            s.login(os.getenv("SMTP_USER"),os.getenv("SMTP_PASSWORD","")); s.sendmail(sender,[to],msg.encode())
        return True
    except Exception: return False
def send_sms(phone,message):
    sid,auth,sender=os.getenv("TWILIO_ACCOUNT_SID"),os.getenv("TWILIO_AUTH_TOKEN"),os.getenv("TWILIO_FROM")
    if not phone or not (sid and auth and sender): return False
    try:
        body=urllib.parse.urlencode({"To":phone,"From":sender,"Body":message}).encode()
        req=urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",data=body,method="POST")
        req.add_header("Authorization","Basic "+base64.b64encode(f"{sid}:{auth}".encode()).decode())
        urllib.request.urlopen(req,timeout=12).close(); return True
    except Exception:return False
def notify(uid,subject,message):
    created=now()
    try:
        supabase.table("notifications").insert({"user_id":uid,"subject":subject,"message":message,"channels":"in_app,email,sms","created_at":created}).execute()
        supabase.table("realtime_notifications").insert({"recipient_id":uid,"subject":subject,"message":message,"channels":"in_app,email,sms","created_at":created}).execute()
    except Exception: pass
    u=get_user_by_id(uid)
    if u:
        send_email(u.get("email"),subject,message); send_sms(u.get("phone"),"VehicleCare: "+message)

def vehicle_for(vid):
    r=supabase.table("vehicles").select("*").eq("id",vid).limit(1).execute()
    return r.data[0] if r.data else None
def job_for(jid):
    r=supabase.table("service_jobs").select("*").eq("id",jid).limit(1).execute()
    return r.data[0] if r.data else None
def job_view(job):
    v=vehicle_for(job["vehicle_id"])
    if not v:return None
    u=get_user_by_id(v["owner_id"]) or {}
    job=dict(job); job.update({"brand":v["brand"],"model":v["model"],"type":v["type"],"registration_no":v["registration_no"],
        "owner_id":v["owner_id"],"owner_name":u.get("name"),"owner_email":u.get("email"),"owner_phone":u.get("phone")})
    return job

class RegisterIn(BaseModel):
    name:str=Field(min_length=2,max_length=80); email:Optional[str]=None; phone:Optional[str]=None; password:str=Field(min_length=6,max_length=128)
class LoginIn(BaseModel): identifier:str; password:str
class OTPIn(BaseModel): identifier:str
class VerifyOTPIn(OTPIn): code:str
class VehicleIn(BaseModel):
    type:str; brand:str; model:str; registration_no:str; year:Optional[int]=None; last_service_date:Optional[str]=None; next_service_date:Optional[str]=None; notes:Optional[str]=None
class JobIn(BaseModel):
    vehicle_id:int; service_type:str="General Service"; problem_type:str="General service"; complaint:str=""
    damage_notes:Optional[str]=None; insurance_claim:bool=False; estimate_amount:float=0; status:str="Received"
    expected_delivery_date:Optional[str]=None; odometer:Optional[int]=None; assigned_to:Optional[str]=None
class StatusIn(BaseModel):
    status:str; work_done:Optional[str]=None; technician_notes:Optional[str]=None; bill_amount:Optional[float]=None
    next_service_date:Optional[str]=None; expected_delivery_date:Optional[str]=None; assigned_to:Optional[str]=None
class EventIn(BaseModel): status:str; note:Optional[str]=""; technician:Optional[str]=None
class PaymentIn(BaseModel): method:str; amount:float=Field(ge=0)
class FeedbackIn(BaseModel): job_id:Optional[int]=None; rating:int=Field(ge=1,le=5); comment:Optional[str]=""
class ChatIn(BaseModel): message:str=Field(min_length=1,max_length=1500)

@app.get("/")
def home(): return FileResponse(ROOT/"static"/"index.html")

@app.post("/api/auth/register")
def register(d:RegisterIn):
    if not d.email and not d.phone: raise HTTPException(400,"Enter an email address or mobile number")
    email=d.email.lower().strip() if d.email else None; phone=d.phone.strip() if d.phone else None
    try:
        if email and supabase.table("users").select("id").eq("email",email).limit(1).execute().data: raise HTTPException(409,"This email is already registered")
        if phone and supabase.table("users").select("id").eq("phone",phone).limit(1).execute().data: raise HTTPException(409,"This mobile number is already registered")
        r=supabase.table("users").insert({"name":d.name.strip(),"email":email,"phone":phone,"password_hash":hash_password(d.password),"role":"customer","created_at":now()}).execute()
        if not r.data: raise HTTPException(500,"Could not create account")
        u={k:r.data[0].get(k) for k in ("id","name","email","phone","role")}; notify(u["id"],"Welcome to VehicleCare","Your account is ready. Add your vehicle to receive service reminders.")
        return {"token":token_for(u),"user":u}
    except HTTPException: raise
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower(): raise HTTPException(409,"Email or mobile number is already registered")
        raise HTTPException(500,"Account creation failed")

@app.post("/api/auth/login")
def login(d:LoginIn):
    u=get_user_by_identifier(d.identifier)
    if not u or not check_password(d.password,u.get("password_hash","")): raise HTTPException(401,"Invalid email/mobile number or password")
    p={k:u.get(k) for k in ("id","name","email","phone","role")}; return {"token":token_for(p),"user":p}
@app.post("/api/auth/request-otp")
def request_otp(d:OTPIn): raise HTTPException(501,"Real OTP will be connected later")
@app.post("/api/auth/verify-otp")
def verify_otp(d:VerifyOTPIn): raise HTTPException(501,"Real OTP will be connected later")
@app.get("/api/me")
def me(u=Depends(current_user)): return u

@app.get("/api/vehicles")
def vehicles(u=Depends(current_user)):
    r=supabase.table("vehicles").select("*").order("id",desc=True).execute()
    out=[]
    for v in r.data or []:
        if u["role"]!="admin" and v["owner_id"]!=u["id"]: continue
        v=dict(v); owner=get_user_by_id(v["owner_id"]) or {}; v["owner_name"]=owner.get("name"); out.append(v)
    return out
@app.post("/api/vehicles")
def add_vehicle(d:VehicleIn,u=Depends(current_user)):
    r=supabase.table("vehicles").insert({"owner_id":u["id"],"type":d.type,"brand":d.brand,"model":d.model,"registration_no":d.registration_no.upper(),
        "year":d.year,"last_service_date":d.last_service_date,"next_service_date":d.next_service_date,"notes":d.notes,"created_at":now()}).execute()
    if not r.data: raise HTTPException(500,"Could not add vehicle")
    return r.data[0]
@app.delete("/api/vehicles/{vid}")
def delete_vehicle(vid:int,u=Depends(current_user)):
    v=vehicle_for(vid)
    if not v or (u["role"]!="admin" and v["owner_id"]!=u["id"]): raise HTTPException(404,"Vehicle not found")
    supabase.table("vehicles").delete().eq("id",vid).execute(); return {"ok":True}

@app.get("/api/jobs")
def jobs(u=Depends(current_user)):
    r=supabase.table("service_jobs").select("*").order("id",desc=True).execute(); out=[]
    for j in r.data or []:
        x=job_view(j)
        if x and (u["role"]=="admin" or x["owner_id"]==u["id"]): out.append(x)
    return out
@app.post("/api/jobs")
def create_job(d:JobIn,admin=Depends(admin_only)):
    v=vehicle_for(d.vehicle_id)
    if not v: raise HTTPException(404,"Vehicle not found")
    token=f"VC-{datetime.now().strftime('%y%m%d')}-{secrets.randbelow(900)+100}"
    payload={"vehicle_id":d.vehicle_id,"token_no":token,"service_type":d.service_type,"problem_type":d.problem_type,"complaint":d.complaint,
        "damage_notes":d.damage_notes,"insurance_claim":d.insurance_claim,"estimate_amount":d.estimate_amount,"status":d.status,
        "check_in_date":date.today().isoformat(),"expected_delivery_date":d.expected_delivery_date,"odometer":d.odometer,"assigned_to":d.assigned_to,"created_at":now()}
    r=supabase.table("service_jobs").insert(payload).execute()
    if not r.data: raise HTTPException(500,"Could not create service job")
    j=r.data[0]
    supabase.table("service_events").insert({"job_id":j["id"],"status":d.status,"note":"Vehicle checked in and token created.","technician":d.assigned_to,"created_at":now()}).execute()
    notify(v["owner_id"],"Vehicle received",f"Token {token}: {v['brand']} {v['model']} ({v['registration_no']}) checked in. Current status: {d.status}.")
    return job_view(j)

@app.patch("/api/jobs/{jid}")
def update_job(jid:int,d:StatusIn,admin=Depends(admin_only)):
    if d.status not in STATUS_FLOW: raise HTTPException(400,"Invalid service status")
    j=job_for(jid)
    if not j: raise HTTPException(404,"Job not found")
    v=vehicle_for(j["vehicle_id"])
    patch={"status":d.status}
    for k in ("work_done","technician_notes","bill_amount","next_service_date","expected_delivery_date","assigned_to"):
        val=getattr(d,k)
        if val is not None: patch[k]=val
    if d.status=="Completed": patch["completed_at"]=now()
    r=supabase.table("service_jobs").update(patch).eq("id",jid).execute()
    supabase.table("service_events").insert({"job_id":jid,"status":d.status,"note":d.work_done or d.technician_notes or "Status updated by service centre.","technician":d.assigned_to or j.get("assigned_to"),"created_at":now()}).execute()
    if d.next_service_date: supabase.table("vehicles").update({"last_service_date":date.today().isoformat(),"next_service_date":d.next_service_date}).eq("id",j["vehicle_id"]).execute()
    if d.status=="Completed":
        bill=float(d.bill_amount if d.bill_amount is not None else j.get("bill_amount") or 0)
        report=d.work_done or j.get("work_done") or "Service completed."
        msg=f"{v['brand']} {v['model']} ({v['registration_no']}) service completed. Bill: ₹{bill:.2f}. Report: {report}. Payment can be completed online or at pickup by cash."
        notify(v["owner_id"],"Service completed - bill & report",msg)
    else: notify(v["owner_id"],"Service update",f"Token {j.get('token_no','')}: {v['brand']} {v['model']} status changed to {d.status}.")
    return {"ok":True,"job":job_view({**j,**patch})}

@app.get("/api/jobs/{jid}/timeline")
def timeline(jid:int,u=Depends(current_user)):
    j=job_for(jid)
    if not j: raise HTTPException(404,"Job not found")
    v=vehicle_for(j["vehicle_id"])
    if u["role"]!="admin" and (not v or v["owner_id"]!=u["id"]): raise HTTPException(403,"Not allowed")
    r=supabase.table("service_events").select("*").eq("job_id",jid).order("id",desc=False).execute()
    return r.data or []

@app.post("/api/jobs/{jid}/events")
def add_event(jid:int,d:EventIn,admin=Depends(admin_only)):
    if d.status not in STATUS_FLOW: raise HTTPException(400,"Invalid status")
    j=job_for(jid)
    if not j: raise HTTPException(404,"Job not found")
    v=vehicle_for(j["vehicle_id"])
    supabase.table("service_events").insert({"job_id":jid,"status":d.status,"note":d.note or "Service progress updated.","technician":d.technician or j.get("assigned_to"),"created_at":now()}).execute()
    supabase.table("service_jobs").update({"status":d.status,"assigned_to":d.technician or j.get("assigned_to")}).eq("id",jid).execute()
    notify(v["owner_id"],"Live service progress",f"Token {j.get('token_no','')}: {v['brand']} {v['model']} is now at '{d.status}'. {d.note or ''}".strip())
    return {"ok":True}

@app.post("/api/jobs/{jid}/payment")
def payment(jid:int,d:PaymentIn,u=Depends(current_user)):
    j=job_for(jid)
    if not j: raise HTTPException(404,"Job not found")
    v=vehicle_for(j["vehicle_id"])
    if u["role"]!="admin" and v["owner_id"]!=u["id"]: raise HTTPException(403,"Not allowed")
    method=d.method.lower()
    if method not in ("online","cash"): raise HTTPException(400,"Payment method must be online or cash")
    status="Paid" if method=="online" else "Cash at pickup"
    r=supabase.table("payments").insert({"job_id":jid,"amount":d.amount,"method":method,"status":status,"paid_at":now() if method=="online" else None,"created_at":now()}).execute()
    if not r.data: raise HTTPException(500,"Could not save payment")
    if method=="online": notify(v["owner_id"],"Payment received",f"Payment of ₹{d.amount:.2f} received for token {j.get('token_no','')}.")
    return r.data[0]

@app.get("/api/jobs/{jid}/payments")
def payments(jid:int,u=Depends(current_user)):
    j=job_for(jid)
    if not j: raise HTTPException(404,"Job not found")
    v=vehicle_for(j["vehicle_id"])
    if u["role"]!="admin" and v["owner_id"]!=u["id"]: raise HTTPException(403,"Not allowed")
    return supabase.table("payments").select("*").eq("job_id",jid).order("id",desc=True).execute().data or []

@app.get("/api/notifications")
def notifications(u=Depends(current_user)):
    return supabase.table("notifications").select("*").eq("user_id",u["id"]).order("id",desc=True).limit(50).execute().data or []
@app.get("/api/dashboard")
def dashboard(u=Depends(current_user)):
    vs=supabase.table("vehicles").select("*").execute().data or []; js=supabase.table("service_jobs").select("*").execute().data or []
    if u["role"]=="customer":
        vs=[v for v in vs if v["owner_id"]==u["id"]]; ids={v["id"] for v in vs}; js=[j for j in js if j["vehicle_id"] in ids]
    today=date.today().isoformat()
    return {"vehicles":len(vs),"active_jobs":sum(j["status"]!="Completed" for j in js),"completed_jobs":sum(j["status"]=="Completed" for j in js),
            "due_services":sum(bool(v.get("next_service_date") and v["next_service_date"]<=today) for v in vs)}

@app.get("/api/service-options")
def service_options(admin=Depends(admin_only)): return {"statuses":STATUS_FLOW,"service_types":SERVICE_TYPES,"problem_types":PROBLEM_TYPES}

@app.post("/api/feedback")
def feedback(d:FeedbackIn,u=Depends(current_user)):
    r=supabase.table("feedback").insert({"user_id":u["id"],"job_id":d.job_id,"rating":d.rating,"comment":d.comment,"created_at":now()}).execute()
    return {"ok":bool(r.data)}
@app.get("/api/feedback")
def list_feedback(admin=Depends(admin_only)):
    r=supabase.table("feedback").select("*").order("id",desc=True).execute().data or []
    for x in r: x["customer_name"]=(get_user_by_id(x["user_id"]) or {}).get("name")
    return r

@app.post("/api/chat")
def chat(d:ChatIn,u=Depends(current_user)):
    m=d.message.lower()
    if "status" in m or "service" in m:return {"reply":"Open My Service to see your live timeline, current stage, complaint and service report.","mode":"built-in help"}
    if "bill" in m or "payment" in m:return {"reply":"When your service is completed, the bill and report appear in My Service. You can choose online payment or cash at pickup.","mode":"built-in help"}
    if "reminder" in m or "due" in m:return {"reply":"Your next-service date and reminders are available in Reminders.","mode":"built-in help"}
    return {"reply":"I can help with service status, timeline, bill, payment, reminders and vehicle details.","mode":"built-in help"}

@app.get("/api/health")
def health(): return {"status":"ok","time":now()}
@app.get("/api/realtime-config")
def realtime_config(u=Depends(current_user)):
    url=os.getenv("SUPABASE_URL"); key=os.getenv("SUPABASE_ANON_KEY")
    return {"enabled":bool(url and key),"url":url if url and key else None,"anon_key":key if url and key else None}
@app.get("/api/cron/send-reminders")
def send_reminders(request:Request):
    secret=os.getenv("CRON_SECRET")
    if secret and request.headers.get("Authorization")!=f"Bearer {secret}": raise HTTPException(401,"Invalid cron authorization")
    today=date.today(); limit=(today+timedelta(days=30)).isoformat(); sent=0
    vs=supabase.table("vehicles").select("*").not_.is_("next_service_date","null").lte("next_service_date",limit).execute().data or []
    for v in vs:
        if supabase.table("notifications").select("id").eq("user_id",v["owner_id"]).eq("subject","Service reminder").gte("created_at",today.isoformat()).limit(1).execute().data: continue
        overdue=v["next_service_date"]<today.isoformat()
        notify(v["owner_id"],"Service reminder",f"Your {v['brand']} {v['model']} ({v['registration_no']}) service is {'overdue' if overdue else 'due on '+v['next_service_date']}.")
        sent+=1
    return {"ok":True,"reminders_sent":sent}
