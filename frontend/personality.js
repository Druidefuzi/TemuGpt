// ─── PERSONALITY.JS — Personality Load, Switch & Logo Cache ─────────────────

// Apply cached personality instantly before any fetch (zero flash)
(function applyCachedPersonality() {
    try {
        const cached = localStorage.getItem('activePersonality');
        if (!cached) return;
        const p = JSON.parse(cached);
        const cachedLogo = localStorage.getItem('activePersonalityLogo');
        if (cachedLogo && p.has_logo) {
            const src = 'data:image/png;base64,' + cachedLogo;
            ['app-logo', 'img-logo'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.src = src;
            });
            window._assistantLogoSrc = src;
        }
        _applyPersonalityMeta(p.name, p);
    } catch(e) {}
})();

async function loadPersonalities() {
    try {
        const r = await fetch('/api/personalities');
        const d = await r.json();

        // Populate dropdown if present
        const sel = document.getElementById('personality-select');
        if (sel) {
            sel.innerHTML = '<option value="">🎭 Persönlichkeit</option>';
            d.personalities.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p.name;
                opt.textContent = (p.name === d.active ? '✓ ' : '') + p.name;
                if (p.name === d.active) opt.selected = true;
                sel.appendChild(opt);
            });
        }

        const active = d.personalities.find(p => p.name === d.active);
        if (!active) return;

        // Cache personality meta
        localStorage.setItem('activePersonality', JSON.stringify(active));

        // Cache logo as base64 for instant next load
        if (active.has_logo) {
            fetch(`/api/personalities/${active.name}/logo`)
                .then(r => r.blob())
                .then(blob => new Promise((res, rej) => {
                    const reader = new FileReader();
                    reader.onload  = () => res(reader.result.split(',')[1]);
                    reader.onerror = rej;
                    reader.readAsDataURL(blob);
                }))
                .then(b64 => localStorage.setItem('activePersonalityLogo', b64))
                .catch(() => {});
        } else {
            localStorage.removeItem('activePersonalityLogo');
        }

        applyActivePersonality(active.name, d.personalities);
    } catch(e) {}
}

function applyActivePersonality(name, list) {
    const p = Array.isArray(list) ? list.find(p => p.name === name) : list;
    if (!p) return;
    const logoSrc = p.has_logo
        ? `/api/personalities/${name}/logo?t=${Date.now()}`
        : 'frontend/assets/logo.png';
    _applyPersonalityMeta(name, p);
    ['app-logo', 'img-logo'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.src = logoSrc;
    });
    window._assistantLogoSrc = logoSrc;
    document.querySelectorAll('.msg.assistant .avatar img').forEach(img => img.src = logoSrc);
}

function _applyPersonalityMeta(name, p) {
    const appName = document.getElementById('app-name');
    if (appName) appName.textContent = `${name} — AI Assistant`;
    const descEl = document.getElementById('welcome-desc');
    if (descEl && p.description) descEl.textContent = p.description;
}

async function switchPersonality(name) {
    if (!name) return;
    try {
        await fetch('/api/personalities/active', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        localStorage.removeItem('activePersonalityLogo');
        await loadPersonalities();
        // Apply TTS voice for this personality
        if (typeof applyPersonalityTtsVoice === 'function') applyPersonalityTtsVoice();
    } catch(e) {}
}

document.addEventListener('DOMContentLoaded', loadPersonalities);
