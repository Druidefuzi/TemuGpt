// ─── WORKFLOW_UI.JS — Auto-Parser & Dynamic UI ───────────────────────────────

let SAMPLERS   = ['euler','euler_ancestral','heun','dpm_2','dpm_2_ancestral',
    'lms','dpm_fast','dpm_adaptive','dpmpp_2s_ancestral',
    'dpmpp_sde','dpmpp_2m','dpmpp_2m_sde','ddim','uni_pc','er_sde'];
let SCHEDULERS = ['normal','karras','exponential','sgm_uniform','simple','ddim_uniform'];

async function loadSamplersAndSchedulers() {
    try {
        const resp = await fetch('http://127.0.0.1:8188/object_info/KSampler');
        const data = await resp.json();
        const required = data?.KSampler?.input?.required;
        if (required?.sampler_name?.[0]) SAMPLERS   = required.sampler_name[0];
        if (required?.scheduler?.[0])    SCHEDULERS = required.scheduler[0];
    } catch(e) {
        console.warn('[Samplers] Abruf fehlgeschlagen, nutze Fallback:', e.message);
    }
}

const ASPECT_SIZES = {
    '1:1':  [1024,1024], '3:4': [896,1152], '4:3': [1152,896],
    '16:9': [1216,704],  '9:16': [704,1216]
};

let currentWorkflow = null;
let currentPatches  = {};
let workflowMeta    = {};
let img2imgState    = { enabled: false, imageFile: null, imageDataUrl: null, denoise: 0.75 };
let extraLoras      = [];   // [{uid, name, strength_model, strength_clip}]
let removedLoras    = new Set(); // node IDs of removed original LoRAs
let _extraLoraUid   = 0;
let refinerState    = { enabled: false, workflow: null, model: null, denoise: 0.5 };
let criticState     = { enabled: false };
let artistState     = { enabled: false, model_type: 'illustrious', artist_name: '' };
let _allArtists     = [];

// ── Load workflow list ────────────────────────────────────────────────────────
async function loadWorkflowList() {
    const list = document.getElementById('workflow-list');
    list.innerHTML = '<div class="wf-loading">↻ Lade...</div>';
    try {
        const r = await fetch('/api/workflows');
        const d = await r.json();
        if (!d.workflows?.length) {
            list.innerHTML = '<div class="wf-empty">Keine Workflows im /workflows/ Ordner</div>';
            return;
        }
        list.innerHTML = d.workflows.map(w => `
            <div class="wf-item" onclick="selectWorkflow('${w.name}', this)">
                <div class="wf-item-icon">⚙️</div>
                <div class="wf-item-info">
                    <div class="wf-item-name">${w.display_name}</div>
                    <div class="wf-item-nodes">${w.node_count} Nodes</div>
                </div>
            </div>`).join('');
    } catch(e) {
        list.innerHTML = '<div class="wf-empty">❌ Server nicht erreichbar</div>';
    }
}

async function selectWorkflow(name, el) {
    document.querySelectorAll('.wf-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
    document.getElementById('wf-placeholder').style.display = 'none';
    document.getElementById('wf-editor').style.display = 'flex';
    document.getElementById('wf-name-title').textContent = el.querySelector('.wf-item-name').textContent;
    const _paBtn = document.getElementById('pa-trigger-btn');
    if (_paBtn) _paBtn.style.display = 'flex';

    const r = await fetch(`/api/workflows/${name}`);
    const d = await r.json();
    currentWorkflow = d.workflow;
    currentPatches  = {};
    img2imgState    = { enabled: false, imageFile: null, imageDataUrl: null, denoise: 0.75 };
    extraLoras      = [];
    removedLoras    = new Set();
    _extraLoraUid   = 0;
    refinerState    = { enabled: false, workflow: null, model: null, denoise: 0.5 };
    artistState     = { enabled: false, model_type: 'illustrious', artist_name: '' };
    _allArtists     = [];
    parseAndRenderWorkflow(currentWorkflow);
}

// ── Parser ────────────────────────────────────────────────────────────────────
function parseAndRenderWorkflow(wf) {
    workflowMeta = { prompts: [], samplers: [], latents: [], models: [], loras: [], existingImg2Img: [] };

    // Find KSampler → trace positive/negative refs
    for (const [id, node] of Object.entries(wf)) {
        if (node.class_type === 'KSampler' || node.class_type === 'KSamplerAdvanced') {
            const posId  = node.inputs.positive?.[0];
            const negId  = node.inputs.negative?.[0];
            workflowMeta.samplers.push({ id, inputs: node.inputs });

            if (posId && wf[posId]?.class_type === 'CLIPTextEncode') {
                workflowMeta.prompts.push({ id: posId, role: 'positive',
                    text: wf[posId].inputs.text || '',
                    title: wf[posId]._meta?.title || 'Positive Prompt' });
            }
            if (negId && wf[negId]?.class_type === 'CLIPTextEncode') {
                workflowMeta.prompts.push({ id: negId, role: 'negative',
                    text: wf[negId].inputs.text || '',
                    title: wf[negId]._meta?.title || 'Negative Prompt' });
            }

            // Detect existing LoadImage → VAEEncode → KSampler pattern
            const latentInput = node.inputs?.latent_image;
            if (Array.isArray(latentInput)) {
                const encId   = String(latentInput[0]);
                const encNode = wf[encId];
                if (encNode?.class_type === 'VAEEncode') {
                    const pixels = encNode.inputs?.pixels;
                    if (Array.isArray(pixels)) {
                        const loadId   = String(pixels[0]);
                        const loadNode = wf[loadId];
                        if (loadNode?.class_type === 'LoadImage') {
                            workflowMeta.existingImg2Img.push({ loadId, encId, samplerId: id });
                        }
                    }
                }
            }
        }
        if (node.class_type === 'FaceDetailer') {
            const posId = node.inputs.positive?.[0];
            if (posId && wf[posId]?.class_type === 'CLIPTextEncode') {
                const already = workflowMeta.prompts.find(p => p.id === posId);
                if (!already) workflowMeta.prompts.push({ id: posId, role: 'positive',
                    text: wf[posId].inputs.text || '', title: 'FaceDetailer Prompt', hidden: true });
            }
        }
        if (node.class_type === 'EmptyLatentImage') {
            workflowMeta.latents.push({ id, w: node.inputs.width, h: node.inputs.height });
        }
        if (['UNETLoader','CheckpointLoaderSimple'].includes(node.class_type)) {
            const field = node.class_type === 'UNETLoader' ? 'unet_name' : 'ckpt_name';
            workflowMeta.models.push({ id, field, value: node.inputs[field], type: node.class_type });
        }
        if (node.class_type === 'LoraLoader') {
            workflowMeta.loras.push({ id,
                name: node.inputs.lora_name,
                strength_model: node.inputs.strength_model ?? 1,
                strength_clip:  node.inputs.strength_clip  ?? 1 });
        }
    }

    renderEditor();
}

// ── Render UI ─────────────────────────────────────────────────────────────────
function renderEditor() {
    const container = document.getElementById('wf-params');
    container.innerHTML = '';

    // ── Prompts
    const mainPos = workflowMeta.prompts.filter(p => p.role === 'positive' && !p.hidden);
    const mainNeg = workflowMeta.prompts.filter(p => p.role === 'negative' && !p.hidden);

    if (mainPos.length) {
        container.appendChild(section('✏️ Positive Prompt', mainPos.map(p => `
            <textarea class="wf-textarea" rows="4"
                onchange="patch('${p.id}','text',this.value)"
                oninput="syncLinkedPrompts('${p.id}',this.value)"
            >${p.text}</textarea>`).join('')));
    }
    if (mainNeg.length) {
        container.appendChild(section('🚫 Negative Prompt', mainNeg.map(p => `
            <textarea class="wf-textarea wf-textarea-neg" rows="3"
                onchange="patch('${p.id}','text',this.value)"
            >${p.text}</textarea>`).join('')));
    }

    // ── KSampler settings
    workflowMeta.samplers.forEach(s => {
        const inp = s.inputs;
        container.appendChild(section('🎛️ Sampler', `
            <div class="wf-grid-2">
                <div class="wf-field">
                    <label>Steps</label>
                    <div class="wf-slider-row">
                        <input type="range" min="1" max="60" step="1" value="${inp.steps}"
                            oninput="this.nextElementSibling.textContent=this.value; patch('${s.id}','steps',+this.value)">
                        <span>${inp.steps}</span>
                    </div>
                </div>
                <div class="wf-field">
                    <label>CFG</label>
                    <div class="wf-slider-row">
                        <input type="range" min="0" max="20" step="0.1" value="${inp.cfg}"
                            oninput="this.nextElementSibling.textContent=(+this.value).toFixed(1); patch('${s.id}','cfg',+this.value)">
                        <span>${(+inp.cfg).toFixed(1)}</span>
                    </div>
                </div>
                <div class="wf-field">
                    <label>Sampler</label>
                    <select onchange="patch('${s.id}','sampler_name',this.value)">
                        ${SAMPLERS.map(n=>`<option ${n===inp.sampler_name?'selected':''}>${n}</option>`).join('')}
                    </select>
                </div>
                <div class="wf-field">
                    <label>Scheduler</label>
                    <select onchange="patch('${s.id}','scheduler',this.value)">
                        ${SCHEDULERS.map(n=>`<option ${n===inp.scheduler?'selected':''}>${n}</option>`).join('')}
                    </select>
                </div>
                <div class="wf-field wf-field-wide">
                    <label>Seed</label>
                    <div class="wf-seed-row">
                        <input type="number" class="wf-seed-input" value="${inp.seed}"
                            onchange="patch('${s.id}','seed',+this.value)" id="seed-${s.id}">
                        <button class="wf-seed-btn" onclick="randomSeed('${s.id}')">🎲</button>
                        <button class="wf-seed-btn" onclick="patch('${s.id}','seed',-1); document.getElementById('seed-${s.id}').value=-1">∞</button>
                    </div>
                </div>
            </div>`));
    });

    // ── Image Size
    if (workflowMeta.latents.length) {
        const l = workflowMeta.latents[0];
        const currentAR = Object.entries(ASPECT_SIZES).find(([,v])=>v[0]===l.w&&v[1]===l.h)?.[0] || 'custom';
        container.appendChild(section('📐 Bildgröße', `
            <div class="wf-aspect-row">
                ${Object.entries(ASPECT_SIZES).map(([ar,[w,h]])=>`
                    <button class="wf-aspect-btn ${ar===currentAR?'active':''}"
                        onclick="setAspect('${ar}',${w},${h},this)">${ar}<span>${w}×${h}</span>
                    </button>`).join('')}
                <button class="wf-aspect-btn ${currentAR==='custom'?'active':''}" onclick="showCustomSize(this)">
                    custom<span id="custom-size-label">${l.w}×${l.h}</span>
                </button>
            </div>
            <div class="wf-custom-size" id="custom-size-fields" style="display:none">
                <input type="number" placeholder="Width" value="${l.w}" min="64" step="64"
                    onchange="patchAllLatents('width',+this.value)">
                <span>×</span>
                <input type="number" placeholder="Height" value="${l.h}" min="64" step="64"
                    onchange="patchAllLatents('height',+this.value)">
            </div>`));
    }

    // ── Model
    if (workflowMeta.models.length) {
        container.appendChild(section('🤖 Modell', workflowMeta.models.map(m => `
            <div class="wf-field">
                <label>${m.type === 'UNETLoader' ? 'UNET' : 'Checkpoint'}</label>
                <div class="wf-model-select" id="model-select-${m.id}">
                    <div class="wf-model-current" onclick="toggleModelList('${m.id}')">
                        <span class="wf-model-current-name">${m.value.split('\\').pop().split('/').pop()}</span>
                        <span class="wf-model-arrow">▾</span>
                    </div>
                    <div class="wf-model-list" id="model-list-${m.id}" style="display:none">
                        <div class="wf-model-loading">↻ Lade...</div>
                    </div>
                </div>
            </div>`).join('')));
        // Modelle laden
        loadModelOptions();
    }

    // ── LoRAs
    {
        const loraSection = section('🎨 LoRAs', '');
        loraSection.id = 'wf-loras-section';
        renderLoraSection(loraSection);
        container.appendChild(loraSection);
        loadLoraOptions();
    }

    // ── Img2Img
    if (workflowMeta.samplers.length) {
        const isExisting = workflowMeta.existingImg2Img.length > 0;
        // Auto-activate if workflow already has LoadImage structure
        if (isExisting && !img2imgState.enabled) img2imgState.enabled = true;

        const hint = isExisting
            ? '<div class="wf-i2i-hint">⚠️ Workflow nutzt bereits ein Eingabebild — neues Bild einlegen zum Ersetzen</div>'
            : '';

        const sec = section('🖼️ Image to Image', `
            ${hint}
            <div class="wf-i2i-toggle-row">
                <label class="wf-toggle">
                    <input type="checkbox" id="i2i-toggle" ${img2imgState.enabled ? 'checked' : ''}
                        onchange="toggleImg2Img(this.checked)">
                    <span class="wf-toggle-track"></span>
                </label>
                <span class="wf-i2i-toggle-label">Enable Img2Img</span>
            </div>
            <div id="i2i-controls" style="display:${img2imgState.enabled ? 'block' : 'none'}">
                <div class="wf-i2i-drop" id="i2i-drop"
                    ondragover="event.preventDefault(); this.classList.add('drag-over')"
                    ondragleave="this.classList.remove('drag-over')"
                    ondrop="handleImg2ImgDrop(event)"
                    onclick="document.getElementById('i2i-file').click()">
                    <div id="i2i-preview-wrap">
                        ${img2imgState.imageDataUrl
            ? `<img id="i2i-preview" src="${img2imgState.imageDataUrl}" class="wf-i2i-preview-img">`
            : `<div class="wf-i2i-drop-hint"><span>🖼️</span><span>Bild hierher ziehen oder klicken</span></div>`}
                    </div>
                    <input type="file" id="i2i-file" accept="image/*" style="display:none"
                        onchange="loadImg2ImgFile(this.files[0])">
                </div>
                <div class="wf-field" style="margin-top:10px">
                    <label>Denoise Strength</label>
                    <div class="wf-slider-row">
                        <input type="range" min="0" max="1" step="0.01" value="${img2imgState.denoise}"
                            oninput="img2imgState.denoise=+this.value; this.nextElementSibling.textContent=(+this.value).toFixed(2)">
                        <span>${img2imgState.denoise.toFixed(2)}</span>
                    </div>
                </div>
            </div>`);
        container.appendChild(sec);
    }

    // ── Refiner
    if (workflowMeta.samplers.length) {
        const refSec = section('✨ Refiner', `
            <div class="wf-i2i-toggle-row">
                <label class="wf-toggle">
                    <input type="checkbox" id="refiner-toggle" ${refinerState.enabled ? 'checked' : ''}
                        onchange="toggleRefiner(this.checked)">
                    <span class="wf-toggle-track"></span>
                </label>
                <span class="wf-i2i-toggle-label">Refiner aktivieren</span>
            </div>
            <div id="refiner-controls" style="display:${refinerState.enabled ? 'block' : 'none'}">
                <div class="wf-field" style="margin-bottom:10px">
                    <label>Refiner Workflow</label>
                    <select class="wf-style-dropdown" style="width:100%" id="refiner-wf-select"
                        onchange="refinerState.workflow=this.value||null">
                        <option value="">— Workflow wählen —</option>
                    </select>
                </div>
                <div class="wf-field" style="margin-bottom:10px">
                    <label>Refiner Modell</label>
                    <div class="wf-model-select" id="refiner-model-select">
                        <div class="wf-model-current" onclick="toggleRefinerModelList()">
                            <span class="wf-model-current-name" id="refiner-model-name">${refinerState.model ? refinerState.model.split('\\').pop().split('/').pop() : '— Modell wählen —'}</span>
                            <span class="wf-model-arrow" id="refiner-model-arrow">▾</span>
                        </div>
                        <div class="wf-model-list" id="refiner-model-list" style="display:none">
                            <div class="wf-model-loading">↻ Lade...</div>
                        </div>
                    </div>
                </div>
                <div class="wf-field">
                    <label>Denoise</label>
                    <div class="wf-slider-row">
                        <input type="range" min="0" max="1" step="0.01" value="${refinerState.denoise}"
                            oninput="refinerState.denoise=+this.value; this.nextElementSibling.textContent=(+this.value).toFixed(2)">
                        <span>${refinerState.denoise.toFixed(2)}</span>
                    </div>
                </div>
            </div>`);
        container.appendChild(refSec);
        loadRefinerWorkflows();
        loadRefinerModels();
    }

    // ── Prompt Critic
    const criticSec = section('🔍 Prompt Critic', `
        <div class="wf-i2i-toggle-row">
            <label class="wf-toggle">
                <input type="checkbox" id="critic-toggle" ${criticState.enabled ? 'checked' : ''}
                    onchange="criticState.enabled=this.checked">
                <span class="wf-toggle-track"></span>
            </label>
            <span class="wf-i2i-toggle-label">Prompt nach Generierung analysieren</span>
        </div>`);
    container.appendChild(criticSec);

    // ── Artist Mode
    {
        const artistSec = section('🎨 Artist Mode', `
            <div class="wf-i2i-toggle-row">
                <label class="wf-toggle">
                    <input type="checkbox" id="artist-toggle" ${artistState.enabled ? 'checked' : ''}
                        onchange="toggleArtistMode(this.checked)">
                    <span class="wf-toggle-track"></span>
                </label>
                <span class="wf-i2i-toggle-label">In Artist-Ordner speichern</span>
            </div>
            <div id="artist-controls" style="display:${artistState.enabled ? 'block' : 'none'};margin-top:10px">
                <div class="wf-field" style="margin-bottom:10px">
                    <label>Modell-Typ</label>
                    <div style="display:flex;gap:6px;margin-top:4px">
                        <button class="wf-aspect-btn ${artistState.model_type==='illustrious'?'active':''}"
                            id="artist-model-illustrious"
                            onclick="setArtistModelType('illustrious')" style="flex:1;font-size:0.75rem">Illustrious</button>
                        <button class="wf-aspect-btn ${artistState.model_type==='anima'?'active':''}"
                            id="artist-model-anima"
                            onclick="setArtistModelType('anima')" style="flex:1;font-size:0.75rem">Anima</button>
                    </div>
                </div>
                <div class="wf-field">
                    <label style="display:flex;align-items:center;justify-content:space-between">
                        <span>Artist</span>
                        <button onclick="surpriseArtist()" style="background:none;border:1px solid var(--border);border-radius:6px;padding:2px 8px;font-size:0.72rem;color:var(--muted);cursor:pointer;font-family:var(--sans)" onmouseover="this.style.borderColor='var(--accent)';this.style.color='var(--accent)'" onmouseout="this.style.borderColor='var(--border)';this.style.color='var(--muted)'">🎲 Surprise Me</button>
                    </label>
                    <input type="text" id="artist-search" placeholder="Suchen..."
                        class="wf-seed-input" style="width:100%;margin-bottom:6px;box-sizing:border-box"
                        oninput="filterArtistList(this.value)"
                        value="${artistState.artist_name}">
                    <div id="artist-list"
                        style="max-height:150px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;background:var(--bg)">
                        <div style="padding:8px 12px;color:var(--muted);font-size:0.78rem">↻ Lade...</div>
                    </div>
                    <div id="artist-selected" style="font-size:0.75rem;color:var(--accent);margin-top:5px">
                        ${artistState.artist_name ? `✓ ${artistState.artist_name}` : 'Kein Artist gewählt'}
                    </div>
                </div>
            </div>`);
        container.appendChild(artistSec);
        if (artistState.enabled) loadArtistList();
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function section(title, content) {
    const div = document.createElement('div');
    div.className = 'wf-section';
    div.innerHTML = `<div class="wf-section-title">${title}</div>${typeof content === 'string' ? content : ''}`;
    if (typeof content !== 'string') div.appendChild(content);
    return div;
}

function patch(nodeId, field, value) {
    if (!currentPatches[nodeId]) currentPatches[nodeId] = {};
    currentPatches[nodeId][field] = value;
}

function syncLinkedPrompts(sourceId, value) {
    // Sync hidden linked prompts (e.g. FaceDetailer positive)
    workflowMeta.prompts
        .filter(p => p.hidden && p.role === 'positive')
        .forEach(p => patch(p.id, 'text', value));
}

function patchAllLatents(field, value) {
    workflowMeta.latents.forEach(l => patch(l.id, field, value));
    document.getElementById('custom-size-label').textContent =
        `${currentPatches[workflowMeta.latents[0]?.id]?.width || workflowMeta.latents[0]?.w}×${currentPatches[workflowMeta.latents[0]?.id]?.height || workflowMeta.latents[0]?.h}`;
}

function randomSeed(nodeId) {
    const seed = Math.floor(Math.random() * 2**32);
    patch(nodeId, 'seed', seed);
    document.getElementById(`seed-${nodeId}`).value = seed;
}

function setAspect(ar, w, h, btn) {
    document.querySelectorAll('.wf-aspect-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('custom-size-fields').style.display = 'none';
    workflowMeta.latents.forEach(l => { patch(l.id,'width',w); patch(l.id,'height',h); });
}

function showCustomSize(btn) {
    document.querySelectorAll('.wf-aspect-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('custom-size-fields').style.display = 'flex';
}

function toggleImg2Img(enabled) {
    img2imgState.enabled = enabled;
    document.getElementById('i2i-controls').style.display = enabled ? 'block' : 'none';
}

function handleImg2ImgDrop(e) {
    e.preventDefault();
    document.getElementById('i2i-drop').classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) loadImg2ImgFile(file);
}

function loadImg2ImgFile(file) {
    if (!file) return;
    img2imgState.imageFile = file;

    // Vorschau laden
    const reader = new FileReader();
    reader.onload = ev => {
        img2imgState.imageDataUrl = ev.target.result;
        const wrap = document.getElementById('i2i-preview-wrap');
        wrap.innerHTML = `<img id="i2i-preview" src="${ev.target.result}" class="wf-i2i-preview-img">`;
    };
    reader.readAsDataURL(file);

    // Nur PNGs können einen eingebetteten Workflow haben
    if (!file.name.toLowerCase().endsWith('.png') && file.type !== 'image/png') return;

    const fd = new FormData();
    fd.append('file', file);
    fetch('/api/workflows/extract-from-image', { method: 'POST', body: fd })
        .then(r => r.json())
        .then(d => {
            if (!d.workflow) return;
            const prompts = extractPromptsFromWorkflow(d.workflow);
            if (!prompts.positive && !prompts.negative) return;
            applyExtractedPrompts(prompts);
        })
        .catch(() => {}); // still silently — image already loaded
}

function extractPromptsFromWorkflow(wf) {
    let positive = '', negative = '';
    for (const node of Object.values(wf)) {
        if (node.class_type !== 'KSampler' && node.class_type !== 'KSamplerAdvanced') continue;
        const posId = node.inputs?.positive?.[0];
        const negId = node.inputs?.negative?.[0];
        if (posId && wf[posId]?.class_type === 'CLIPTextEncode')
            positive = wf[posId].inputs?.text || '';
        if (negId && wf[negId]?.class_type === 'CLIPTextEncode')
            negative = wf[negId].inputs?.text || '';
        break; // ersten KSampler verwenden
    }
    return { positive, negative };
}

function applyExtractedPrompts({ positive, negative }) {
    // Positive Prompts patchen
    if (positive) {
        workflowMeta.prompts
            .filter(p => p.role === 'positive')
            .forEach(p => {
                patch(p.id, 'text', positive);
                const ta = document.querySelector(`.wf-textarea:not(.wf-textarea-neg)`);
                if (ta) ta.value = positive;
            });
        syncLinkedPrompts(workflowMeta.prompts.find(p => p.role === 'positive' && !p.hidden)?.id, positive);
    }
    // Negative Prompts patchen
    if (negative) {
        workflowMeta.prompts
            .filter(p => p.role === 'negative')
            .forEach(p => {
                patch(p.id, 'text', negative);
                const ta = document.querySelector(`.wf-textarea-neg`);
                if (ta) ta.value = negative;
            });
    }
    // Badge anzeigen
    const wrap = document.getElementById('i2i-preview-wrap');
    if (wrap) {
        const badge = document.createElement('div');
        badge.className = 'wf-i2i-prompt-badge';
        badge.textContent = '✓ Prompt übernommen';
        wrap.appendChild(badge);
        setTimeout(() => badge.remove(), 3000);
    }
}

// ── LoRA Dynamic Management ────────────────────────────────────────────────────

function renderLoraSection(container) {
    container.innerHTML = `<div class="wf-section-title">🎨 LoRAs</div>`;

    // Original LoRAs (aus Workflow)
    workflowMeta.loras.forEach(l => {
        if (removedLoras.has(l.id)) return;
        container.appendChild(buildLoraRow({
            id:             l.id,
            isExtra:        false,
            displayName:    l.name.split('\\').pop().split('/').pop(),
            strength_model: l.strength_model,
            strength_clip:  l.strength_clip
        }));
    });

    // Extra hinzugefügte LoRAs
    extraLoras.forEach(l => {
        container.appendChild(buildLoraRow({
            id:             `extra_${l.uid}`,
            isExtra:        true,
            uid:            l.uid,
            displayName:    l.name ? l.name.split('\\').pop().split('/').pop() : '— Kein LoRA gewählt —',
            strength_model: l.strength_model,
            strength_clip:  l.strength_clip
        }));
    });

    // Add-Button
    const addBtn = document.createElement('button');
    addBtn.className = 'wf-lora-add-btn';
    addBtn.textContent = '＋ LoRA hinzufügen';
    addBtn.onclick = addExtraLora;
    container.appendChild(addBtn);
}

function buildLoraRow({ id, isExtra, uid, displayName, strength_model, strength_clip }) {
    const div = document.createElement('div');
    div.className = 'wf-lora-row';
    div.id = `lora-row-${id}`;
    div.innerHTML = `
        <div class="wf-lora-row-header">
            <div class="wf-model-select" id="lora-select-${id}">
                <div class="wf-model-current" onclick="toggleLoraList('${id}')">
                    <span class="wf-model-current-name">${displayName}</span>
                    <span class="wf-model-arrow">▾</span>
                </div>
                <div class="wf-model-list" id="lora-list-${id}" style="display:none">
                    <div class="wf-model-loading">↻ Lade...</div>
                </div>
            </div>
            <button class="wf-lora-remove-btn" onclick="${isExtra ? `removeExtraLora(${uid})` : `removeOriginalLora('${id}')`}" title="LoRA entfernen">✕</button>
        </div>
        <div class="wf-lora-strengths">
            <div class="wf-field">
                <label>Model</label>
                <div class="wf-slider-row">
                    <input type="range" min="0" max="2" step="0.05" value="${strength_model}"
                        oninput="this.nextElementSibling.textContent=(+this.value).toFixed(2); ${isExtra ? `updateExtraLora(${uid},'strength_model',+this.value)` : `patch('${id}','strength_model',+this.value)`}">
                    <span>${(+strength_model).toFixed(2)}</span>
                </div>
            </div>
            <div class="wf-field">
                <label>CLIP</label>
                <div class="wf-slider-row">
                    <input type="range" min="0" max="2" step="0.05" value="${strength_clip}"
                        oninput="this.nextElementSibling.textContent=(+this.value).toFixed(2); ${isExtra ? `updateExtraLora(${uid},'strength_clip',+this.value)` : `patch('${id}','strength_clip',+this.value)`}">
                    <span>${(+strength_clip).toFixed(2)}</span>
                </div>
            </div>
        </div>`;
    return div;
}

function addExtraLora() {
    const uid = _extraLoraUid++;
    extraLoras.push({ uid, name: '', strength_model: 1, strength_clip: 1 });
    const sec = document.getElementById('wf-loras-section');
    if (sec) renderLoraSection(sec);
    // Direkt Liste öffnen damit User sofort auswählen kann
    setTimeout(() => toggleLoraList(`extra_${uid}`), 50);
}

function removeOriginalLora(nodeId) {
    removedLoras.add(nodeId);
    document.getElementById(`lora-row-${nodeId}`)?.remove();
}

function removeExtraLora(uid) {
    extraLoras = extraLoras.filter(l => l.uid !== uid);
    document.getElementById(`lora-row-extra_${uid}`)?.remove();
}

function updateExtraLora(uid, field, value) {
    const l = extraLoras.find(l => l.uid === uid);
    if (l) l[field] = value;
}

// Override selectLora to handle extra loras
function selectLora(el) {
    const nodeId   = el.dataset.node;
    const fullPath = allLoras[parseInt(el.dataset.index)];

    if (nodeId.startsWith('extra_')) {
        const uid = parseInt(nodeId.replace('extra_', ''));
        const l = extraLoras.find(l => l.uid === uid);
        if (l) l.name = fullPath;
    } else {
        patch(nodeId, 'lora_name', fullPath);
    }

    document.querySelector(`#lora-select-${nodeId} .wf-model-current-name`).textContent = el.textContent;
    document.getElementById(`lora-list-${nodeId}`).style.display = 'none';
    document.querySelector(`#lora-select-${nodeId} .wf-model-arrow`).textContent = '▾';
}

// ── Refiner Helpers ────────────────────────────────────────────────────────────

function toggleRefiner(enabled) {
    refinerState.enabled = enabled;
    document.getElementById('refiner-controls').style.display = enabled ? 'block' : 'none';
}

async function loadRefinerWorkflows() {
    const sel = document.getElementById('refiner-wf-select');
    if (!sel) return;
    try {
        const r = await fetch('/api/workflows');
        const d = await r.json();
        (d.workflows || []).forEach(w => {
            const opt = document.createElement('option');
            opt.value = w.name;
            opt.textContent = w.display_name;
            if (w.name === refinerState.workflow) opt.selected = true;
            sel.appendChild(opt);
        });
    } catch(e) {}
}

let allRefinerModels = [];

async function loadRefinerModels() {
    try {
        const r = await fetch('/api/comfy/all-checkpoints');
        const d = await r.json();
        allRefinerModels = [...(d.checkpoints || []), ...(d.unets || [])];
    } catch(e) {}
}

function toggleRefinerModelList() {
    const list  = document.getElementById('refiner-model-list');
    const arrow = document.getElementById('refiner-model-arrow');
    const isOpen = list.style.display !== 'none';
    document.querySelectorAll('.wf-model-list').forEach(l => l.style.display = 'none');
    document.querySelectorAll('.wf-model-arrow').forEach(a => a.textContent = '▾');
    if (isOpen) return;

    list.innerHTML = allRefinerModels.length
        ? allRefinerModels.map((m, i) => {
            const short = m.split('\\').pop().split('/').pop();
            return `<div class="wf-model-item" onclick="selectRefinerModel(${i})" title="${m}">${short}</div>`;
        }).join('')
        : '<div class="wf-model-loading">Keine Modelle gefunden</div>';
    list.style.display = 'block';
    arrow.textContent = '▴';
}

function selectRefinerModel(index) {
    const fullPath = allRefinerModels[index];
    refinerState.model = fullPath;
    document.getElementById('refiner-model-name').textContent = fullPath.split('\\').pop().split('/').pop();
    document.getElementById('refiner-model-list').style.display = 'none';
    document.getElementById('refiner-model-arrow').textContent = '▾';
}

// ── Artist Mode Helpers ────────────────────────────────────────────────────────

function toggleArtistMode(enabled) {
    artistState.enabled = enabled;
    document.getElementById('artist-controls').style.display = enabled ? 'block' : 'none';
    if (enabled) loadArtistList();
}

function setArtistModelType(type) {
    artistState.model_type = type;
    artistState.artist_name = '';
    document.getElementById('artist-model-illustrious').classList.toggle('active', type === 'illustrious');
    document.getElementById('artist-model-anima').classList.toggle('active', type === 'anima');
    const searchEl = document.getElementById('artist-search');
    const selEl    = document.getElementById('artist-selected');
    if (searchEl) searchEl.value = '';
    if (selEl)    selEl.textContent = 'Kein Artist gewählt';
    loadArtistList();
}

async function loadArtistList() {
    const listEl = document.getElementById('artist-list');
    if (!listEl) return;
    listEl.innerHTML = '<div style="padding:8px 12px;color:var(--muted);font-size:0.78rem">↻ Lade...</div>';
    try {
        const r = await fetch(`/api/reference/artists?model=${artistState.model_type}`);
        const d = await r.json();
        _allArtists = d.artists || [];
        renderArtistList(_allArtists);
    } catch(e) {
        if (listEl) listEl.innerHTML = '<div style="padding:8px 12px;color:var(--muted);font-size:0.78rem">❌ Laden fehlgeschlagen</div>';
    }
}

function renderArtistList(artists) {
    const listEl = document.getElementById('artist-list');
    if (!listEl) return;
    if (!artists.length) {
        listEl.innerHTML = '<div style="padding:8px 12px;color:var(--muted);font-size:0.78rem">Keine Artists gefunden</div>';
        return;
    }
    listEl.innerHTML = artists.map(a => `
        <div class="wf-model-item" onclick="selectArtist('${a.name.replace(/'/g, "\\'")}')"
             style="${a.name === artistState.artist_name ? 'background:rgba(108,99,255,.15);color:var(--accent)' : ''}">
            ${a.name}
            <span style="font-size:0.68rem;color:var(--muted);margin-left:6px">${a.img_count} Bilder</span>
        </div>`).join('');
}

function filterArtistList(q) {
    const filtered = _allArtists.filter(a => a.name.toLowerCase().includes(q.toLowerCase()));
    renderArtistList(filtered);
}

function selectArtist(name) {
    artistState.artist_name = name;
    const searchEl = document.getElementById('artist-search');
    const selEl    = document.getElementById('artist-selected');
    if (searchEl) searchEl.value = name;
    if (selEl)    selEl.textContent = `✓ ${name}`;
    renderArtistList(_allArtists);
}

function surpriseArtist() {
    if (!_allArtists.length) { alert('Bitte zuerst Artist Mode aktivieren.'); return; }
    const pick = _allArtists[Math.floor(Math.random() * _allArtists.length)];
    selectArtist(pick.name);
}

// ── Build final workflow & run ────────────────────────────────────────────────
// ── buildFinalWorkflow helpers ────────────────────────────────────────────────

function _wf_applyPatches(wf) {
    for (const [nodeId, fields] of Object.entries(currentPatches)) {
        if (!wf[nodeId]) continue;
        for (const [field, value] of Object.entries(fields)) {
            wf[nodeId].inputs[field] = field === 'seed' && value === -1
                ? Math.floor(Math.random() * 2**32) : value;
        }
    }
}

function _wf_bridgeRemovedLoras(wf) {
    for (const removedId of removedLoras) {
        const removedNode = wf[removedId];
        if (!removedNode) continue;
        const modelSrc = removedNode.inputs?.model;
        const clipSrc  = removedNode.inputs?.clip;
        for (const node of Object.values(wf)) {
            if (!node.inputs) continue;
            for (const [field, val] of Object.entries(node.inputs)) {
                if (Array.isArray(val) && String(val[0]) === removedId)
                    node.inputs[field] = val[1] === 0 ? modelSrc : clipSrc;
            }
        }
        delete wf[removedId];
    }
}

function _wf_injectExtraLoras(wf) {
    const validExtras = extraLoras.filter(l => l.name);
    if (!validExtras.length) return;

    let modelRef = null, clipRef = null;
    for (const node of Object.values(wf)) {
        if (node.class_type === 'KSampler' || node.class_type === 'KSamplerAdvanced') {
            modelRef = node.inputs.model; break;
        }
    }
    for (const node of Object.values(wf)) {
        if (node.class_type === 'CLIPTextEncode' && Array.isArray(node.inputs?.clip)) {
            clipRef = node.inputs.clip; break;
        }
    }
    if (!modelRef || !clipRef) return;

    let prevModelRef = modelRef, prevClipRef = clipRef;
    validExtras.forEach((l, i) => {
        const newId = `wf_extra_lora_${i}`;
        wf[newId] = {
            class_type: 'LoraLoader', _meta: { title: `Extra LoRA ${i + 1}` },
            inputs: { lora_name: l.name, strength_model: l.strength_model,
                      strength_clip: l.strength_clip, model: prevModelRef, clip: prevClipRef }
        };
        prevModelRef = [newId, 0];
        prevClipRef  = [newId, 1];
    });
    for (const node of Object.values(wf)) {
        if (node.class_type === 'KSampler' || node.class_type === 'KSamplerAdvanced')
            node.inputs.model = prevModelRef;
        if (node.class_type === 'CLIPTextEncode' &&
            Array.isArray(node.inputs?.clip) &&
            String(node.inputs.clip[0]) === String(clipRef[0]))
            node.inputs.clip = prevClipRef;
    }
}

function _wf_prependArtistTag(wf) {
    if (!artistState.enabled || !artistState.artist_name) return;
    const tag = artistState.artist_name.trim();
    workflowMeta.prompts
        .filter(p => p.role === 'positive' && !p.hidden)
        .forEach(p => {
            const current = wf[p.id]?.inputs?.text || '';
            if (!current.startsWith(tag)) wf[p.id].inputs.text = `${tag}, ${current}`;
        });
}

function buildFinalWorkflow() {
    const wf = JSON.parse(JSON.stringify(currentWorkflow));
    _wf_applyPatches(wf);
    _wf_bridgeRemovedLoras(wf);
    _wf_injectExtraLoras(wf);
    _wf_prependArtistTag(wf);
    return wf;
}

async function runWorkflow() {
    if (!currentWorkflow) return;

    // Img2Img-Validierung
    if (img2imgState.enabled && !img2imgState.imageDataUrl) {
        const msg = workflowMeta.existingImg2Img.length
            ? '⚠️ Workflow erwartet ein Eingabebild — bitte in der Img2Img-Zone einlegen.'
            : '⚠️ Img2Img aktiv, aber kein Bild geladen.';
        document.getElementById('wf-output').innerHTML = `<div class="wf-error">${msg}</div>`;
        return;
    }

    const btn = document.getElementById('run-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Generiere...';
    document.getElementById('wf-output').innerHTML = '<div class="wf-generating"><div class="wf-spinner"></div><span>Workflow läuft...</span></div>';

    const finalWf = buildFinalWorkflow();

    // Img2Img-Payload bauen: DataURL → reines Base64
    let img2imgPayload = null;
    if (img2imgState.enabled && img2imgState.imageDataUrl) {
        const b64 = img2imgState.imageDataUrl.split(',')[1];
        img2imgPayload = { image_b64: b64, denoise: img2imgState.denoise };
    }

    const body = { workflow: finalWf };
    if (img2imgPayload) body.img2img = img2imgPayload;
    if (refinerState.enabled && refinerState.workflow) {
        body.refiner = {
            workflow: refinerState.workflow,
            model:    refinerState.model,
            denoise:  refinerState.denoise
        };
    }
    if (artistState.enabled && artistState.artist_name) {
        body.artist_mode = { model_type: artistState.model_type, artist_name: artistState.artist_name };
    }

    try {
        const resp = await fetch('/api/workflows/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        const reader = resp.body.getReader();
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
                const data = JSON.parse(line.slice(6));

                if (data.type === 'image_preview') {
                    document.getElementById('wf-output').innerHTML = `
                        <div class="wf-result">
                            <img src="data:image/jpeg;base64,${data.b64}" style="opacity:0.6;filter:blur(2px)" class="preview-img">
                        </div>`;
                } else if (data.type === 'image_progress') {
                    const prev = document.querySelector('.preview-img');
                    if (prev) prev.style.opacity = 0.4 + (data.pct / 100) * 0.6;
                } else if (data.type === 'image_done') {
                    document.getElementById('wf-output').innerHTML = `
                        <div class="wf-result" id="wf-result-main">
                            <div class="wf-result-label">🖼️ Generiert</div>
                            <img src="data:image/png;base64,${data.image_b64}" onclick="this.classList.toggle('fullsize')" title="Klicken zum Vergrößern">
                            <div class="wf-result-actions">
                                <a href="data:image/png;base64,${data.image_b64}" download="${data.filename || 'output.png'}" class="wf-dl-btn">⬇ Speichern</a>
                            </div>
                        </div>`;
                    if (criticState.enabled) runPromptCritic();
                } else if (data.type === 'refiner_done') {
                    const out = document.getElementById('wf-output');
                    const refDiv = document.createElement('div');
                    refDiv.className = 'wf-result';
                    refDiv.innerHTML = `
                        <div class="wf-result-label">✨ Refined</div>
                        <img src="data:image/png;base64,${data.image_b64}" onclick="this.classList.toggle('fullsize')" title="Klicken zum Vergrößern">
                        <div class="wf-result-actions">
                            <a href="data:image/png;base64,${data.image_b64}" download="${data.filename || 'refined.png'}" class="wf-dl-btn">⬇ Speichern</a>
                        </div>`;
                    out.appendChild(refDiv);
                } else if (data.type === 'step' && data.status === 'error') {
                    document.getElementById('wf-output').innerHTML = `<div class="wf-error">❌ ${data.text}</div>`;
                }
            }
        }
    } catch(e) {
        document.getElementById('wf-output').innerHTML = `<div class="wf-error">❌ ${e.message}</div>`;
    }

    btn.disabled = false;
    btn.textContent = '▶ Generieren';
}

// ── Model & LoRA Selection ────────────────────────────────────────────────────
let allCheckpoints = [];
let allUnets = [];
let allLoras = [];

async function loadModelOptions() {
    try {
        const r = await fetch('/api/comfy/all-checkpoints');
        const d = await r.json();
        allCheckpoints = d.checkpoints || [];
        allUnets = d.unets || [];
    } catch(e) { console.error('Modelle laden fehlgeschlagen:', e); }
}

async function loadLoraOptions() {
    try {
        const r = await fetch('/api/comfy/all-loras');
        const d = await r.json();
        allLoras = d.loras || [];
    } catch(e) { console.error('LoRAs laden fehlgeschlagen:', e); }
}

function toggleModelList(nodeId) {
    const listEl = document.getElementById(`model-list-${nodeId}`);
    const isOpen = listEl.style.display !== 'none';
    document.querySelectorAll('.wf-model-list').forEach(l => l.style.display = 'none');
    document.querySelectorAll('.wf-model-arrow').forEach(a => a.textContent = '▾');
    if (isOpen) return;

    const meta = workflowMeta.models.find(m => m.id === nodeId);
    const items = meta?.type === 'UNETLoader' ? allUnets : allCheckpoints;
    const field = meta?.type === 'UNETLoader' ? 'unet_name' : 'ckpt_name';

    if (!items.length) {
        listEl.innerHTML = '<div class="wf-model-loading">Keine Modelle gefunden</div>';
    } else {
        listEl.innerHTML = items.map((m, i) => {
            const short = m.split('\\').pop().split('/').pop();
            return `<div class="wf-model-item" data-index="${i}" data-node="${nodeId}" data-field="${field}" onclick="selectModel(this)" title="${m}">${short}</div>`;
        }).join('');
    }
    listEl.style.display = 'block';
    document.querySelector(`#model-select-${nodeId} .wf-model-arrow`).textContent = '▴';
}

function toggleLoraList(nodeId) {
    const listEl = document.getElementById(`lora-list-${nodeId}`);
    const isOpen = listEl.style.display !== 'none';
    document.querySelectorAll('.wf-model-list').forEach(l => l.style.display = 'none');
    document.querySelectorAll('.wf-model-arrow').forEach(a => a.textContent = '▾');
    if (isOpen) return;

    if (!allLoras.length) {
        listEl.innerHTML = '<div class="wf-model-loading">Keine LoRAs gefunden</div>';
    } else {
        listEl.innerHTML = allLoras.map((l, i) => {
            const short = l.split('\\').pop().split('/').pop();
            return `<div class="wf-model-item" data-index="${i}" data-node="${nodeId}" onclick="selectLora(this)" title="${l}">${short}</div>`;
        }).join('');
    }
    listEl.style.display = 'block';
    document.querySelector(`#lora-select-${nodeId} .wf-model-arrow`).textContent = '▴';
}

function selectModel(el) {
    const nodeId = el.dataset.node;
    const field  = el.dataset.field;
    const items  = field === 'unet_name' ? allUnets : allCheckpoints;
    const fullPath = items[parseInt(el.dataset.index)];
    patch(nodeId, field, fullPath);
    document.querySelector(`#model-select-${nodeId} .wf-model-current-name`).textContent = el.textContent;
    document.getElementById(`model-list-${nodeId}`).style.display = 'none';
    document.querySelector(`#model-select-${nodeId} .wf-model-arrow`).textContent = '▾';
}

// Klick außerhalb schließt Listen
document.addEventListener('click', e => {
    if (!e.target.closest('.wf-model-select')) {
        document.querySelectorAll('.wf-model-list').forEach(l => l.style.display = 'none');
        document.querySelectorAll('.wf-model-arrow').forEach(a => a.textContent = '▾');
    }
});

// Sampler & Scheduler beim Start laden
loadSamplersAndSchedulers();

// ── Prompt Critic ─────────────────────────────────────────────────────────────

async function runPromptCritic() {
    const posPrompt = workflowMeta.prompts.find(p => p.role === 'positive' && !p.hidden);
    if (!posPrompt) return;
    const promptText = currentPatches[posPrompt.id]?.text ?? posPrompt.text;
    if (!promptText) return;

    const criticDiv = document.createElement('div');
    criticDiv.className = 'wf-critic';
    criticDiv.innerHTML = `<div class="wf-critic-loading">🔍 Analysiere Prompt...</div>`;
    document.getElementById('wf-output').appendChild(criticDiv);

    try {
        const r = await fetch('/api/workflows/critique-prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: promptText })
        });
        const d = await r.json();

        const scoreColor = d.score >= 8 ? '#4caf50' : d.score >= 5 ? '#ff9800' : '#f44336';
        const issuesHtml = d.issues?.length
            ? `<ul class="wf-critic-issues">${d.issues.map(i => `<li>${i}</li>`).join('')}</ul>`
            : `<p style="color:var(--muted);margin:6px 0">✓ Keine Probleme gefunden.</p>`;
        const hasImproved = d.improved_prompt && d.improved_prompt !== promptText;

        criticDiv.innerHTML = `
            <div class="wf-critic-header">
                <span class="wf-critic-title">🔍 Prompt Critic</span>
                <span class="wf-critic-score" style="background:${scoreColor}">${d.score ?? '?'}/10</span>
            </div>
            ${issuesHtml}
            ${hasImproved ? `
                <div class="wf-critic-improved">
                    <div class="wf-critic-improved-label">✨ Verbesserter Prompt</div>
                    <div class="wf-critic-improved-text">${d.improved_prompt}</div>
                    <button class="wf-critic-apply-btn"
                        onclick="applyCriticPrompt(this.parentElement.querySelector('.wf-critic-improved-text').textContent, '${posPrompt.id}')">
                        ✓ Anwenden
                    </button>
                </div>` : ''}`;
    } catch(e) {
        criticDiv.innerHTML = `<div class="wf-error">❌ Critic: ${e.message}</div>`;
    }
}

function applyCriticPrompt(improved, nodeId) {
    patch(nodeId, 'text', improved);
    const ta = document.querySelector('.wf-textarea:not(.wf-textarea-neg)');
    if (ta) ta.value = improved;
    syncLinkedPrompts(nodeId, improved);
}


loadWildcards();

// ── Prompt Assistant Overlay ─────────────────────────────────────────────────

function togglePromptAssist() {
    const overlay = document.getElementById('pa-overlay');
    if (!overlay) return;
    const isOpen = overlay.style.display === 'flex';
    overlay.style.display = isOpen ? 'none' : 'flex';
    const btn = document.getElementById('pa-trigger-btn');
    if (btn) {
        btn.style.borderColor = isOpen ? 'var(--border)' : 'var(--accent)';
        btn.style.color       = isOpen ? 'var(--muted)'  : 'var(--accent)';
        btn.style.background  = isOpen ? 'none' : 'rgba(108,99,255,.08)';
    }
    if (!isOpen) {
        document.getElementById('prompt-assist-input')?.focus();
    }
}

// ── Migrated from workflows.html inline script ───────────────────────────────

// Sidebar Mobile Toggle
function toggleWfSidebar() {
    document.querySelector('.wf-sidebar').classList.toggle('mobile-open');
    document.getElementById('wf-sidebar-overlay').classList.toggle('visible');
}
document.addEventListener('click', (e) => {
    if (window.innerWidth <= 768 && e.target.closest('.wf-item')) setTimeout(toggleWfSidebar, 150);
});

// Prompt Style
function updateWfStyleBtns(style) {
    document.querySelectorAll('.wf-style-btn').forEach(btn =>
        btn.classList.toggle('active', btn.dataset.style === style));
}
async function setWfPromptStyle(style) {
    updateWfStyleBtns(style);
    await fetch('/api/prompt-style', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ style })
    });
}

// Image Styles / Themes / Characters
async function loadWfImageStyles() {
    const sel = document.getElementById('wf-style-select');
    if (!sel) return;
    try {
        const [stylesResp, activeResp] = await Promise.all([fetch('/api/styles'), fetch('/api/image-style')]);
        const { styles } = await stylesResp.json();
        const { style: activeStyle } = await activeResp.json();
        styles.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s; opt.textContent = s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g,' ');
            if (s === activeStyle) opt.selected = true;
            sel.appendChild(opt);
        });
    } catch(e) {}
}
async function loadWfImageThemes() {
    const sel = document.getElementById('wf-theme-select');
    if (!sel) return;
    try {
        const [themesResp, activeResp] = await Promise.all([fetch('/api/themes'), fetch('/api/image-theme')]);
        const { themes } = await themesResp.json();
        const { theme: activeTheme } = await activeResp.json();
        themes.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t; opt.textContent = t.charAt(0).toUpperCase() + t.slice(1).replace(/_/g,' ');
            if (t === activeTheme) opt.selected = true;
            sel.appendChild(opt);
        });
    } catch(e) {}
}
async function loadWfImageCharacters() {
    const sel = document.getElementById('wf-character-select');
    if (!sel) return;
    try {
        const [charsResp, activeResp] = await Promise.all([fetch('/api/characters'), fetch('/api/image-character')]);
        const { characters } = await charsResp.json();
        const { character: activeChar } = await activeResp.json();
        characters.forEach(ch => {
            const opt = document.createElement('option');
            opt.value = ch; opt.textContent = ch.charAt(0).toUpperCase() + ch.slice(1).replace(/_/g,' ');
            if (ch === activeChar) opt.selected = true;
            sel.appendChild(opt);
        });
    } catch(e) {}
}
function setWfImageStyle(style) { const s = document.getElementById('wf-style-select'); if (s) s.value = style; }
function setWfImageTheme(theme) { const s = document.getElementById('wf-theme-select'); if (s) s.value = theme; }
function setWfImageCharacter(c) { const s = document.getElementById('wf-character-select'); if (s) s.value = c; }

// Load from image (called by file input onchange in HTML)
async function loadWorkflowFromImage(input) {
    const file = input.files[0];
    if (!file) return;
    input.value = '';
    const list = document.getElementById('workflow-list');
    const prevContent = list.innerHTML;
    list.innerHTML = '<div class="wf-loading">↻ Lese Bild...</div>';
    const fd = new FormData();
    fd.append('file', file);
    try {
        const r = await fetch('/api/workflows/extract-from-image', { method: 'POST', body: fd });
        const d = await r.json();
        if (d.error) {
            list.innerHTML = `<div class="wf-empty">❌ ${d.error}</div>`;
            setTimeout(() => list.innerHTML = prevContent, 3000); return;
        }
        const name = file.name.replace('.png', '');
        list.innerHTML = prevContent;
        const tempItem = document.createElement('div');
        tempItem.className = 'wf-item active';
        tempItem.innerHTML = `<div class="wf-item-icon">🖼️</div><div class="wf-item-info"><div class="wf-item-name">${name}</div><div class="wf-item-nodes">Aus Bild • ${Object.keys(d.workflow).length} Nodes</div></div>`;
        list.prepend(tempItem);
        document.getElementById('wf-placeholder').style.display = 'none';
        document.getElementById('wf-editor').style.display = 'flex';
        document.getElementById('wf-name-title').textContent = name;
        currentWorkflow = d.workflow; currentPatches = {};
        const _paBtn2 = document.getElementById('pa-trigger-btn');
        if (_paBtn2) _paBtn2.style.display = 'flex';
        parseAndRenderWorkflow(currentWorkflow);
    } catch(e) {
        list.innerHTML = `<div class="wf-empty">❌ ${e.message}</div>`;
        setTimeout(() => list.innerHTML = prevContent, 3000);
    }
}

// Prompt Assistant
let lastSuggestedPrompt = '';
let promptInputMode     = 'text';
let promptImageB64      = null;

function setPromptInputMode(mode) {
    promptInputMode = mode;
    document.getElementById('pa-text-btn').classList.toggle('active', mode === 'text');
    document.getElementById('pa-img-btn').classList.toggle('active', mode === 'image');
    document.getElementById('pa-text-wrap').style.display = mode === 'text'  ? 'flex' : 'none';
    document.getElementById('pa-img-wrap').style.display  = mode === 'image' ? 'block' : 'none';
}
function handlePaImgDrop(e) {
    e.preventDefault();
    document.getElementById('pa-img-drop').classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) loadPaImageFile(file);
}
function loadPaImageFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => {
        promptImageB64 = ev.target.result.split(',')[1];
        document.getElementById('pa-img-preview-wrap').innerHTML = `<img src="${ev.target.result}" class="wf-pa-img-preview">`;
    };
    reader.readAsDataURL(file);
}

async function suggestPrompt() {
    const input  = document.getElementById('prompt-assist-input');
    const btn    = document.getElementById('prompt-assist-btn');
    const result = document.getElementById('prompt-assist-result');
    const text   = document.getElementById('prompt-assist-text');

    if (promptInputMode === 'image' && !promptImageB64) {
        const drop = document.getElementById('pa-img-drop');
        drop.style.borderColor = 'var(--accent)';
        setTimeout(() => drop.style.borderColor = '', 1500); return;
    }
    const msg = promptInputMode === 'text' ? input.value.trim() : '';
    if (promptInputMode === 'text' && !msg) return;

    btn.disabled = true; btn.classList.add('loading');
    result.style.display = 'flex'; text.textContent = ''; lastSuggestedPrompt = '';

    try {
        const resp = await fetch('/api/workflows/prompt-suggest', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message:   msg,
                image_b64: promptInputMode === 'image' ? (promptImageB64 || '') : '',
                style:     document.getElementById('wf-style-select')?.value || null,
                theme:     document.getElementById('wf-theme-select')?.value || null,
                character: document.getElementById('wf-character-select')?.value || null
            })
        });
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '', fullText = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n'); buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const json = JSON.parse(line.slice(6));
                    if (json.type === 'token') {
                        fullText += json.text;
                        const promptMatch = fullText.match(/"prompt"\s*:\s*"/);
                        if (promptMatch) {
                            const startIdx = promptMatch.index + promptMatch[0].length;
                            let partial = fullText.slice(startIdx);
                            const endMatch = partial.match(/(?<!\\)"\s*[,}]/);
                            if (endMatch) partial = partial.slice(0, endMatch.index);
                            try { partial = partial.replace(/\\n/g,'\n').replace(/\\"/g,'"').replace(/\\\\/g,'\\'); } catch(e) {}
                            if (partial.length > 0) text.textContent = partial;
                        } else { text.textContent = '⏳ Generating...'; }
                    } else if (json.type === 'done') {
                        lastSuggestedPrompt = json.prompt || '';
                        text.textContent = lastSuggestedPrompt;
                        document.getElementById('pa-critic-btn').style.display = '';
                        document.getElementById('pa-critic-result').innerHTML = '';
                        if (lastSuggestedPrompt && document.getElementById('pa-critic-enabled').checked) runPromptAssistCritic();
                    } else if (json.type === 'error') { text.textContent = '❌ Error: ' + json.text; }
                } catch(e) {}
            }
        }
    } catch(e) { text.textContent = '❌ Error: ' + e.message; result.style.display = 'flex'; }
    btn.disabled = false; btn.classList.remove('loading');
}

function handlePromptAssistKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); suggestPrompt(); }
}
function copyPromptToEditor() {
    if (!lastSuggestedPrompt) return;
    document.querySelectorAll('.wf-textarea:not(.wf-textarea-neg)').forEach(ta => {
        ta.value = lastSuggestedPrompt; ta.dispatchEvent(new Event('change'));
    });
    const nodeId = workflowMeta.prompts.find(p => p.role === 'positive' && !p.hidden)?.id;
    if (nodeId) { patch(nodeId, 'text', lastSuggestedPrompt); syncLinkedPrompts(nodeId, lastSuggestedPrompt); }
    // Close overlay after applying
    const overlay = document.getElementById('pa-overlay');
    if (overlay) overlay.style.display = 'none';
    const btn = document.getElementById('pa-trigger-btn');
    if (btn) { btn.style.borderColor='var(--border)'; btn.style.color='var(--muted)'; btn.style.background='none'; }
}

async function runPromptAssistCritic() {
    if (!lastSuggestedPrompt) return;
    const resultDiv = document.getElementById('pa-critic-result');
    const btn       = document.getElementById('pa-critic-btn');
    btn.disabled = true; btn.textContent = '⏳';
    resultDiv.innerHTML = `<div style="color:var(--muted);font-size:0.78rem;margin-top:8px">🔍 Analysiere...</div>`;
    try {
        const r = await fetch('/api/workflows/critique-prompt', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: lastSuggestedPrompt })
        });
        const d = await r.json();
        const scoreColor = d.score >= 8 ? '#4caf50' : d.score >= 5 ? '#ff9800' : '#f44336';
        const issuesHtml = d.issues?.length
            ? `<ul style="margin:6px 0 8px 16px;padding:0;color:var(--muted);font-size:0.78rem;line-height:1.6">${d.issues.map(i=>`<li>${i}</li>`).join('')}</ul>`
            : `<p style="color:var(--muted);font-size:0.78rem;margin:6px 0 0">✓ Keine Probleme.</p>`;
        const hasImproved = d.improved_prompt && d.improved_prompt !== lastSuggestedPrompt;
        resultDiv.innerHTML = `
            <div style="margin-top:10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px 12px">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
                    <span style="font-size:0.75rem;font-weight:700;color:var(--text)">🔍 Critic</span>
                    <span style="padding:1px 8px;border-radius:20px;color:#fff;font-weight:700;font-size:0.78rem;background:${scoreColor}">${d.score ?? '?'}/10</span>
                </div>
                ${issuesHtml}
                ${hasImproved ? `<button onclick="applyPaCriticImprovement(this)"
                    style="margin-top:4px;padding:4px 12px;border-radius:6px;border:none;background:var(--accent);color:#fff;font-family:'Syne',sans-serif;font-size:0.75rem;font-weight:700;cursor:pointer"
                    data-prompt="${d.improved_prompt.replace(/"/g,'&quot;')}">✓ Verbesserung übernehmen</button>` : ''}
            </div>`;
    } catch(e) { resultDiv.innerHTML = `<div style="color:#f44336;font-size:0.78rem;margin-top:6px">❌ ${e.message}</div>`; }
    btn.disabled = false; btn.textContent = '🔍 Analysieren';
}

function applyPaCriticImprovement(btn) {
    lastSuggestedPrompt = btn.dataset.prompt;
    document.getElementById('prompt-assist-text').textContent = lastSuggestedPrompt;
    btn.textContent = '✅ Übernommen'; btn.disabled = true;
}

// Save Workflow
async function saveWorkflowAs() {
    if (!currentWorkflow) return;
    const currentName = document.getElementById('wf-name-title')?.textContent || 'workflow';
    const name = prompt('Save workflow as:', currentName);
    if (!name) return;
    const finalWf = buildFinalWorkflow();
    try {
        const resp = await fetch('/api/workflows/save', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, workflow: finalWf })
        });
        const data = await resp.json();
        if (data.ok) {
            const btn = document.querySelector('.wf-save-btn');
            btn.textContent = '✅ Saved';
            setTimeout(() => btn.textContent = '💾 Save', 1500);
            loadWorkflowList();
        } else { alert('Save failed: ' + (data.error || 'Unknown error')); }
    } catch(e) { alert('Save failed: ' + e.message); }
}

// Unload LLM before generation
async function runWorkflowWithUnload() {
    const btn = document.getElementById('run-btn');
    btn.disabled = true; btn.textContent = '🧹 Unloading LLM...';
    try {
        const activeResp = await fetch('/api/models/active', { signal: AbortSignal.timeout(4000) });
        if (activeResp.ok) {
            const { active: instanceId } = await activeResp.json();
            if (instanceId) await fetch('/api/models/unload', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ instance_id: instanceId }),
                signal: AbortSignal.timeout(4000)
            }).catch(() => {});
        }
    } catch(e) {}
    btn.textContent = '▶ Generate'; btn.disabled = false;
    runWorkflow();
}

// DOMContentLoaded init
document.addEventListener('DOMContentLoaded', () => {
    loadWorkflowList();
    loadWildcards();
    loadWfImageStyles();
    loadWfImageThemes();
    loadWfImageCharacters();
    fetch('/api/prompt-style').then(r => r.json()).then(d => updateWfStyleBtns(d.style));

    // Check for pending workflow from Gallery
    const pending = sessionStorage.getItem('pending_workflow');
    if (!pending) return;
    sessionStorage.removeItem('pending_workflow');
    try {
        const data = JSON.parse(pending);
        if (!data.workflow) return;
        document.getElementById('wf-placeholder').style.display = 'none';
        document.getElementById('wf-editor').style.display = 'flex';
        document.getElementById('wf-name-title').textContent = data.name || 'From Gallery';
    const _paBtn = document.getElementById('pa-trigger-btn');
    if (_paBtn) _paBtn.style.display = 'flex';
        currentWorkflow = data.workflow; currentPatches = {};
        if (data.artistMode) {
            artistState.enabled = true;
            artistState.model_type  = data.artistMode.model_type;
            artistState.artist_name = data.artistMode.artist_name;
            parseAndRenderWorkflow(currentWorkflow);
        } else if (data.imageUrl) {
            fetch(data.imageUrl).then(r => r.blob())
                .then(blob => new Promise((res, rej) => { const reader = new FileReader(); reader.onload = e => res(e.target.result); reader.onerror = rej; reader.readAsDataURL(blob); }))
                .then(dataUrl => { img2imgState.imageDataUrl = dataUrl; img2imgState.enabled = true; parseAndRenderWorkflow(currentWorkflow); })
                .catch(() => parseAndRenderWorkflow(currentWorkflow));
        } else { parseAndRenderWorkflow(currentWorkflow); }
    } catch(e) { console.error('[Gallery] Failed to load pending workflow:', e); }
});
