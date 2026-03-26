# ─── server_workflows_snippet.py ─────────────────────────────────────────────
# Diese Routes in server.py einfügen (nach den bestehenden Imports / app-Setup)
# Voraussetzung: import os, json, glob am Anfang von server.py schon vorhanden
#
# Außerdem: einen /workflows/ Ordner im Projekt-Root anlegen und
# ComfyUI-JSON-Exports dort reinwerfen.

import os
import json
import glob

WORKFLOWS_DIR = os.path.join(os.path.dirname(__file__), 'workflows')
os.makedirs(WORKFLOWS_DIR, exist_ok=True)


# ── GET /api/workflows — Liste aller verfügbaren Workflow-JSONs ───────────────
@app.route('/api/workflows', methods=['GET'])
def list_workflows():
    files = glob.glob(os.path.join(WORKFLOWS_DIR, '*.json'))
    workflows = []
    for f in sorted(files):
        name = os.path.basename(f)
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                wf = json.load(fh)
            workflows.append({
                'name':         name,
                'display_name': name.replace('.json','').replace('_',' '),
                'node_count':   len(wf),
            })
        except Exception:
            pass
    return jsonify({'workflows': workflows})


# ── GET /api/workflows/<name> — Einen Workflow laden ─────────────────────────
@app.route('/api/workflows/<path:name>', methods=['GET'])
def get_workflow(name):
    # Sicherheit: nur .json Dateien aus dem workflows/ Ordner
    if not name.endswith('.json') or '/' in name or '\\' in name:
        return jsonify({'error': 'Ungültiger Name'}), 400
    path = os.path.join(WORKFLOWS_DIR, name)
    if not os.path.exists(path):
        return jsonify({'error': 'Nicht gefunden'}), 404
    with open(path, 'r', encoding='utf-8') as f:
        wf = json.load(f)
    return jsonify({'workflow': wf})


# ── POST /api/workflows/run — Workflow ausführen ──────────────────────────────
# Erwartet: { "workflow": { ...ComfyUI API-Format... } }
# Gibt zurück: { "image_b64": "...", "filename": "..." }
@app.route('/api/workflows/run', methods=['POST'])
def run_custom_workflow():
    data = request.get_json()
    if not data or 'workflow' not in data:
        return jsonify({'error': 'Kein Workflow übergeben'}), 400

    workflow = data['workflow']

    # ComfyUI erwartet den Workflow unter dem Key "prompt"
    import requests as req
    import base64, time, uuid

    COMFY_URL = os.getenv('COMFY_URL', 'http://127.0.0.1:8188')
    client_id = str(uuid.uuid4())

    # Workflow absenden
    resp = req.post(f'{COMFY_URL}/prompt', json={
        'prompt':    workflow,
        'client_id': client_id,
    }, timeout=10)

    if resp.status_code != 200:
        return jsonify({'error': f'ComfyUI Fehler: {resp.text}'}), 500

    prompt_id = resp.json().get('prompt_id')
    if not prompt_id:
        return jsonify({'error': 'Keine prompt_id erhalten'}), 500

    # Polling bis fertig (max 5 Minuten)
    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(1.5)
        hist = req.get(f'{COMFY_URL}/history/{prompt_id}', timeout=5)
        if hist.status_code != 200:
            continue
        history = hist.json().get(prompt_id, {})
        if not history:
            continue
        outputs = history.get('outputs', {})

        # Erstes Bild aus irgendeinem Output-Node holen
        for node_id, output in outputs.items():
            images = output.get('images', [])
            for img_info in images:
                if img_info.get('type') == 'output':
                    filename  = img_info['filename']
                    subfolder = img_info.get('subfolder', '')
                    # Bild herunterladen
                    img_resp = req.get(
                        f'{COMFY_URL}/view',
                        params={'filename': filename, 'subfolder': subfolder, 'type': 'output'},
                        timeout=30
                    )
                    if img_resp.status_code == 200:
                        b64 = base64.b64encode(img_resp.content).decode('utf-8')
                        return jsonify({'image_b64': b64, 'filename': filename})

    return jsonify({'error': 'Timeout — ComfyUI hat nicht rechtzeitig geantwortet'}), 504


# ── GET /workflows — Seite ausliefern ────────────────────────────────────────
# Falls du Flask verwendest und statische Files über Flask servist:
@app.route('/workflows')
def workflows_page():
    return send_from_directory('.', 'workflows.html')  # oder den korrekten Pfad
