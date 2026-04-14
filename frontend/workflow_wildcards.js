// ─── WORKFLOW_WILDCARDS.JS — Wildcard Autocomplete ───────────────────────────

let _wildcards  = [];
let _acDropdown = null;
let _acTarget   = null;

async function loadWildcards() {
    try {
        const r = await fetch('/api/wildcards');
        const d = await r.json();
        _wildcards = d.wildcards || [];
    } catch(e) {}
}

function _createDropdown() {
    if (_acDropdown) return _acDropdown;
    const el = document.createElement('div');
    el.id = 'wf-ac-dropdown';
    el.style.cssText = `
        position: fixed; z-index: 9999;
        background: var(--surface); border: 1px solid var(--accent);
        border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.3);
        max-height: 220px; overflow-y: auto;
        font-family: 'DM Mono', monospace; font-size: 0.78rem;
        min-width: 220px;
    `;
    document.body.appendChild(el);
    _acDropdown = el;
    return el;
}

function _hideDropdown() {
    if (_acDropdown) _acDropdown.style.display = 'none';
    _acTarget = null;
}

function _showDropdown(textarea, query) {
    const matches = _wildcards.filter(w =>
        w.name.toLowerCase().includes(query.toLowerCase())
    );
    if (!matches.length) { _hideDropdown(); return; }

    const dd = _createDropdown();
    dd.innerHTML = '';

    matches.forEach(w => {
        const item = document.createElement('div');
        item.style.cssText = `
            padding: 7px 12px; cursor: pointer;
            display: flex; align-items: center; gap: 8px;
            transition: background .1s;
        `;
        item.innerHTML = `
            <span style="font-size:0.65rem;color:var(--muted);min-width:48px">${w.folder}</span>
            <span style="color:var(--accent)">WILDCARD:</span>
            <span style="color:var(--text)">${w.name}</span>`;
        item.onmouseenter = () => item.style.background = 'rgba(108,99,255,.12)';
        item.onmouseleave = () => item.style.background = '';
        item.onmousedown  = e => { e.preventDefault(); _insertWildcard(textarea, w.name); };
        dd.appendChild(item);
    });

    const rect       = textarea.getBoundingClientRect();
    const lineHeight = parseInt(getComputedStyle(textarea).lineHeight) || 20;
    const textBefore = textarea.value.substring(0, textarea.selectionStart);
    const linesBefore = textBefore.split('\n').length - 1;
    const cursorY    = rect.top + linesBefore * lineHeight + lineHeight;
    const spaceBelow = window.innerHeight - cursorY - 8;

    if (spaceBelow < 80) {
        dd.style.bottom = (window.innerHeight - rect.top + 4) + 'px';
        dd.style.top    = 'auto';
    } else {
        dd.style.top    = (cursorY + 4) + 'px';
        dd.style.bottom = 'auto';
    }
    dd.style.left    = rect.left + 'px';
    dd.style.display = 'block';
    _acTarget = textarea;
}

function _insertWildcard(textarea, name) {
    const pos    = textarea.selectionStart;
    const val    = textarea.value;
    const before = val.substring(0, pos);
    const braceIdx = before.lastIndexOf('{');
    if (braceIdx === -1) return;

    const insert   = `{WILDCARD:${name}}`;
    textarea.value = val.substring(0, braceIdx) + insert + val.substring(pos);
    const newPos   = braceIdx + insert.length;
    textarea.selectionStart = textarea.selectionEnd = newPos;
    textarea.dispatchEvent(new Event('change'));
    _hideDropdown();
    textarea.focus();
}

function _onTextareaInput(e) {
    const ta = e.target;
    if (!ta.classList.contains('wf-textarea') && ta.id !== 'prompt-assist-input') return;

    const pos    = ta.selectionStart;
    const before = ta.value.substring(0, pos);
    const braceIdx = before.lastIndexOf('{');
    if (braceIdx === -1) { _hideDropdown(); return; }

    const afterBrace = before.substring(braceIdx + 1);
    if (afterBrace.includes('}')) { _hideDropdown(); return; }

    const query = afterBrace.replace(/^WILDCARD:/i, '');
    _showDropdown(ta, query);
}

function _onTextareaKeydown(e) {
    if (!_acDropdown || _acDropdown.style.display === 'none') return;
    const items  = _acDropdown.querySelectorAll('div');
    const active = _acDropdown.querySelector('div[data-active]');

    if (e.key === 'Escape') {
        e.preventDefault(); _hideDropdown();
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        const next = active ? (active.nextElementSibling || items[0]) : items[0];
        if (active) { delete active.dataset.active; active.style.background = ''; }
        if (next) { next.dataset.active = '1'; next.style.background = 'rgba(108,99,255,.12)'; next.scrollIntoView({ block: 'nearest' }); }
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = active ? (active.previousElementSibling || items[items.length - 1]) : items[items.length - 1];
        if (active) { delete active.dataset.active; active.style.background = ''; }
        if (prev) { prev.dataset.active = '1'; prev.style.background = 'rgba(108,99,255,.12)'; prev.scrollIntoView({ block: 'nearest' }); }
    } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (active) {
            e.preventDefault();
            _insertWildcard(e.target, active.querySelector('span:last-child').textContent);
        }
    }
}

document.addEventListener('input',   _onTextareaInput);
document.addEventListener('keydown', _onTextareaKeydown);
document.addEventListener('click', e => {
    if (!e.target.closest('#wf-ac-dropdown') && e.target !== _acTarget) _hideDropdown();
});
