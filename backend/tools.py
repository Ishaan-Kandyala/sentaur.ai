import os
import re
import requests
import feedparser
from sqlalchemy.orm import Session
from datetime import datetime

from .models import Reminder, Todo, CalendarEvent

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
FROM_EMAIL = os.getenv("BREVO_FROM_EMAIL", "ishaan43@hotmail.com")
FROM_NAME = "Sentaur AI"

# -----------------------------
# WEATHER TOOL
# -----------------------------
def get_weather_summary(city: str = None):
    api_key = os.getenv("WEATHER_API_KEY")
    if not api_key:
        return "Weather is unavailable — WEATHER_API_KEY is not configured."

    city = city or os.getenv("WEATHER_CITY", "New York")
    # Strip the stored state suffix (format: "City|State, Country")
    if "|" in city:
        city = city.split("|")[0].strip()

    url = (
        f"https://api.openweathermap.org/data/2.5/weather?"
        f"q={city}&appid={api_key}&units=metric"
    )

    try:
        data = requests.get(url, timeout=10).json()

        if data.get("cod") != 200:
            msg = data.get("message", "unknown error")
            print(f"OpenWeatherMap error for '{city}': {msg}")
            return f"Couldn't get weather for '{city}': {msg}."

        temp = data["main"]["temp"]
        feels = data["main"]["feels_like"]
        humidity = data["main"]["humidity"]
        desc = data["weather"][0]["description"].title()
        return (
            f"The weather in {city} is {temp:.1f}°C (feels like {feels:.1f}°C) "
            f"with {desc}. Humidity: {humidity}%."
        )
    except Exception as e:
        print(f"Weather fetch error: {e}")
        return "I couldn't fetch the weather right now — the weather service may be down."


# -----------------------------
# EMAIL SENDING TOOL
# -----------------------------
def send_email(to_email: str, subject: str, body: str) -> bool:
    if not BREVO_API_KEY:
        print("Email error: BREVO_API_KEY not configured")
        return False
    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
            json={
                "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
                "to": [{"email": to_email}],
                "subject": subject,
                "textContent": body,
            },
            timeout=10,
        )
        if resp.status_code == 201:
            print(f"Email sent to {to_email}")
            return True
        print(f"Email error to {to_email}: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        print(f"Email error to {to_email}: {e}")
        return False


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
# IMAGE GENERATION
# -----------------------------
def generate_image(prompt: str):
    """Generate image — FLUX.1-schnell via HuggingFace router (confirmed working)."""
    import base64, urllib.parse

    # 1. HuggingFace router — FLUX.1-schnell is confirmed working
    hf_token = os.getenv("HF_TOKEN")
    if hf_token:
        for hf_url in [
            "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
            "https://router.huggingface.co/hf-inference/models/stabilityai/stable-diffusion-xl-base-1.0",
        ]:
            try:
                resp = requests.post(
                    hf_url,
                    headers={"Authorization": f"Bearer {hf_token}"},
                    json={"inputs": prompt},
                    timeout=90,
                )
                print(f"HF {hf_url}: {resp.status_code}")
                if resp.status_code == 200 and resp.content:
                    enc = base64.b64encode(resp.content).decode("utf-8")
                    print(f"Image via HF: {hf_url}")
                    return f"data:image/jpeg;base64,{enc}"
            except Exception as e:
                print(f"HF error ({hf_url}): {e}")

    # 3. Pollinations (last resort — likely 402 but worth trying)
    encoded_prompt = urllib.parse.quote(prompt)
    try:
        resp = requests.get(
            f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true",
            timeout=60,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        ct = resp.headers.get("content-type", "")
        print(f"Pollinations: {resp.status_code} {ct} {resp.text[:100]}")
        if resp.status_code == 200 and "image" in ct:
            enc = base64.b64encode(resp.content).decode("utf-8")
            return f"data:image/jpeg;base64,{enc}"
    except Exception as e:
        print(f"Pollinations error: {e}")

    return None


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


# -----------------------------
# CYBER TOOLS
# -----------------------------

_DNS_TYPES = {1:"A", 2:"NS", 5:"CNAME", 6:"SOA", 15:"MX", 16:"TXT", 28:"AAAA", 33:"SRV", 257:"CAA"}

def dns_lookup(domain: str, record_type: str = "A") -> str:
    try:
        resp = requests.get(
            "https://cloudflare-dns.com/dns-query",
            params={"name": domain, "type": record_type},
            headers={"Accept": "application/dns-json"},
            timeout=8,
        )
        d = resp.json()
        answers = d.get("Answer") or d.get("Authority") or []
        if d.get("Status") != 0 or not answers:
            return f"No {record_type} records found for {domain}."
        lines = [f"DNS {record_type} records for **{domain}**:"]
        for rec in answers:
            t = _DNS_TYPES.get(rec.get("type"), rec.get("type"))
            lines.append(f"- `{t}` TTL:{rec['TTL']}s → `{rec['data']}`")
        return "\n".join(lines)
    except Exception as e:
        return f"DNS lookup failed: {e}"


def whois_lookup(target: str) -> str:
    try:
        is_ip = bool(re.match(r'^(\d{1,3}\.){3}\d{1,3}$', target))
        url = f"https://rdap.org/{'ip' if is_ip else 'domain'}/{target}"
        resp = requests.get(url, timeout=10, headers={"Accept": "application/json"})
        if not resp.ok:
            return f"WHOIS lookup failed: HTTP {resp.status_code}"
        d = resp.json()
        lines = [f"WHOIS/RDAP for **{target}**:"]
        if d.get("ldhName"):
            lines.append(f"- **Domain:** {d['ldhName']}")
        if d.get("startAddress"):
            lines.append(f"- **IP Range:** {d['startAddress']} – {d.get('endAddress','')}")
        if d.get("status"):
            lines.append(f"- **Status:** {', '.join(d['status'])}")
        for ev in d.get("events", []):
            lines.append(f"- **{ev['eventAction'].title()}:** {ev['eventDate'][:10]}")
        if d.get("nameservers"):
            ns = [ns.get("ldhName", "") for ns in d["nameservers"]]
            lines.append(f"- **Name Servers:** {', '.join(ns)}")
        for ent in d.get("entities", []):
            if ent.get("roles") and ent.get("vcardArray"):
                role = ent["roles"][0].title()
                for field in ent["vcardArray"][1]:
                    if field[0] == "fn" and field[3]:
                        lines.append(f"- **{role}:** {field[3]}")
        return "\n".join(lines) if len(lines) > 1 else "No data returned."
    except Exception as e:
        return f"WHOIS lookup failed: {e}"


def ip_lookup(ip: str = "") -> str:
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,regionName,city,zip,lat,lon,isp,org,as,query"
        resp = requests.get(url, timeout=8)
        d = resp.json()
        if d.get("status") != "success":
            return f"IP lookup failed: {d.get('message', 'unknown error')}"
        lines = [f"IP Lookup for **{d['query']}**:"]
        if d.get("country"):    lines.append(f"- **Country:** {d['country']} ({d.get('countryCode','')})")
        if d.get("regionName"): lines.append(f"- **Region:** {d['regionName']}")
        if d.get("city"):       lines.append(f"- **City:** {d['city']}")
        if d.get("isp"):        lines.append(f"- **ISP:** {d['isp']}")
        if d.get("org"):        lines.append(f"- **Org:** {d['org']}")
        if d.get("as"):         lines.append(f"- **ASN:** {d['as']}")
        if d.get("lat"):        lines.append(f"- **Coords:** {d['lat']}, {d['lon']}")
        return "\n".join(lines)
    except Exception as e:
        return f"IP lookup failed: {e}"


def subdomain_search(domain: str) -> str:
    try:
        resp = requests.get(
            f"https://crt.sh/?q=%.{domain}&output=json",
            timeout=15,
            headers={"Accept": "application/json"},
        )
        if not resp.ok:
            return f"crt.sh lookup failed: HTTP {resp.status_code}"
        data = resp.json()
        seen: set = set()
        for entry in data:
            for name in (entry.get("name_value") or "").split("\n"):
                name = name.strip().lower().lstrip("*.")
                if name and name.endswith(domain.lower()):
                    seen.add(name)
        subs = sorted(seen)
        if not subs:
            return f"No subdomains found in certificate transparency logs for {domain}."
        lines = [f"Subdomains found for **{domain}** ({len(subs)} total):"]
        for s in subs[:60]:
            lines.append(f"- `{s}`")
        if len(subs) > 60:
            lines.append(f"… and {len(subs)-60} more")
        return "\n".join(lines)
    except Exception as e:
        return f"Subdomain search failed: {e}"


def cve_lookup(cve_id: str) -> str:
    try:
        if not cve_id.upper().startswith("CVE-"):
            cve_id = "CVE-" + cve_id
        cve_id = cve_id.upper()
        resp = requests.get(
            "https://services.nvd.nist.gov/rest/json/cves/2.0",
            params={"cveId": cve_id},
            timeout=12,
        )
        if not resp.ok:
            return f"CVE lookup failed: HTTP {resp.status_code}"
        d = resp.json()
        vulns = d.get("vulnerabilities", [])
        if not vulns:
            return f"{cve_id} not found in NVD."
        cve = vulns[0]["cve"]
        lines = [f"**{cve['id']}**"]
        for desc in cve.get("descriptions", []):
            if desc.get("lang") == "en":
                lines.append(f"\n{desc['value']}\n")
                break
        m = cve.get("metrics", {})
        for key in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
            arr = m.get(key, [])
            if arr:
                cd = arr[0]["cvssData"]
                sev = cd.get("baseSeverity") or arr[0].get("baseSeverity", "N/A")
                lines.append(f"- **CVSS Score:** {cd['baseScore']} ({sev})")
                break
        lines.append(f"- **Published:** {cve.get('published','')[:10]}")
        refs = cve.get("references", [])[:4]
        if refs:
            lines.append("- **References:**")
            for r in refs:
                lines.append(f"  - {r['url']}")
        return "\n".join(lines)
    except Exception as e:
        return f"CVE lookup failed: {e}"


def check_hash_malware(hash_value: str) -> str:
    """Query MalwareBazaar (Abuse.ch) for a file hash. No API key required."""
    try:
        resp = requests.post(
            "https://mb-api.abuse.ch/api/v1/",
            data={"query": "get_info", "hash": hash_value.strip()},
            timeout=12,
        )
        d = resp.json()
        if d.get("query_status") == "hash_not_found":
            return f"✅ Hash `{hash_value}` — **not found** in MalwareBazaar. Not a known malware sample."
        if d.get("query_status") != "ok" or not d.get("data"):
            return f"MalwareBazaar returned: {d.get('query_status', 'unknown error')}"
        rec = d["data"][0]
        lines = [f"🚨 **MALWARE DETECTED** — Hash found in MalwareBazaar"]
        if rec.get("file_name"):   lines.append(f"- **File Name:** `{rec['file_name']}`")
        if rec.get("file_type"):   lines.append(f"- **File Type:** {rec['file_type']}")
        if rec.get("file_size"):   lines.append(f"- **File Size:** {rec['file_size']} bytes")
        if rec.get("signature"):   lines.append(f"- **Signature:** `{rec['signature']}`")
        if rec.get("tags"):        lines.append(f"- **Tags:** {', '.join(rec['tags'])}")
        if rec.get("first_seen"):  lines.append(f"- **First Seen:** {rec['first_seen']}")
        if rec.get("sha256_hash"): lines.append(f"- **SHA256:** `{rec['sha256_hash']}`")
        if rec.get("vendor_intel"):
            av = [f"{k}: {v.get('result','?')}" for k, v in list(rec["vendor_intel"].items())[:5]]
            if av: lines.append(f"- **AV Detections:** {', '.join(av)}")
        lines.append("\n⚠️ **Containment advice:** Isolate the host immediately, kill any running process associated with this file, preserve memory/disk image for forensics, then remediate.")
        return "\n".join(lines)
    except Exception as e:
        return f"MalwareBazaar lookup failed: {e}"


def check_url_malware(url: str) -> str:
    """Query URLhaus (Abuse.ch) for a URL or domain. No API key required."""
    try:
        resp = requests.post(
            "https://urlhaus-api.abuse.ch/v1/url/",
            data={"url": url.strip()},
            timeout=12,
        )
        d = resp.json()
        if d.get("query_status") == "no_results":
            return f"✅ URL `{url}` — **not found** in URLhaus. Not a known malware-distribution URL."
        lines = [f"🚨 **MALICIOUS URL DETECTED** — Found in URLhaus"]
        if d.get("threat"):      lines.append(f"- **Threat:** {d['threat']}")
        if d.get("url_status"):  lines.append(f"- **Status:** {d['url_status']}")
        if d.get("tags"):        lines.append(f"- **Tags:** {', '.join(d['tags'])}")
        if d.get("date_added"):  lines.append(f"- **Reported:** {d['date_added']}")
        if d.get("host"):        lines.append(f"- **Host:** `{d['host']}`")
        payloads = d.get("payloads") or []
        if payloads:
            lines.append(f"- **Payloads delivered:** {len(payloads)}")
            for p in payloads[:3]:
                sig = p.get("signature") or "unknown"
                ftype = p.get("file_type") or "?"
                lines.append(f"  - `{sig}` ({ftype})")
        lines.append("\n⚠️ **Containment advice:** Block this URL/host at the firewall and DNS level immediately. If a user clicked it, isolate the machine and check for dropped payloads.")
        return "\n".join(lines)
    except Exception as e:
        return f"URLhaus lookup failed: {e}"