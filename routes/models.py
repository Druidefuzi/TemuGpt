# ─── ROUTES/MODELS.PY — LM Studio Modell-Verwaltung ──────────────────────────

import requests
from flask import Blueprint, request, jsonify

from config import LM_API, MODEL_DEFAULT
import state

models_bp = Blueprint("models", __name__)


@models_bp.route("/api/models", methods=["GET"])
def list_models():
    try:
        resp = requests.get(f"{LM_API}/api/v1/models", timeout=5)
        if not resp.ok:
            return jsonify({"models": [], "active": state.active_model["name"], "loaded_ids": []})
        models_raw = resp.json().get("models", [])
    except Exception as e:
        print(f"[Models] Error: {e}")
        return jsonify({"models": [], "active": state.active_model["name"], "loaded_ids": []})

    available  = []
    loaded_ids = []
    for m in models_raw:
        key              = m.get("key", "")
        loaded_instances = m.get("loaded_instances", [])
        is_loaded        = len(loaded_instances) > 0
        instance_id      = loaded_instances[0]["id"] if loaded_instances else None
        if is_loaded:
            loaded_ids.append(key)
        available.append({
            "id":          key,
            "name":        m.get("display_name", key),
            "folder":      m.get("publisher", ""),
            "load_id":     key,
            "instance_id": instance_id,
            "size_gb":     round(m.get("size_bytes", 0) / 1e9, 1),
            "loaded":      is_loaded,
            "active":      state.active_model["name"] == key,
            "type":        m.get("type", "llm"),
        })
    available.sort(key=lambda x: (not x["loaded"], x["name"]))
    return jsonify({"models": available, "active": state.active_model["name"], "loaded_ids": loaded_ids})


@models_bp.route("/api/models/load", methods=["POST"])
def load_model():
    data         = request.json
    load_id      = data.get("load_id", "")
    display_name = data.get("name", load_id)
    gpu_offload  = data.get("gpu_offload", 1)
    if not load_id:
        return jsonify({"ok": False, "error": "No load_id provided"}), 400
    try:
        resp = requests.post(f"{LM_API}/api/v1/models/load", json={
            "model": load_id, "flash_attention": True, "offload_kv_cache_to_gpu": True
        }, timeout=60)
        if resp.ok:
            instance_id = resp.json().get("instance_id", load_id)
            state.active_model["name"] = instance_id
            print(f"[Model] Loaded: {display_name} (GPU: {gpu_offload*100:.0f}%)")
            return jsonify({"ok": True, "active": instance_id})
        return jsonify({"ok": False, "error": resp.text}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@models_bp.route("/api/models/unload", methods=["POST"])
def unload_model():
    data        = request.json
    instance_id = data.get("instance_id", "")
    try:
        resp = requests.post(f"{LM_API}/api/v1/models/unload", json={"instance_id": instance_id}, timeout=30)
        if resp.ok:
            if state.active_model["name"] == instance_id:
                state.active_model["name"] = MODEL_DEFAULT
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": resp.text}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@models_bp.route("/api/models/active", methods=["GET"])
def get_active_model():
    return jsonify({"active": state.active_model["name"]})


@models_bp.route("/api/models/active", methods=["POST"])
def set_active_model():
    data     = request.json
    model_id = data.get("id", "")
    if not model_id:
        return jsonify({"ok": False, "error": "No model ID"}), 400
    state.active_model["name"] = model_id
    print(f"[Model] Active model: {model_id}")
    return jsonify({"ok": True, "active": model_id})
