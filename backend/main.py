from dotenv import load_dotenv
load_dotenv()
import os
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

from .database import Base, engine, get_db, SessionLocal
from .auth import router as auth_router, get_current_user
from .ai import chat_with_centaur
from .tools import get_due_reminders, mark_reminder_sent, send_email
from .models import ConversationTurn, Conversation

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(SessionMiddleware, secret_key=os.getenv("JWT_SECRET", "dev-secret"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

class ChatIn(BaseModel):
    message: str
    conversation_id: Optional[int] = None

class ChatOut(BaseModel):
    response: str
    conversation_id: int

@app.post("/chat", response_model=ChatOut)
def chat(req: ChatIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Get or create conversation
    if req.conversation_id:
        convo = db.get(Conversation, req.conversation_id)
        if not convo or convo.user_id != user.id:
            convo = None
    else:
        convo = None

    if not convo:
        convo = Conversation(user_id=user.id, title="New Chat")
        db.add(convo)
        db.commit()
        db.refresh(convo)

    answer = chat_with_centaur(db, user, req.message, convo.id)

    # Auto-title from first message
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
