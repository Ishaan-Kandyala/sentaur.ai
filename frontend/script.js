const API = "";

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
    localStorage.setItem("darkMode", document.body.classList.contains("dark"));
}

/* ── MODEL SELECTOR ── */
function saveModel(val) {
    localStorage.setItem("modelPreference", val);
}

(function initModel() {
    const saved = localStorage.getItem("modelPreference");
    const sel = document.getElementById("modelSelect");
    if (saved && sel) sel.value = saved;
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
    document.querySelectorAll("#chatbox .msg-row").forEach((el) => el.remove());
    updateWelcomeState();
    const res = await fetch(API + "/history/" + id, {
        headers: { Authorization: "Bearer " + getToken() },
    });
    if (!res.ok) return;
    const turns = await res.json();
    turns.forEach((t) => {
        addMessage("user", t.content);
        addMessage("bot", t.bot);
    });
    await loadConversations();
    closeSidebar();
}

async function newConversation() {
    currentConversationId = null;
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

/* ── WELCOME STATE ── */
function updateWelcomeState() {
    const welcome = document.getElementById("welcome");
    if (!welcome) return;
    const msgs = document.querySelectorAll("#chatbox .msg-row");
    welcome.style.display = msgs.length === 0 ? "flex" : "none";
}

function fillPrompt(text) {
    const msg = document.getElementById("msg");
    if (!msg) return;
    msg.value = text;
    msg.focus();
    autoGrow(msg);
}

/* ── IMAGE UPLOAD ── */
let pendingImageData = null;
let pendingImageMime = null;

function handleImage(event) {
    const file = event.target.files[0];
    if (!file) return;
    pendingImageMime = file.type;
    const reader = new FileReader();
    reader.onload = (e) => {
        const dataUrl = e.target.result;
        pendingImageData = dataUrl.split(",")[1];
        document.getElementById("imgPreview").innerHTML = `
            <img src="${dataUrl}" alt="preview">
            <button onclick="clearImage()">✕</button>`;
    };
    reader.readAsDataURL(file);
}

function clearImage() {
    pendingImageData = null;
    pendingImageMime = null;
    const inp = document.getElementById("imgInput");
    if (inp) inp.value = "";
    const prev = document.getElementById("imgPreview");
    if (prev) prev.innerHTML = "";
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
})();

/* ── ADD MESSAGE (history / non-streaming) ── */
function addMessage(sender, text, imageDataUrl) {
    const box = document.getElementById("chatbox");
    const row = document.createElement("div");
    row.className = "msg-row " + sender;

    if (sender === "bot") {
        const avatar = document.createElement("div");
        avatar.className = "avatar bot-avatar";
        avatar.textContent = "S";

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

/* Creates an empty streaming bot bubble and returns the bubble element + copy button */
function addStreamingBotBubble() {
    const box = document.getElementById("chatbox");
    const row = document.createElement("div");
    row.className = "msg-row bot";

    const avatar = document.createElement("div");
    avatar.className = "avatar bot-avatar";
    avatar.textContent = "S";

    const wrapper = document.createElement("div");
    wrapper.className = "bubble-wrapper";

    const bubble = document.createElement("div");
    bubble.className = "bubble";

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

    return { bubble, copyBtn };
}

/* ── SEND MESSAGE (streaming) ── */
async function sendMessage() {
    const msgInput = document.getElementById("msg");
    const msg = msgInput.value.trim();
    if (!msg && !pendingImageData) return;

    const imageDataUrl = pendingImageData ? `data:${pendingImageMime};base64,${pendingImageData}` : null;
    const imageData = pendingImageData;
    const imageMime = pendingImageMime;

    addMessage("user", msg || "(image)", imageDataUrl);
    msgInput.value = "";
    msgInput.style.height = "auto";
    clearImage();

    document.getElementById("typing").style.display = "block";
    const { bubble, copyBtn } = addStreamingBotBubble();

    try {
        const res = await fetch(API + "/chat/stream", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: "Bearer " + getToken(),
            },
            body: JSON.stringify({
                message: msg || "(image attached)",
                conversation_id: currentConversationId,
                model_preference: localStorage.getItem("modelPreference") || "auto",
                image_data: imageData,
                image_mime: imageMime,
            }),
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
                        bubble.innerHTML = marked.parse(fullText);
                        document.getElementById("chatbox").scrollTop =
                            document.getElementById("chatbox").scrollHeight;
                    } else if (event.type === "meta") {
                        currentConversationId = event.conversation_id;
                        await loadConversations();
                    }
                } catch (_) {}
            }
        }

        copyBtn.onclick = () => {
            navigator.clipboard.writeText(bubble.innerText);
            copyBtn.textContent = "Copied!";
            setTimeout(() => (copyBtn.textContent = "Copy"), 2000);
        };
    } catch (e) {
        document.getElementById("typing").style.display = "none";
        bubble.textContent = "Connection error. Please try again.";
    }
}

/* ── INIT ── */
if (document.getElementById("chatbox")) {
    loadConversations();
    updateWelcomeState();
}
