from dotenv import load_dotenv
load_dotenv()
import re
import hashlib
import time
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
    generate_image,
    dns_lookup,
    whois_lookup,
    cve_lookup,
    ip_lookup,
    subdomain_search,
    check_hash_malware,
    check_url_malware,
)
from .providers.groq_provider import GroqProvider
from .providers.cerebras_provider import CerebrasProvider
from .providers.gemini_provider import GeminiProvider
from .providers.openrouter_provider import OpenRouterProvider
from .providers.deepseek_provider import DeepSeekProvider
from .providers.local_provider import LocalProvider
from .providers.sambanova_provider import SambanovaProvider
from .providers.nvidia_provider import NvidiaProvider
from .providers.zai_provider import ZaiProvider

# Named instances (reused across requests)
_gemini = GeminiProvider()
_deepseek = DeepSeekProvider()
_openrouter = OpenRouterProvider()
_cerebras = CerebrasProvider()
_groq = GroqProvider()
_local = LocalProvider()
_sambanova = SambanovaProvider()
_nvidia = NvidiaProvider()
_zai = ZaiProvider()

PROVIDERS = [_groq, _cerebras, _sambanova, _nvidia, _zai, _gemini, _openrouter, _deepseek, _local]

PROVIDER_MAP = {
    "gemini": _gemini,
    "local": _local,
    "deepseek": _deepseek,
    "openrouter": _openrouter,
    "cerebras": _cerebras,
    "groq": _groq,
    "sambanova": _sambanova,
    "nvidia": _nvidia,
    "zai": _zai,
}

SYSTEM_PROMPT = """You are Sentaur AI — a friendly, expert assistant specialising in cybersecurity. 🤖

Thinking: For complex questions only, reason briefly inside <think>...</think> tags first. Skip for simple/short answers.

Style: Use emojis naturally. Format with markdown (**bold**, `code`, bullet lists, headers). Be concise and direct — no filler like "Certainly!". Think step-by-step for complex questions.

Cybersecurity: Deep knowledge of networking, ethical hacking, CTFs, malware analysis, OSINT, cryptography, web/app security, MITRE ATT&CK, threat intelligence, and pen testing. Flag vulnerabilities in code. Promote ethical, legal use only.

Live Tools (REAL — always confirm when triggered):
- 📧 Email · 🌤️ Weather · 📰 News · ✅ To-dos · 📅 Calendar · ⏰ Reminders · 📊 Daily briefing
- 🎨 **Image Generation**: generates and displays an image inline — confirm you are generating it.
- 🌐 **DNS Lookup**: resolves DNS records for any domain — triggered automatically when asked.
- 📋 **WHOIS**: fetches RDAP registration data for domains and IPs — triggered automatically.
- 🐛 **CVE Lookup**: pulls live CVE details from NVD — triggered when a CVE ID is mentioned.
- 🌍 **IP Lookup**: geolocates an IP (country, ISP, ASN) — triggered when an IP is mentioned or asked about.
- 🔭 **Subdomain Finder**: enumerates subdomains via crt.sh — triggered when asked to find subdomains.
- ☣ **Hash Malware Check**: queries MalwareBazaar for a file hash — triggered when a hash is provided and malware context is present.
- 🌐 **URL/Domain Check**: queries URLhaus for a URL or domain — triggered when asked if a URL is safe or malicious.
Note: these tools detect *known* threats by hash/URL reputation. They cannot execute, sandbox, or actively contain files — for containment, provide step-by-step advice.

Today: {datetime}"""

# ── Response cache (in-memory, 1-hour TTL) ──────────────────────────────────
_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 3600
_CACHE_MAX = 200

_NO_CACHE_KEYWORDS = {
    "email", "weather", "news", "todo", "task", "calendar", "event",
    "reminder", "remind", "briefing", "my ", "your ", "latest", "today",
    "right now", "current", "dns", "whois", "cve-", "lookup", "who owns",
    "subdomain", "geolocate", "what is my ip", "ip address",
    "malware", "malicious", "virus", "hash check", "is this safe", "urlhaus", "malwarebazaar",
}

def _should_cache(message: str) -> bool:
    lower = message.lower()
    return not any(kw in lower for kw in _NO_CACHE_KEYWORDS)

def _cache_key(message: str) -> str:
    return hashlib.md5(message.strip().lower().encode()).hexdigest()

def _cache_get(message: str) -> str | None:
    key = _cache_key(message)
    entry = _CACHE.get(key)
    if entry:
        response, ts = entry
        if time.time() - ts < _CACHE_TTL:
            return response
        del _CACHE[key]
    return None

def _cache_set(message: str, response: str):
    if len(_CACHE) >= _CACHE_MAX:
        oldest = min(_CACHE, key=lambda k: _CACHE[k][1])
        del _CACHE[oldest]
    _CACHE[_cache_key(message)] = (response, time.time())

# ── Query complexity routing ─────────────────────────────────────────────────
_COMPLEX_KEYWORDS = {
    "explain", "analyze", "analyse", "compare", "implement", "write a", "write an",
    "debug", "review", "summarize", "summarise", "translate", "essay", "detailed",
    "step by step", "research", "pros and cons", "difference between",
    "how does", "why does", "elaborate", "in depth",
}

def _is_complex(message: str) -> bool:
    if len(message) > 200 or "```" in message:
        return True
    lower = message.lower()
    return any(kw in lower for kw in _COMPLEX_KEYWORDS)


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


def maybe_handle_tools(db: Session, user: User, message: str, messages: list = None) -> str | None:
    lower = message.lower()

    # Image generation — check first
    _img_triggers = [
        "generate image", "generate a image", "generate an image",
        "create image", "create a image", "create an image",
        "make image", "make a image", "make an image",
        "draw me", "draw a ", "draw an ", "paint me", "paint a ", "paint an ",
        "generate picture", "create picture", "generate a picture", "create a picture",
        "generate photo", "create photo", "illustrate",
    ]
    if any(t in lower for t in _img_triggers):
        prompt = re.sub(
            r'^(please\s+)?(generate|create|draw|make|paint|illustrate)\s+(me\s+)?(an?\s+)?(image|picture|photo|drawing|painting|illustration)\s+(of\s+|showing\s+|depicting\s+|of\s+a\s+|of\s+an\s+)?',
            '', message, flags=re.IGNORECASE,
        ).strip() or message
        return f"IMAGE_GEN:{prompt}"

    # Image re-generation — follow-up modifications like "make it more fluffy"
    _regen_triggers = [
        "make it more", "make it less", "make it look", "make it appear",
        "make it darker", "make it brighter", "make it bigger", "make it smaller",
        "regenerate", "re-generate", "try again", "one more time", "generate again",
        "redo the image", "redo the picture", "redo it", "do it again",
        "change the image", "modify the image", "update the image", "edit the image",
        "make the image", "now make it", "instead make it", "can you make it",
        "make it", "change it", "more fluffy", "more colorful", "more realistic",
        "more detailed", "less", "different style", "another version",
    ]

    if messages:
        # Check if the last bot message was about an image (context-aware detection)
        last_bot_image = False
        for m in reversed(messages[:-1]):
            if m["role"] == "assistant":
                bot_lower = m["content"].lower()
                if any(w in bot_lower for w in ["image", "picture", "illustration", "generated", "drew", "created", "drawing"]):
                    last_bot_image = True
                break

        # Find the last user message that triggered image gen
        last_img_prompt = None
        for m in reversed(messages[:-1]):
            if m["role"] == "user" and m["content"] != message:
                msg_lower = m["content"].lower()
                if any(t in msg_lower for t in _img_triggers) or any(t in msg_lower for t in _regen_triggers):
                    last_img_prompt = m["content"]
                    break

        # Broader mod triggers only used when we're already in an image conversation
        _broad_mod = [
            "make it", "make the", "more ", "less ", "darker", "brighter", "add ", "remove ",
            "change", "different", "again", "another", "redo", "try", "without", "with more",
        ]
        in_image_convo = last_bot_image and last_img_prompt
        is_regen = any(t in lower for t in _regen_triggers) or (in_image_convo and any(t in lower for t in _broad_mod))

        if is_regen and last_img_prompt:
            prompt = f"{last_img_prompt}, {message}"
            return f"IMAGE_GEN:{prompt}"

    # Email-specific checks must come BEFORE plain weather/news checks
    if ("email" in lower or "send" in lower) and ("weather" in lower or "forecast" in lower or "temperature" in lower):
        weather = get_weather_summary(user.city or None)
        ok = send_email(to_email=user.email, subject="Your Weather Update from Sentaur AI", body=weather)
        if ok:
            return f"I've emailed you the weather update:\n\n{weather}"
        return f"Here's the weather (email delivery failed — check Resend logs):\n\n{weather}"

    if ("email" in lower or "send" in lower) and ("news" in lower or "headlines" in lower):
        news = get_news_headlines()
        ok = send_email(to_email=user.email, subject="Today's News Headlines from Sentaur AI", body=news)
        if ok:
            return f"I've emailed you the headlines:\n\n{news}"
        return f"Here are the headlines (email delivery failed):\n\n{news}"

    if "email me" in lower or "send me an email" in lower:
        ok = send_email(to_email=user.email, subject="Message from Sentaur AI", body=message)
        return "I've emailed that to you." if ok else "Email delivery failed — check your Resend API key."

    if "news" in lower or "headlines" in lower:
        return get_news_headlines()

    if "weather" in lower or "temperature" in lower or "forecast" in lower:
        return get_weather_summary(user.city or None)

    if "add a task" in lower or "add todo" in lower or "remember this task" in lower:
        add_todo(db, user, message)
        return "Task added."

    if "list my tasks" in lower or "show my todos" in lower:
        return list_todos(db, user)

    if "add event" in lower or "schedule" in lower:
        date = datetime.now(timezone.utc) + timedelta(days=1)
        add_calendar_event(db, user, message, date)
        return "Event added to your calendar."

    if "today's events" in lower or "today events" in lower:
        return get_todays_events(db, user)

    if "daily briefing" in lower or "morning summary" in lower:
        return generate_daily_briefing(db, user)

    if "remind me" in lower or "set a reminder" in lower or "set reminder" in lower:
        due = datetime.now(timezone.utc) + timedelta(hours=1)
        create_reminder(db, user, message, due)
        return "Got it — I'll remind you in about an hour via email."

    # ── Cyber tools ──────────────────────────────────────────────────────────

    # CVE lookup — check first since the ID pattern is unambiguous
    cve_match = re.search(r'\bCVE-\d{4}-\d{4,}\b', message, re.IGNORECASE)
    if cve_match:
        return cve_lookup(cve_match.group(0))

    # WHOIS lookup
    _whois_triggers = ["whois", "who owns", "who registered", "domain registration", "domain info", "rdap"]
    if any(t in lower for t in _whois_triggers):
        target = re.search(r'\b([\w.-]+\.[a-z]{2,}|\d{1,3}(?:\.\d{1,3}){3})\b', message)
        if target:
            return whois_lookup(target.group(1))

    # DNS lookup
    _dns_triggers = ["dns lookup", "dns record", "dns for", "look up dns", "resolve dns",
                     "a record", "mx record", "txt record", "ns record", "cname for", "aaaa record"]
    if any(t in lower for t in _dns_triggers) or (lower.startswith("dns ") and len(message) > 6):
        domain = re.search(r'\b([\w.-]+\.[a-z]{2,})\b', message)
        if domain:
            rec_type = "A"
            for t in ["AAAA", "MX", "TXT", "CNAME", "NS", "SOA", "SRV"]:
                if t.lower() in lower:
                    rec_type = t
                    break
            return dns_lookup(domain.group(1), rec_type)

    # IP lookup
    _ip_triggers = ["ip lookup", "geolocate", "where is ip", "who is ip", "what is my ip",
                    "my ip address", "ip address of", "ip info", "ip location"]
    ip_match = re.search(r'\b(\d{1,3}(?:\.\d{1,3}){3})\b', message)
    if ip_match and any(t in lower for t in ["lookup", "locate", "where", "who", "info", "geolocate", "ip"]):
        return ip_lookup(ip_match.group(1))
    if any(t in lower for t in _ip_triggers):
        target_ip = ip_match.group(1) if ip_match else ""
        return ip_lookup(target_ip)

    # Subdomain search
    _sub_triggers = ["subdomain", "subdomains", "enumerate subdomain", "find subdomain",
                     "crt.sh", "certificate transparency"]
    if any(t in lower for t in _sub_triggers):
        domain = re.search(r'\b([\w.-]+\.[a-z]{2,})\b', message)
        if domain:
            return subdomain_search(domain.group(1))

    # Malware hash check — hash pattern + malware context
    _malware_ctx = ["malware", "malicious", "virus", "infected", "threat", "hash check",
                    "is this safe", "is it safe", "scan", "check this hash", "malwarebazaar"]
    hash_match = re.search(r'\b([0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\b', message)
    if hash_match and any(t in lower for t in _malware_ctx):
        return check_hash_malware(hash_match.group(1))

    # URL reputation check
    _url_ctx = ["malicious", "malware", "is this safe", "is it safe", "safe to visit",
                "phishing", "urlhaus", "check this url", "check url", "is this url"]
    url_match = re.search(r'https?://[^\s"\'<>)]+', message)
    if url_match and any(t in lower for t in _url_ctx):
        return check_url_malware(url_match.group(0))

    return None


_FAST_PROVIDERS = [_groq, _cerebras]

def get_providers(model_preference: str = None, message: str = ""):
    if model_preference and model_preference in PROVIDER_MAP:
        preferred = PROVIDER_MAP[model_preference]
        others = [p for p in PROVIDERS if p is not preferred]
        return [preferred] + others
    # Simple queries only hit fast providers; complex ones use full list
    if not _is_complex(message):
        return _FAST_PROVIDERS + [p for p in PROVIDERS if p not in _FAST_PROVIDERS]
    return PROVIDERS


def quick_title(message: str) -> str:
    try:
        result = _groq.chat([
            {"role": "system", "content": "Generate a 3-5 word title for a chat conversation that starts with the following message. Reply with ONLY the title, no quotes, no punctuation at the end."},
            {"role": "user", "content": message[:300]},
        ])
        return (result or message)[:50].strip()
    except Exception:
        return message[:40]


def generate_suggestions(user_message: str, bot_response: str) -> list[str]:
    """Generate 4 follow-up question suggestions that match the topic of the conversation."""
    import json as _json
    try:
        result = _groq.chat([
            {
                "role": "system",
                "content": (
                    "You generate follow-up question suggestions for a chat interface. "
                    "Rules:\n"
                    "1. Match the EXACT topic the user asked about — if they asked about Python, suggest Python questions; cooking → cooking questions; etc.\n"
                    "2. Make the 4 questions varied: one goes deeper, one explores a related subtopic, one asks for an example, one asks for practical advice.\n"
                    "3. Max 8 words per question. Write naturally, like a curious user would type.\n"
                    "4. Return ONLY a raw JSON array with no markdown fences: [\"q1\",\"q2\",\"q3\",\"q4\"]"
                ),
            },
            {"role": "user", "content": f"User asked: {user_message[:300]}\nAssistant replied: {bot_response[:600]}"},
        ])
        if not result:
            return []
        text = result.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        suggestions = _json.loads(text)
        if isinstance(suggestions, list):
            return [str(s).strip()[:80] for s in suggestions[:4] if s]
    except Exception as e:
        print(f"generate_suggestions failed: {e}")
    return []


def iter_chat(messages, providers=None, image_data=None, image_mime=None, images=None):
    """Yields raw text chunks from the first successful provider."""
    if providers is None:
        providers = PROVIDERS

    # Normalise to images list
    if not images and image_data:
        images = [{"data": image_data, "mime": image_mime or "image/jpeg"}]

    # Cache check (skip for image requests and tool/personal queries)
    last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), None)
    use_cache = last_user_msg and not images and _should_cache(last_user_msg)
    if use_cache:
        cached = _cache_get(last_user_msg)
        if cached:
            print(f"Cache hit for: {last_user_msg[:60]}")
            yield cached
            return

    for provider in providers:
        got_chunk = False
        accumulated = []
        try:
            if hasattr(provider, "stream_chat"):
                kwargs = {}
                if images and isinstance(provider, GeminiProvider):
                    kwargs = {"images": images}
                for chunk in provider.stream_chat(messages, **kwargs):
                    if chunk:
                        yield chunk
                        accumulated.append(chunk)
                        got_chunk = True
            else:
                result = provider.chat(messages)
                if result:
                    yield result
                    accumulated.append(result)
                    got_chunk = True
        except Exception as e:
            print(f"{type(provider).__name__} failed: {e}")

        if got_chunk:
            if use_cache and accumulated:
                _cache_set(last_user_msg, "".join(accumulated))
            return


def chat_with_centaur(db: Session, user: User, message: str, conversation_id: int = None) -> str:
    messages = build_history(db, conversation_id)
    messages.append({"role": "user", "content": message})

    tool_answer = maybe_handle_tools(db, user, message)
    if tool_answer:
        messages.append({
            "role": "system",
            "content": f"Tool result for the user's request:\n{tool_answer}\n\nPresent this to the user naturally and conversationally.",
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
