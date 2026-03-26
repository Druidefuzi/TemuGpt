// ─── WORKFLOW_UI.JS — Auto-Parser & Dynamic UI ───────────────────────────────

const SAMPLERS  = ['euler','euler_ancestral','heun','dpm_2','dpm_2_ancestral',
    'lms','dpm_fast','dpm_adaptive','dpmpp_2s_ancestral',
    'dpmpp_sde','dpmpp_2m','dpmpp_2m_sde','ddim','uni_pc','er_sde'];
const SCHEDULERS = ['normal','karras','exponential','sgm_uniform','simple','ddim_uniform'];

const ASPECT_SIZES = {
    '1:1':  [1024,1024], '3:4': [896,1152], '4:3': [1152,896],
    '16:9': [1216,704],  '9:16': [704,1216]
};

let currentWorkflow = null;
let currentPatches  = {};   // nodeId → { field → value }
let workflowMeta    = {};   // parsed structure info

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

    const r = await fetch(`/api/workflows/${name}`);
    const d = await r.json();
    currentWorkflow = d.workflow;
    currentPatches  = {};
    parseAndRenderWorkflow(currentWorkflow);
}

// ── Parser ────────────────────────────────────────────────────────────────────
function parseAndRenderWorkflow(wf) {
    workflowMeta = { prompts: [], samplers: [], latents: [], models: [], loras: [] };

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
                <input type="text" class="wf-text-input" value="${m.value}"
                    onchange="patch('${m.id}','${m.field}',this.value)" placeholder="Modellpfad...">
            </div>`).join('')));
    }

    // ── LoRAs
    if (workflowMeta.loras.length) {
        container.appendChild(section('🎨 LoRAs', workflowMeta.loras.map(l => `
            <div class="wf-lora-row">
                <input type="text" class="wf-text-input" value="${l.name}"
                    onchange="patch('${l.id}','lora_name',this.value)" placeholder="LoRA Pfad...">
                <div class="wf-lora-strengths">
                    <div class="wf-field">
                        <label>Model</label>
                        <div class="wf-slider-row">
                            <input type="range" min="0" max="2" step="0.05" value="${l.strength_model}"
                                oninput="this.nextElementSibling.textContent=(+this.value).toFixed(2); patch('${l.id}','strength_model',+this.value)">
                            <span>${(+l.strength_model).toFixed(2)}</span>
                        </div>
                    </div>
                    <div class="wf-field">
                        <label>CLIP</label>
                        <div class="wf-slider-row">
                            <input type="range" min="0" max="2" step="0.05" value="${l.strength_clip}"
                                oninput="this.nextElementSibling.textContent=(+this.value).toFixed(2); patch('${l.id}','strength_clip',+this.value)">
                            <span>${(+l.strength_clip).toFixed(2)}</span>
                        </div>
                    </div>
                </div>
            </div>`).join('')));
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

// ── Build final workflow & run ────────────────────────────────────────────────
function buildFinalWorkflow() {
    const wf = JSON.parse(JSON.stringify(currentWorkflow));
    for (const [nodeId, fields] of Object.entries(currentPatches)) {
        if (wf[nodeId]) {
            for (const [field, value] of Object.entries(fields)) {
                // Handle seed=-1 → randomize
                if (field === 'seed' && value === -1) {
                    wf[nodeId].inputs[field] = Math.floor(Math.random() * 2**32);
                } else {
                    wf[nodeId].inputs[field] = value;
                }
            }
        }
    }
    return wf;
}

async function runWorkflow() {
    if (!currentWorkflow) return;
    const btn = document.getElementById('run-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Generiere...';
    document.getElementById('wf-output').innerHTML = '<div class="wf-generating"><div class="wf-spinner"></div><span>Workflow läuft...</span></div>';

    const finalWf = buildFinalWorkflow();

    try {
        const resp = await fetch('/api/workflows/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow: finalWf })
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
                        <div class="wf-result">
                            <img src="data:image/png;base64,${data.image_b64}" onclick="this.classList.toggle('fullsize')" title="Klicken zum Vergrößern">
                            <div class="wf-result-actions">
                                <a href="data:image/png;base64,${data.image_b64}" download="${data.filename || 'output.png'}" class="wf-dl-btn">⬇ Speichern</a>
                            </div>
                        </div>`;
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