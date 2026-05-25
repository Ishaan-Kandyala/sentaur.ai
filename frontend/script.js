const API = "";

// Handle OAuth redirect token
(function() {
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

/* SIGNUP */
async function signup() {
    const email = document.getElementById("email").value;
    const password = document.getElementById("password").value;
    const res = await fetch(API + "/auth/signup", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ email, password })
    });
    const data = await res.json();
    if (res.ok && data.access_token) {
        localStorage.setItem("token", data.access_token);
        window.location = "chat.html";
    } else {
        alert("Signup failed");
    }
}

/* LOGIN */
async function login() {
    const email = document.getElementById("email").value;
    const password = document.getElementById("password").value;
    const res = await fetch(API + "/auth/login", {
        method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body: new URLSearchParams({ username: email, password })
    });
    const data = await res.json();
    if (res.ok && data.access_token) {
        localStorage.setItem("token", data.access_token);
        window.location = "chat.html";
    } else {
        alert("Invalid login");
    }
}

/* CONVERSATIONS */
let currentConversationId = null;

async function loadConversations() {
    const res = await fetch(API + "/conversations", {
        headers: { "Authorization": "Bearer " + getToken() }
    });
    if (!res.ok) return;
    const convos = await res.json();
    const list = document.getElementById("history");
    if (!list) return;
    list.innerHTML = "";
    convos.forEach(c => {
        const div = document.createElement("div");
        div.className = "convo-item" + (c.id === currentConversationId ? " active" : "");
        div.innerHTML = `<span onclick="loadConversation(${c.id})">${c.title}</span>
                         <button class="del-btn" onclick="event.stopPropagation(); deleteConversation(${c.id})">✕</button>`;
        list.appendChild(div);
    });
}

async function loadConversation(id) {
    currentConversationId = id;
    document.getElementById("chatbox").innerHTML = "";
    const res = await fetch(API + "/history/" + id, {
        headers: { "Authorization": "Bearer " + getToken() }
    });
    if (!res.ok) return;
    const turns = await res.json();
    turns.forEach(t => {
        addMessage("user", t.content);
        addMessage("bot", t.bot);
    });
    await loadConversations();
}

async function newConversation() {
    const res = await fetch(API + "/conversations", {
        method: "POST",
        headers: { "Authorization": "Bearer " + getToken() }
    });
    const data = await res.json();
    currentConversationId = data.id;
    document.getElementById("chatbox").innerHTML = "";
    await loadConversations();
}

async function deleteConversation(id) {
    await fetch(API + "/conversations/" + id, {
        method: "DELETE",
        headers: { "Authorization": "Bearer " + getToken() }
    });
    if (currentConversationId === id) {
        currentConversationId = null;
        document.getElementById("chatbox").innerHTML = "";
    }
    await loadConversations();
}

/* CHAT */
async function sendMessage() {
    const msgInput = document.getElementById("msg");
    const msg = msgInput.value.trim();
    if (!msg) return;

    addMessage("user", msg);
    msgInput.value = "";
    document.getElementById("typing").style.display = "block";

    const res = await fetch(API + "/chat", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + getToken()
        },
        body: JSON.stringify({ message: msg, conversation_id: currentConversationId })
    });

    const data = await res.json();
    document.getElementById("typing").style.display = "none";

    if (res.ok) {
        currentConversationId = data.conversation_id;
        addMessage("bot", data.response);
        await loadConversations();
    } else {
        addMessage("bot", "Auth error. Please log in again.");
    }
}

function logout() {
    localStorage.removeItem("token");
    window.location = "login.html";
}

function toggleDarkMode() {
    document.body.classList.toggle("dark");
    localStorage.setItem("darkMode", document.body.classList.contains("dark"));
}

if (localStorage.getItem("darkMode") === "true") {
    document.body.classList.add("dark");
}

function addMessage(sender, text) {
    const box = document.getElementById("chatbox");
    const row = document.createElement("div");
    row.className = "msg-row " + sender;

    if (sender === "bot") {
        const avatar = document.createElement("div");
        avatar.className = "avatar bot-avatar";
        avatar.textContent = "S";
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.innerHTML = marked.parse(text);
        row.appendChild(avatar);
        row.appendChild(bubble);
    } else {
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.textContent = text;
        row.appendChild(bubble);
    }

    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
}

if (document.getElementById("chatbox")) loadConversations();
