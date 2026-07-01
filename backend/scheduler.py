from apscheduler.schedulers.background import BackgroundScheduler
from .database import SessionLocal
from .models import User
from .tools import send_email, get_weather_summary

def send_daily_updates():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        for user in users:
            weather = get_weather_summary()
            body = f"Good morning!\n\n{weather}\n\nHave a great day!"
            send_email(user.email, "Your Daily Sentaur Briefing", body)
    except Exception as e:
        print("Scheduler error:", e)
    finally:
        db.close()

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_daily_updates, "cron", hour=7, minute=0)
    scheduler.start()
