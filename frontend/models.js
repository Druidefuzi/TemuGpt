// ─── MODELS.JS — Modell-Manager, Einstellungen, Knowledge, System Prompt ─────

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
        const instanceId = m.instance_id || m.id;
        let actions = '';
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

// ── REASONING TOGGLE (clientseitig) ──
let showReasoning = localStorage.getItem('showReasoning') !== 'false'; // default: AN

document.addEventListener('DOMContentLoaded', () => updateThinkBtn(showReasoning));

async function toggleThinkMode() {
    showReasoning = !showReasoning;
    localStorage.setItem('showReasoning', showReasoning);
    updateThinkBtn(showReasoning);
    // Server-Sync (optional, für Statusabfrage bei Init)
    await fetch('/api/thinking/toggle', { method: 'POST' });
}

function updateThinkBtn(enabled) {
    const btn = document.getElementById('think-toggle-btn');
    const label = document.getElementById('think-toggle-label');
    if (enabled) {
        btn.classList.add('active');
        label.textContent = '🧠 Reasoning: AN';
    } else {
        btn.classList.remove('active');
        label.textContent = '🧠 Reasoning: AUS';
    }
}

// ── RESEARCH MODE ──
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

// ── PERMISSIONS ──
const PERMISSION_LABELS = {
    search:    { on: '🔍 Suche: AN',      off: '🔍 Suche: AUS' },
    document:  { on: '📄 Dokumente: AN',  off: '📄 Dokumente: AUS' },
    knowledge: { on: '📚 Knowledge: AN',  off: '📚 Knowledge: AUS' },
    image:     { on: '🖼️ Bilder: AN',     off: '🖼️ Bilder: AUS' },
};

async function loadPermissions() {
    try {
        const resp = await fetch('/api/permissions/status');
        const data = await resp.json();
        Object.keys(data).forEach(p => updatePermissionBtn(p, data[p]));
    } catch(e) {}
}

async function togglePermission(permission) {
    const resp = await fetch('/api/permissions/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ permission })
    });
    const data = await resp.json();
    updatePermissionBtn(permission, data.enabled);

    // Bildgenerierung Panel sync (bestehender Mechanismus)
    if (permission === 'image') updateImageGenBtn(data.enabled);
}

function updatePermissionBtn(permission, enabled) {
    const btn   = document.getElementById(`perm-btn-${permission}`);
    const label = document.getElementById(`perm-label-${permission}`);
    if (!btn || !label) return;
    const def = PERMISSION_LABELS[permission] || { on: 'AN', off: 'AUS' };
    if (enabled) {
        btn.classList.add('active');
        label.textContent = def.on;
    } else {
        btn.classList.remove('active');
        label.textContent = def.off;
    }
}
