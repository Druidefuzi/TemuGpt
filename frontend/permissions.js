// ─── PERMISSIONS.JS — Feature Toggles & Switch State ────────────────────────

function setSwitch(id, on) {
    const el = document.getElementById(id);
    if (el) el.className = 'sb-toggle-switch' + (on ? ' on' : '');
}

// ── Thinking ──────────────────────────────────────────────────────────────────
async function toggleThinkMode() {
    try {
        const r = await fetch('/api/thinking/toggle', { method: 'POST' });
        const d = await r.json();
        setSwitch('sw-thinking', d.enabled);
        updateThinkBtn(d.enabled);
    } catch(e) {}
}

// ── Research ──────────────────────────────────────────────────────────────────
async function toggleResearchMode() {
    try {
        const r = await fetch('/api/research/toggle', { method: 'POST' });
        const d = await r.json();
        setSwitch('sw-research', d.enabled);
        updateResearchBtn(d.enabled);
        const rsEl = document.getElementById('research-settings');
        if (rsEl) rsEl.style.display = d.enabled ? 'block' : 'none';
    } catch(e) {}
}

// ── Permissions ───────────────────────────────────────────────────────────────
async function togglePermission(type) {
    try {
        await fetch('/api/permissions/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ permission: type })
        });
        await _syncPermissionSwitches();
    } catch(e) {}
}

async function _syncPermissionSwitches() {
    try {
        const r = await fetch('/api/permissions/status');
        const d = await r.json();
        setSwitch('sw-search',    d.search);
        setSwitch('sw-image',     d.image);
        setSwitch('sw-document',  d.document);
        setSwitch('sw-knowledge', d.knowledge);
        // legacy label updates
        _setLegacyLabel('perm-label-search',    '🔍 Suche',     d.search);
        _setLegacyLabel('perm-label-image',     '🖼️ Bilder',    d.image);
        _setLegacyLabel('perm-label-document',  '📄 Dokumente', d.document);
        _setLegacyLabel('perm-label-knowledge', '📚 Knowledge', d.knowledge);
    } catch(e) {}
}

function _setLegacyLabel(id, text, on) {
    const el = document.getElementById(id);
    if (el) el.textContent = `${text}: ${on ? 'AN' : 'AUS'}`;
}

// ── Load all states on init ────────────────────────────────────────────────────
async function loadPermissions() {
    try {
        const [thinkR, researchR] = await Promise.all([
            fetch('/api/thinking/status'),
            fetch('/api/research/status')
        ]);
        const td = await thinkR.json();
        const rd = await researchR.json();
        setSwitch('sw-thinking', td.enabled);
        setSwitch('sw-research', rd.enabled);
        updateThinkBtn(td.enabled);
        updateResearchBtn(rd.enabled);
        const rsEl = document.getElementById('research-settings');
        if (rsEl) rsEl.style.display = rd.enabled ? 'block' : 'none';
    } catch(e) {}
    await _syncPermissionSwitches();
}

document.addEventListener('DOMContentLoaded', loadPermissions);
