import os
import requests
import feedparser
import resend
from sqlalchemy.orm import Session
from datetime import datetime

from .models import Reminder, Todo, CalendarEvent

resend.api_key = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM", "Sentaur AI <onboarding@resend.dev>")

# -----------------------------
# WEATHER TOOL
# -----------------------------
def get_weather_summary():
    api_key = os.getenv("WEATHER_API_KEY")
    city = os.getenv("WEATHER_CITY", "Wellington,FL")

    url = (
        f"https://api.openweathermap.org/data/2.5/weather?"
        f"q={city}&appid={api_key}&units=metric"
    )

    try:
        data = requests.get(url).json()
        temp = data["main"]["temp"]
        desc = data["weather"][0]["description"].title()
        return f"The weather in {city} is {temp}°C with {desc}."
    except Exception:
        return "I couldn't fetch the weather right now."


# -----------------------------
# EMAIL SENDING TOOL
# -----------------------------
def send_email(to_email: str, subject: str, body: str):
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "text": body,
        })
    except Exception as e:
        print("Email error:", e)


# -----------------------------
# REMINDER CREATION
# -----------------------------
def create_reminder(db: Session, user, text: str, due: datetime):
    reminder = Reminder(
        user_id=user.id,
        text=text,
        due_at=due,
        sent=False,
    )
    db.add(reminder)
    db.commit()
    return reminder


# -----------------------------
# REMINDER QUERYING
# -----------------------------
def get_due_reminders(db: Session, now: datetime):
    return (
        db.query(Reminder)
        .filter(Reminder.sent == False)
        .filter(Reminder.due_at <= now)
        .all()
    )


# -----------------------------
# MARK REMINDER AS SENT
# -----------------------------
def mark_reminder_sent(db: Session, reminder: Reminder):
    reminder.sent = True
    db.commit()


# -----------------------------
# NEWS HEADLINES
# -----------------------------
def get_news_headlines(limit=5):
    url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)

    headlines = [entry.title for entry in feed.entries[:limit]]

    if not headlines:
        return "I couldn't fetch the news right now."

    formatted = "\n".join([f"- {h}" for h in headlines])
    return f"Here are the top news headlines:\n{formatted}"


# -----------------------------
# TO-DO LIST
# -----------------------------
def add_todo(db: Session, user, text: str):
    todo = Todo(user_id=user.id, text=text, done=False)
    db.add(todo)
    db.commit()
    return todo


def list_todos(db: Session, user):
    todos = db.query(Todo).filter(Todo.user_id == user.id).all()
    if not todos:
        return "You have no tasks."
    return "\n".join([f"[{'x' if t.done else ' '}] {t.text}" for t in todos])


# -----------------------------
# CALENDAR EVENTS
# -----------------------------
def add_calendar_event(db: Session, user, title: str, date: datetime):
    event = CalendarEvent(user_id=user.id, title=title, date=date)
    db.add(event)
    db.commit()
    return event


def get_todays_events(db: Session, user):
    from datetime import timedelta
    today = datetime.utcnow().date()
    start = datetime(today.year, today.month, today.day)
    end = start + timedelta(days=1)
    events = (
        db.query(CalendarEvent)
        .filter(CalendarEvent.user_id == user.id)
        .filter(CalendarEvent.date >= start)
        .filter(CalendarEvent.date < end)
        .all()
    )

    if not events:
        return "You have no events today."

    return "\n".join([f"- {e.title} at {e.date.strftime('%I:%M %p')}" for e in events])


# -----------------------------
# DAILY BRIEFING
# -----------------------------
def generate_daily_briefing(db: Session, user):
    weather = get_weather_summary()
    news = get_news_headlines()
    events = get_todays_events(db, user)

    return f"""
Good morning! Here's your daily briefing:

🌤 Weather:
{weather}

📰 News:
{news}

📅 Today's Events:
{events}
"""