from dotenv import load_dotenv
load_dotenv()
import os
import json
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .database import Base, engine, get_db, SessionLocal
from .auth import router as auth_router, get_current_user
from .ai import chat_with_centaur, build_history, maybe_handle_tools, iter_chat, quick_title, get_providers
from .tools import get_due_reminders, mark_reminder_sent, send_email
from .models import ConversationTurn, Conversation

Base.metadata.create_all(bind=engine)

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
    image_data: Optional[str] = None   # base64-encoded image
    image_mime: Optional[str] = None   # e.g. "image/jpeg"


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
    messages.append({"role": "user", "content": req.message})

    tool_answer = maybe_handle_tools(db, user, req.message)
    if tool_answer:
        messages.append({
            "role": "system",
            "content": f"Tool result for the user's request:\n{tool_answer}\n\nPresent this to the user naturally and conversationally.",
        })

    providers = get_providers(req.model_preference)

    def generate():
        full_text = ""

        for chunk in iter_chat(messages, providers, req.image_data, req.image_mime):
            full_text += chunk
            yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"

        if not full_text:
            full_text = "All AI providers are currently unavailable. Please try again later."
            yield f"data: {json.dumps({'type': 'chunk', 'text': full_text})}\n\n"

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

        yield f"data: {json.dumps({'type': 'meta', 'conversation_id': convo.id, 'title': title})}\n\n"
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
    return [{"content": t.user_message, "bot": t.bot_message} for t in turns]


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
scheduler.start()

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
