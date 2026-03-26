// ─── COMFY.JS — Bild-Modell-Selector, Rendering, DB-Speicherung ─────────────

// ── State ──
let imageModelType = localStorage.getItem('imgModelType') || 'anima';
let imageModelName = localStorage.getItem('imgModelName') || '';
let imageModelList = [];
let imageTurbo     = false;
let imageRawPrompt = false;

// ── Typ-Wechsel ──────────────────────────────────────────────────────────────
function setImageModelType(type) {
    imageModelType = type;
    imageModelName = '';
    localStorage.setItem('imgModelType', type);
    localStorage.removeItem('imgModelName');  // reset model when type changes

    // Buttons updaten
    document.querySelectorAll('.img-type-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.type === type);
    });

    // Z-Image deaktivieren solange kein Workflow
    if (type === 'zimage') {
        document.getElementById('img-model-list').innerHTML =
            '<div class="img-model-item disabled">⏳ Z-Image Workflow noch nicht konfiguriert</div>';
        return;
    }

    loadImageModels();
}

function toggleImageGenPanel() {
    const panel = document.getElementById('imggen-panel');
    const btn   = document.getElementById('imggen-toggle-btn');
    const isOpen = panel.classList.toggle('open');
    btn.classList.toggle('panel-open', isOpen);
}

// Klick außerhalb schließt Panel
document.addEventListener('click', e => {
    const panel = document.getElementById('imggen-panel');
    const btn   = document.getElementById('imggen-toggle-btn');
    if (panel && !panel.contains(e.target) && e.target !== btn) {
        panel.classList.remove('open');
        btn.classList.remove('panel-open');
    }
});

async function toggleImageGeneration() {
    const resp = await fetch('/api/image-generation/toggle', { method: 'POST' });
    const data = await resp.json();
    updateImageGenBtn(data.enabled);
}

function updateImageGenBtn(enabled) {
    const powerBtn  = document.getElementById('imggen-power-btn');
    const panelBody = document.getElementById('imggen-panel-body');
    if (powerBtn) {
        if (enabled) {
            powerBtn.classList.add('active');
        } else {
            powerBtn.classList.remove('active');
        }
    }
    if (panelBody) {
        panelBody.style.opacity  = enabled ? '1' : '0.4';
        panelBody.style.pointerEvents = enabled ? '' : 'none';
    }
}

function toggleTurbo() {
    imageTurbo = !imageTurbo;
    const btn = document.getElementById('turbo-toggle-btn');
    if (imageTurbo) {
        btn.classList.add('active');
        btn.title = 'Turbo: AN (weniger Qualität, schneller)';
    } else {
        btn.classList.remove('active');
        btn.title = 'Turbo: AUS';
    }
}

function toggleRawPrompt() {
    imageRawPrompt = !imageRawPrompt;
    const btn = document.getElementById('raw-prompt-btn');
    if (imageRawPrompt) {
        btn.classList.add('active');
        btn.title = 'Raw Prompt: AN — dein Text wird direkt genutzt';
    } else {
        btn.classList.remove('active');
        btn.title = 'Raw Prompt: AUS — KI optimiert den Prompt';
    }
}

async function loadImageModels() {
    const list = document.getElementById('img-model-list');
    list.innerHTML = '<div class="img-model-item disabled">↻ Lade...</div>';
    try {
        const resp = await fetch(`/api/comfy/image-models?type=${imageModelType}`);
        const data = await resp.json();
        imageModelList = data.models || [];
        renderImageModelList(imageModelList);
    } catch (e) {
        list.innerHTML = '<div class="img-model-item disabled">❌ Fehler</div>';
    }
}

function renderImageModelList(models) {
    const list = document.getElementById('img-model-list');
    if (!models.length) {
        list.innerHTML = '<div class="img-model-item disabled">Keine Modelle gefunden</div>';
        return;
    }
    // data-fullpath speichert den vollen Pfad, angezeigt wird nur der Dateiname
    list.innerHTML = models.map(m => {
        const short = m.split('\\').pop().split('/').pop();
        const isSelected = m === imageModelName;
        return `<div class="img-model-item ${isSelected ? 'selected' : ''}" data-fullpath="${m.replace(/"/g, '&quot;')}" onclick="selectImageModel(this)" title="${m}">${short}</div>`;
    }).join('');
}

function filterImageModels() {
    const q = document.getElementById('img-model-search').value.toLowerCase();
    const filtered = imageModelList.filter(m => m.toLowerCase().includes(q));
    renderImageModelList(filtered);
}

function selectImageModel(el) {
    const fullPath = el.dataset.fullpath;
    imageModelName = fullPath;
    localStorage.setItem('imgModelName', fullPath);
    const short = fullPath.split('\\').pop().split('/').pop();
    document.getElementById('img-model-search').value = short;
    document.getElementById('img-model-list').innerHTML = '';
    console.log('[Comfy] Modell gewählt:', fullPath);
}

// Dropdown öffnen wenn ins Suchfeld geklickt wird
document.addEventListener('DOMContentLoaded', () => {
    // Gespeicherten Typ wiederherstellen
    document.querySelectorAll('.img-type-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.type === imageModelType);
    });

    const searchInput = document.getElementById('img-model-search');
    if (searchInput) {
        // Gespeicherten Modellnamen anzeigen
        if (imageModelName) {
            const short = imageModelName.split('\\').pop().split('/').pop();
            searchInput.value = short;
        }
        searchInput.addEventListener('focus', () => {
            if (imageModelType !== 'zimage') renderImageModelList(imageModelList);
        });
        searchInput.addEventListener('blur', () => {
            setTimeout(() => {
                document.getElementById('img-model-list').innerHTML = '';
            }, 200);
        });
    }
    loadImageModels();
    // Status vom Server holen
    fetch('/api/image-generation/status').then(r => r.json()).then(d => updateImageGenBtn(d.enabled));
});


// ── Bild-Rendering ───────────────────────────────────────────────────────────
function appendImageMessage(json, userPrompt) {
    const msgs = document.getElementById('messages');
    const div = document.createElement('div');
    div.className = 'msg assistant';
    const typeLabel = { anima: '🌸', illustrious: '🎨', zimage: '⚡' }[json.model_type] || '🖼️';
    div.innerHTML = `
        <div class="avatar">🤖</div>
        <div class="bubble">
            <div class="image-result">
                <img src="data:image/png;base64,${json.image_b64}" alt="${json.prompt}" class="generated-image" onclick="openImageFullscreen(this)">
                <div class="image-meta">
                    <span class="image-model">${typeLabel} ${json.model}</span>
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

// ── DB Speichern ─────────────────────────────────────────────────────────────
async function saveImageMsgToDB(userMsg, imgJson) {
    if (!currentChatId) {
        const resp = await fetch('/api/chats', { method: 'POST' });
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