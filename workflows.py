# ─── WORKFLOWS.PY — ComfyUI Workflows & Patch-Logik ─────────────────────────
import copy
import random

# ── Aspect Ratio → Pixel-Dimensionen ─────────────────────────────────────────

ASPECT_SIZES = {
    "1:1":              (1024, 1024),
    "3:4 (Golden Ratio)":(896,  1152),
    "4:3":              (1152,  896),
    "16:9":             (1216,  704),
    "9:16":             (704,  1216),
}

def aspect_to_wh(aspect_ratio: str):
    return ASPECT_SIZES.get(aspect_ratio, (1024, 1024))


# ── WORKFLOW: ANIMA (UNET + Qwen CLIP) ───────────────────────────────────────

WORKFLOW_ANIMA = {
    "1":  {"inputs": {"images": ["8", 0]},                                  "class_type": "PreviewImage"},
    "8":  {"inputs": {"samples": ["19", 0], "vae": ["15", 0]},              "class_type": "VAEDecode"},
    "11": {"inputs": {"text": "", "clip": ["45", 0]},                       "class_type": "CLIPTextEncode"},
    "12": {"inputs": {"text": "worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, sepia", "clip": ["45", 0]}, "class_type": "CLIPTextEncode"},
    "15": {"inputs": {"vae_name": "qwen_image_vae.safetensors"},             "class_type": "VAELoader"},
    "19": {
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 4,
            "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1,
            "model": ["44", 0], "positive": ["11", 0], "negative": ["12", 0], "latent_image": ["28", 0]
        },
        "class_type": "KSampler"
    },
    "28": {"inputs": {"width": 1024, "height": 1024, "batch_size": 1},      "class_type": "EmptyLatentImage"},
    "44": {"inputs": {"unet_name": "Anima\\anima-preview2.safetensors", "weight_dtype": "default"}, "class_type": "UNETLoader"},
    "45": {"inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "qwen_image", "device": "default"}, "class_type": "CLIPLoader"},
}

def patch_anima(prompt: str, negative: str, aspect_ratio: str, model_name: str) -> dict:
    w, h = aspect_to_wh(aspect_ratio)
    wf = copy.deepcopy(WORKFLOW_ANIMA)
    wf["44"]["inputs"]["unet_name"] = model_name
    wf["11"]["inputs"]["text"]      = prompt
    wf["12"]["inputs"]["text"]      = negative
    wf["19"]["inputs"]["seed"]      = random.randint(0, 2**32 - 1)
    wf["28"]["inputs"]["width"]     = w
    wf["28"]["inputs"]["height"]    = h
    return wf


# ── WORKFLOW: ILLUSTRIOUS (Checkpoint + FaceDetailer) ────────────────────────

WORKFLOW_ILLUSTRIOUS = {
    "3": {
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 4,
            "sampler_name": "euler_ancestral", "scheduler": "karras", "denoise": 1,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]
        },
        "class_type": "KSampler"
    },
    "4":  {"inputs": {"ckpt_name": "mergetoon\\prototype2.safetensors"},     "class_type": "CheckpointLoaderSimple"},
    "5":  {"inputs": {"width": 1024, "height": 1024, "batch_size": 1},      "class_type": "EmptyLatentImage"},
    "6":  {"inputs": {"text": "", "clip": ["4", 1]},                        "class_type": "CLIPTextEncode"},
    "7":  {"inputs": {"text": "embedding:lazyneg", "clip": ["4", 1]},       "class_type": "CLIPTextEncode"},
    "8":  {"inputs": {"samples": ["3", 0], "vae": ["4", 2]},                "class_type": "VAEDecode"},
    "9":  {"inputs": {"filename_prefix": "illustrious_", "images": ["18", 0]}, "class_type": "SaveImage"},
    "18": {
        "inputs": {
            "guide_size": 576, "guide_size_for": True, "max_size": 1024,
            "seed": 0, "steps": 20, "cfg": 4,
            "sampler_name": "euler_ancestral", "scheduler": "karras", "denoise": 0.7,
            "feather": 5, "noise_mask": True, "force_inpaint": True,
            "bbox_threshold": 0.5, "bbox_dilation": 10, "bbox_crop_factor": 3,
            "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
            "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False",
            "drop_size": 50, "wildcard": "", "cycle": 1,
            "inpaint_model": False, "noise_mask_feather": 27,
            "tiled_encode": False, "tiled_decode": False,
            "image": ["8", 0], "model": ["84", 0], "clip": ["4", 1], "vae": ["4", 2],
            "positive": ["21", 0], "negative": ["7", 0],
            "bbox_detector": ["19", 0], "sam_model_opt": ["20", 0]
        },
        "class_type": "FaceDetailer"
    },
    "19": {"inputs": {"model_name": "bbox/face_yolov8m.pt"},                "class_type": "UltralyticsDetectorProvider"},
    "20": {"inputs": {"model_name": "sam_vit_b_01ec64.pth", "device_mode": "AUTO"}, "class_type": "SAMLoader"},
    "21": {"inputs": {"text": "", "clip": ["4", 1]},                        "class_type": "CLIPTextEncode"},
    "84": {"inputs": {"strength": 1, "model": ["4", 0]},                   "class_type": "DifferentialDiffusion"},
}

def patch_illustrious(prompt: str, aspect_ratio: str, model_name: str) -> dict:
    w, h = aspect_to_wh(aspect_ratio)
    wf = copy.deepcopy(WORKFLOW_ILLUSTRIOUS)
    wf["4"]["inputs"]["ckpt_name"]   = model_name
    wf["6"]["inputs"]["text"]        = prompt   # positive
    wf["21"]["inputs"]["text"]       = prompt   # FaceDetailer positive (gleich)
    wf["7"]["inputs"]["text"]        = "embedding:lazyneg"  # hardcoded negativ
    wf["3"]["inputs"]["seed"]        = random.randint(0, 2**32 - 1)
    wf["18"]["inputs"]["seed"]       = random.randint(0, 2**32 - 1)
    wf["5"]["inputs"]["width"]       = w
    wf["5"]["inputs"]["height"]      = h
    return wf


# ── WORKFLOW: ANIMA TURBO (AnimaLayerReplayPatcher) ─────────────────────────

WORKFLOW_ANIMA_TURBO = {
    "8":  {"inputs": {"samples": ["19", 0], "vae": ["15", 0]},              "class_type": "VAEDecode"},
    "11": {"inputs": {"text": "", "clip": ["45", 0]},                       "class_type": "CLIPTextEncode"},
    "12": {"inputs": {"text": "worst quality, low quality, score_1, score_2, score_3, blurry, jpeg artifacts, extra limbs, deformed face, bad anatomy, messy hair, dull colors, text, watermark, ugly, cartoonish, overexposed, underexposed", "clip": ["45", 0]}, "class_type": "CLIPTextEncode"},
    "15": {"inputs": {"vae_name": "qwen_image_vae.safetensors"},             "class_type": "VAELoader"},
    "19": {
        "inputs": {
            "seed": 0, "steps": 20, "cfg": 4,
            "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1,
            "model": ["47", 0], "positive": ["11", 0], "negative": ["12", 0], "latent_image": ["28", 0]
        },
        "class_type": "KSampler"
    },
    "28": {"inputs": {"width": 1024, "height": 1024, "batch_size": 1},      "class_type": "EmptyLatentImage"},
    "44": {"inputs": {"unet_name": "Anima\\anima-preview2.safetensors", "weight_dtype": "default"}, "class_type": "UNETLoader"},
    "45": {"inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "qwen_image", "device": "default"}, "class_type": "CLIPLoader"},
    "46": {"inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]},    "class_type": "SaveImage"},
    "47": {
        "inputs": {
            "enable_replay": True, "block_indices": "3,4,5",
            "denoise_start_pct": 0.5, "denoise_end_pct": 1,
            "enable_spectrum": True, "spectrum_w": 0.2, "spectrum_m": 16,
            "spectrum_lam": 0.5, "spectrum_warmup_steps": 6,
            "spectrum_window_size": 2, "spectrum_flex_window": 0,
            "model": ["44", 0]
        },
        "class_type": "AnimaLayerReplayPatcher"
    },
}

def patch_anima_turbo(prompt: str, negative: str, aspect_ratio: str, model_name: str) -> dict:
    w, h = aspect_to_wh(aspect_ratio)
    wf = copy.deepcopy(WORKFLOW_ANIMA_TURBO)
    wf["44"]["inputs"]["unet_name"] = model_name
    wf["11"]["inputs"]["text"]      = prompt
    wf["12"]["inputs"]["text"]      = negative
    wf["19"]["inputs"]["seed"]      = random.randint(0, 2**32 - 1)
    wf["28"]["inputs"]["width"]     = w
    wf["28"]["inputs"]["height"]    = h
    return wf


# ── WORKFLOW: ILLUSTRIOUS TURBO (DMD2 LoRA, 6 Steps, cfg 1.3) ────────────────

WORKFLOW_ILLUSTRIOUS_TURBO = {
    "3": {
        "inputs": {
            "seed": 0, "steps": 6, "cfg": 1.3,
            "sampler_name": "euler_ancestral", "scheduler": "karras", "denoise": 1,
            "model": ["100", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]
        },
        "class_type": "KSampler"
    },
    "4":  {"inputs": {"ckpt_name": "mergetoon\\prototype2.safetensors"},     "class_type": "CheckpointLoaderSimple"},
    "5":  {"inputs": {"width": 1024, "height": 1024, "batch_size": 1},      "class_type": "EmptyLatentImage"},
    "6":  {"inputs": {"text": "", "clip": ["100", 1]},                      "class_type": "CLIPTextEncode"},
    "7":  {"inputs": {"text": "embedding:lazyneg", "clip": ["100", 1]},     "class_type": "CLIPTextEncode"},
    "8":  {"inputs": {"samples": ["3", 0], "vae": ["4", 2]},                "class_type": "VAEDecode"},
    "9":  {"inputs": {"filename_prefix": "turbo_illustrious_", "images": ["18", 0]}, "class_type": "SaveImage"},
    "18": {
        "inputs": {
            "guide_size": 576, "guide_size_for": True, "max_size": 1024,
            "seed": 0, "steps": 6, "cfg": 1.3,
            "sampler_name": "euler_ancestral", "scheduler": "karras", "denoise": 0.7,
            "feather": 5, "noise_mask": True, "force_inpaint": True,
            "bbox_threshold": 0.5, "bbox_dilation": 10, "bbox_crop_factor": 3,
            "sam_detection_hint": "center-1", "sam_dilation": 0, "sam_threshold": 0.93,
            "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False",
            "drop_size": 50, "wildcard": "", "cycle": 1,
            "inpaint_model": False, "noise_mask_feather": 27,
            "tiled_encode": False, "tiled_decode": False,
            "image": ["8", 0], "model": ["84", 0], "clip": ["100", 1], "vae": ["4", 2],
            "positive": ["21", 0], "negative": ["7", 0],
            "bbox_detector": ["19", 0], "sam_model_opt": ["20", 0]
        },
        "class_type": "FaceDetailer"
    },
    "19": {"inputs": {"model_name": "bbox/face_yolov8m.pt"},                "class_type": "UltralyticsDetectorProvider"},
    "20": {"inputs": {"model_name": "sam_vit_b_01ec64.pth", "device_mode": "AUTO"}, "class_type": "SAMLoader"},
    "21": {"inputs": {"text": "", "clip": ["100", 1]},                      "class_type": "CLIPTextEncode"},
    "84": {"inputs": {"strength": 1, "model": ["100", 0]},                  "class_type": "DifferentialDiffusion"},
    "100": {
        "inputs": {
            "lora_name": "SDXL 1.0\\tool\\dmd2_sdxl_4step_lora_fp16.safetensors",
            "strength_model": 1, "strength_clip": 1,
            "model": ["4", 0], "clip": ["4", 1]
        },
        "class_type": "LoraLoader"
    },
}

def patch_illustrious_turbo(prompt: str, aspect_ratio: str, model_name: str) -> dict:
    w, h = aspect_to_wh(aspect_ratio)
    wf = copy.deepcopy(WORKFLOW_ILLUSTRIOUS_TURBO)
    wf["4"]["inputs"]["ckpt_name"]   = model_name
    wf["6"]["inputs"]["text"]        = prompt
    wf["21"]["inputs"]["text"]       = prompt
    wf["7"]["inputs"]["text"]        = "embedding:lazyneg"
    wf["3"]["inputs"]["seed"]        = random.randint(0, 2**32 - 1)
    wf["18"]["inputs"]["seed"]       = random.randint(0, 2**32 - 1)
    wf["5"]["inputs"]["width"]       = w
    wf["5"]["inputs"]["height"]      = h
    return wf


# ── WORKFLOW: Z-IMAGE (Placeholder — wird ergänzt) ───────────────────────────

WORKFLOW_ZIMAGE = {}   # TODO: Workflow einfügen sobald bereit

def patch_zimage(prompt: str, negative: str, aspect_ratio: str, model_name: str) -> dict:
    raise NotImplementedError("Z-Image Workflow noch nicht konfiguriert")


# ── Dispatch ─────────────────────────────────────────────────────────────────

def build_workflow(model_type: str, prompt: str, negative: str, aspect_ratio: str, model_name: str, turbo: bool = False) -> dict:
    """Gibt den gepatchten Workflow zurück. turbo=True wählt den Turbo-Variant."""
    t = model_type.lower()
    if t == "anima":
        return patch_anima_turbo(prompt, negative, aspect_ratio, model_name) if turbo else patch_anima(prompt, negative, aspect_ratio, model_name)
    elif t == "illustrious":
        return patch_illustrious_turbo(prompt, aspect_ratio, model_name) if turbo else patch_illustrious(prompt, aspect_ratio, model_name)
    elif t == "zimage":
        return patch_zimage(prompt, negative, aspect_ratio, model_name)
    else:
        raise ValueError(f"Unbekannter Workflow-Typ: {model_type}")
