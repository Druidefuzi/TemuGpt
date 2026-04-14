// ─── NAVIGATION.JS — Global Command Palette (Ctrl+K) ─────────────────────────

(function() {
    const NAV_ITEMS = [
        { group: "Chat",           label: "Chat",             icon: "💬", desc: "Hauptchat mit LM Studio",          url: "/" },
        { group: "Image",          label: "Image Generator",  icon: "⚡", desc: "ComfyUI Workflow-Editor",           url: "/workflows" },
        { group: "Image",          label: "Gallery",          icon: "🗂️", desc: "Bildergalerie mit Ordnern",         url: "/gallery" },
        { group: "Image",          label: "Creator",          icon: "✨", desc: "Character · Style · Theme · Sort",  url: "/creator" },
        { group: "Image",          label: "Model Merger",     icon: "🔀", desc: "Modelle zusammenführen",            url: "/merger" },
        { group: "Image",          label: "Artist Reference", icon: "🎨", desc: "Referenzgalerie für Artists",       url: "/reference" },
        { group: "Media",          label: "Song Generator",   icon: "🎵", desc: "Lieder via ACE-Step erstellen",     url: "/music" },
        { group: "Einstellungen",  label: "Personality",      icon: "🎭", desc: "Personalities verwalten",           url: "/personality" },
        { group: "Einstellungen",  label: "Settings",         icon: "⚙️", desc: "App-Konfiguration",                 url: "/settings" },
        { group: "Tools",          label: "Sort",             icon: "🗂️", desc: "KI-gestützte Bildkategorisierung",    url: "/sort" },
        { group: "Tools",          label: "Workflow Editor",  icon: "🔧", desc: "Visueller ComfyUI Node-Editor",        url: "/node-editor" },
    ];

    let _filtered   = [...NAV_ITEMS];
    let _highlighted = 0;
    let _isOpen     = false;

    // ── Inject CSS ──────────────────────────────────────────────────────────
    const style = document.createElement('style');
    style.textContent = `
        #nav-overlay {
            position: fixed; inset: 0; z-index: 9999;
            background: rgba(0,0,0,.55);
            display: flex; align-items: flex-start; justify-content: center;
            padding-top: 80px;
            opacity: 0; pointer-events: none;
            transition: opacity .15s;
        }
        #nav-overlay.open { opacity: 1; pointer-events: all; }
        #nav-palette-box {
            width: 560px; max-width: calc(100vw - 32px);
            background: var(--surface);
            border-radius: 12px;
            border: 1px solid var(--border);
            overflow: hidden;
            transform: translateY(-8px);
            transition: transform .15s;
        }
        #nav-overlay.open #nav-palette-box { transform: translateY(0); }
        #nav-search-wrap {
            display: flex; align-items: center; gap: 10px;
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
        }
        #nav-search-wrap svg { flex-shrink: 0; opacity: .4; color: var(--muted); }
        #nav-search {
            flex: 1; border: none; background: transparent;
            font-family: 'Syne', sans-serif; font-size: 15px;
            color: var(--text); outline: none;
        }
        #nav-search::placeholder { color: var(--muted); }
        .nav-kbd {
            font-size: 11px; color: var(--muted);
            background: var(--surface2); border: 1px solid var(--border);
            border-radius: 4px; padding: 2px 7px;
            font-family: 'DM Mono', monospace;
        }
        #nav-list { max-height: 380px; overflow-y: auto; padding: 6px; }
        .nav-group-label {
            padding: 6px 12px 3px;
            font-size: 10px; font-weight: 700;
            text-transform: uppercase; letter-spacing: .1em;
            color: var(--muted);
        }
        .nav-item {
            display: flex; align-items: center; gap: 12px;
            padding: 9px 12px; border-radius: 8px; cursor: pointer;
            transition: background .1s;
        }
        .nav-item:hover, .nav-item.highlighted { background: rgba(108,99,255,.12); }
        .nav-item-icon { font-size: 16px; width: 24px; text-align: center; flex-shrink: 0; }
        .nav-item-label { font-size: 14px; font-weight: 700; color: var(--text); }
        .nav-item-desc  { font-size: 12px; color: var(--muted); }
        .nav-item-url   { font-size: 11px; color: var(--muted); font-family: 'DM Mono', monospace; margin-left: auto; flex-shrink: 0; }
        #nav-item-active-indicator {
            width: 6px; height: 6px; border-radius: 50%;
            background: var(--accent); flex-shrink: 0; display: none;
        }
        .nav-footer {
            display: flex; gap: 16px; padding: 8px 16px;
            border-top: 1px solid var(--border);
        }
        .nav-footer-hint { font-size: 11px; color: var(--muted); display: flex; align-items: center; gap: 4px; }
        #nav-trigger-btn {
            position: fixed; bottom: 20px; right: 20px;
            width: 44px; height: 44px; border-radius: 50%;
            background: var(--accent); border: none;
            color: #fff; font-size: 18px; cursor: pointer;
            display: none;
            align-items: center; justify-content: center;
            box-shadow: 0 4px 12px rgba(108,99,255,.4);
            transition: transform .15s, opacity .15s;
            z-index: 9998;
        }
        #nav-trigger-btn:hover { transform: scale(1.08); }
        @media (max-width: 768px) { #nav-trigger-btn { display: flex; } }
        #nav-restart-btn {
            display: flex; align-items: center; justify-content: center;
            gap: 7px; width: calc(100% - 12px); margin: 4px 6px 2px;
            padding: 8px 12px; border-radius: 8px;
            border: 1px solid var(--border); background: none;
            color: var(--muted); font-family: 'Syne', sans-serif;
            font-size: 0.78rem; font-weight: 600; cursor: pointer;
            transition: all .15s; text-align: left;
        }
        #nav-restart-btn:hover { border-color: var(--accent2); color: var(--accent2); background: rgba(255,101,132,.06); }
        #nav-restart-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--success); flex-shrink: 0; }
        #nav-header-search {
            display: flex; align-items: center; justify-content: center;
            width: 30px; height: 30px; border-radius: 8px;
            border: 1px solid var(--border); background: none;
            color: var(--muted); cursor: pointer;
            transition: all .15s; flex-shrink: 0;
        }
        #nav-header-search:hover { border-color: var(--accent); color: var(--accent); background: rgba(108,99,255,.08); }
    `;
    document.head.appendChild(style);

    // ── Inject HTML ─────────────────────────────────────────────────────────
    const overlay = document.createElement('div');
    overlay.id = 'nav-overlay';
    overlay.innerHTML = `
        <div id="nav-palette-box">
            <div id="nav-search-wrap">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                    <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.5"/>
                    <path d="M10.5 10.5L14 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                </svg>
                <input id="nav-search" placeholder="Wohin möchtest du?" autocomplete="off" spellcheck="false">
                <span class="nav-kbd">Esc</span>
            </div>
            <div id="nav-list"></div>
            <div style="padding:0 0 4px;border-top:1px solid var(--border);margin-top:2px">
                <button id="nav-restart-btn" onclick="restartServer()">
                    <span id="nav-restart-dot"></span>
                    <span id="nav-restart-label">Server neu starten</span>
                </button>
            </div>
            <div class="nav-footer">
                <span class="nav-footer-hint"><span class="nav-kbd">↑↓</span> navigieren</span>
                <span class="nav-footer-hint"><span class="nav-kbd">↵</span> öffnen</span>
                <span class="nav-footer-hint"><span class="nav-kbd">Ctrl K</span> schließen</span>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    // Floating trigger button (mobile fallback)
    const triggerBtn = document.createElement('button');
    triggerBtn.id = 'nav-trigger-btn';
    triggerBtn.title = 'Navigation (Ctrl+K)';
    triggerBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 18 18" fill="none"><circle cx="7.5" cy="7.5" r="5" stroke="white" stroke-width="1.8"/><path d="M11.5 11.5L16 16" stroke="white" stroke-width="1.8" stroke-linecap="round"/></svg>`;
    triggerBtn.onclick = openPalette;
    document.body.appendChild(triggerBtn);

    // Inject search icon into app-header
    const header = document.querySelector('.app-header');
    if (header) {
        const searchBtn = document.createElement('button');
        searchBtn.id    = 'nav-header-search';
        searchBtn.title = 'Navigation (Ctrl+K)';
        searchBtn.innerHTML = `<svg width="15" height="15" viewBox="0 0 15 15" fill="none"><circle cx="6" cy="6" r="4.2" stroke="currentColor" stroke-width="1.6"/><path d="M9.5 9.5L13 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`;
        searchBtn.onclick = openPalette;
        // Insert before the first child of app-nav, or append to header
        const nav = header.querySelector('.app-nav');
        if (nav) nav.prepend(searchBtn);
        else header.appendChild(searchBtn);
    }

    // ── Render ───────────────────────────────────────────────────────────────
    function renderList() {
        const list = document.getElementById('nav-list');
        if (!_filtered.length) {
            list.innerHTML = `<div style="padding:24px;text-align:center;color:var(--muted);font-size:14px">Keine Ergebnisse</div>`;
            return;
        }
        const currentPath = window.location.pathname;
        let html = '';
        let lastGroup = null;
        _filtered.forEach((item, i) => {
            if (item.group !== lastGroup) {
                html += `<div class="nav-group-label">${item.group}</div>`;
                lastGroup = item.group;
            }
            const isHl      = i === _highlighted;
            const isCurrent = item.url === currentPath;
            html += `<div class="nav-item${isHl ? ' highlighted' : ''}" data-idx="${i}">
                <span class="nav-item-icon">${item.icon}</span>
                <div style="flex:1;min-width:0">
                    <div class="nav-item-label">${item.label}${isCurrent ? ' <span style="font-size:10px;background:rgba(108,99,255,.2);color:var(--accent);border-radius:4px;padding:1px 6px;font-weight:600">Aktuell</span>' : ''}</div>
                    <div class="nav-item-desc">${item.desc}</div>
                </div>
                <span class="nav-item-url">${item.url}</span>
            </div>`;
        });
        list.innerHTML = html;
        // Event delegation — no DOM rebuilds on hover
        list.onclick = (e) => {
            const item = e.target.closest('.nav-item');
            if (item) navigateTo(_filtered[parseInt(item.dataset.idx)]);
        };
        list.onmousemove = (e) => {
            const item = e.target.closest('.nav-item');
            if (!item) return;
            const idx = parseInt(item.dataset.idx);
            if (idx === _highlighted) return;
            _highlighted = idx;
            list.querySelectorAll('.nav-item').forEach((el, i) => {
                el.classList.toggle('highlighted', i === idx);
            });
        };
        // Scroll highlighted into view
        const hlEl = list.querySelector('.highlighted');
        if (hlEl) hlEl.scrollIntoView({ block: 'nearest' });
    }

    // ── Open / Close ─────────────────────────────────────────────────────────
    function openPalette() {
        _filtered   = [...NAV_ITEMS];
        _highlighted = 0;
        _isOpen      = true;
        overlay.classList.add('open');
        const input = document.getElementById('nav-search');
        input.value = '';
        renderList();
        setTimeout(() => input.focus(), 50);
    }

    function closePalette() {
        _isOpen = false;
        overlay.classList.remove('open');
    }

    function navigateTo(item) {
        closePalette();
        window.location.href = item.url;
    }

    // ── Search ───────────────────────────────────────────────────────────────
    document.getElementById('nav-search').addEventListener('input', function() {
        const q = this.value.toLowerCase();
        _highlighted = 0;
        _filtered = q
            ? NAV_ITEMS.filter(i =>
                i.label.toLowerCase().includes(q) ||
                i.desc.toLowerCase().includes(q)  ||
                i.group.toLowerCase().includes(q))
            : [...NAV_ITEMS];
        renderList();
    });

    // ── Keyboard ─────────────────────────────────────────────────────────────
    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            _isOpen ? closePalette() : openPalette();
            return;
        }
        if (!_isOpen) return;
        if (e.key === 'Escape')    { closePalette(); return; }
        if (e.key === 'ArrowDown') { e.preventDefault(); _highlighted = Math.min(_highlighted + 1, _filtered.length - 1); renderList(); }
        if (e.key === 'ArrowUp')   { e.preventDefault(); _highlighted = Math.max(_highlighted - 1, 0); renderList(); }
        if (e.key === 'Enter')     { if (_filtered[_highlighted]) navigateTo(_filtered[_highlighted]); }
    });

    // Restart server
    async function restartServer() {
        const label = document.getElementById('nav-restart-label');
        const dot   = document.getElementById('nav-restart-dot');
        label.textContent = 'Startet neu...';
        dot.style.background = '#ff9800';
        try {
            await fetch('/api/server/restart', { method: 'POST' });
            label.textContent = 'Neu gestartet — Seite lädt...';
            dot.style.background = 'var(--accent)';
            setTimeout(() => window.location.reload(), 2000);
        } catch(e) {
            label.textContent = 'Fehler: ' + e.message;
            dot.style.background = 'var(--accent2)';
            setTimeout(() => { label.textContent = 'Server neu starten'; dot.style.background = 'var(--success)'; }, 3000);
        }
    }

    // Close on backdrop click
    overlay.addEventListener('click', e => { if (e.target === overlay) closePalette(); });
})();
