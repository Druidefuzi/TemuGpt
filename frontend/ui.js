// ─── UI.JS — DOM Helpers, Formatierung, Message-Rendering ───────────────────

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
    div.innerHTML = `
        <div class="avatar">${role === 'user' ? '👤' : '🤖'}</div>
        <div class="bubble">${formatText(text)}</div>
    `;
    msgs.appendChild(div);
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
        <div class="avatar">🤖</div>
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
        <div class="avatar">🤖</div>
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
