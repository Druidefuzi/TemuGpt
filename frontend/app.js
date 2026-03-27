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

// ── KEYBOARD SHORTCUTS ──
document.addEventListener('keydown', e => {
    // Ctrl+N — Neuer Chat (außer wenn in einem Input/Textarea)
    if (e.ctrlKey && e.key === 'n') {
        const tag = document.activeElement?.tagName?.toLowerCase();
        if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') {
            e.preventDefault();
            newChat();
        }
    }
});

// ── SIDEBAR RESIZE ──
(function() {
    const handle  = document.getElementById('sidebar-resize-handle');
    const sidebar = document.querySelector('.sidebar');
    const STORAGE_KEY = 'sidebarWidth';
    const MIN = 180, MAX = 520;

    // Gespeicherte Breite wiederherstellen
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) sidebar.style.setProperty('--sidebar-width', saved + 'px');

    let dragging = false;
    let startX, startWidth;

    handle.addEventListener('mousedown', e => {
        dragging  = true;
        startX    = e.clientX;
        startWidth = sidebar.getBoundingClientRect().width;
        handle.classList.add('dragging');
        document.body.style.cursor    = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', e => {
        if (!dragging) return;
        const delta    = e.clientX - startX;
        const newWidth = Math.min(MAX, Math.max(MIN, startWidth + delta));
        sidebar.style.setProperty('--sidebar-width', newWidth + 'px');
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove('dragging');
        document.body.style.cursor    = '';
        document.body.style.userSelect = '';
        // Breite persistent speichern
        const w = parseInt(getComputedStyle(sidebar).width);
        localStorage.setItem(STORAGE_KEY, w);
    });
})();

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