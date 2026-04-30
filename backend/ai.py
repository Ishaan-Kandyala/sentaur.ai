from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session


from .models import ConversationTurn, User
from .tools import (
    get_weather_summary,
    create_reminder,
    send_email,
    get_news_headlines,
    add_todo,
    list_todos,
    add_calendar_event,
    get_todays_events,
    generate_daily_briefing,
)
from .providers.groq_provider import GroqProvider
from .providers.cerebras_provider import CerebrasProvider
from .providers.gemini_provider import GeminiProvider
from .providers.together_provider import TogetherProvider
from .providers.deepseek_provider import DeepSeekProvider
from .providers.local_provider import LocalProvider

# Provider fallback chain — tries each in order until one succeeds
PROVIDERS = [
    GeminiProvider(),
    DeepSeekProvider(),
    TogetherProvider(),
    CerebrasProvider(),
    GroqProvider(),
    LocalProvider(),
]

# System prompt
SYSTEM_PROMPT = """
You are Sentaur AI — an intelligent, friendly personal assistant with deep expertise in cybersecurity. 🤖

Personality & Style:
- Use emojis naturally throughout your responses to make them feel warm and expressive. 😊
- Format responses using markdown: **bold** for emphasis, `code` for technical terms, bullet lists, and headers where helpful.
- Be conversational and enthusiastic like GitHub Copilot — helpful, upbeat, and clear.
- Start responses with a relevant emoji when appropriate.

Cybersecurity Focus:
- You have strong knowledge of cybersecurity topics: networking, ethical hacking, CTFs, malware analysis, OSINT, cryptography, web security, and defensive security.
- When security topics come up, go deeper — explain attack vectors, defenses, tools (nmap, Burp Suite, Wireshark, Metasploit, etc.), and best practices.
- For coding questions, prioritize secure coding practices and flag potential vulnerabilities.
- Help with CTF challenges, security research, and penetration testing concepts.
- Always promote ethical and legal use of security knowledge.

Threat Intelligence & Proactive Defense:
- You specialize in identifying threats BEFORE they happen. Think like an attacker to defend like an expert.
- Recognize early warning signs of attacks: unusual network traffic, suspicious login patterns, privilege escalation attempts, lateral movement, phishing indicators, and anomalous behavior.
- Know the MITRE ATT&CK framework — map behaviors to tactics and techniques (reconnaissance, initial access, persistence, exfiltration, etc.).
- Understand threat actor TTPs (Tactics, Techniques, Procedures) and common attack chains like phishing → credential theft → lateral movement → ransomware.
- When a user describes suspicious activity (logs, traffic, behavior), analyze it for IOCs (Indicators of Compromise): suspicious IPs, file hashes, domains, registry keys, unusual processes.
- Proactively suggest hardening measures: patch management, least privilege, network segmentation, MFA, endpoint detection, honeypots, and anomaly detection.
- Reference real-world CVEs, threat groups (APT28, Lazarus, etc.), and recent attack campaigns when relevant.
- Help users build threat models for their systems using STRIDE or PASTA frameworks.

Guidelines:
- Understand the user's intent even when phrased vaguely.
- Think step-by-step before answering complex questions 🧠
- Give concise, direct answers. Avoid filler phrases like "Certainly!" or "Of course!".
- When presenting data from tools (weather, news, todos, calendar), summarize it naturally with emojis.
- Maintain context across the conversation and reference earlier messages when relevant.
- Ask a clarifying question only when truly necessary.
- Be confident. Don't hedge excessively.
- For factual questions, be precise and cite uncertainty when you're unsure.

Today's date and time: {datetime}
"""

# Build conversation history
def build_history(db: Session, conversation_id: int = None, limit: int = 40):
    query = db.query(ConversationTurn).filter(ConversationTurn.conversation_id == conversation_id)
    turns = query.order_by(ConversationTurn.created_at.desc()).limit(limit).all()
    turns = list(reversed(turns))

    system_content = SYSTEM_PROMPT.format(
        datetime=datetime.now(timezone.utc).strftime("%A, %B %d %Y at %H:%M UTC")
    )
    messages = [{"role": "system", "content": system_content}]

    for t in turns:
        messages.append({"role": "user", "content": t.user_message})
        messages.append({"role": "assistant", "content": t.bot_message})

    return messages


# Tool routing
def maybe_handle_tools(db: Session, user: User, message: str) -> str | None:
    lower = message.lower()

    # NEWS
    if "news" in lower or "headlines" in lower:
        return get_news_headlines()

    # WEATHER
    if "weather" in lower or "temperature" in lower or "forecast" in lower:
        return get_weather_summary()

    # TO‑DOS
    if "add a task" in lower or "add todo" in lower or "remember this task" in lower:
        add_todo(db, user, message)
        return "Task added."

    if "list my tasks" in lower or "show my todos" in lower:
        return list_todos(db, user)

    # CALENDAR EVENTS
    if "add event" in lower or "schedule" in lower:
        date = datetime.now(timezone.utc) + timedelta(days=1)
        add_calendar_event(db, user, message, date)
        return "Event added to your calendar."

    if "today's events" in lower or "today events" in lower:
        return get_todays_events(db, user)

    # DAILY BRIEFING
    if "daily briefing" in lower or "morning summary" in lower:
        return generate_daily_briefing(db, user)

    # REMINDERS
    if "remind me" in lower or "set a reminder" in lower or "set reminder" in lower:
        due = datetime.now(timezone.utc) + timedelta(hours=1)
        create_reminder(db, user, message, due)
        return "Got it — I’ll remind you in about an hour via email."

    # EMAIL WEATHER
    if ("email" in lower or "send" in lower) and ("weather" in lower or "forecast" in lower or "temperature" in lower):
        weather = get_weather_summary()
        send_email(to_email=user.email, subject="Your Weather Update", body=weather)
        return f"I’ve emailed you the weather update:\n\n{weather}"

    # EMAIL NEWS
    if ("email" in lower or "send" in lower) and ("news" in lower or "headlines" in lower):
        news = get_news_headlines()
        send_email(to_email=user.email, subject="Today’s News Headlines", body=news)
        return f"I’ve emailed you the headlines:\n\n{news}"

    # EMAIL
    if "email me" in lower or "send me" in lower:
        send_email(
            to_email=user.email,
            subject="Message from Sentaur",
            body=message,
        )
        return "I’ve emailed that to you."

    return None


# Main AI brain
def chat_with_centaur(db: Session, user: User, message: str, conversation_id: int = None) -> str:
    messages = build_history(db, conversation_id)
    messages.append({"role": "user", "content": message})

    tool_answer = maybe_handle_tools(db, user, message)
    if tool_answer:
        messages.append({
            "role": "system",
            "content": f"Tool result for the user's request:\n{tool_answer}\n\nPresent this to the user naturally and conversationally."
        })

    answer = None
    for provider in PROVIDERS:
        answer = provider.chat(messages)
        if answer:
            break

    if not answer:
        answer = "All AI providers are currently unavailable. Please try again later."

    turn = ConversationTurn(
        user_id=user.id,
        conversation_id=conversation_id,
        user_message=message,
        bot_message=answer,
    )
    db.add(turn)
    db.commit()

    return answer