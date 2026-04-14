// ─── UI.JS — DOM Helpers, Formatierung, Message-Rendering ───────────────────

// ── TTS STATE ──
let _ttsEnabled   = false;
let _ttsVoice     = 'af_bella';
let _ttsAudio     = null;  // currently playing Audio object
let _ttsPlayingBtn = null; // button that triggered playback

async function loadTtsState() {
    try {
        const r = await fetch('/api/tts/settings');
        const d = await r.json();
        _ttsEnabled = d.enabled;
        _ttsVoice   = d.voice || 'af_bella';
        // Override with active personality voice if set
        await applyPersonalityTtsVoice();
    } catch(e) {}
}

async function applyPersonalityTtsVoice() {
    try {
        const r = await fetch('/api/personalities/active');
        const d = await r.json();
        if (!d.active) return;
        const vr = await fetch(`/api/personalities/${d.active}/tts-voice`);
        const vd = await vr.json();
        if (vd.voice) _ttsVoice = vd.voice;
    } catch(e) {}
}

async function speakText(text, btn) {
    if (!_ttsEnabled) return;

    // Stop current playback if any
    if (_ttsAudio) {
        _ttsAudio.pause();
        _ttsAudio = null;
        if (_ttsPlayingBtn) {
            _ttsPlayingBtn.textContent = '🔊';
            _ttsPlayingBtn.classList.remove('tts-playing');
            _ttsPlayingBtn = null;
        }
        if (btn.classList.contains('tts-playing')) return; // toggle off
    }

    btn.textContent = '⏳';
    btn.classList.add('tts-playing');
    _ttsPlayingBtn = btn;

    try {
        const resp = await fetch('/api/tts/speak', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, voice: _ttsVoice })
        });
        if (!resp.ok) throw new Error(await resp.text());
        const blob = await resp.blob();
        const url  = URL.createObjectURL(blob);
        _ttsAudio  = new Audio(url);
        btn.textContent = '🔉';
        _ttsAudio.onended = () => {
            btn.textContent = '🔊';
            btn.classList.remove('tts-playing');
            _ttsAudio = null;
            _ttsPlayingBtn = null;
            URL.revokeObjectURL(url);
        };
        _ttsAudio.onerror = () => {
            btn.textContent = '🔊';
            btn.classList.remove('tts-playing');
            _ttsAudio = null;
            _ttsPlayingBtn = null;
        };
        _ttsAudio.play();
    } catch(e) {
        btn.textContent = '🔊';
        btn.classList.remove('tts-playing');
        _ttsPlayingBtn = null;
        console.error('[TTS]', e);
    }
}

document.addEventListener('DOMContentLoaded', loadTtsState);

// ── ACTIVE PERSONALITY LOGO ──
let _assistantLogoSrc = 'assets/logo.png';

async function loadAssistantLogo() {
    try {
        const r = await fetch('/api/personalities/active');
        const d = await r.json();
        if (d.active && d.active !== 'default') {
            _assistantLogoSrc = `/api/personalities/${d.active}/logo`;
        } else {
            _assistantLogoSrc = 'frontend/assets/logo.png';
        }
        // Update any existing avatars already in DOM
        document.querySelectorAll('.msg.assistant .avatar img').forEach(img => {
            img.src = _assistantLogoSrc;
        });
    } catch(e) {}
}

document.addEventListener('DOMContentLoaded', loadAssistantLogo);

// ── ACCORDION ──
function toggleAccordion(btn) {
    btn.classList.toggle('open');
}

// ── AUTO RESIZE TEXTAREA ──
function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}

// ── FORMAT TEXT (Markdown → HTML) ──
function formatText(text) {
    let t = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    // Code blocks
    t = t.replace(/```([\w]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        const language = lang || "plaintext";
        return `<pre><div class="code-block-header"><span>${language}</span><button class="copy-btn" onclick="copyCode(this)">copy</button></div><code class="language-${language}">${code.trim()}</code></pre>`;
    });

    // Inline code
    t = t.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Tables
    t = t.replace(/((?:\|.+\|\n?)+)/g, block => {
        const rows = block.trim().split("\n").filter(r => r.trim());
        if (rows.length < 2) return block;
        const isSep = r => /^[\|\s\-:]+$/.test(r);
        let html = "<table>", headerDone = false;
        rows.forEach((row, i) => {
            if (isSep(row)) return;
            const cells = row.split("|").map(c => c.trim()).filter((c, idx, a) => idx > 0 && idx < a.length - 1);
            if (!headerDone && rows[i + 1] && isSep(rows[i + 1])) {
                html += "<tr>" + cells.map(c => `<th>${c}</th>`).join("") + "</tr>";
                headerDone = true;
            } else {
                html += "<tr>" + cells.map(c => `<td>${c}</td>`).join("") + "</tr>";
            }
        });
        return html + "</table>";
    });

    // Headings
    t = t.replace(/^### (.+)$/gm, "<h3>$1</h3>");
    t = t.replace(/^## (.+)$/gm, "<h2>$1</h2>");
    t = t.replace(/^# (.+)$/gm, "<h1>$1</h1>");

    // Bold & italic
    t = t.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
    t = t.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    t = t.replace(/\*(.+?)\*/g, "<em>$1</em>");

    // Blockquote
    t = t.replace(/^&gt; (.+)$/gm, "<blockquote>$1</blockquote>");

    // HR
    t = t.replace(/^[-*]{3,}$/gm, "<hr>");

    // Unordered lists
    t = t.replace(/((?:^[\-\*] .+\n?)+)/gm, block => {
        const items = block.trim().split("\n").map(l => l.replace(/^[\-\*] /, "").trim());
        return "<ul>" + items.map(i => `<li>${i}</li>`).join("") + "</ul>";
    });

    // Ordered lists
    t = t.replace(/((?:^\d+\. .+\n?)+)/gm, block => {
        const items = block.trim().split("\n").map(l => l.replace(/^\d+\. /, "").trim());
        return "<ol>" + items.map(i => `<li>${i}</li>`).join("") + "</ol>";
    });

    // Line breaks
    t = t.replace(/\n(?!<\/?(ul|ol|li|table|tr|th|td|h[1-3]|pre|blockquote|hr))/g, "<br>");

    return t;
}

function highlightCode(container) {
    container.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
    });
}

function copyCode(btn) {
    const code = btn.closest('pre').querySelector('code');
    navigator.clipboard.writeText(code.innerText).then(() => {
        btn.textContent = 'copied!';
        btn.classList.add('copied');
        setTimeout(() => { btn.textContent = 'copy'; btn.classList.remove('copied'); }, 2000);
    });
}

// ── MESSAGE APPEND HELPERS ──
function appendMessage(role, text) {
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.dataset.rawText = text;
    const actions = role === 'user'
        ? `<div class="msg-actions">
               <button class="msg-action-btn" onclick="copyMessage(this)" title="Copy">📋</button>
               <button class="msg-action-btn" onclick="editMessage(this)" title="Edit">✏️</button>
           </div>`
        : `<div class="msg-actions">
               <button class="msg-action-btn tts-btn" onclick="speakText(this.closest('.msg').dataset.rawText, this)" title="Vorlesen" style="display:${_ttsEnabled?'':'none'}">🔊</button>
               <button class="msg-action-btn" onclick="copyMessage(this)" title="Copy">📋</button>
           </div>`;
    div.innerHTML = `
    <div class="avatar">
        ${role === 'user' ? '<img src="frontend/assets/user.png" alt="User">' : `<img src="${_assistantLogoSrc}" alt="Assistant">`}
    </div>
    <div class="bubble">
        ${formatText(text)}${actions}
    </div>
`;
    msgs.appendChild(div);
    highlightCode(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function appendDocumentMessage(data) {
    const msgs = document.getElementById('messages');
    const ext = data.filename.split('.').pop().toLowerCase();
    const icons = { docx: '📝', xlsx: '📊', txt: '📃' };
    const icon = icons[ext] || '📄';
    const div = document.createElement('div');
    div.className = 'msg assistant';
    div.innerHTML = `
        <div class="avatar">
            <img src="${_assistantLogoSrc}" alt="Assistant">
        </div>
        <div class="bubble">
            ${formatText(data.message)}
            <div class="download-card">
                <span class="file-icon">${icon}</span>
                <div class="file-info">
                    <div class="file-name">${data.filename}</div>
                    <div class="file-type">${ext.toUpperCase()} · Fertig</div>
                </div>
                <a class="dl-btn" href="${data.download_url}" download="${data.filename}">↓ Download</a>
            </div>
        </div>
    `;
    msgs.appendChild(div);
    highlightCode(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function appendThinking() {
    const msgs = document.getElementById('messages');
    const id = 'think-' + Date.now();
    const div = document.createElement('div');
    div.className = 'msg assistant thinking';
    div.id = id;
    div.innerHTML = `
        <div class="avatar"><img src="${_assistantLogoSrc}" alt="Assistant"></div>>
        <div class="bubble">
            <div class="dots"><span></span><span></span><span></span></div>
            Denkt nach...
        </div>
    `;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return id;
}

function removeThinking(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function toggleReasoning(id, btn) {
    document.getElementById(id).classList.toggle('visible');
    btn.classList.toggle('open');
}

function toggleThinkingBlock(id, btn) {
    document.getElementById(id).classList.toggle('visible');
    btn.classList.toggle('open');
}
// ── TTS: update button visibility on settings change ──
function refreshTtsButtons() {
    document.querySelectorAll('.tts-btn').forEach(btn => {
        btn.style.display = _ttsEnabled ? '' : 'none';
    });
}