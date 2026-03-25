// ─── APP.JS — Globaler State & Init ──────────────────────────────────────────

let history = [];
let attachedFiles = [];
let isLoading = false;
let currentChatId = null;

// ── DRAG & DROP ──
const inputBox = document.getElementById('input-box');
inputBox.addEventListener('dragover', e => { e.preventDefault(); inputBox.classList.add('drag-over'); });
inputBox.addEventListener('dragleave', () => inputBox.classList.remove('drag-over'));
inputBox.addEventListener('drop', e => {
    e.preventDefault();
    inputBox.classList.remove('drag-over');
    addFiles(e.dataTransfer.files);
});

// ── MODAL CLOSE ON BACKDROP ──
document.getElementById('knowledge-modal').addEventListener('click', function(e) {
    if (e.target === this) closeModal();
});
document.getElementById('system-prompt-modal').addEventListener('click', function(e) {
    if (e.target === this) closeSystemPromptModal();
});

// ── INIT ──
fetch('/api/thinking/status').then(r => r.json()).then(d => updateThinkBtn(d.enabled));
fetch('/api/research/status').then(r => r.json()).then(d => updateResearchBtn(d.enabled));
loadKnowledge();
loadModels();
loadChatHistory();
