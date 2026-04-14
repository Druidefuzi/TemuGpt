// ─── PERSONALITY_UI.JS — Personality Page Logic ───────────────────────────────

let currentName      = '';
let generatedLogoB64 = null;
let allModels        = [];
let _kokoroVoices    = [];
let _comfyAvailable  = null; // null=unknown, true/false after check

// ── Tab switching ────────────────────────────────────────────────────────────

function switchTab(tab) {
    document.querySelectorAll('.p-tab').forEach((btn, i) => {
        const tabs = ['text','logo','voice'];
        btn.classList.toggle('active', tabs[i] === tab);
    });
    document.querySelectorAll('.p-tab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === 'tab-' + tab);
    });
}

// ── ComfyUI availability check ────────────────────────────────────────────────
async function checkComfyAvailable() {
    if (_comfyAvailable !== null) return _comfyAvailable;
    try {
        const r = await fetch('/api/comfy/all-checkpoints', { signal: AbortSignal.timeout(3000) });
        _comfyAvailable = r.ok;
    } catch(e) {
        _comfyAvailable = false;
    }
    return _comfyAvailable;
}


    // ── Init ──────────────────────────────────────────────────────────────────

    async function init() {
        await Promise.all([loadPersonalities(), loadWorkflows(), loadModels(), loadKokoroVoices()]);
    }


    async function loadKokoroVoices() {
        // Standard Kokoro-FastAPI voices (hardcoded — no reliable list endpoint)
        _kokoroVoices = [
            'af_bella','af_sky','af_sarah','af_nicole',
            'bf_emma','bf_isabella',
            'am_adam','am_michael',
            'bm_george','bm_lewis'
        ];
        renderVoiceMixer();
    }

    function renderVoiceMixer() {
        const wrap = document.getElementById('voice-mixer-wrap');
        if (!_kokoroVoices.length) return;
        wrap.innerHTML = _kokoroVoices.map(v => `
            <div class="voice-row" id="vrow-${v}">
                <label style="display:flex;align-items:center;gap:6px;cursor:pointer;flex:1">
                    <input type="checkbox" class="voice-cb" data-voice="${v}"
                           onchange="updateVoiceBlend()" style="accent-color:var(--accent)">
                    <span style="font-size:0.8rem;font-family:'DM Mono',monospace">${v}</span>
                </label>
                <input type="range" class="voice-weight" data-voice="${v}"
                       min="0.1" max="2" step="0.1" value="1"
                       style="width:80px;accent-color:var(--accent);display:none"
                       oninput="this.nextElementSibling.textContent=parseFloat(this.value).toFixed(1);updateVoiceBlend()">
                <span style="font-size:0.7rem;color:var(--accent);min-width:22px;display:none">1.0</span>
            </div>`).join('');
    }

    function updateVoiceBlend() {
        const checked = [...document.querySelectorAll('.voice-cb:checked')];
        // Show/hide weight sliders
        document.querySelectorAll('.voice-weight, .voice-weight + span').forEach(el => {
            el.style.display = 'none';
        });
        checked.forEach(cb => {
            const row = document.getElementById('vrow-' + cb.dataset.voice);
            row.querySelectorAll('.voice-weight, .voice-weight + span').forEach(el => {
                el.style.display = checked.length > 1 ? '' : 'none';
            });
        });

        // Build blend string
        let blend = '';
        if (checked.length === 0) {
            blend = '';
        } else if (checked.length === 1) {
            blend = checked[0].dataset.voice;
        } else {
            blend = checked.map(cb => {
                const w = document.querySelector(`.voice-weight[data-voice="${cb.dataset.voice}"]`);
                const weight = w ? parseFloat(w.value) : 1;
                return weight === 1 ? cb.dataset.voice : `${cb.dataset.voice}(${weight.toFixed(1)})`;
            }).join('+');
        }
        document.getElementById('p-tts-voice').value = blend;
        document.getElementById('voice-blend-preview').textContent = blend || '— global —';
        const previewBtn = document.getElementById('voice-preview-btn');
        if (previewBtn) previewBtn.disabled = !blend;
    }

    async function previewVoice() {
        const voice = document.getElementById('p-tts-voice').value.trim();
        if (!voice) return;
        const btn    = document.getElementById('voice-preview-btn');
        const status = document.getElementById('voice-preview-status');
        const audio  = document.getElementById('voice-preview-audio');
        btn.disabled = true;
        btn.textContent = '⏳ Generiere...';
        status.style.display = 'block';
        status.textContent = `Stimme: ${voice}`;
        audio.style.display = 'none';
        try {
            const r = await fetch('/api/tts/settings');
            const s = await r.json();
            const ttsUrl = s.url || 'http://localhost:8880';
            const sampleText = "Hello, I am your AI assistant. How can I help you today?";
            const resp = await fetch('/api/tts/speak', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: sampleText, voice })
            });
            if (!resp.ok) throw new Error(await resp.text());
            const blob = await resp.blob();
            audio.src = URL.createObjectURL(blob);
            audio.style.display = 'block';
            audio.play().catch(() => {});
            status.textContent = `✓ Stimme: ${voice}`;
        } catch(e) {
            status.textContent = '❌ ' + e.message;
        }
        btn.disabled = false;
        btn.textContent = '🔊 Vorschau';
    }

    function randomVoiceBlend() {
        if (!_kokoroVoices.length) return;
        // Uncheck all
        document.querySelectorAll('.voice-cb').forEach(cb => cb.checked = false);
        // Pick 1-3 random voices
        const shuffled = [..._kokoroVoices].sort(() => Math.random() - 0.5);
        const count    = Math.floor(Math.random() * 3) + 1;
        const picked   = shuffled.slice(0, count);
        picked.forEach(v => {
            const cb = document.querySelector(`.voice-cb[data-voice="${v}"]`);
            if (cb) {
                cb.checked = true;
                if (count > 1) {
                    const slider = document.querySelector(`.voice-weight[data-voice="${v}"]`);
                    if (slider) slider.value = (Math.round((Math.random() * 1.4 + 0.3) * 10) / 10).toString();
                }
            }
        });
        updateVoiceBlend();
    }

    async function loadPersonalities() {
        try {
            const r = await fetch('/api/personalities');
            const d = await r.json();
            renderList(d.personalities, d.active);
        } catch(e) {
            document.getElementById('p-list').innerHTML =
                '<div style="padding:12px;color:var(--muted);font-size:0.78rem">❌ Laden fehlgeschlagen</div>';
        }
    }

    function renderList(personalities, active) {
        const list = document.getElementById('p-list');
        list.innerHTML = '';
        if (!personalities.length) {
            const empty = document.createElement('div');
            empty.style.cssText = 'padding:12px;color:var(--muted);font-size:0.78rem';
            empty.textContent = 'Noch keine Persönlichkeiten';
            list.appendChild(empty);
            return;
        }
        personalities.forEach(p => {
            const item = document.createElement('div');
            item.className = 'p-item' + (p.name === currentName ? ' active' : '');
            item.onclick = () => selectPersonality(p.name, p.has_logo, p.has_text);

            const img = document.createElement('img');
            img.className = 'p-item-logo';
            img.src = p.has_logo ? `/api/personalities/${p.name}/logo` : 'frontend/assets/logo.png';
            img.onerror = () => { img.src = 'frontend/assets/logo.png'; };

            const info = document.createElement('div');
            info.className = 'p-item-info';
            const nameEl = document.createElement('div');
            nameEl.className = 'p-item-name';
            nameEl.textContent = p.name;
            const preview = document.createElement('div');
            preview.className = 'p-item-preview';
            preview.textContent = p.preview || '—';
            info.appendChild(nameEl);
            info.appendChild(preview);

            item.appendChild(img);
            item.appendChild(info);

            if (p.name === active) {
                const badge = document.createElement('span');
                badge.className = 'p-item-badge';
                badge.textContent = 'Aktiv';
                item.appendChild(badge);
            }
            list.appendChild(item);
        });
    }

    async function loadWorkflows() {
        try {
            const r = await fetch('/api/workflows');
            const d = await r.json();
            const sel = document.getElementById('p-workflow-select');
            (d.workflows || []).forEach(w => {
                const opt = document.createElement('option');
                opt.value = w.name;
                opt.textContent = w.display_name;
                sel.appendChild(opt);
            });
        } catch(e) {}
    }

    async function loadModels() {
        try {
            const r = await fetch('/api/comfy/all-checkpoints', { signal: AbortSignal.timeout(3000) });
            if (!r.ok) throw new Error('ComfyUI not available');
            const d = await r.json();
            allModels = [...(d.checkpoints || []), ...(d.unets || [])];
            const sel = document.getElementById('p-model-select');
            allModels.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m.split('\\').pop().split('/').pop();
                sel.appendChild(opt);
            });
            _comfyAvailable = true;
        } catch(e) {
            _comfyAvailable = false;
            // ComfyUI not available — show fallback hint on logo section
            const genLogoBtn = document.getElementById('gen-logo-btn');
            if (genLogoBtn) {
                genLogoBtn.textContent = '🎨 Default Logo verwenden';
                genLogoBtn.title = 'ComfyUI nicht verfügbar — Default Logo wird verwendet';
            }
            const workflowSel = document.getElementById('p-workflow-select');
            if (workflowSel) workflowSel.closest('.p-field')?.style.setProperty('display','none');
            const modelSel = document.getElementById('p-model-select');
            if (modelSel) modelSel.closest('.p-field')?.style.setProperty('display','none');
        }
    }

    // ── Personality selection ─────────────────────────────────────────────────

    function selectPersonality(name, hasLogo, hasText) {
        currentName = name;
        document.getElementById('p-name').value = name;
        document.querySelectorAll('.p-item').forEach(i =>
            i.classList.toggle('active', i.querySelector('.p-item-name')?.textContent === name));

        // Logo
        if (hasLogo) {
            document.getElementById('logo-preview').innerHTML =
                `<img class="p-logo-img" src="/api/personalities/${name}/logo?t=${Date.now()}" alt="Logo">`;
            document.getElementById('logo-label').textContent = 'logo.png';
        } else {
            document.getElementById('logo-preview').innerHTML = '<div class="p-logo-empty">🤖</div>';
            document.getElementById('logo-label').textContent = 'Kein Logo';
        }

        // Text
        if (hasText) {
            fetch(`/api/personalities/${name}/text`)
                .then(r => r.json())
                .then(d => {
                    generatedText = d.text || '';
                    showText(generatedText);
                    document.getElementById('save-btn').disabled = false;
                    document.getElementById('activate-btn').disabled = false;
                    document.getElementById('delete-btn').disabled = name === 'default';
                    document.getElementById('gen-desc-btn').disabled = false;
                })
                .catch(() => {});
        } else {
            resetText();
        }
        // Load description + TTS in one call
        fetch(`/api/personalities/${name}/full`)
            .then(r => r.json())
            .then(d => {
                const desc = d.description || '';
                document.getElementById('p-desc-tagline').value = desc;
                document.getElementById('desc-display').textContent = desc || 'Beschreibung erscheint hier...';
                const voice = d.tts_voice || '';
                document.getElementById('p-tts-voice').value = voice;
                document.getElementById('voice-blend-preview').textContent = voice || '— global —';
                document.querySelectorAll('.voice-cb').forEach(cb => { cb.checked = false; });
                if (voice) {
                    voice.split('+').forEach(part => {
                        const match = part.match(/^([^(]+)(?:\(([^)]+)\))?$/);
                        if (!match) return;
                        const vname  = match[1].trim();
                        const weight = match[2] ? parseFloat(match[2]) : 1;
                        const cb = document.querySelector(`.voice-cb[data-voice="${vname}"]`);
                        if (cb) {
                            cb.checked = true;
                            const slider = document.querySelector(`.voice-weight[data-voice="${vname}"]`);
                            if (slider) slider.value = weight;
                        }
                    });
                    updateVoiceBlend();
                }
            })
            .catch(() => {});
    }

    function newPersonality() {
        currentName = '';
        generatedText = '';
        generatedLogoB64 = '';
        document.getElementById('p-name').value = '';
        document.getElementById('p-desc').value = '';
        document.getElementById('p-logo-desc').value = '';
        document.getElementById('p-tts-voice').value = '';
        document.getElementById('voice-blend-preview').textContent = '— global —';
        document.querySelectorAll('.voice-cb').forEach(cb => cb.checked = false);
        updateVoiceBlend();
        switchTab('text');
        document.getElementById('p-desc-tagline').value = '';
        document.getElementById('desc-display').textContent = 'Beschreibung erscheint hier...';
        document.getElementById('gen-desc-btn').disabled = true;
        document.getElementById('logo-preview').innerHTML = '<div class="p-logo-empty">🤖</div>';
        document.getElementById('logo-label').textContent = 'Noch kein Logo generiert';
        resetText();
        document.querySelectorAll('.p-item').forEach(i => i.classList.remove('active'));
        document.getElementById('p-name').focus();
    }

    function showText(text) {
        const display = document.getElementById('text-display');
        const edit    = document.getElementById('text-edit');
        display.style.display = 'none';
        edit.style.display    = 'block';
        edit.value = text;
        document.getElementById('save-btn').disabled = false;
    }

    function resetText() {
        const display = document.getElementById('text-display');
        const edit    = document.getElementById('text-edit');
        display.style.display = 'block';
        display.className = 'p-preview-box';
        display.textContent = 'Persönlichkeitstext erscheint hier...';
        edit.style.display  = 'none';
        edit.value = '';
        document.getElementById('save-btn').disabled = true;
        document.getElementById('activate-btn').disabled = true;
        document.getElementById('delete-btn').disabled = true;
    }

    // ── Generate personality text ─────────────────────────────────────────────

    async function generatePersonalityText() {
        const desc = document.getElementById('p-desc').value.trim();
        if (!desc || isGenerating) return;
        isGenerating = true;

        const display = document.getElementById('text-display');
        const edit    = document.getElementById('text-edit');
        display.style.display = 'block';
        display.className = 'p-preview-box streaming p-cursor';
        display.textContent = '';
        edit.style.display = 'none';
        document.getElementById('gen-text-btn').disabled = true;
        document.getElementById('save-btn').disabled = true;

        let full = '';
        try {
            const resp = await fetch('/api/personalities/generate-text', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ description: desc })
            });
            const reader  = resp.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += decoder.decode(value, { stream: true });
                const lines = buf.split('\n');
                buf = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'token') {
                            full += data.text;
                            display.textContent = full;
                        } else if (data.type === 'done') {
                            generatedText = full.trim();
                            display.className = 'p-preview-box';
                            display.style.display = 'none';
                            edit.value = generatedText;
                            edit.style.display = 'block';
                            document.getElementById('save-btn').disabled = false;
                            document.getElementById('gen-desc-btn').disabled = false;
                        }
                    } catch(e) {}
                }
            }
        } catch(e) {
            display.textContent = '❌ ' + e.message;
            display.className = 'p-preview-box';
        }
        isGenerating = false;
        document.getElementById('gen-text-btn').disabled = false;
    }

    // ── Generate logo ─────────────────────────────────────────────────────────

    async function generateLogo() {
        const subject  = document.getElementById('p-logo-desc').value.trim();
        const workflow = document.getElementById('p-workflow-select').value;
        if (!subject) { alert('Bitte beschreibe was im Logo sein soll.'); return; }

        // If ComfyUI not available — use default logo
        const comfyOk = await checkComfyAvailable();
        if (!comfyOk || !workflow) {
            useDefaultLogo();
            return;
        }

        const btn = document.getElementById('gen-logo-btn');
        btn.disabled = true;
        btn.textContent = '⏳ Generiere...';
        document.getElementById('logo-label').textContent = '⏳ Generiere...';

        try {
            // Build prompt
            const pr = await fetch('/api/personalities/logo-prompt', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ subject })
            });
            const pd = await pr.json();
            if (pd.error) throw new Error(pd.error);

            // Load workflow
            const wr = await fetch(`/api/workflows/${workflow}`);
            const wd = await wr.json();
            const wf = wd.workflow;

            // Inject prompt into positive CLIPTextEncode
            for (const [id, node] of Object.entries(wf)) {
                if (node.class_type === 'CLIPTextEncode') {
                    // find positive one via KSampler
                    for (const n of Object.values(wf)) {
                        if ((n.class_type === 'KSampler' || n.class_type === 'KSamplerAdvanced')
                            && String(n.inputs?.positive?.[0]) === id) {
                            node.inputs.text = pd.prompt;
                        }
                    }
                }
                // Force 1:1 aspect
                if (node.class_type === 'EmptyLatentImage') {
                    node.inputs.width  = 1024;
                    node.inputs.height = 1024;
                }
            }

            // Patch model if selected
            const model = document.getElementById('p-model-select').value;
            if (model) {
                for (const node of Object.values(wf)) {
                    if (node.class_type === 'CheckpointLoaderSimple') { node.inputs.ckpt_name = model; break; }
                    if (node.class_type === 'UNETLoader')              { node.inputs.unet_name = model; break; }
                }
            }

            // Run
            const resp = await fetch('/api/workflows/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workflow: wf, artist_mode: null })
            });

            const reader  = resp.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += decoder.decode(value, { stream: true });
                const lines = buf.split('\n');
                buf = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'image_preview') {
                            document.getElementById('logo-preview').innerHTML =
                                `<img class="p-logo-img" src="data:image/jpeg;base64,${data.b64}" style="opacity:.6;filter:blur(2px)">`;
                        } else if (data.type === 'image_done') {
                            generatedLogoB64 = data.image_b64;
                            document.getElementById('logo-preview').innerHTML =
                                `<img class="p-logo-img" src="data:image/png;base64,${data.image_b64}" alt="Logo">`;
                            document.getElementById('logo-label').textContent = '✓ Bereit zum Speichern';
                            document.getElementById('save-btn').disabled = !document.getElementById('text-edit').value.trim();
                        }
                    } catch(e) {}
                }
            }
        } catch(e) {
            document.getElementById('logo-label').textContent = '❌ ' + e.message;
        }

        btn.disabled = false;
        btn.textContent = '🎨 Logo generieren';
    }

    function useDefaultLogo() {
        // Fetch default logo and use as personality logo
        fetch('frontend/assets/logo.png')
            .then(r => r.blob())
            .then(blob => new Promise((res, rej) => {
                const reader = new FileReader();
                reader.onload  = () => res(reader.result.split(',')[1]);
                reader.onerror = rej;
                reader.readAsDataURL(blob);
            }))
            .then(b64 => {
                generatedLogoB64 = b64;
                document.getElementById('logo-preview').innerHTML =
                    `<img class="p-logo-img" src="frontend/assets/logo.png" alt="Default Logo">`;
                document.getElementById('logo-label').textContent = '✓ Default Logo übernommen';
                const saveBtn = document.getElementById('save-btn');
                if (saveBtn && document.getElementById('text-edit').value.trim())
                    saveBtn.disabled = false;
            })
            .catch(() => {
                document.getElementById('logo-label').textContent = '❌ Default Logo nicht gefunden';
            });
    }

    // ── Generate description ─────────────────────────────────────────────────

    async function generateDescription() {
        const personalityText = document.getElementById('text-edit').value.trim()
            || document.getElementById('text-display').textContent.trim();
        if (!personalityText || personalityText === 'Persönlichkeitstext erscheint hier...') {
            alert('Bitte zuerst einen Persönlichkeitstext generieren.');
            return;
        }

        const btn     = document.getElementById('gen-desc-btn');
        const display = document.getElementById('desc-display');
        const input   = document.getElementById('p-desc-tagline');
        btn.disabled  = true;
        btn.textContent = '⏳ Generiere...';
        display.textContent = '';

        let full = '';
        try {
            const resp = await fetch('/api/personalities/generate-description', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ personality_text: personalityText })
            });
            const reader  = resp.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += decoder.decode(value, { stream: true });
                const lines = buf.split('\n');
                buf = lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'token') {
                            full += data.text;
                            display.textContent = full;
                        } else if (data.type === 'done') {
                            input.value = full.trim();
                        }
                    } catch(e) {}
                }
            }
        } catch(e) {
            display.textContent = '❌ ' + e.message;
        }

        btn.disabled = false;
        btn.textContent = '✨ Beschreibung generieren';
    }

    // ── Save ──────────────────────────────────────────────────────────────────

    async function savePersonality() {
        const name    = document.getElementById('p-name').value.trim().replace(/\s+/g, '_');
        const content = document.getElementById('text-edit').value.trim();
        const status  = document.getElementById('save-status');

        if (!name) { document.getElementById('p-name').focus(); return; }
        if (!content && !generatedLogoB64) { status.textContent = '⚠️ Kein Inhalt'; return; }

        const btn = document.getElementById('save-btn');
        btn.disabled = true;
        status.textContent = '💾 Speichert...';

        try {
            const descContent = document.getElementById('p-desc-tagline').value.trim();
            const ttsVoice    = document.getElementById('p-tts-voice').value.trim();
            await fetch('/api/personalities/save-all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    content:     content || undefined,
                    description: descContent || undefined,
                    tts_voice:   ttsVoice,
                    image_b64:   generatedLogoB64 || undefined,
                })
            });
            currentName = name;
            status.textContent = '✅ Gespeichert';
            document.getElementById('activate-btn').disabled = false;
            document.getElementById('delete-btn').disabled = name === 'default';
            setTimeout(() => { status.textContent = ''; btn.disabled = false; }, 2000);
            loadPersonalities();
        } catch(e) {
            status.textContent = '❌ ' + e.message;
            btn.disabled = false;
        }
    }

    async function activatePersonality() {
        const name = currentName || document.getElementById('p-name').value.trim().replace(/\s+/g, '_');
        if (!name) return;
        try {
            await fetch('/api/personalities/active', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            document.getElementById('save-status').textContent = `⚡ "${name}" aktiviert`;
            setTimeout(() => document.getElementById('save-status').textContent = '', 2000);
            loadPersonalities();
        } catch(e) {}
    }

    async function deletePersonality() {
        const name = currentName;
        if (!name || name === 'default') return;
        if (!confirm(`"${name}" wirklich löschen?`)) return;
        try {
            await fetch(`/api/personalities/${name}`, { method: 'DELETE' });
            newPersonality();
            loadPersonalities();
        } catch(e) {}
    }

    init();

    // ── App Header: Personality ──
    (async function loadAppHeader() {
        try {
            const [ar, lr] = await Promise.all([
                fetch('/api/personalities/active'),
                fetch('/api/personalities')
            ]);
            const { active } = await ar.json();
            const { personalities } = await lr.json();
            const p = personalities.find(x => x.name === active);
            const nameEl = document.getElementById('app-name');
            if (nameEl) nameEl.textContent = `${active} — AI Assistant`;
            const logoEl = document.getElementById('app-logo');
            if (logoEl && p?.has_logo)
                logoEl.src = `/api/personalities/${active}/logo?t=${Date.now()}`;
        } catch(e) {}
    })();