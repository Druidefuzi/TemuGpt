// ─── COMFY.JS — Bild-Rendering, Preview, DB-Speicherung ─────────────────────

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

async function saveImageMsgToDB(userMsg, imgJson) {
    if (!currentChatId) {
        const resp = await fetch('/api/chats', { method: 'POST' });
        const data = await resp.json();
        currentChatId = data.id;
        await loadChatHistory();
    }
    const imgContent = JSON.stringify({
        __type: 'image',
        b64: imgJson.image_b64,
        model: imgJson.model,
        prompt: imgJson.prompt,
        filename: imgJson.filename
    });
    await fetch(`/api/chats/${currentChatId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: [
            { role: 'user', content: userMsg },
            { role: 'assistant', content: imgContent }
        ]})
    });
    await loadChatHistory();
}
