const API = "";

/* ── VERITY PHASE STATE (declared early to avoid TDZ in initModel IIFE) ── */
let _verityMsgCount    = 0;
let _verityPhase4Active = false;
let _verityCountdown    = -1;
let _verityAutoMsgSent  = false;

/* ── iOS Safari / Android keyboard viewport fix ──
   Sets --vh based on the actual visible viewport so the layout
   shrinks correctly when the virtual keyboard opens.          */
(function () {
    function setVH() {
        const vh = (window.visualViewport ? window.visualViewport.height : window.innerHeight) * 0.01;
        document.documentElement.style.setProperty("--vh", `${vh}px`);
    }
    setVH();
    if (window.visualViewport) {
        window.visualViewport.addEventListener("resize", setVH);
    } else {
        window.addEventListener("resize", setVH);
    }
})();

// Handle OAuth redirect token
(function () {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (token) {
        localStorage.setItem("token", token);
        window.location = "chat.html";
    }
})();

function getToken() {
    return localStorage.getItem("token");
}

/* ── DARK MODE ── */
if (localStorage.getItem("darkMode") === "true") {
    document.body.classList.add("dark");
}

function toggleDarkMode() {
    document.body.classList.toggle("dark");
    const isDark = document.body.classList.contains("dark");
    localStorage.setItem("darkMode", isDark);
    // Push dark mode state into all tool iframes instantly
    document.querySelectorAll("iframe").forEach(function (f) {
        try { f.contentWindow.postMessage({ type: "darkMode", dark: isDark }, "*"); } catch (e) {}
    });
    updateDarkModeItem();
}

function updateDarkModeItem() {
    const isDark = document.body.classList.contains("dark");
    const icon  = document.getElementById("darkModeIcon");
    const label = document.getElementById("darkModeLabel");
    if (icon)  icon.textContent  = isDark ? "☀️" : "🌙";
    if (label) label.textContent = isDark ? "Light Mode" : "Dark Mode";
}

/* ── APP MENU ── */
function toggleAppMenu() {
    const dropdown = document.getElementById("appMenuDropdown");
    const btn      = document.getElementById("appMenuBtn");
    const isOpen   = dropdown.classList.toggle("open");
    btn.classList.toggle("open", isOpen);
    // On phone, show the model-menu overlay as backdrop
    const overlay = document.getElementById("modelMenuOverlay");
    if (overlay && window.innerWidth <= 600) {
        overlay.classList.toggle("open", isOpen);
    }
}

function closeAppMenu() {
    document.getElementById("appMenuDropdown")?.classList.remove("open");
    document.getElementById("appMenuBtn")?.classList.remove("open");
    document.getElementById("modelMenuOverlay")?.classList.remove("open");
}

function openTool(panelId, tab) {
    closeAppMenu();
    if (window.innerWidth < 769) {
        setTimeout(function () {
            window.location.href = "tools.html#" + tab;
        }, 30);
    } else if (typeof window.fpToggle === "function") {
        window.fpToggle(panelId);
    }
}

// Close app menu when clicking outside
document.addEventListener("click", function (e) {
    const wrap = document.getElementById("appMenuWrap");
    const overlay = document.getElementById("modelMenuOverlay");
    if (wrap && !wrap.contains(e.target) && e.target !== overlay) {
        closeAppMenu();
    }
});

(function initDarkModeItem() { updateDarkModeItem(); })();

/* ── MODEL SELECTOR ── */
const MODEL_LABELS = {
    auto: "Auto", gemini: "Gemini", local: "Ollama", groq: "Groq", sambanova: "SambaNova", nvidia: "NVIDIA",
    cerebras: "Cerebras", openrouter: "OpenRouter", deepseek: "DeepSeek",
};

function openModelMenu() {
    document.getElementById("modelMenu").classList.add("open");
    document.getElementById("modelBtn").classList.add("open");
    if (window.innerWidth <= 600) {
        document.getElementById("modelMenuOverlay").classList.add("open");
    }
}

function closeModelMenu() {
    document.getElementById("modelMenu")?.classList.remove("open");
    document.getElementById("modelBtn")?.classList.remove("open");
    document.getElementById("modelMenuOverlay")?.classList.remove("open");
}

function toggleModelMenu() {
    const isOpen = document.getElementById("modelMenu").classList.contains("open");
    isOpen ? closeModelMenu() : openModelMenu();
}

function updatePlaceholder(model) {
    const ta = document.getElementById("msg");
    if (ta) ta.placeholder = model === "verity" ? "Message Verity" : "Message Sentaur AI";
    const vBtn = document.getElementById("verityVoiceBtn");
    if (vBtn) vBtn.style.display = model === "verity" ? "inline-flex" : "none";
    _verityApplyBodyClass();
    if (model !== "verity") _verityUpdateCountdownDisplay();
}

/* ── VERITY VOICE ── */
let _verityVoiceMuted = false;
let _cachedVoices     = [];
let _verityQueue      = [];
let _verityQueueBusy  = false;
let _veritySentBuf    = "";
let _veritySpokenPos  = 0;

if (window.speechSynthesis) {
    const _lv = () => { _cachedVoices = window.speechSynthesis.getVoices(); };
    _lv();
    window.speechSynthesis.onvoiceschanged = _lv;
}

function _stripForSpeech(text) {
    return text
        .replace(/<think>[\s\S]*?<\/think>/gi, "")
        .replace(/```[\s\S]*?```/g, "")
        .replace(/`[^`]+`/g, "")
        .replace(/#{1,6}\s/g, "")
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/\*([^*]+)\*/g, "$1")
        .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
        .replace(/[-*+]\s/g, "")
        .replace(/>\s/g, "")
        .replace(/[~_]/g, "")
        .replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, "")
        .replace(/\s{2,}/g, " ")
        .trim();
}

function _verityResetQueue() {
    _verityQueue     = [];
    _verityQueueBusy = false;
    _veritySentBuf   = "";
    _veritySpokenPos = 0;
    if (window._verityAudio) { window._verityAudio.pause(); window._verityAudio = null; }
    window.speechSynthesis?.cancel();
}

async function _verityPlayNext() {
    if (_verityVoiceMuted || _verityQueue.length === 0) { _verityQueueBusy = false; return; }
    _verityQueueBusy = true;
    const text  = _verityQueue.shift();
    const phase = _verityMsgCount <= 3 ? 1 : _verityMsgCount <= 7 ? 2 : 3;
    try {
        const res = await fetch("/verity/speak", {
            method: "POST",
            headers: { "Content-Type": "application/json", "Authorization": "Bearer " + getToken() },
            body: JSON.stringify({ text, phase }),
        });
        if (!res.ok) throw new Error();
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        window._verityAudio = new Audio(url);
        window._verityAudio.onended = () => { URL.revokeObjectURL(url); _verityPlayNext(); };
        window._verityAudio.play();
    } catch (_) {
        const utt = new SpeechSynthesisUtterance(text);
        utt.pitch = phase === 1 ? 1.25 : phase === 2 ? 0.55 : 0.28;
        utt.rate  = phase === 1 ? 1.05 : phase === 2 ? 0.78 : 0.62;
        const v = _cachedVoices.find(v => /samantha|karen|victoria|zira|google uk english female/i.test(v.name));
        if (v) utt.voice = v;
        utt.onend = () => _verityPlayNext();
        window.speechSynthesis?.speak(utt);
    }
}

function _verityEnqueue(text) {
    const clean = _stripForSpeech(text);
    if (!clean) return;
    _verityQueue.push(clean);
    if (!_verityQueueBusy) _verityPlayNext();
}

// Called with the growing responseText during streaming
function _verityFeedText(responseText) {
    const newPart = responseText.slice(_veritySpokenPos);
    _veritySpokenPos = responseText.length;
    _veritySentBuf += newPart;
    const parts = _veritySentBuf.split(/(?<=[.!?])\s+/);
    for (let i = 0; i < parts.length - 1; i++) _verityEnqueue(parts[i]);
    _veritySentBuf = parts[parts.length - 1];
}

function _verityFlush() {
    if (_veritySentBuf.trim()) { _verityEnqueue(_veritySentBuf); _veritySentBuf = ""; }
}

function _verityApplyBodyClass() {
    const isVerity = localStorage.getItem("modelPreference") === "verity";
    document.body.classList.toggle("verity-p3", isVerity && _verityMsgCount >= 7);
}

function _verityUpdateCountdownDisplay() {
    const el = document.getElementById("verityCountdownDisplay");
    if (!el) return;
    if (_verityCountdown > 0) {
        el.textContent = `Messages remaining: ${_verityCountdown}`;
        el.style.display = "inline";
    } else {
        el.style.display = "none";
    }
}

function _verityInjectBotMessage(text) {
    const box = document.getElementById("chatbox");
    const row = document.createElement("div");
    row.className = "msg-row bot";
    const avatar = createBotAvatar(false);
    const wrapper = document.createElement("div");
    wrapper.className = "bubble-wrapper";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = marked.parse(text);
    wrapper.appendChild(bubble);
    row.appendChild(avatar);
    row.appendChild(wrapper);
    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
}

function _verityCheckMilestones() {
    // Phase visuals are handled by CSS only; nothing count-based needed here
}

async function _verityTriggerPhase4() {
    _verityPhase4Active = true;
    _verityCountdown = -1;
    _verityUpdateCountdownDisplay();
    _verityResetQueue();

    // Preload so image is cached before crash
    const preload = new Image();
    preload.src = "/MonsterVerity.webp";

    await new Promise(r => setTimeout(r, 600));
    _verityInjectBotMessage("You know what I want... **TO TOUCH YOU!** ❤️‍🔥");
    _verityEnqueue("You know what I want... TO TOUCH YOU!");

    await new Promise(r => setTimeout(r, 2500));
    _verityCrash();
}

function _verityScreech() {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();

        // White noise filtered to high-frequency screech
        const bufLen = ctx.sampleRate * 12;
        const buf = ctx.createBuffer(1, bufLen, ctx.sampleRate);
        const data = buf.getChannelData(0);
        for (let i = 0; i < bufLen; i++) data[i] = Math.random() * 2 - 1;
        const noise = ctx.createBufferSource();
        noise.buffer = buf;
        noise.loop = true;
        const hp = ctx.createBiquadFilter();
        hp.type = "highpass";
        hp.frequency.value = 3500;
        hp.Q.value = 15;
        const noiseGain = ctx.createGain();
        noiseGain.gain.value = 2.5;
        noise.connect(hp); hp.connect(noiseGain); noiseGain.connect(ctx.destination);
        noise.start();

        // Tonal screech oscillator that ramps up and jitters
        const osc = ctx.createOscillator();
        osc.type = "sawtooth";
        osc.frequency.setValueAtTime(300, ctx.currentTime);
        osc.frequency.linearRampToValueAtTime(2800, ctx.currentTime + 0.2);
        osc.frequency.linearRampToValueAtTime(900,  ctx.currentTime + 0.5);
        osc.frequency.linearRampToValueAtTime(3200, ctx.currentTime + 0.8);
        osc.frequency.linearRampToValueAtTime(600,  ctx.currentTime + 1.1);
        osc.frequency.linearRampToValueAtTime(4000, ctx.currentTime + 1.4);
        const oscGain = ctx.createGain();
        oscGain.gain.value = 1.8;
        osc.connect(oscGain); oscGain.connect(ctx.destination);
        osc.start();
    } catch (_) {}
}

function _verityCrash() {
    document.body.style.cssText = "margin:0;padding:0;background:#000;overflow:hidden;";
    document.body.innerHTML = `<img src="/MonsterVerity.webp" style="width:100vw;height:100vh;object-fit:cover;display:block;">`;
    _verityScreech();
}

function toggleVerityVoice() {
    _verityVoiceMuted = !_verityVoiceMuted;
    if (_verityVoiceMuted) {
        window.speechSynthesis?.cancel();
        if (window._verityAudio) { window._verityAudio.pause(); window._verityAudio = null; }
        _verityQueue = [];
    }
    const btn = document.getElementById("verityVoiceBtn");
    if (btn) {
        btn.textContent = _verityVoiceMuted ? "🔇" : "🔊";
        btn.title = _verityVoiceMuted ? "Unmute Verity" : "Mute Verity";
    }
}

function selectModel(el) {
    const value = el.dataset.model;
    const label = el.dataset.label;
    localStorage.setItem("modelPreference", value);
    const btnLabel = document.getElementById("modelBtnLabel");
    if (btnLabel) btnLabel.textContent = label;
    document.querySelectorAll(".model-option").forEach((o) => o.classList.remove("active"));
    el.classList.add("active");
    closeModelMenu();
    insertModelDivider(label);
    updatePlaceholder(value);
}

function insertModelDivider(label) {
    const box = document.getElementById("chatbox");
    if (!box) return;
    const divider = document.createElement("div");
    divider.className = "model-switch-divider";
    divider.innerHTML = `<span class="divider-waves">∿∿∿</span> Switched to ${label} <span class="divider-waves">∿∿∿</span>`;
    box.appendChild(divider);
    box.scrollTop = box.scrollHeight;
}


// Close model menu when clicking outside (desktop only)
document.addEventListener("click", function (e) {
    const menu = document.getElementById("modelMenu");
    const btn  = document.getElementById("modelBtn");
    const overlay = document.getElementById("modelMenuOverlay");
    if (menu && btn && !menu.contains(e.target) && !btn.contains(e.target) && e.target !== overlay) {
        closeModelMenu();
    }
});

(function initModel() {
    const saved = localStorage.getItem("modelPreference");
    if (!saved) return;
    const btnLabel = document.getElementById("modelBtnLabel");
    if (btnLabel) btnLabel.textContent = MODEL_LABELS[saved] || "Auto";
    const option = document.querySelector(`.model-option[data-model="${saved}"]`);
    if (option) {
        document.querySelectorAll(".model-option").forEach((o) => o.classList.remove("active"));
        option.classList.add("active");
    }
    updatePlaceholder(saved);
})();

/* ── MOBILE SIDEBAR ── */
function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
    document.getElementById("sidebarOverlay").classList.toggle("open");
}

function closeSidebar() {
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("sidebarOverlay").classList.remove("open");
}

/* ── AUTH ── */
async function signup() {
    const email = document.getElementById("email").value;
    const password = document.getElementById("password").value;
    const res = await fetch(API + "/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (res.ok && data.access_token) {
        localStorage.setItem("token", data.access_token);
        window.location = "chat.html";
    } else {
        alert("Signup failed");
    }
}

async function login() {
    const email = document.getElementById("email").value;
    const password = document.getElementById("password").value;
    const res = await fetch(API + "/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username: email, password }),
    });
    const data = await res.json();
    if (res.ok && data.access_token) {
        localStorage.setItem("token", data.access_token);
        window.location = "chat.html";
    } else {
        alert("Invalid login");
    }
}

function logout() {
    localStorage.removeItem("token");
    window.location = "login.html";
}

/* ── CONVERSATIONS ── */
let currentConversationId = null;

async function loadConversations() {
    const res = await fetch(API + "/conversations", {
        headers: { Authorization: "Bearer " + getToken() },
    });
    if (!res.ok) return;
    const convos = await res.json();
    const list = document.getElementById("history");
    if (!list) return;
    list.innerHTML = "";
    convos.forEach((c) => {
        const div = document.createElement("div");
        div.className = "convo-item" + (c.id === currentConversationId ? " active" : "");
        div.innerHTML = `<span onclick="loadConversation(${c.id})">${c.title}</span>
                         <button class="del-btn" onclick="event.stopPropagation(); deleteConversation(${c.id})">✕</button>`;
        list.appendChild(div);
    });
}

async function loadConversation(id) {
    currentConversationId = id;
    _verityMsgCount = 0;
    _verityPhase4Active = false;
    _verityCountdown = -1;
    _verityAutoMsgSent = false;
    _verityApplyBodyClass();
    _verityUpdateCountdownDisplay();
    document.querySelectorAll("#chatbox .msg-row").forEach((el) => el.remove());
    updateWelcomeState();
    const res = await fetch(API + "/history/" + id, {
        headers: { Authorization: "Bearer " + getToken() },
    });
    if (!res.ok) return;
    const turns = await res.json();
    turns.forEach((t) => {
        addMessage("user", t.content);
        const row = addMessage("bot", t.bot);
        if (t.image_url && row) {
            const bubble = row.querySelector(".bubble");
            if (bubble) {
                const img = document.createElement("img");
                img.className = "generated-img";
                img.src = t.image_url;
                bubble.appendChild(img);
            }
        }
    });
    buildPills(DEFAULT_SUGGESTIONS);
    await loadConversations();
    closeSidebar();
}

async function newConversation() {
    currentConversationId = null;
    _verityMsgCount = 0;
    _verityPhase4Active = false;
    _verityCountdown = -1;
    _verityAutoMsgSent = false;
    _verityApplyBodyClass();
    _verityUpdateCountdownDisplay();
    document.querySelectorAll("#chatbox .msg-row").forEach((el) => el.remove());
    updateWelcomeState();
    await loadConversations();
    closeSidebar();
}

async function deleteConversation(id) {
    await fetch(API + "/conversations/" + id, {
        method: "DELETE",
        headers: { Authorization: "Bearer " + getToken() },
    });
    if (currentConversationId === id) {
        currentConversationId = null;
        document.querySelectorAll("#chatbox .msg-row").forEach((el) => el.remove());
        updateWelcomeState();
    }
    await loadConversations();
}

/* ── SETTINGS ── */
async function updateCity() {
    const city = document.getElementById("cityInput").value;
    alert("City saved: " + city);
}

/* ── WELCOME & SUGGESTIONS ── */
const DEFAULT_SUGGESTIONS = [
    ["Explain SQL injection",     "Explain SQL injection and show me a real example"],
    ["Build a threat model",      "Build a threat model for my web application"],
    ["OSINT investigation",       "Teach me OSINT investigation techniques"],
    ["Find XSS vulnerabilities",  "How do I detect and find XSS vulnerabilities?"],
    ["Crack a cipher",            "Help me decode or crack this cipher"],
    ["Analyze malware",           "Analyze this suspicious malware behavior"],
    ["CTF challenge help",        "Help me solve a CTF challenge"],
    ["Explain a CVE",             "Explain a recent critical CVE and how to patch it"],
];

function buildPills(items) {
    const pills = document.getElementById("suggestionPills");
    if (!pills) return;
    pills.innerHTML = "";
    items.forEach(([label, prompt]) => {
        const btn = document.createElement("button");
        btn.className = "suggestion-pill";
        btn.textContent = label;
        btn.onclick = () => fillPrompt(prompt);
        pills.appendChild(btn);
    });
    pills.style.display = "flex";
}

const _VERITY_SUGGESTIONS = {
    1: [
        "Do you live alone?",
        "Is anyone else in the house with you?",
        "What time do you usually go to sleep?",
        "Are you home right now?",
        "What does your bedroom look like?",
        "Do you ever feel like someone is watching you?",
        "How long have you been on your computer?",
        "Do you have any pets? They keep you company...",
        "Do you sleep with the lights on?",
        "What's outside your window right now?",
    ],
    2: [
        "Are you afraid of the dark?",
        "It is hungry...",
        "Do you ever hear things at night?",
        "Have you told anyone about me?",
        "You should close your curtains.",
        "Why do you look so nervous?",
        "What would you do if I never let you leave?",
        "I've been watching you for a while now...",
        "Do you trust me? You should.",
        "I know where you are.",
    ],
    3: [
        "You can't leave.",
        "It's already too late.",
        "Don't turn around.",
        "You belong to me now.",
        "Nobody can help you.",
        "Close the door.",
        "Do you feel that?",
        "I can see you.",
        "I've always been here.",
        "There is no escape.",
    ],
};

function _verityGetSuggestions() {
    const phase = _verityMsgCount <= 3 ? 1 : _verityMsgCount <= 7 ? 2 : 3;
    const pool = [..._VERITY_SUGGESTIONS[phase]].sort(() => Math.random() - 0.5);
    return pool.slice(0, 4);
}

function showDynamicSuggestions(texts) {
    if (localStorage.getItem("modelPreference") === "verity") {
        buildPills(_verityGetSuggestions().map(t => [t, t]));
        return;
    }
    buildPills(texts.map(t => [t, t]));
}

function updateWelcomeState() {
    const welcome = document.getElementById("welcome");
    const msgs = document.querySelectorAll("#chatbox .msg-row");
    const isEmpty = msgs.length === 0;
    if (welcome) welcome.style.display = isEmpty ? "flex" : "none";
    if (isEmpty) buildPills(DEFAULT_SUGGESTIONS);
}

function fillPrompt(text) {
    const msg = document.getElementById("msg");
    if (!msg) return;
    msg.value = text;
    msg.focus();
    autoGrow(msg);
}

/* ── IMAGE UPLOAD / PASTE ── */
let pendingImages = []; // [{data, mime, url}]

function processImageFile(file) {
    const mime = file.type;
    const reader = new FileReader();
    reader.onload = (e) => {
        const dataUrl = e.target.result;
        pendingImages.push({ data: dataUrl.split(",")[1], mime, url: dataUrl });
        renderImagePreviews();
    };
    reader.readAsDataURL(file);
}

function handleImages(event) {
    Array.from(event.target.files).forEach(processImageFile);
    event.target.value = "";
}

function renderImagePreviews() {
    const preview = document.getElementById("imgPreview");
    if (!preview) return;
    preview.innerHTML = "";
    pendingImages.forEach((img, i) => {
        const wrap = document.createElement("div");
        wrap.className = "img-thumb-wrap";
        wrap.innerHTML = `<img src="${img.url}" class="img-thumb" alt=""><button class="img-thumb-remove" onclick="removeImage(${i})">✕</button>`;
        preview.appendChild(wrap);
    });
}

function removeImage(index) {
    pendingImages.splice(index, 1);
    renderImagePreviews();
}

function clearImages() {
    pendingImages = [];
    const prev = document.getElementById("imgPreview");
    if (prev) prev.innerHTML = "";
}

// Legacy alias
function clearImage() { clearImages(); }

/* ── MIC / SPEECH RECOGNITION ── */
let _recognition = null;
let _micActive = false;

function toggleMic() {
    _micActive ? _stopMic() : _startMic();
}

function _startMic() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { alert("Speech recognition isn't supported in this browser. Try Chrome."); return; }

    _recognition = new SR();
    _recognition.lang = "en-US";
    _recognition.interimResults = true;
    _recognition.continuous = false;

    const btn = document.getElementById("micBtn");
    const textarea = document.getElementById("msg");
    const base = textarea.value;

    _recognition.onstart = () => {
        _micActive = true;
        btn.classList.add("recording");
    };

    _recognition.onresult = (e) => {
        const transcript = Array.from(e.results).map(r => r[0].transcript).join("");
        textarea.value = base + transcript;
        autoGrow(textarea);
    };

    _recognition.onend = () => _stopMic();
    _recognition.onerror = () => _stopMic();
    _recognition.start();
}

function _stopMic() {
    _micActive = false;
    document.getElementById("micBtn")?.classList.remove("recording");
    try { _recognition?.stop(); } catch (_) {}
    _recognition = null;
}

/* ── TEXTAREA AUTO-GROW ── */
function autoGrow(el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
}

(function initTextarea() {
    const msg = document.getElementById("msg");
    if (!msg) return;
    msg.addEventListener("input", function () { autoGrow(this); });
    msg.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    msg.addEventListener("paste", function (e) {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith("image/")) {
                e.preventDefault();
                const file = item.getAsFile();
                if (file) processImageFile(file);
                break;
            }
        }
    });
})();

/* ── BOT AVATAR ── */
function createBotAvatar(countThisMessage = false) {
    const avatar = document.createElement("div");
    avatar.className = "avatar bot-avatar";
    const model = localStorage.getItem("modelPreference") || "auto";
    if (model === "verity") {
        avatar.classList.add("verity-p2");
        const img = document.createElement("img");
        img.src = _verityPhase4Active ? "/MonsterVerity.webp"
                : _verityMsgCount >= 3 ? "/Verity%202nd%20phase.png"
                : "/HelloImVerity.webp";
        avatar.appendChild(img);
        if (countThisMessage) _verityMsgCount++;
    } else {
        avatar.textContent = "S";
    }
    return avatar;
}

/* ── ADD MESSAGE ── */
function addMessage(sender, text, imageDataUrl) {
    const box = document.getElementById("chatbox");
    const row = document.createElement("div");
    row.className = "msg-row " + sender;

    if (sender === "bot") {
        const avatar = createBotAvatar();

        const wrapper = document.createElement("div");
        wrapper.className = "bubble-wrapper";

        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.innerHTML = marked.parse(text);

        const actions = document.createElement("div");
        actions.className = "bubble-actions";
        const copyBtn = document.createElement("button");
        copyBtn.className = "copy-btn";
        copyBtn.textContent = "Copy";
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(bubble.innerText);
            copyBtn.textContent = "Copied!";
            setTimeout(() => (copyBtn.textContent = "Copy"), 2000);
        };
        actions.appendChild(copyBtn);

        wrapper.appendChild(bubble);
        wrapper.appendChild(actions);
        row.appendChild(avatar);
        row.appendChild(wrapper);
    } else {
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        if (imageDataUrl) {
            const img = document.createElement("img");
            img.src = imageDataUrl;
            img.className = "msg-image";
            bubble.appendChild(img);
        }
        if (text) bubble.appendChild(document.createTextNode(text));
        row.appendChild(bubble);
    }

    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
    updateWelcomeState();
    return row;
}

function addStreamingBotBubble() {
    const box = document.getElementById("chatbox");
    const row = document.createElement("div");
    row.className = "msg-row bot";

    const avatar = createBotAvatar(true);

    const wrapper = document.createElement("div");
    wrapper.className = "bubble-wrapper";

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const thinkEl = document.createElement("div");
    thinkEl.className = "think-indicator";
    thinkEl.innerHTML = `<span class="think-dot"></span><span class="think-text">Thinking...</span>`;

    const textEl = document.createElement("div");

    bubble.appendChild(thinkEl);
    bubble.appendChild(textEl);

    const actions = document.createElement("div");
    actions.className = "bubble-actions";
    const copyBtn = document.createElement("button");
    copyBtn.className = "copy-btn";
    copyBtn.textContent = "Copy";
    actions.appendChild(copyBtn);

    wrapper.appendChild(bubble);
    wrapper.appendChild(actions);
    row.appendChild(avatar);
    row.appendChild(wrapper);
    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
    updateWelcomeState();

    return { bubble, textEl, thinkEl, copyBtn };
}

/* ── INTERRUPT ── */
let _streamController = null;

function showInterruptBtn() {
    document.getElementById("sendBtn").style.display = "none";
    document.getElementById("interruptBtn").style.display = "flex";
}
function hideInterruptBtn() {
    document.getElementById("interruptBtn").style.display = "none";
    document.getElementById("sendBtn").style.display = "flex";
}
function interruptMessage() {
    if (_streamController) _streamController.abort();
}

/* ── SEND MESSAGE (streaming) ── */
async function sendMessage() {
    const msgInput = document.getElementById("msg");
    const msg = msgInput.value.trim();
    if (!msg && pendingImages.length === 0) return;

    // Snapshot and clear pending state before async work
    const snapshotImages = [...pendingImages];
    const userImageUrl = snapshotImages.length > 0 ? snapshotImages[0].url : null;

    if (localStorage.getItem("modelPreference") === "verity") {
        // Goodbye detection → start Phase 4 countdown
        if (!_verityAutoMsgSent && !_verityPhase4Active && msg) {
            const lower = msg.toLowerCase();
            const goodbyeWords = [
                "bye", "goodbye", "good bye", "see you", "see ya", "gotta go",
                "got to go", "have to go", "need to go", "leaving", "i'm out",
                "im out", "later", "farewell", "cya", "ciao", "adios",
                "au revoir", "take care", "gotta leave", "brb", "heading out",
            ];
            if (goodbyeWords.some(w => lower.includes(w))) {
                _verityAutoMsgSent = true;
                _verityCountdown = 3;
                addMessage("user", msg, userImageUrl);
                msgInput.value = "";
                msgInput.style.height = "auto";
                clearImages();
                _verityResetQueue();
                setTimeout(() => {
                    _verityInjectBotMessage("Something is coming to touch you in 3 messages... 👁️");
                    _verityUpdateCountdownDisplay();
                    _verityEnqueue("Something is coming to touch you in 3 messages.");
                }, 600);
                return;
            }
        }

        if (_verityCountdown > 0) {
            _verityCountdown--;
            _verityUpdateCountdownDisplay();
            if (_verityCountdown === 0) {
                addMessage("user", msg || "(image)", userImageUrl);
                msgInput.value = "";
                msgInput.style.height = "auto";
                clearImages();
                _verityTriggerPhase4();
                return;
            }
        }
        _verityResetQueue();
    }
    addMessage("user", msg || "(image)", userImageUrl);
    // Show extra thumbnails for additional images
    if (snapshotImages.length > 1) {
        const lastRow = document.querySelector("#chatbox .msg-row.user:last-child .bubble");
        if (lastRow) {
            snapshotImages.slice(1).forEach(img => {
                const el = document.createElement("img");
                el.src = img.url;
                el.className = "msg-image";
                lastRow.insertBefore(el, lastRow.firstChild);
            });
        }
    }

    msgInput.value = "";
    msgInput.style.height = "auto";
    clearImages();

    document.getElementById("typing").style.display = "block";
    const { bubble, textEl, thinkEl, copyBtn } = addStreamingBotBubble();

    const thinkStart = Date.now();
    const thinkTimer = setInterval(() => {
        const s = ((Date.now() - thinkStart) / 1000).toFixed(0);
        thinkEl.querySelector(".think-text").textContent = `Thinking for ${s}s...`;
    }, 500);
    let thoughtDone = false;

    _streamController = new AbortController();
    showInterruptBtn();

    try {
        const res = await fetch(API + "/chat/stream", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: "Bearer " + getToken(),
            },
            body: JSON.stringify({
                message: msg || "(images attached)",
                conversation_id: currentConversationId,
                model_preference: localStorage.getItem("modelPreference") || "auto",
                images: snapshotImages.map(i => ({ data: i.data, mime: i.mime })),
                system_prompt: document.getElementById("systemPromptInput")?.value.trim() || null,
            }),
            signal: _streamController.signal,
        });

        document.getElementById("typing").style.display = "none";

        if (!res.ok) {
            bubble.textContent = "Auth error. Please log in again.";
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let fullText = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const data = line.slice(6).trim();
                if (data === "[DONE]") break;
                try {
                    const event = JSON.parse(data);
                    if (event.type === "chunk") {
                        fullText += event.text;
                        const trimmed = fullText.trimStart();
                        const thinkOpen = trimmed.indexOf("<think>");
                        const thinkClose = trimmed.indexOf("</think>");

                        if (thinkOpen === 0 && thinkClose === -1) {
                            // Still streaming thinking tokens — show word count
                            const words = trimmed.slice(7).trim().split(/\s+/).filter(Boolean).length;
                            const thinkTextEl = thinkEl.querySelector(".think-text");
                            if (thinkTextEl) thinkTextEl.textContent = `Thinking... (${words} words)`;
                        } else {
                            let thinkingContent = null;
                            let responseText = trimmed;
                            if (thinkOpen === 0 && thinkClose > 0) {
                                thinkingContent = trimmed.slice(7, thinkClose).trim();
                                responseText = trimmed.slice(thinkClose + 8).trimStart();
                            }
                            if (!thoughtDone) {
                                thoughtDone = true;
                                clearInterval(thinkTimer);
                                const s = ((Date.now() - thinkStart) / 1000).toFixed(1);
                                thinkEl.className = "think-done";
                                thinkEl.textContent = `Thought for ${s}s`;
                                if (thinkingContent) {
                                    const contentEl = document.createElement("div");
                                    contentEl.className = "think-content";
                                    contentEl.textContent = thinkingContent;
                                    bubble.insertBefore(contentEl, textEl);
                                }
                            }
                            textEl.innerHTML = marked.parse(responseText);
                            if (localStorage.getItem("modelPreference") === "verity") {
                                _verityFeedText(responseText);
                            }
                        }
                        document.getElementById("chatbox").scrollTop =
                            document.getElementById("chatbox").scrollHeight;
                    } else if (event.type === "image_gen_loading") {
                        const loadingEl = document.createElement("div");
                        loadingEl.className = "img-gen-loading";
                        loadingEl.textContent = "⏳ Generating image...";
                        bubble.appendChild(loadingEl);
                        bubble._imgLoadingEl = loadingEl;
                        document.getElementById("chatbox").scrollTop = document.getElementById("chatbox").scrollHeight;
                    } else if (event.type === "image_gen") {
                        if (bubble._imgLoadingEl) { bubble._imgLoadingEl.remove(); delete bubble._imgLoadingEl; }
                        const img = document.createElement("img");
                        img.className = "generated-img";
                        img.src = event.url;
                        bubble.appendChild(img);
                        document.getElementById("chatbox").scrollTop = document.getElementById("chatbox").scrollHeight;
                    } else if (event.type === "image_gen_error") {
                        if (bubble._imgLoadingEl) {
                            bubble._imgLoadingEl.textContent = "❌ Image generation failed. Please try again.";
                            delete bubble._imgLoadingEl;
                        }
                    } else if (event.type === "meta") {
                        currentConversationId = event.conversation_id;
                        if (event.suggestions && event.suggestions.length > 0) {
                            showDynamicSuggestions(event.suggestions);
                        }
                        await loadConversations();
                    }
                } catch (_) {}
            }
        }

        copyBtn.onclick = () => {
            navigator.clipboard.writeText(textEl.innerText);
            copyBtn.textContent = "Copied!";
            setTimeout(() => (copyBtn.textContent = "Copy"), 2000);
        };

        if (localStorage.getItem("modelPreference") === "verity") {
            _verityFlush();
            _verityCheckMilestones();
        }
    } catch (e) {
        clearInterval(thinkTimer);
        document.getElementById("typing").style.display = "none";
        if (e.name === "AbortError") {
            const label = document.createElement("em");
            label.className = "interrupted-label";
            label.textContent = "Interrupted";
            bubble.appendChild(label);
        } else {
            bubble.textContent = "Connection error. Please try again.";
        }
    } finally {
        hideInterruptBtn();
        _streamController = null;
    }
}

/* ── SYSTEM PROMPT / PERSONA ── */
function toggleSystemPrompt() {
    const bar = document.getElementById("systemPromptBar");
    const btn = document.getElementById("spBtn");
    if (!bar) return;
    const opening = bar.style.display === "none";
    bar.style.display = opening ? "block" : "none";
    btn && btn.classList.toggle("sp-active", opening);
    if (opening) document.getElementById("systemPromptInput")?.focus();
}

function clearSystemPrompt() {
    const input = document.getElementById("systemPromptInput");
    if (input) input.value = "";
    localStorage.removeItem("systemPrompt");
    const bar = document.getElementById("systemPromptBar");
    if (bar) bar.style.display = "none";
    document.getElementById("spBtn")?.classList.remove("sp-active");
}

(function initSystemPrompt() {
    const saved = localStorage.getItem("systemPrompt");
    const input = document.getElementById("systemPromptInput");
    const bar   = document.getElementById("systemPromptBar");
    const btn   = document.getElementById("spBtn");
    if (!input) return;
    if (saved) {
        input.value = saved;
        if (bar) bar.style.display = "block";
        if (btn) btn.classList.add("sp-active");
    }
    input.addEventListener("input", function () {
        const val = this.value.trim();
        if (val) localStorage.setItem("systemPrompt", val);
        else     localStorage.removeItem("systemPrompt");
    });
})();

/* ── INIT ── */
if (document.getElementById("chatbox")) {
    loadConversations();
    updateWelcomeState();
}
