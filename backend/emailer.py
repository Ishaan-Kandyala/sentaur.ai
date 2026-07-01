import os
import resend

resend.api_key = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM", "Sentaur AI <onboarding@resend.dev>")

def send_email(to: str, subject: str, body: str):
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to],
            "subject": subject,
            "text": body,
        })
    except Exception as e:
        print("Email error:", e)
