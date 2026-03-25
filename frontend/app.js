let history = [];
let attachedFiles = [];
let isLoading = false;

// ── ACCORDION ──
function toggleAccordion(btn) {
    btn.classList.toggle('open');
}

// ── AUTO RESIZE TEXTAREA ──
function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}

// ── KEYBOARD ──
function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

// ── QUICK ACTIONS ──
function quickAction(text) {
    document.getElementById('msg-input').value = text;
    autoResize(document.getElementById('msg-input'));
    sendMessage();
}

// ── FILES ──
function addFiles(fileList) {
    for (const f of fileList) attachedFiles.push(f);
    renderFileChips();
}

function removeFile(idx) {
    attachedFiles.splice(idx, 1);
    renderFileChips();
}

function renderFileChips() {
    const container = document.getElementById('file-preview');
    container.innerHTML = '';
    attachedFiles.forEach((f, i) => {
        const chip = document.createElement('div');
        chip.className = 'file-chip';
        chip.innerHTML = `<span>${fileIcon(f.name)}</span><span>${f.name}</span><span class="remove-chip" onclick="removeFile(${i})">×</span>`;
        container.appendChild(chip);
    });
}

function fileIcon(name) {
    const ext = name.split('.').pop().toLowerCase();
    const icons = { pdf: '📄', docx: '📝', xlsx: '📊', xls: '📊', png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️', webp: '🖼️', txt: '📃' };
    return icons[ext] || '📎';
}

// ── DRAG & DROP ──
const inputBox = document.getElementById('input-box');
inputBox.addEventListener('dragover', e => { e.preventDefault(); inputBox.classList.add('drag-over'); });
inputBox.addEventListener('dragleave', () => inputBox.classList.remove('drag-over'));
inputBox.addEventListener('drop', e => {
    e.preventDefault();
    inputBox.classList.remove('drag-over');
    addFiles(e.dataTransfer.files);
});

// ── SEND ──
async function sendMessage() {
    if (isLoading) return;
    const input = document.getElementById('msg-input');
    const text = input.value.trim();
    if (!text && attachedFiles.length === 0) return;

    const welcome = document.getElementById('welcome');
    if (welcome) welcome.remove();

    const displayText = text || `[${attachedFiles.map(f => f.name).join(', ')}]`;
    appendMessage('user', displayText);

    const msgText = text;
    const files = [...attachedFiles];

    input.value = '';
    input.style.height = 'auto';
    attachedFiles = [];
    renderFileChips();

    isLoading = true;
    document.getElementById('send-btn').disabled = true;

    try {
        if (files.length > 0) {
            const thinkId = appendThinking();
            const fd = new FormData();
            fd.append('message', msgText);
            fd.append('history', JSON.stringify(history));
            files.forEach(f => fd.append('files', f));

            const resp = await fetch('/chat', { method: 'POST', body: fd });
            const data = await resp.json();
            removeThinking(thinkId);

            if (data.error) {
                appendMessage('assistant', `❌ ${data.error}`);
            } else if (data.action === 'create_document') {
                appendDocumentMessage(data);
                history.push({ role: 'user', content: msgText });
                history.push({ role: 'assistant', content: data.message });
                await saveMsgsToDB(msgText, data.message);
            } else {
                appendMessage('assistant', data.message);
                history.push({ role: 'user', content: msgText });
                history.push({ role: 'assistant', content: data.message });
                await saveMsgsToDB(msgText, data.message);
            }
        } else {
            await smartSend(msgText, history);
        }

        if (history.length > 20) history = history.slice(-20);

    } catch (err) {
        appendMessage('assistant', `❌ Verbindungsfehler: ${err.message}`);
    }

    isLoading = false;
    document.getElementById('send-btn').disabled = false;
}

// ── SMART SEND ──
async function smartSend(msgText, history) {
    const thinkId = appendThinking();

    const temperature = parseFloat(document.getElementById('setting-temp')?.value ?? 0.3);
    const contextLength = parseInt(document.getElementById('setting-ctx')?.value ?? 8192);

    const resp = await fetch('/smart_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message: msgText,
            history,
            temperature,
            context_length: contextLength,
            research_max_results: parseInt(document.getElementById('research-max-results')?.value ?? 8),
            research_min_pages: parseInt(document.getElementById('research-min-pages')?.value ?? 5)
        })
    });

    const contentType = resp.headers.get("content-type");

    if (contentType && contentType.includes("application/json")) {
        removeThinking(thinkId);
        const data = await resp.json();

        if (data.mode === "document") {
            appendDocumentMessage(data);
            history.push({ role: 'user', content: msgText });
            history.push({ role: 'assistant', content: data.message });
            await saveMsgsToDB(msgText, data.message);
            return;
        }

        appendMessage('assistant', data.message);
        history.push({ role: 'user', content: msgText });
        history.push({ role: 'assistant', content: data.message });
        await saveMsgsToDB(msgText, data.message);
        return;
    }

    // SSE Stream — thinking bleibt bis erster content kommt
    await handleSmartStream(resp, msgText, thinkId);
}

// ── STREAM HANDLER ──
async function handleSmartStream(resp, msgText, thinkId = null) {
    if (thinkId) removeThinking(thinkId);
    const msgs = document.getElementById('messages');

    const div = document.createElement('div');
    div.className = 'msg assistant';
    div.innerHTML = `<div class="avatar">🤖</div><div class="bubble"><div class="stream-content"></div></div>`;
    msgs.appendChild(div);

    const bubble = div.querySelector('.bubble');
    const streamContent = div.querySelector('.stream-content');
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();

    let fullText = "";
    let buffer = "";
    let stepsDiv = null;

    let sourcesDiv = null;

    function getOrCreateSteps() {
        if (!stepsDiv) {
            stepsDiv = document.createElement('div');
            stepsDiv.className = 'status-steps';
            bubble.insertBefore(stepsDiv, streamContent);
        }
        return stepsDiv;
    }

    function getOrCreateSources() {
        if (!sourcesDiv) {
            sourcesDiv = document.createElement('div');
            sourcesDiv.className = 'source-cards';
            bubble.insertBefore(sourcesDiv, streamContent);
        }
        return sourcesDiv;
    }

    function addStep(text, status = 'active') {
        const steps = getOrCreateSteps();
        steps.querySelectorAll('.status-step.active').forEach(s => {
            s.classList.remove('active');
            s.classList.add('done');
        });
        const step = document.createElement('div');
        step.className = `status-step ${status}`;
        step.textContent = text;
        steps.appendChild(step);
        msgs.scrollTop = msgs.scrollHeight;
    }

    function addSource(title, host, url) {
        const sources = getOrCreateSources();
        const card = document.createElement('a');
        card.className = 'source-card';
        card.href = url;
        card.target = '_blank';
        card.innerHTML = `<span class="source-host">${host}</span><span class="source-title">${title}</span>`;
        sources.appendChild(card);
        msgs.scrollTop = msgs.scrollHeight;
    }

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (let line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
                const json = JSON.parse(line.slice(6));

                if (json.type === "step") {
                    addStep(json.text, json.status || 'active');
                }

                else if (json.type === "source") {
                    addSource(json.title, json.host, json.url);
                }

                else if (json.type === "search_done") {
                    if (stepsDiv) stepsDiv.style.display = 'none';
                    if (sourcesDiv) bubble.appendChild(sourcesDiv);
                    streamContent.innerHTML = formatText(json.message);
                    highlightCode(div);
                    history.push({ role: 'user', content: msgText });
                    history.push({ role: 'assistant', content: json.message });
                    await saveMsgsToDB(msgText, json.message);
                    msgs.scrollTop = msgs.scrollHeight;
                }

                else if (json.type === "document_done") {
                    if (stepsDiv) stepsDiv.remove();
                    streamContent.remove();
                    appendDocumentMessage(json);
                    history.push({ role: 'user', content: msgText });
                    history.push({ role: 'assistant', content: json.message });
                    await saveMsgsToDB(msgText, json.message);
                }

                else if (json.type === "image_done") {
                    if (stepsDiv) stepsDiv.remove();
                    streamContent.remove();
                    appendImageMessage(json, msgText);
                    history.push({ role: 'user', content: msgText });
                    history.push({ role: 'assistant', content: `[Bild generiert: ${json.prompt}]` });
                    await saveMsgsToDB(msgText, `[Bild generiert: ${json.prompt}]`);
                }

                else if (json.type === "content") {
                    fullText += json.text;
                    const looksLikeJson = fullText.trimStart().startsWith('{');
                    if (!looksLikeJson) {
                        streamContent.innerHTML = formatText(fullText);
                        msgs.scrollTop = msgs.scrollHeight;
                    } else {
                        streamContent.innerHTML = '<span class="typing-dots"><span>.</span><span>.</span><span>.</span></span>';
                    }
                }

                else if (json.type === "done") {
                    let displayText = fullText;
                    try {
                        const start = fullText.indexOf('{'), end = fullText.lastIndexOf('}');
                        if (start !== -1 && end !== -1) {
                            const parsed = JSON.parse(fullText.slice(start, end + 1));
                            if (parsed.action === 'create_document') {
                                streamContent.remove();
                                appendDocumentMessage(parsed);
                                history.push({ role: 'user', content: msgText });
                                history.push({ role: 'assistant', content: parsed.message || fullText });
                                await saveMsgsToDB(msgText, parsed.message || fullText);
                                return;
                            }
                            displayText = parsed.message || parsed.query || fullText;
                        }
                    } catch (e) {}
                    streamContent.innerHTML = formatText(displayText);
                    highlightCode(div);
                    history.push({ role: 'user', content: msgText });
                    history.push({ role: 'assistant', content: displayText });
                    await saveMsgsToDB(msgText, displayText);
                    msgs.scrollTop = msgs.scrollHeight;
                }

                else if (json.type === "error") {
                    streamContent.innerHTML = `❌ ${json.text}`;
                }

            } catch (e) {}
        }
    }
}

// ── MESSAGE HELPERS ──
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

// ── FORMAT TEXT (Markdown) ──
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

// ── MODEL MANAGER ──
async function loadModels() {
    const section = document.getElementById('model-section');
    section.innerHTML = '<div class="models-loading">↻ Lade...</div>';
    try {
        const resp = await fetch('/api/models');
        const data = await resp.json();
        renderModels(data);
        updateActiveModelBadge(data.active);
    } catch (e) {
        section.innerHTML = '<div class="models-loading">❌ Fehler</div>';
    }
}

function updateActiveModelBadge(modelId) {
    const el = document.getElementById('active-model-name');
    if (!el) return;
    // Nur den letzten Teil des Modellnamens anzeigen (nach letztem /)
    const short = modelId ? modelId.split('/').pop() : '–';
    el.textContent = short;
    el.title = modelId;
}

function renderModels(data) {
    const section = document.getElementById('model-section');
    if (!data.models || data.models.length === 0) {
        section.innerHTML = '<div class="models-loading">Keine Modelle gefunden</div>';
        return;
    }
    section.innerHTML = data.models.map(m => {
        const isActive = m.active;
        const isLoaded = m.loaded;
        let actions = '';
        const instanceId = m.instance_id || m.id;
        if (isActive) {
            actions = `
                <button class="model-btn use-btn" disabled>✓ Aktiv</button>
                <button class="model-btn unload-btn" onclick="unloadModel('${instanceId}', this)">Entladen</button>`;
        } else if (isLoaded) {
            actions = `
                <button class="model-btn use-btn" onclick="setActive('${m.id}')">Nutzen</button>
                <button class="model-btn unload-btn" onclick="unloadModel('${instanceId}', this)">Entladen</button>`;
        } else {
            actions = `<button class="model-btn load-btn" onclick="loadModel('${m.load_id}', '${m.name}', '${m.id}', this)">Laden</button>`;
        }
        return `
            <div class="model-card ${isActive ? 'active-model' : ''}">
                <div class="model-card-top">
                    <div class="model-dot ${isLoaded ? 'loaded' : 'unloaded'}"></div>
                    <div class="model-name" title="${m.name}">${m.name}</div>
                </div>
                <div class="model-meta">${m.size_gb} GB · ${m.folder}</div>
                <div class="model-actions">${actions}</div>
            </div>`;
    }).join('');
}

async function loadModel(loadId, name, modelId, btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Laden...';
    try {
        const resp = await fetch('/api/models/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ load_id: loadId, name })
        });
        const data = await resp.json();
        if (data.ok) {
            await loadModels();
        } else {
            btn.textContent = '❌ Fehler';
            btn.disabled = false;
            setTimeout(() => { btn.textContent = 'Laden'; }, 2000);
        }
    } catch (e) {
        btn.textContent = '❌ Fehler';
        btn.disabled = false;
    }
}

async function unloadModel(instanceId, btn) {
    btn.disabled = true;
    btn.textContent = '⏳...';
    try {
        await fetch('/api/models/unload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instance_id: instanceId })
        });
        await loadModels();
    } catch (e) {
        btn.disabled = false;
        btn.textContent = 'Entladen';
    }
}

async function setActive(id) {
    await fetch('/api/models/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
    });
    await loadModels();
}

// ── THINK MODE TOGGLE ──
async function toggleThinkMode() {
    const resp = await fetch('/api/thinking/toggle', { method: 'POST' });
    const data = await resp.json();
    updateThinkBtn(data.enabled);
}

function updateThinkBtn(enabled) {
    const btn = document.getElementById('think-toggle-btn');
    const label = document.getElementById('think-toggle-label');
    if (enabled) {
        btn.classList.add('active');
        label.textContent = '🧠 Fake-Think: AN';
    } else {
        btn.classList.remove('active');
        label.textContent = '🧠 Fake-Think: AUS';
    }
}

// ── RESEARCH MODE TOGGLE ──
async function toggleResearchMode() {
    const resp = await fetch('/api/research/toggle', { method: 'POST' });
    const data = await resp.json();
    updateResearchBtn(data.enabled);
}

function updateResearchBtn(enabled) {
    const btn = document.getElementById('research-toggle-btn');
    const label = document.getElementById('research-toggle-label');
    const panel = document.getElementById('research-settings');
    if (enabled) {
        btn.classList.add('active');
        label.textContent = '🔬 Research: AN';
        panel?.classList.add('visible');
    } else {
        btn.classList.remove('active');
        label.textContent = '🔬 Research: AUS';
        panel?.classList.remove('visible');
    }
}

// ── KNOWLEDGE ──
async function loadKnowledge() {
    const section = document.getElementById('knowledge-section');
    try {
        const resp = await fetch('/api/knowledge');
        const data = await resp.json();
        if (!data.files.length) {
            section.innerHTML = '<div class="models-loading">Keine Dateien</div>';
            return;
        }
        const icons = { html: '🌐', css: '🎨', js: '⚙️', txt: '📃', md: '📝', json: '📋' };
        section.innerHTML = data.files.map(f => {
            const ext = f.name.split('.').pop();
            const icon = icons[ext] || '📄';
            return `<div class="knowledge-file">
                <span>${icon}</span>
                <div class="knowledge-file-info">
                    <div class="knowledge-file-name">${f.name}</div>
                    <div class="knowledge-file-meta">${f.modified} · ${(f.size / 1024).toFixed(1)}kb</div>
                </div>
                <button class="knowledge-view-btn" onclick="viewKnowledge('${f.name}')">ansehen</button>
            </div>`;
        }).join('');
    } catch (e) {
        section.innerHTML = '<div class="models-loading">❌ Fehler</div>';
    }
}

async function viewKnowledge(filename) {
    const resp = await fetch(`/api/knowledge/${filename}`);
    const text = await resp.text();
    document.getElementById('modal-filename').textContent = filename;
    document.getElementById('modal-content').textContent = text;
    document.getElementById('knowledge-modal').classList.add('visible');
}

function closeModal() {
    document.getElementById('knowledge-modal').classList.remove('visible');
}

// ── CHAT HISTORY ──
let currentChatId = null;

async function loadChatHistory() {
    const section = document.getElementById('chat-history-section');
    try {
        const resp = await fetch('/api/chats');
        const data = await resp.json();
        renderChatHistory(data.chats);
    } catch (e) {
        section.innerHTML = '<div class="models-loading">❌ Fehler</div>';
    }
}

function renderChatHistory(chats) {
    const section = document.getElementById('chat-history-section');
    if (!chats.length) {
        section.innerHTML = '<div class="models-loading">Keine Chats</div>';
        return;
    }
    section.innerHTML = chats.map(c => `
        <div class="chat-history-item ${c.id === currentChatId ? 'active-chat' : ''}" id="chat-item-${c.id}">
            <div class="chat-item-title" onclick="loadChat(${c.id})" title="${c.title}">${c.title}</div>
            <div class="chat-item-actions">
                <button class="chat-action-btn" onclick="renameChat(${c.id})" title="Umbenennen">✏️</button>
                <button class="chat-action-btn" onclick="deleteChat(${c.id})" title="Löschen">🗑️</button>
            </div>
        </div>`).join('');
}

async function newChat() {
    const resp = await fetch('/api/chats', { method: 'POST' });
    const data = await resp.json();
    currentChatId = data.id;
    history = [];
    attachedFiles = [];
    renderFileChips();
    const msgs = document.getElementById('messages');
    msgs.innerHTML = `
        <div class="welcome" id="welcome">
            <div class="big-icon">✨</div>
            <h2>Womit kann ich helfen?</h2>
            <p>Erstelle Word-Dokumente, Excel-Tabellen, Protokolle und mehr — oder lade Dateien hoch die ich analysieren soll.</p>
        </div>`;
    await loadChatHistory();
}

async function loadChat(chatId) {
    const resp = await fetch(`/api/chats/${chatId}`);
    const data = await resp.json();
    currentChatId = chatId;

    // History aus DB laden
    history = data.messages.map(m => ({ role: m.role, content: m.content }));

    // Nachrichten anzeigen
    const msgs = document.getElementById('messages');
    msgs.innerHTML = '';
    for (const m of data.messages) {
        const div = document.createElement('div');
        div.className = `msg ${m.role}`;
        div.innerHTML = `
            <div class="avatar">${m.role === 'user' ? '👤' : '🤖'}</div>
            <div class="bubble">${formatText(m.content)}</div>`;
        msgs.appendChild(div);
        highlightCode(div);
    }
    msgs.scrollTop = msgs.scrollHeight;
    await loadChatHistory();
}

async function renameChat(chatId) {
    const title = prompt('Neuer Name:');
    if (!title) return;
    await fetch(`/api/chats/${chatId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
    });
    await loadChatHistory();
}

async function deleteChat(chatId) {
    if (!confirm('Chat löschen?')) return;
    await fetch(`/api/chats/${chatId}`, { method: 'DELETE' });
    if (currentChatId === chatId) {
        currentChatId = null;
        history = [];
        const msgs = document.getElementById('messages');
        msgs.innerHTML = `
            <div class="welcome" id="welcome">
                <div class="big-icon">✨</div>
                <h2>Womit kann ich helfen?</h2>
                <p>Erstelle Word-Dokumente, Excel-Tabellen, Protokolle und mehr.</p>
            </div>`;
    }
    await loadChatHistory();
}

async function saveMsgsToDB(userMsg, assistantMsg) {
    if (!currentChatId) {
        // Automatisch neuen Chat erstellen
        const resp = await fetch('/api/chats', { method: 'POST' });
        const data = await resp.json();
        currentChatId = data.id;
        await loadChatHistory();
    }
    await fetch(`/api/chats/${currentChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [
                { role: 'user', content: userMsg },
                { role: 'assistant', content: assistantMsg }
            ]})
    });
    await loadChatHistory();
}

function clearChat() {
    newChat();
}

// ── INIT ──
document.getElementById('knowledge-modal').addEventListener('click', function (e) {
    if (e.target === this) closeModal();
});

fetch('/api/thinking/status').then(r => r.json()).then(d => updateThinkBtn(d.enabled));
fetch('/api/research/status').then(r => r.json()).then(d => updateResearchBtn(d.enabled));
loadKnowledge();
loadModels();
loadChatHistory();

// Modelle & Knowledge Accordions beim Start aufklappen
document.querySelectorAll('.accordion-header').forEach(btn => {
    const label = btn.querySelector('span')?.textContent || '';
    if (label.includes('Modelle') || label.includes('Knowledge')) {
        btn.classList.add('open');
    }
});
// ── SYSTEM PROMPT MODAL ──
async function openSystemPromptModal() {
    const resp = await fetch('/api/system-prompt');
    const data = await resp.json();
    document.getElementById('system-prompt-textarea').value = data.prompt;
    document.getElementById('system-prompt-modal').classList.add('visible');
}

function closeSystemPromptModal() {
    document.getElementById('system-prompt-modal').classList.remove('visible');
}

async function saveSystemPrompt() {
    const prompt = document.getElementById('system-prompt-textarea').value.trim();
    if (!prompt) return;
    await fetch('/api/system-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt })
    });
    closeSystemPromptModal();
}

async function resetSystemPrompt() {
    if (!confirm('System Prompt auf Standard zurücksetzen?')) return;
    const resp = await fetch('/api/system-prompt/reset', { method: 'POST' });
    const data = await resp.json();
    document.getElementById('system-prompt-textarea').value = data.prompt;
}

document.getElementById('system-prompt-modal').addEventListener('click', function(e) {
    if (e.target === this) closeSystemPromptModal();
});

// ── IMAGE MESSAGE ──
function appendImageMessage(json, userPrompt) {
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'msg assistant';
    div.innerHTML = `
        <div class="avatar">🤖</div>
        <div class="bubble">
            <div class="image-result">
                <img src="data:image/png;base64,${json.image_b64}" alt="${json.prompt}" class="generated-image" onclick="openImageFullscreen(this)">
                <div class="image-meta">
                    <span class="image-model">🤖 ${json.model}</span>
                    <span class="image-prompt-text">🖊 ${json.prompt.substring(0, 80)}${json.prompt.length > 80 ? '…' : ''}</span>
                    <a class="image-download" href="data:image/png;base64,${json.image_b64}" download="${json.filename}">⬇ Speichern</a>
                </div>
            </div>
        </div>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}

function openImageFullscreen(img) {
    const overlay = document.createElement('div');
    overlay.className = 'image-fullscreen-overlay';
    overlay.innerHTML = `<img src="${img.src}" alt="${img.alt}">`;
    overlay.onclick = () => overlay.remove();
    document.body.appendChild(overlay);
}