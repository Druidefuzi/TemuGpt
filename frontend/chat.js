// ─── CHAT.JS — Senden, Stream, Datei-Handling, Chat-History & DB ─────────────

// ── KEYBOARD & QUICK ACTIONS ──
function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function quickAction(text) {
    document.getElementById('msg-input').value = text;
    autoResize(document.getElementById('msg-input'));
    sendMessage();
}

// ── FILE HANDLING ──
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

    const temperature   = parseFloat(document.getElementById('setting-temp')?.value ?? 0.3);
    const contextLength = parseInt(document.getElementById('setting-ctx')?.value ?? 8192);

    const resp = await fetch('/smart_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message: msgText,
            history,
            temperature,
            context_length: contextLength,
            forced_action:  typeof getForcedAction === 'function' ? getForcedAction() : 'auto',
            research_max_results: parseInt(document.getElementById('research-max-results')?.value ?? 8),
            research_min_pages:   parseInt(document.getElementById('research-min-pages')?.value ?? 5),
            image_model_type: typeof imageModelType !== 'undefined' ? imageModelType : 'anima',
            image_model_name: typeof imageModelName !== 'undefined' ? imageModelName : '',
            image_turbo:      typeof imageTurbo      !== 'undefined' ? imageTurbo      : false,
            image_raw_prompt: typeof imageRawPrompt !== 'undefined' ? imageRawPrompt : false
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

    await handleSmartStream(resp, msgText, thinkId);
}

// ── STREAM HANDLER ──
async function handleSmartStream(resp, msgText, thinkId = null) {
    const msgs = document.getElementById('messages');

    const div = document.createElement('div');
    div.className = 'msg assistant';
    div.innerHTML = `<div class="avatar"><img src="${typeof _assistantLogoSrc !== 'undefined' ? _assistantLogoSrc : 'assets/logo.png'}" alt="Assistant"></div><div class="bubble"><div class="stream-content"></div></div>`;
    msgs.appendChild(div);

    const bubble        = div.querySelector('.bubble');
    const streamContent = div.querySelector('.stream-content');
    const reader        = resp.body.getReader();
    const decoder       = new TextDecoder();

    let fullText   = "";
    let buffer     = "";
    let stepsDiv   = null;
    let sourcesDiv = null;
    let reasoningBuf = "";
    let reasoningEl  = null;
    let firstEventReceived = false;
    let searchPrefix = "";  // Für "🔍 Gesucht nach: ..." während Search-Streaming

    function onFirstEvent() {
        if (!firstEventReceived) {
            firstEventReceived = true;
            if (thinkId) removeThinking(thinkId);
        }
    }

    function getOrCreateReasoning() {
        if (!reasoningEl && typeof showReasoning !== 'undefined' && showReasoning) {
            reasoningEl = document.createElement('div');
            reasoningEl.className = 'reasoning-block';
            const id = 'reasoning-' + Date.now();
            reasoningEl.innerHTML = `
                <button class="reasoning-toggle" onclick="this.classList.toggle('open');document.getElementById('${id}').classList.toggle('visible')">
                    <span>🧠 Reasoning</span><span class="reasoning-arrow">▾</span>
                </button>
                <div class="reasoning-body" id="${id}">
                    <pre class="reasoning-text"></pre>
                </div>`;
            bubble.insertBefore(reasoningEl, streamContent);
        }
        return reasoningEl;
    }

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
                    onFirstEvent();
                    addStep(json.text, json.status || 'active');
                }
                else if (json.type === "reasoning") {
                    onFirstEvent();
                    // Reasoning-Text akkumulieren
                    reasoningBuf += json.text;
                    if (!reasoningEl) reasoningEl = getOrCreateReasoning();
                    if (reasoningEl) {
                        reasoningEl.querySelector('.reasoning-text').textContent = reasoningBuf;
                    }
                }
                else if (json.type === "source") {
                    onFirstEvent();
                    addSource(json.title, json.host, json.url);
                }
                else if (json.type === "search_stream_start") {
                    onFirstEvent();
                    if (stepsDiv) stepsDiv.style.display = 'none';
                    if (sourcesDiv) bubble.appendChild(sourcesDiv);
                    searchPrefix = `🔍 *Gesucht nach: ${json.query}*\n\n`;
                    streamContent.innerHTML = formatText(searchPrefix);
                    fullText = "";  // Reset für den gestreamten Content
                }
                else if (json.type === "search_done") {
                    onFirstEvent();
                    if (stepsDiv) stepsDiv.style.display = 'none';
                    if (sourcesDiv && !sourcesDiv.parentElement?.classList?.contains('bubble')) {
                        bubble.appendChild(sourcesDiv);
                    }
                    // Finale Darstellung mit Search-Prefix
                    const prefix = json.query ? `🔍 *Gesucht nach: ${json.query}*\n\n` : '';
                    const finalText = prefix + (json.message || '');
                    const saveText = json.message || streamContent.textContent || fullText;
                    if (json.message) {
                        streamContent.innerHTML = formatText(finalText);
                    }
                    // Add copy button to search result message
                    div.dataset.rawText = saveText;
                    const searchActionsHtml = `<div class="msg-actions"><button class="msg-action-btn tts-btn" onclick="speakText(this.closest('.msg').dataset.rawText, this)" title="Vorlesen" style="${typeof _ttsEnabled !== 'undefined' && _ttsEnabled ? '' : 'display:none'}">🔊</button><button class="msg-action-btn" onclick="copyMessage(this)" title="Copy">📋</button></div>`;
                    bubble.insertAdjacentHTML('beforeend', searchActionsHtml);
                    highlightCode(div);
                    history.push({ role: 'user', content: msgText });
                    history.push({ role: 'assistant', content: saveText });
                    await saveMsgsToDB(msgText, saveText);
                    msgs.scrollTop = msgs.scrollHeight;
                    searchPrefix = "";  // Reset
                }
                else if (json.type === "document_done") {
                    if (stepsDiv) stepsDiv.remove();
                    streamContent.remove();
                    appendDocumentMessage(json);
                    history.push({ role: 'user', content: msgText });
                    history.push({ role: 'assistant', content: json.message });
                    await saveMsgsToDB(msgText, json.message);
                }
                else if (json.type === "image_preview") {
                    onFirstEvent();
                    let previewEl = div.querySelector('.comfy-preview');
                    if (!previewEl) {
                        previewEl = document.createElement('img');
                        previewEl.className = 'comfy-preview';
                        previewEl.style.cssText = 'max-width:100%;border-radius:8px;margin-top:8px;opacity:0.85;display:block;';
                        bubble.insertBefore(previewEl, streamContent);
                    }
                    previewEl.src = `data:image/jpeg;base64,${json.b64}`;
                    msgs.scrollTop = msgs.scrollHeight;
                }
                else if (json.type === "image_progress") {
                    let progressEl = div.querySelector('.comfy-progress');
                    if (!progressEl) {
                        progressEl = document.createElement('div');
                        progressEl.className = 'comfy-progress';
                        progressEl.style.cssText = 'margin-top:6px;';
                        progressEl.innerHTML = `<div style="background:var(--border);border-radius:4px;height:4px;overflow:hidden;"><div class="comfy-bar" style="height:100%;background:var(--accent);transition:width 0.2s;width:0%;"></div></div><span style="font-size:11px;color:var(--text-muted);"></span>`;
                        bubble.insertBefore(progressEl, streamContent);
                    }
                    progressEl.querySelector('.comfy-bar').style.width = json.pct + '%';
                    progressEl.querySelector('span').textContent = `Step ${json.value}/${json.max}`;
                    msgs.scrollTop = msgs.scrollHeight;
                }
                else if (json.type === "image_done") {
                    if (stepsDiv) stepsDiv.remove();
                    div.querySelector('.comfy-preview')?.remove();
                    div.querySelector('.comfy-progress')?.remove();
                    streamContent.remove();
                    appendImageMessage(json, msgText);
                    history.push({ role: 'user', content: msgText });
                    history.push({ role: 'assistant', content: `[Bild generiert: ${json.prompt}]` });
                    await saveImageMsgToDB(msgText, json);
                }
                else if (json.type === "content") {
                    onFirstEvent();
                    fullText += json.text;
                    const looksLikeJson = fullText.trimStart().startsWith('{');
                    if (!looksLikeJson) {
                        streamContent.innerHTML = formatText(searchPrefix + fullText);
                        msgs.scrollTop = msgs.scrollHeight;
                    } else {
                        // JSON-Antwort: versuche "message"-Wert live zu extrahieren
                        const msgMatch = fullText.match(/"message"\s*:\s*"/);
                        if (msgMatch) {
                            // Alles nach "message": " extrahieren (unvollständiges JSON)
                            const startIdx = msgMatch.index + msgMatch[0].length;
                            let partial = fullText.slice(startIdx);
                            // Trailing unescaped quote + rest abschneiden (Ende des Strings)
                            const endMatch = partial.match(/(?<!\\)"\s*[,}]\s*$/);
                            if (endMatch) {
                                partial = partial.slice(0, endMatch.index);
                            }
                            // JSON-Escapes auflösen
                            try {
                                partial = partial.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
                            } catch(e) {}
                            if (partial.length > 0) {
                                streamContent.innerHTML = formatText(searchPrefix + partial);
                                msgs.scrollTop = msgs.scrollHeight;
                            } else {
                                streamContent.innerHTML = '<span class="typing-dots"><span>.</span><span>.</span><span>.</span></span>';
                            }
                        } else {
                            streamContent.innerHTML = '<span class="typing-dots"><span>.</span><span>.</span><span>.</span></span>';
                        }
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
                    } catch (e) {
                        // JSON.parse fehlgeschlagen (z.B. abgeschnittene Antwort bei max_tokens)
                        // → Message-Wert per Regex extrahieren
                        const msgMatch = fullText.match(/"message"\s*:\s*"/);
                        if (msgMatch) {
                            const startIdx = msgMatch.index + msgMatch[0].length;
                            let partial = fullText.slice(startIdx);
                            // Schließendes Quote finden (unescaped)
                            const endMatch = partial.match(/(?<!\\)"\s*[,}]/);
                            if (endMatch) {
                                partial = partial.slice(0, endMatch.index);
                            }
                            // JSON-Escapes auflösen
                            try {
                                partial = partial.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
                            } catch(e2) {}
                            if (partial.length > 0) {
                                displayText = partial;
                            }
                        }
                    }
                    streamContent.innerHTML = formatText(displayText);
                    // Add copy button to streamed message
                    div.dataset.rawText = displayText;
                    const actionsHtml = `<div class="msg-actions"><button class="msg-action-btn tts-btn" onclick="speakText(this.closest('.msg').dataset.rawText, this)" title="Vorlesen" style="${typeof _ttsEnabled !== 'undefined' && _ttsEnabled ? '' : 'display:none'}">🔊</button><button class="msg-action-btn" onclick="copyMessage(this)" title="Copy">📋</button></div>`;
                    bubble.insertAdjacentHTML('beforeend', actionsHtml);
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

// ── CHAT HISTORY & DB ──
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
                <button class="chat-action-btn" onclick="exportChat(${c.id})" title="Exportieren">⬇️</button>
                <button class="chat-action-btn" onclick="renameChat(${c.id})" title="Umbenennen">✏️</button>
                <button class="chat-action-btn" onclick="deleteChat(${c.id})" title="Löschen">🗑️</button>
            </div>
        </div>`).join('');
}

async function newChat() {
    const resp = await fetch('/api/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
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

    history = data.messages.map(m => {
        if (m.role === 'assistant' && m.content.startsWith('{"__type":"image"')) {
            try {
                const img = JSON.parse(m.content);
                return { role: m.role, content: `[Bild generiert: ${img.prompt}]` };
            } catch(e) {}
        }
        return { role: m.role, content: m.content };
    });

    const msgs = document.getElementById('messages');
    msgs.innerHTML = '';
    for (const m of data.messages) {
        if (m.role === 'assistant' && m.content.startsWith('{"__type":"image"')) {
            try {
                const img = JSON.parse(m.content);
                appendImageMessage({ image_b64: img.b64, model: img.model, model_type: img.model_type || 'anima', prompt: img.prompt, filename: img.filename }, '');
                continue;
            } catch(e) {}
        }
        const div = document.createElement('div');
        div.className = `msg ${m.role}`;
        div.dataset.rawText = m.content;
        const actions = m.role === 'user'
            ? `<div class="msg-actions">
                   <button class="msg-action-btn" onclick="copyMessage(this)" title="Copy">📋</button>
                   <button class="msg-action-btn" onclick="editMessage(this)" title="Edit">✏️</button>
               </div>`
            : `<div class="msg-actions">
                   <button class="msg-action-btn" onclick="copyMessage(this)" title="Copy">📋</button>
               </div>`;
        div.innerHTML = `
            <div class="avatar">
        ${m.role === 'user' ? '<img src="frontend/assets/user.png" alt="User">' : `<img src="${typeof _assistantLogoSrc !== 'undefined' ? _assistantLogoSrc : 'assets/logo.png'}" alt="Assistant">`}
    </div>
            <div class="bubble">${formatText(m.content)}${actions}</div>`;
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
    const isFirstMessage = !currentChatId;
    if (!currentChatId) {
        const resp = await fetch('/api/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        const data = await resp.json();
        currentChatId = data.id;
        await loadChatHistory();
    }
    await fetch(`/api/chats/${currentChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [
                { role: 'user',      content: userMsg      },
                { role: 'assistant', content: assistantMsg }
            ]})
    });
    await loadChatHistory();

    // Auto-Titel nach erster Antwort generieren (fire & forget)
    if (isFirstMessage && currentChatId) {
        generateChatTitle(currentChatId, userMsg, assistantMsg);
    }
}

async function generateChatTitle(chatId, userMsg, assistantMsg) {
    try {
        await fetch(`/api/chats/${chatId}/generate-title`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_message: userMsg, assistant_message: assistantMsg })
        });
        await loadChatHistory();
    } catch (e) {
        // silent fail — Titel bleibt wie er ist
    }
}

async function exportChat(chatId) {
    try {
        const resp = await fetch(`/api/chats/${chatId}`);
        const data = await resp.json();
        const title = data.chat.title || 'Chat';
        let md = `# ${title}\n\n`;
        md += `_Exportiert: ${new Date().toLocaleString('de-DE')}_\n\n---\n\n`;
        for (const m of data.messages) {
            const role = m.role === 'user' ? '👤 **Du**' : '🤖 **Assistent**';
            let content = m.content;
            // Bild-JSON zu lesbarem Text
            if (content.startsWith('{"__type":"image"')) {
                try {
                    const img = JSON.parse(content);
                    content = `_[Bild generiert: ${img.prompt}]_`;
                } catch(e) {}
            }
            md += `${role}\n\n${content}\n\n---\n\n`;
        }
        const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `${title.replace(/[^a-zA-Z0-9äöüÄÖÜß\s]/g, '_')}.md`;
        a.click();
        URL.revokeObjectURL(url);
    } catch (e) {
        console.error('[Export] Fehler:', e);
    }
}

async function saveImageMsgToDB(userMsg, imgJson) {
    if (!currentChatId) {
        const resp = await fetch('/api/chats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        const data = await resp.json();
        currentChatId = data.id;
        await loadChatHistory();
    }
    const imgContent = JSON.stringify({
        __type:     'image',
        b64:        imgJson.image_b64,
        model:      imgJson.model,
        model_type: imgJson.model_type || 'anima',
        prompt:     imgJson.prompt,
        filename:   imgJson.filename
    });
    await fetch(`/api/chats/${currentChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [
                { role: 'user',      content: userMsg    },
                { role: 'assistant', content: imgContent }
            ]})
    });
    await loadChatHistory();
}

function clearChat() {
    newChat();
}

// ── COPY & EDIT MESSAGE ──
function copyMessage(btn) {
    const msg = btn.closest('.msg');
    const text = msg.dataset.rawText || msg.querySelector('.bubble').innerText;
    navigator.clipboard.writeText(text).then(() => {
        btn.textContent = '✅';
        setTimeout(() => btn.textContent = '📋', 1500);
    });
}

function editMessage(btn) {
    const msg = btn.closest('.msg');
    const text = msg.dataset.rawText || msg.querySelector('.bubble').innerText;
    const msgs = document.getElementById('messages');
    const allMsgs = Array.from(msgs.querySelectorAll('.msg'));
    const idx = allMsgs.indexOf(msg);

    // Remove this message and everything after it from DOM
    for (let i = allMsgs.length - 1; i >= idx; i--) {
        allMsgs[i].remove();
    }

    // Trim history: each msg pair = 2 entries (user + assistant)
    // Count how many user messages remain in DOM
    const remainingMsgs = msgs.querySelectorAll('.msg').length;
    // Each visible pair = 2 history entries
    const keepPairs = Math.floor(remainingMsgs / 2);
    history = history.slice(0, keepPairs * 2);

    // Put text in input field for editing
    const input = document.getElementById('msg-input');
    input.value = text;
    autoResize(input);
    input.focus();
}