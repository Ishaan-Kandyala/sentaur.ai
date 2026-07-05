from dotenv import load_dotenv
load_dotenv()
import os
import json
import requests as _requests
from fastapi import FastAPI, Depends, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .database import Base, engine, get_db, SessionLocal
from .auth import router as auth_router, get_current_user
from .ai import chat_with_centaur, build_history, maybe_handle_tools, iter_chat, quick_title, get_providers, generate_suggestions
from .tools import get_due_reminders, mark_reminder_sent, send_email, get_weather_summary, generate_image
from .models import ConversationTurn, Conversation

Base.metadata.create_all(bind=engine)

# Add new columns to existing tables without Alembic
with engine.connect() as _conn:
    for _sql in [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_weather_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR",
        "ALTER TABLE conversation_turns ADD COLUMN IF NOT EXISTS image_url TEXT",
    ]:
        try:
            _conn.execute(text(_sql))
        except Exception:
            pass
    _conn.commit()

limiter = Limiter(key_func=get_remote_address)

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(SessionMiddleware, secret_key=os.getenv("JWT_SECRET", "dev-secret"))

BASE_URL = os.getenv("BASE_URL", "https://sentaur-ai.onrender.com")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[BASE_URL, "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


class ChatIn(BaseModel):
    message: str
    conversation_id: Optional[int] = None
    model_preference: Optional[str] = None
    image_data: Optional[str] = None
    image_mime: Optional[str] = None
    images: Optional[List[dict]] = None  # [{data, mime}, ...]
    system_prompt: Optional[str] = None


class ChatOut(BaseModel):
    response: str
    conversation_id: int


def _get_or_create_convo(db: Session, user, conversation_id: Optional[int]) -> Conversation:
    if conversation_id:
        convo = db.get(Conversation, conversation_id)
        if convo and convo.user_id == user.id:
            return convo
    convo = Conversation(user_id=user.id, title="New Chat")
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


@app.post("/chat/stream")
@limiter.limit("30/minute")
def chat_stream(request: Request, req: ChatIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    convo = _get_or_create_convo(db, user, req.conversation_id)

    messages = build_history(db, convo.id)
    if req.system_prompt and req.system_prompt.strip():
        messages[0]["content"] += f"\n\nAdditional instructions from the user:\n{req.system_prompt.strip()}"
    messages.append({"role": "user", "content": req.message})

    tool_answer = maybe_handle_tools(db, user, req.message, messages)
    image_gen_prompt = None
    if tool_answer:
        if tool_answer.startswith("IMAGE_GEN:"):
            image_gen_prompt = tool_answer[len("IMAGE_GEN:"):]
            tool_answer = "I'm generating that image for you right now! 🎨"
        messages.append({
            "role": "system",
            "content": f"Tool result for the user's request:\n{tool_answer}\n\nPresent this to the user naturally and conversationally.",
        })

    # Normalise images: prefer the array, fall back to single image_data
    images = req.images or (
        [{"data": req.image_data, "mime": req.image_mime or "image/jpeg"}] if req.image_data else None
    )

    providers = get_providers(req.model_preference, req.message)

    def generate():
        nonlocal image_gen_prompt
        full_text = ""

        for chunk in iter_chat(messages, providers, images=images):
            full_text += chunk
            yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"

        if not full_text:
            full_text = "All AI providers are currently unavailable. Please try again later."
            yield f"data: {json.dumps({'type': 'chunk', 'text': full_text})}\n\n"

        # Fallback: if AI response implies it generated an image but keyword trigger missed
        if not image_gen_prompt:
            _img_signals = [
                "i've generated", "i generated", "here's the image", "here is the image",
                "image appears below", "image should appear", "generated an image",
                "image for you", "i created an image", "i've created an image",
                "i drew", "i've drawn", "here's your image", "here is your image",
            ]
            if any(s in full_text.lower() for s in _img_signals):
                image_gen_prompt = req.message

        turn = ConversationTurn(
            user_id=user.id,
            conversation_id=convo.id,
            user_message=req.message,
            bot_message=full_text,
        )
        db.add(turn)

        title = convo.title
        if convo.title == "New Chat":
            title = quick_title(req.message)
            convo.title = title

        db.commit()
        db.refresh(turn)

        if image_gen_prompt:
            yield f"data: {json.dumps({'type': 'image_gen_loading'})}\n\n"
            data_uri = generate_image(image_gen_prompt)
            if data_uri:
                turn.image_url = data_uri
                db.commit()
                yield f"data: {json.dumps({'type': 'image_gen', 'url': data_uri})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'image_gen_error'})}\n\n"

        suggestions = generate_suggestions(req.message, full_text)
        yield f"data: {json.dumps({'type': 'meta', 'conversation_id': convo.id, 'title': title, 'suggestions': suggestions})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat", response_model=ChatOut)
def chat(req: ChatIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    convo = _get_or_create_convo(db, user, req.conversation_id)
    answer = chat_with_centaur(db, user, req.message, convo.id)
    if convo.title == "New Chat":
        convo.title = req.message[:40]
        db.commit()
    return ChatOut(response=answer, conversation_id=convo.id)


@app.get("/conversations")
def list_conversations(db: Session = Depends(get_db), user=Depends(get_current_user)):
    convos = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
        .all()
    )
    return [{"id": c.id, "title": c.title, "created_at": c.created_at} for c in convos]


@app.post("/conversations")
def new_conversation(db: Session = Depends(get_db), user=Depends(get_current_user)):
    convo = Conversation(user_id=user.id, title="New Chat")
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return {"id": convo.id, "title": convo.title}


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    convo = db.get(Conversation, conversation_id)
    if convo and convo.user_id == user.id:
        db.query(ConversationTurn).filter(ConversationTurn.conversation_id == conversation_id).delete()
        db.delete(convo)
        db.commit()
    return {"ok": True}


@app.get("/history/{conversation_id}")
def get_history(conversation_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    turns = (
        db.query(ConversationTurn)
        .filter(ConversationTurn.conversation_id == conversation_id)
        .order_by(ConversationTurn.created_at.asc())
        .limit(100)
        .all()
    )
    return [{"content": t.user_message, "bot": t.bot_message, "image_url": t.image_url} for t in turns]


class SettingsIn(BaseModel):
    city: Optional[str] = None
    daily_weather_enabled: Optional[bool] = None


@app.get("/settings/me")
def get_settings(user=Depends(get_current_user)):
    return {
        "email": user.email,
        "name": user.name or "",
        "avatar_url": user.avatar_url or "",
        "city": user.city or "",
        "daily_weather_enabled": bool(user.daily_weather_enabled),
    }


@app.post("/settings/me")
def update_settings(req: SettingsIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if req.city is not None:
        user.city = req.city.strip()
    if req.daily_weather_enabled is not None:
        user.daily_weather_enabled = req.daily_weather_enabled
    db.commit()
    return {"ok": True}


def daily_weather_job():
    from .ai import _groq
    db = SessionLocal()
    try:
        from .models import User as UserModel
        users = db.query(UserModel).filter(UserModel.daily_weather_enabled == True).all()
        for u in users:
            if not u.email:
                continue
            weather = get_weather_summary(u.city or None)
            # Ask AI to write a friendly weather email
            try:
                body = _groq.chat([
                    {"role": "system", "content": "You are Sentaur AI. Write a short, friendly daily weather email (3-5 sentences, include relevant tips). No subject line needed."},
                    {"role": "user", "content": f"Write a daily weather email based on this data: {weather}"},
                ])
            except Exception:
                body = weather
            send_email(
                to_email=u.email,
                subject="☀️ Your Daily Weather Update – Sentaur AI",
                body=body or weather,
            )
    finally:
        db.close()


def reminder_job():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        due = get_due_reminders(db, now)
        for r in due:
            if r.user and r.user.email:
                send_email(to_email=r.user.email, subject="Sentaur reminder", body=r.text)
            mark_reminder_sent(db, r)
    finally:
        db.close()


scheduler = BackgroundScheduler()
scheduler.add_job(reminder_job, "interval", minutes=1)
scheduler.add_job(daily_weather_job, "cron", hour=8, minute=0)  # 8 AM UTC daily
scheduler.start()


@app.get("/city-search")
def city_search(q: str = Query(..., min_length=2), user=Depends(get_current_user)):
    api_key = os.getenv("WEATHER_API_KEY")
    if not api_key:
        return []
    try:
        resp = _requests.get(
            "http://api.openweathermap.org/geo/1.0/direct",
            params={"q": q, "limit": 5, "appid": api_key},
            timeout=5,
        )
        seen = set()
        results = []
        for item in resp.json():
            city = item.get("name", "")
            state = item.get("state", "")
            country = item.get("country", "")
            key = f"{city}|{state}|{country}"
            if key not in seen and city:
                seen.add(key)
                results.append({"city": city, "state": state, "country": country})
        return results
    except Exception as e:
        print(f"City search error: {e}")
        return []


@app.get("/api/tools/ip-lookup")
@limiter.limit("30/minute")
async def proxy_ip_lookup(request: Request, ip: str = ""):
    try:
        fields = "status,message,country,countryCode,regionName,city,zip,lat,lon,isp,org,as,query"
        target = f"http://ip-api.com/json/{ip}?fields={fields}"
        resp = _requests.get(target, timeout=10)
        return resp.json()
    except Exception as e:
        return {"status": "fail", "message": str(e)}


@app.get("/api/tools/cve-lookup")
@limiter.limit("20/minute")
async def proxy_cve_lookup(request: Request, cve_id: str = ""):
    cve_id = cve_id.strip().upper()
    if not cve_id:
        return {"error": "no_id"}
    # Try NVD first
    try:
        resp = _requests.get(
            f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}",
            headers={"User-Agent": "SentaurAI/1.0"},
            timeout=12,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("vulnerabilities"):
                return {"source": "nvd", "data": data}
    except Exception:
        pass
    # Fallback: cve.circl.lu (no rate limits, no key needed)
    try:
        resp2 = _requests.get(
            f"https://cve.circl.lu/api/cve/{cve_id}",
            timeout=10,
        )
        if resp2.status_code == 200 and resp2.json():
            return {"source": "circl", "data": resp2.json()}
    except Exception:
        pass
    return {"error": "not_found"}


@app.post("/api/tools/hash-check")
@limiter.limit("30/minute")
async def proxy_hash_check(request: Request):
    body = await request.json()
    hash_val = (body.get("hash") or "").strip()
    if not hash_val:
        return {"query_status": "error"}
    try:
        resp = _requests.post(
            "https://mb-api.abuse.ch/api/v1/",
            data={"query": "get_info", "hash": hash_val},
            timeout=12,
        )
        return resp.json()
    except Exception:
        return {"query_status": "error"}


@app.post("/api/tools/url-check")
@limiter.limit("30/minute")
async def proxy_url_check(request: Request):
    body = await request.json()
    url_val = (body.get("url") or "").strip()
    if not url_val:
        return {"query_status": "error"}
    api_key = os.getenv("URLHAUS_API_KEY", "")
    if not api_key:
        return {"query_status": "no_key"}
    try:
        resp = _requests.post(
            "https://urlhaus-api.abuse.ch/v1/url/",
            data={"url": url_val},
            headers={"Auth-Key": api_key, "User-Agent": "SentaurAI-SecurityTools/1.0"},
            timeout=12,
        )
        return resp.json()
    except Exception as e:
        print(f"URLhaus request error: {e}")
        return {"query_status": "error"}


@app.post("/api/tools/virustotal-hash")
@limiter.limit("10/minute")
async def virustotal_hash(request: Request):
    body = await request.json()
    hash_val = (body.get("hash") or "").strip()
    if not hash_val:
        return {"error": "no_hash"}
    api_key = os.getenv("VIRUSTOTAL_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    try:
        resp = _requests.get(
            f"https://www.virustotal.com/api/v3/files/{hash_val}",
            headers={"x-apikey": api_key},
            timeout=15,
        )
        if resp.status_code == 404:
            return {"error": "not_found"}
        if resp.status_code == 429:
            return {"error": "rate_limited"}
        return resp.json()
    except Exception as e:
        print(f"VirusTotal error: {e}")
        return {"error": str(e)}


@app.get("/api/tools/breach-check")
@limiter.limit("10/minute")
async def proxy_breach_check(request: Request, email: str = ""):
    email = email.strip()
    if not email:
        return {"error": "no_email"}
    try:
        resp = _requests.get(
            f"https://api.xposedornot.com/v1/check-email/{email}",
            headers={"User-Agent": "SentaurAI/1.0"},
            timeout=10,
        )
        if resp.status_code == 404:
            return {"breaches": []}
        if not resp.ok:
            return {"error": f"HTTP {resp.status_code}"}
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tools/abuseipdb")
@limiter.limit("20/minute")
async def proxy_abuseipdb(request: Request, ip: str = ""):
    ip = ip.strip()
    if not ip:
        return {"error": "no_ip"}
    api_key = os.getenv("ABUSEIPDB_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    try:
        resp = _requests.get(
            "https://api.abuseipdb.com/api/v2/check",
            params={"ipAddress": ip, "maxAgeInDays": 90, "verbose": True},
            headers={"Key": api_key, "Accept": "application/json"},
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tools/ipinfo")
@limiter.limit("30/minute")
async def proxy_ipinfo(request: Request, ip: str = ""):
    ip = ip.strip()
    if not ip:
        return {"error": "no_ip"}
    api_key = os.getenv("IPINFO_TOKEN", "")
    if not api_key:
        return {"error": "no_key"}
    try:
        resp = _requests.get(
            f"https://ipinfo.io/{ip}/json",
            params={"token": api_key},
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tools/otx")
@limiter.limit("20/minute")
async def proxy_otx(request: Request, type: str = "ip", value: str = ""):
    value = value.strip()
    if not value:
        return {"error": "no_value"}
    api_key = os.getenv("OTX_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    type_map = {"ip": "IPv4", "domain": "domain", "hash": "file", "hostname": "hostname"}
    otx_type = type_map.get(type, "IPv4")
    try:
        resp = _requests.get(
            f"https://otx.alienvault.com/api/v1/indicators/{otx_type}/{value}/general",
            headers={"X-OTX-API-KEY": api_key},
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tools/internetdb")
@limiter.limit("30/minute")
async def proxy_internetdb(request: Request, ip: str = ""):
    ip = ip.strip()
    if not ip:
        return {"error": "no_ip"}
    try:
        resp = _requests.get(
            f"https://internetdb.shodan.io/{ip}",
            headers={"User-Agent": "SentaurAI/1.0"},
            timeout=10,
        )
        if resp.status_code == 404:
            return {"error": "not_found"}
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
