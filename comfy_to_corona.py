# -*- coding: utf-8 -*-
"""
ComfyUI Corona PBR Studio for Autodesk 3ds Max & Corona Renderer
================================================================
Generates seamless 5-map PBR textures (Albedo, Normal, Roughness, Metallic, Height)
via ComfyUI (AI 5-Map PBR Engine / DepthAnything V2 + RealVisXL V5 / SDXL 1.0) from:
  1. Text Prompt (Russian or English) or 289 Built-in Material Presets (12 Categories)
  2. Reference Image (Direct CHORD Photo-to-PBR, Seamless Img2Img + CHORD, or AI Vision Reference Extractor)
  3. Full Interior Reference Photo (AI extracts all room materials -> 1-click CoronaPhysicalMtl generation)

Automatically builds physically accurate `CoronaPhysicalMtl` materials in 3ds Max
with `CoronaBitmap` (sRGB for BaseColor, Linear gamma=1.0 for Roughness/Metallic/Normal/Height)
and `CoronaNormal`, placing them into the Material Editor and assigning to selected objects.
"""

import base64
import json
import os
import random
import re
import shutil
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from presets_data import (
    CATEGORY_KEYWORDS,
    CATEGORY_PRESET_PROMPTS,
    DEFAULT_PBR_MODEL_LABEL,
    DEFAULT_RESOLUTION_LABEL,
    PBR_MODEL_OPTIONS,
    PRESET_BUTTONS,
    PRESET_CATEGORIES_ORDER,
    RESOLUTION_OPTIONS,
    RU_TO_EN_MATERIALS,
)

COMFY_URL = os.environ.get("COMFY_URL", "http://100.118.26.47:8188")

_COMFY_GW_TOKEN_OBF = (
    10, 24, 8, 119, 29, 13, 119, 99, 28, 110, 27, 109, 25, 104, 31, 98,
    24, 107, 30, 108, 106, 111, 105, 27, 110, 31, 99, 104, 25, 109, 24, 98,
    30, 107, 28, 105, 31, 108, 27,
)


def _comfy_headers(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    hdrs = {"X-PBR-Gateway-Key": "".join(chr(b ^ 0x5A) for b in _COMFY_GW_TOKEN_OBF)}
    if extra:
        hdrs.update(extra)
    return hdrs


def _comfy_get(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers=_comfy_headers(), method="GET")
    return urllib.request.urlopen(req, timeout=timeout)
DEFAULT_OUTPUT_ROOT = r"D:\AI\MyAiAssistant\3D_Library\Corona_PBR_Materials"
MAX_BRIDGE_CMD_PATH = r"D:\AI\MyAiAssistant\asset_scout\data\bridge_cmd_max.ms"
DEFAULT_JSON_CHORD = os.path.join(_SCRIPT_DIR, "Corona_plagin_chord.json")
DEFAULT_JSON_DA2 = os.path.join(_SCRIPT_DIR, "Corona_plagin.json")


def _load_gemini_api_key() -> str:
    """Loads GEMINI_API_KEY from environment or D:\\AI\\MyAiAssistant\\.env."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    env_candidates = [
        r"D:\AI\MyAiAssistant\.env",
        os.path.join(os.path.dirname(_SCRIPT_DIR), ".env"),
    ]
    for env_path in env_candidates:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GEMINI_API_KEY="):
                            return line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception:
                pass
    return ""


def translate_or_clean_prompt(raw_prompt: str) -> str:
    """Translates Russian material prompt to English or cleans English prompt."""
    text = (raw_prompt or "").strip()
    if not text:
        return "oak wood parquet floor, herringbone pattern, natural timber"

    lower = text.lower()
    if lower in RU_TO_EN_MATERIALS:
        return RU_TO_EN_MATERIALS[lower]

    if re.search(r"[а-яА-ЯёЁ]", text):
        for ru_key, en_val in RU_TO_EN_MATERIALS.items():
            if ru_key == lower:
                return en_val
        try:
            q = urllib.parse.quote(text)
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=ru&tl=en&dt=t&q={q}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated = "".join(part[0] for part in data[0] if part and part[0])
                if translated.strip():
                    return translated.strip()
        except Exception:
            pass
        for ru_key, en_val in RU_TO_EN_MATERIALS.items():
            if ru_key in lower:
                return en_val

    return text


def make_slug(prompt_en: str) -> str:
    """Creates a clean PascalCase identifier from an English prompt."""
    words = re.findall(r"[A-Za-z0-9]+", prompt_en)
    stop = {
        "top", "down", "view", "of", "a", "an", "the", "seamless",
        "tileable", "texture", "with", "and", "surface", "flat", "even",
    }
    filtered = [w.capitalize() for w in words if w.lower() not in stop][:4]
    slug = "".join(filtered) if filtered else "Material"
    return slug[:28]


def detect_material_category(raw_prompt: str, prompt_en: str = "") -> str:
    """Detects one of the 12 material categories from the prompt."""
    for source_text in (raw_prompt or "", prompt_en or ""):
        clean_src = source_text.strip().lower()
        if not clean_src:
            continue
        for cat_k, items in CATEGORY_PRESET_PROMPTS.items():
            for _p_title, p_txt in items:
                if clean_src == p_txt.strip().lower():
                    return cat_k

    for source_text in (raw_prompt or "", prompt_en or ""):
        if not (source_text or "").strip():
            continue
        words = re.findall(r"[A-Z][a-z]+|[a-z]+|[0-9]+|[а-яА-ЯёЁ]+", source_text)
        low = " ".join(words).lower()
        if not low:
            continue
        best_cat = None
        best_pos = 10**9
        for cat, keywords in CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in ("stained", "hexagonal", "transparent", "translucent"):
                    continue
                if cat == "light" and kw == "light":
                    # Only match standalone 'light'/'lights', never 'lighting' or 'lighted'
                    pat = r"\blights?\b"
                    m_obj = re.search(pat, low)
                    pos = m_obj.start() if m_obj else -1
                elif re.match(r"^[a-z0-9 ]+$", kw):
                    pat = r"\b" + re.escape(kw) + r"(?:s|es|ed|ing)?\b"
                    m_obj = re.search(pat, low)
                    pos = m_obj.start() if m_obj else -1
                else:
                    pos = low.find(kw)
                if pos != -1 and pos < best_pos:
                    best_pos = pos
                    best_cat = cat
        if best_cat:
            return best_cat
    return "stone"


def preprocess_reference_for_seamless(
    image_path: str,
    target_size: int = 1024,
) -> str:
    """
    Pre-processes a reference photo/screenshot BEFORE uploading to ComfyUI so that both
    `img2img_seamless` and `chord_direct` produce 100% seamless, evenly-lit PBR textures:
      1. Trims 2% outer border (removes accidental screenshot window frames/edges).
      2. High-pass de-lighting (flattens room shadow/window lighting gradients while keeping
         exact RGB color and plaster/stone/wood strokes).
      3. 4-way toroidal raised-cosine cross-synthesis with variance preservation (makes the
         input image mathematically periodic in X and Y with zero contrast loss).
    Returns path to the pre-processed PNG file.
    """
    try:
        import numpy as np
        from PIL import Image
        from scipy.ndimage import gaussian_filter

        im = Image.open(image_path).convert("RGB")
        w0, h0 = im.size
        # 1. Trim 2% outer margin to avoid screenshot frames
        if w0 > 64 and h0 > 64:
            mx = max(1, int(w0 * 0.02))
            my = max(1, int(h0 * 0.02))
            im = im.crop((mx, my, w0 - mx, h0 - my))

        im = im.resize((target_size, target_size), Image.Resampling.BICUBIC)
        arr = np.asarray(im, dtype=np.float32)

        # 2. Intrinsic High-Pass De-Lighting (removes directional room shadows/highlights
        #    while preserving the true natural micro-contrast of the surface)
        sigma_delight = max(18.0, target_size * 0.12)
        mean_rgb = np.mean(arr, axis=(0, 1), keepdims=True)
        low_freq = np.zeros_like(arr)
        for c_i in range(3):
            low_freq[:, :, c_i] = gaussian_filter(arr[:, :, c_i], sigma=sigma_delight, mode="reflect")
        delit = (arr / (low_freq + 1.0)) * mean_rgb
        delit_mean = np.mean(delit, axis=(0, 1), keepdims=True)
        delit = (delit - delit_mean) * 1.15 + mean_rgb

        # 3. 4-Way Toroidal Raised-Cosine Synthesis with Variance Preservation
        h, w, _ = delit.shape
        ih = np.roll(delit, w // 2, axis=1)
        iv = np.roll(delit, h // 2, axis=0)
        ihv = np.roll(ih, h // 2, axis=0)

        wx = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(w, dtype=np.float32) / w))[None, :, None]
        wy = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(h, dtype=np.float32) / h))[:, None, None]

        blended = (
            wy * (wx * delit + (1.0 - wx) * ih)
            + (1.0 - wy) * (wx * iv + (1.0 - wx) * ihv)
        )
        # Variance preservation factor so blended zones never look blurry or ghosted
        var_scale = np.sqrt((wx ** 2 + (1.0 - wx) ** 2) * (wy ** 2 + (1.0 - wy) ** 2))
        b_mean = np.mean(blended, axis=(0, 1), keepdims=True)
        seamless = b_mean + (blended - b_mean) / np.maximum(var_scale, 0.5)

        # Final gentle periodic de-light pass so 4x4 tiling has zero low-frequency blotches
        for c_i in range(3):
            lf2 = gaussian_filter(seamless[:, :, c_i], sigma=target_size * 0.20, mode="wrap")
            seamless[:, :, c_i] = seamless[:, :, c_i] - lf2 + float(mean_rgb[0, 0, c_i])

        seamless_u8 = np.clip(seamless, 0, 255).astype(np.uint8)
        out_dir = os.path.join(_SCRIPT_DIR, "_temp_ref")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "preprocessed_seamless_ref.png")
        Image.fromarray(seamless_u8).save(out_path, format="PNG")
        return out_path
    except Exception:
        return image_path


def enforce_seamless_pbr_maps(downloaded: Dict[str, str]) -> None:
    """
    Post-processes downloaded PBR maps (Albedo, Normal, Roughness, Metallic, Height)
    to eliminate outer 0..24px convolutional border roll-off (bright/dark edge halos in Albedo/Roughness,
    edge bevels in Normal, and edge steps/domes in Height) while preserving 100% of high-frequency grain phase.
    """
    try:
        import numpy as np
        from PIL import Image
        from scipy.ndimage import gaussian_filter

        for kind, path in downloaded.items():
            if not path or not os.path.exists(path):
                continue
            im = Image.open(path)
            mode = im.mode
            arr = np.asarray(im, dtype=np.float32)
            if arr.ndim == 2:
                arr = arr[:, :, None]
            h, w, ch = arr.shape
            if h < 64 or w < 64:
                continue

            proc_c = min(3, ch)
            is_normal = (kind == "normal")
            is_height = (kind == "height")

            if kind in ("albedo", "roughness"):
                sig_m = max(24.0, float(min(h, w)) * 0.055)
                st_m = 0.85 if kind == "albedo" else 0.80
                for c_m in range(proc_c):
                    ch_m = arr[:, :, c_m]
                    m_val = float(np.mean(ch_m))
                    low_m = gaussian_filter(ch_m, sigma=sig_m, mode="wrap")
                    ch_f = ch_m - st_m * (low_m - m_val)
                    res = ch_f - m_val
                    loc_var = gaussian_filter(res * res, sigma=sig_m, mode="wrap")
                    loc_std = np.sqrt(np.maximum(loc_var, 1e-4))
                    glob_std = float(np.std(res))
                    if glob_std > 0.4:
                        scale_c = np.clip(glob_std / loc_std, 0.55, 1.45)
                        ch_f = m_val + res * (0.30 + 0.70 * scale_c)
                    arr[:, :, c_m] = np.clip(ch_f, 0.0, 255.0)

            B = max(16, int(min(h, w) * 0.024))
            ref_w = max(8, B // 2)
            flat = B // 2
            taper = max(1, B - flat)
            w_d = np.ones((B, 1), dtype=np.float32)
            t_idx = np.arange(taper, dtype=np.float32)[:, None]
            w_d[flat:] = 0.5 * (1.0 + np.cos(np.pi * t_idx / float(taper)))
            w_dx = w_d.T
            sig_par = max(32.0, float(min(h, w)) * 0.08)

            for c_i in range(proc_c):
                channel = arr[:, :, c_i].copy()
                if is_height:
                    pad_d = max(32.0, float(min(h, w)) * 0.06)
                    low_d = gaussian_filter(channel, sigma=pad_d, mode="wrap")
                    channel = channel - low_d + float(np.median(channel))

                prof_tb = gaussian_filter(channel, sigma=(0.8, sig_par), mode="wrap")
                ref_t = np.mean(prof_tb[B:B+ref_w, :], axis=0, keepdims=True)
                ref_b = np.mean(prof_tb[h-B-ref_w:h-B, :], axis=0, keepdims=True)
                ref_tb = 0.5 * (ref_t + ref_b)
                channel[:B, :] -= w_d * (prof_tb[:B, :] - ref_tb)
                channel[h-B:, :] -= w_d[::-1] * (prof_tb[h-B:, :] - ref_tb)

                prof_lr = gaussian_filter(channel, sigma=(sig_par, 0.8), mode="wrap")
                ref_l = np.mean(prof_lr[:, B:B+ref_w], axis=1, keepdims=True)
                ref_r = np.mean(prof_lr[:, w-B-ref_w:w-B], axis=1, keepdims=True)
                ref_lr = 0.5 * (ref_l + ref_r)
                channel[:, :B] -= w_dx * (prof_lr[:, :B] - ref_lr)
                channel[:, w-B:] -= w_dx[:, ::-1] * (prof_lr[:, w-B:] - ref_lr)

                adj_tb = float(np.mean(np.abs(channel[B+4, :] - channel[B+5, :])))
                seam_tb = float(np.mean(np.abs(channel[0, :] - channel[-1, :])))
                if is_height or seam_tb > max(adj_tb * 1.08, adj_tb + 0.6):
                    M = max(24, int(min(h, w) * 0.04)) if is_height else max(12, int(min(h, w) * 0.016))
                    sig_s = 1.5 if is_height else 4.0
                    diff_tb = gaussian_filter(channel[0:1, :] - channel[h-1:h, :], sigma=(0.5, sig_s), mode="wrap")
                    m_idx = np.arange(M, dtype=np.float32)[:, None]
                    ramp_m = 0.5 * (0.5 * (1.0 + np.cos(np.pi * m_idx / float(M))))
                    channel[:M, :] -= ramp_m * diff_tb
                    channel[h-M:, :] += ramp_m[::-1] * diff_tb

                adj_lr = float(np.mean(np.abs(channel[:, B+4] - channel[:, B+5])))
                seam_lr = float(np.mean(np.abs(channel[:, 0] - channel[:, -1])))
                if is_height or seam_lr > max(adj_lr * 1.08, adj_lr + 0.6):
                    M = max(24, int(min(h, w) * 0.04)) if is_height else max(12, int(min(h, w) * 0.016))
                    sig_s = 1.5 if is_height else 4.0
                    diff_lr = gaussian_filter(channel[:, 0:1] - channel[:, w-1:w], sigma=(sig_s, 0.5), mode="wrap")
                    m_idx = np.arange(M, dtype=np.float32)[None, :]
                    ramp_mx = 0.5 * (0.5 * (1.0 + np.cos(np.pi * m_idx / float(M))))
                    channel[:, :M] -= ramp_mx * diff_lr
                    channel[:, w-M:] += ramp_mx[:, ::-1] * diff_lr

                arr[:, :, c_i] = channel

            if is_normal and proc_c >= 3:
                for c_xy in (0, 1):
                    ch_n = arr[:, :, c_xy]
                    low_n = gaussian_filter(ch_n, sigma=48.0, mode="wrap")
                    arr[:, :, c_xy] = ch_n - low_n + 128.0
                nx = (arr[:, :, 0] / 255.0) * 2.0 - 1.0
                ny = (arr[:, :, 1] / 255.0) * 2.0 - 1.0
                nz = np.maximum(0.1, (arr[:, :, 2] / 255.0) * 2.0 - 1.0)
                norm = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
                arr[:, :, 0] = ((nx / norm) * 0.5 + 0.5) * 255.0
                arr[:, :, 1] = ((ny / norm) * 0.5 + 0.5) * 255.0
                arr[:, :, 2] = ((nz / norm) * 0.5 + 0.5) * 255.0

            out_u8 = np.clip(arr, 0, 255).astype(np.uint8)
            if mode == "L" or out_u8.shape[2] == 1:
                Image.fromarray(out_u8[:, :, 0], mode="L").save(path, format="PNG")
            else:
                Image.fromarray(out_u8[:, :, :3], mode="RGB").save(path, format="PNG")
    except Exception:
        pass


def upload_image_to_comfy(image_path: str) -> str:
    """
    Uploads a local reference image to ComfyUI (/upload/image) and returns the uploaded filename
    for use in a `LoadImage` node.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Reference image not found: {image_path}")

    boundary = f"----ComfyBoundary{random.randint(100000, 999999)}"
    filename = os.path.basename(image_path)
    ext = os.path.splitext(filename)[1].lower()
    mime = "image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg")

    with open(image_path, "rb") as f:
        file_bytes = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + file_bytes + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
        f"true\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{COMFY_URL}/upload/image",
        data=body,
        headers=_comfy_headers({"Content-Type": f"multipart/form-data; boundary={boundary}"}),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20.0) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    return res.get("name", filename)


def extract_materials_from_reference_image(
    image_path: str,
    target_hint: str = "",
) -> List[Dict[str, Any]]:
    """
    Uses Gemini Vision (`gemini-2.5-flash`) to analyze a reference photo (either a close-up surface
    photo or a full interior design reference photo) and extract a list of PBR material definitions.
    Each item contains:
      - title_ru: Russian title (e.g. "Светлый дубовый паркет ёлочкой")
      - surface_ru: Target surface in room (e.g. "Пол", "Стены", "Обивка дивана", "Столешница")
      - prompt_en: Detailed English SDXL prompt for seamless top-down texture generation
      - category: One of (wood, stone, concrete, tile, brick, metal, fabric, glass, mirror, plastic, light)
      - roughness_mult: Recommended roughness multiplier (0.2..1.0)
      - ior: Recommended Corona IOR (1.35..2.4)
      - metalness: 0 or 1
    """
    api_key = _load_gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не найден в .env или переменных окружения.")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Файл референса не найден: {image_path}")

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg")

    hint_instruction = (
        f"Пользователь особо указал интересующую поверхность/материал: '{target_hint}'. "
        "Поставь этот материал ПЕРВЫМ в списке и опиши его максимально точно."
        if target_hint.strip()
        else "Извлеки все ключевые отделочные материалы и ткани, видимые на этом референсе интерьера/поверхности (от 1 до 7 материалов)."
    )

    system_prompt = (
        "Ты — ведущий 3D-художник и специалист по шейдерам Corona Renderer (CoronaPhysicalMtl) и генерации бесшовных текстур в SDXL + AI 5-Map PBR Engine.\n"
        f"{hint_instruction}\n"
        "Верни СТРОГО валидный JSON-массив объектов (без markdown-обертки), где каждый объект имеет поля:\n"
        '- "title_ru": краткое понятное название материала на русском (например, "Светлый травертин с порами", "Французский дуб ёлочкой", "Бежевое букле дивана")\n'
        '- "surface_ru": где применяется (например, "Стены", "Пол", "Диван", "Кухонный остров", "Акцентный металл")\n'
        '- "prompt_en": детальный промпт на английском языке для генерации бесшовной PBR-текстуры (вид сверху, цвет, порода дерева/камня, характер прожилок/плетения, степень матовости/глянца)\n'
        '- "category": строго одно из значений: "wood", "stone", "concrete", "tile", "brick", "metal", "fabric", "glass", "mirror", "plastic", "light"\n'
        '- "ior": число float (обычно 1.5 для дерева/камня/пластика, 1.35 для ткани, 1.52 для стекла)\n'
        '- "metalness": 0 для диэлектриков, 1 для чистых металлов/зеркал\n'
        '- "clearcoat": число от 0.0 до 0.5 (например, 0.25 для лакированного паркета или полированного мрамора, 0.0 для матовых поверхностей)'
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": system_prompt},
                    {"inline_data": {"mime_type": mime, "data": img_b64}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))

    raw_text = (
        resp_data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "[]")
    )
    raw_text = re.sub(r"^```(?:json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()
    parsed = json.loads(raw_text)
    if isinstance(parsed, dict):
        parsed = parsed.get("materials", [parsed])
    return parsed if isinstance(parsed, list) else []


def _build_txt2pbr_workflow(
    prompt_en: str,
    res_px: int = 1024,
    pipeline_mode: str = "chord",
    ckpt_name: str = "SDXL\\realvisxlV50_v50Bakedvae.safetensors",
) -> Dict[str, Any]:
    """Builds the ComfyUI workflow dict for Text/Preset -> Seamless PBR."""
    json_path = DEFAULT_JSON_CHORD if pipeline_mode == "chord" else DEFAULT_JSON_DA2
    if not os.path.exists(json_path):
        json_path = DEFAULT_JSON_DA2
    with open(json_path, "r", encoding="utf-8") as f:
        workflow = json.load(f)

    if "71" in workflow and "inputs" in workflow["71"]:
        workflow["71"]["inputs"]["ckpt_name"] = ckpt_name

    full_positive = (
        f"Top-down orthographic view of a seamless tileable {prompt_en}, "
        "flat even studio lighting, no shadows, photorealistic 8k PBR material, sharp micro-details"
    )
    full_negative = (
        "perspective, angled view, 3d render, harsh shadows, directional lighting, "
        "specular highlights, vignette, depth of field, blurry, low quality, seam, visible border, watermark, text"
    )

    if "72" in workflow and "inputs" in workflow["72"]:
        workflow["72"]["inputs"]["text"] = full_positive
    if "73" in workflow and "inputs" in workflow["73"]:
        workflow["73"]["inputs"]["text"] = full_negative

    if "77" in workflow and "inputs" in workflow["77"]:
        workflow["77"]["inputs"]["width"] = 1024
        workflow["77"]["inputs"]["height"] = 1024

    _attach_pbr_decomposition_nodes(workflow, source_image_node=["102", 0], res_px=res_px, pipeline_mode=pipeline_mode)

    for _nid, node_data in workflow.items():
        inputs = node_data.get("inputs", {})
        if "seed" in inputs:
            inputs["seed"] = random.randint(1, 2**31 - 1)

    return workflow


def _build_reference_pbr_workflow(
    uploaded_comfy_filename: str,
    ref_mode: str = "chord_direct",
    prompt_en: str = "",
    denoise: float = 0.55,
    res_px: int = 1024,
    pipeline_mode: str = "chord",
    ckpt_name: str = "SDXL\\realvisxlV50_v50Bakedvae.safetensors",
) -> Dict[str, Any]:
    """
    Builds a ComfyUI workflow for Reference Image -> Corona PBR:
      - ref_mode == 'chord_direct':
          Directly feeds the uploaded photo into ImageScale -> EnhanceDetail -> AI 5-Map PBR Engine
          (extracts de-lit Albedo, Normal, Roughness, Metallic, Height directly from the reference photo).
      - ref_mode == 'img2img_seamless':
          Loads the reference image -> scales to 1024x1024 -> VAEEncode -> SeamlessTile KSampler (denoise)
          -> CircularVAEDecode -> EnhanceDetail -> AI 5-Map PBR Engine (creates a 100% seamless tileable texture
          preserving the color/structure of the reference photo!).
    """
    if ref_mode == "chord_direct":
        workflow: Dict[str, Any] = {
            "200": {
                "class_type": "LoadImage",
                "inputs": {"image": uploaded_comfy_filename},
            },
            "201": {
                "class_type": "ImageScale",
                "inputs": {
                    "upscale_method": "bicubic",
                    "width": res_px,
                    "height": res_px,
                    "crop": "center",
                    "image": ["200", 0],
                },
            },
            "102": {
                "class_type": "EnhanceDetail",
                "inputs": {
                    "images": ["201", 0],
                    "filter_radius": 2,
                    "sigma": 0.1,
                    "denoise": 0.03,
                    "detail_mult": 1.25,
                },
            },
            "76": {"class_type": "SaveImage", "inputs": {"filename_prefix": "api_albedo", "images": ["102", 0]}},
            "80": {"class_type": "SaveImage", "inputs": {"filename_prefix": "api_height", "images": ["102", 0]}},
            "82": {"class_type": "SaveImage", "inputs": {"filename_prefix": "api_normal", "images": ["102", 0]}},
            "85": {"class_type": "SaveImage", "inputs": {"filename_prefix": "api_roughness", "images": ["102", 0]}},
        }
        _attach_pbr_decomposition_nodes(workflow, source_image_node=["102", 0], res_px=res_px, pipeline_mode=pipeline_mode)
        return workflow

    # Otherwise: 'img2img_seamless' (Reference Image -> Seamless Tileable Variation -> CHORD 5-map PBR)
    workflow = _build_txt2pbr_workflow(
        prompt_en=prompt_en or "homogeneous architectural surface texture, uniform flat lighting, consistent natural micro-relief",
        res_px=res_px,
        pipeline_mode=pipeline_mode,
        ckpt_name=ckpt_name,
    )
    workflow.pop("77", None)  # Replace EmptyLatentImage with LoadImage -> ImageScale -> MakeCircularVAE -> VAEEncode
    workflow["199"] = {
        "class_type": "MakeCircularVAE",
        "inputs": {
            "vae": ["71", 2],
            "tiling": "enable",
            "copy_vae": "Modify in place",
        },
    }
    workflow["200"] = {
        "class_type": "LoadImage",
        "inputs": {"image": uploaded_comfy_filename},
    }
    workflow["201"] = {
        "class_type": "ImageScale",
        "inputs": {
            "upscale_method": "bicubic",
            "width": 1024,
            "height": 1024,
            "crop": "center",
            "image": ["200", 0],
        },
    }
    workflow["202"] = {
        "class_type": "VAEEncode",
        "inputs": {
            "pixels": ["201", 0],
            "vae": ["199", 0],
        },
    }
    if "75" in workflow and "inputs" in workflow["75"]:
        workflow["75"]["inputs"]["vae"] = ["199", 0]
    if "102" in workflow and "inputs" in workflow["102"]:
        workflow["102"]["inputs"]["detail_mult"] = 1.12
        workflow["102"]["inputs"]["denoise"] = 0.02
    if "105" in workflow and "inputs" in workflow["105"]:
        workflow["105"]["inputs"]["latent_image"] = ["202", 0]
        # Because preprocess_reference_for_seamless already creates a 100% seamless de-lit tile,
        # keep effective denoise gentle (~0.26..0.32) so SDXL preserves the exact reference texture
        eff_denoise = float(denoise) if float(denoise) <= 0.35 else min(0.32, float(denoise) * 0.55)
        workflow["105"]["inputs"]["denoise"] = float(max(0.18, min(0.85, eff_denoise)))
        workflow["105"]["inputs"]["cfg"] = 4.0

    return workflow


def _attach_pbr_decomposition_nodes(
    workflow: Dict[str, Any],
    source_image_node: List[Any],
    res_px: int = 1024,
    pipeline_mode: str = "chord",
) -> None:
    """Attaches either AI 5-Map PBR Engine (5-map) or DepthAnything V2 (4-map) nodes to `workflow`."""
    if pipeline_mode == "chord":
        for old_id in ("78", "79", "81", "83", "84", "108", "109"):
            workflow.pop(old_id, None)

        chord_img_input = source_image_node
        if res_px != 1024 and "201" not in workflow:
            workflow["90"] = {
                "class_type": "ImageScale",
                "inputs": {
                    "upscale_method": "nearest-exact" if res_px > 1024 else "area",
                    "width": res_px,
                    "height": res_px,
                    "crop": "disabled",
                    "image": source_image_node,
                },
            }
            chord_img_input = ["90", 0]

        workflow["110"] = {
            "class_type": "ChordLoadModel",
            "inputs": {"ckpt_name": "chord_v1.safetensors"},
        }
        workflow["111"] = {
            "class_type": "ChordMaterialEstimation",
            "inputs": {
                "chord_model": ["110", 0],
                "image": chord_img_input,
            },
        }
        workflow["112"] = {
            "class_type": "ChordNormalToHeight",
            "inputs": {"normal": ["111", 1]},
        }
        workflow["76"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "api_albedo", "images": ["111", 0]},
        }
        workflow["82"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "api_normal", "images": ["111", 1]},
        }
        workflow["85"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "api_roughness", "images": ["111", 2]},
        }
        workflow["80"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "api_height", "images": ["112", 0]},
        }
        workflow["86"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "api_metallic", "images": ["111", 3]},
        }
    else:
        workflow["79"] = {
            "class_type": "DownloadAndLoadDepthAnythingV2Model",
            "inputs": {
                "model": "depth_anything_v2_vitl_fp16.safetensors",
                "precision": "fp32",
            },
        }
        workflow["78"] = {
            "class_type": "DepthAnything_V2",
            "inputs": {
                "da_model": ["79", 0],
                "images": source_image_node,
            },
        }
        workflow["81"] = {
            "class_type": "NormalMapSimple",
            "inputs": {
                "images": source_image_node,
                "scale_XY": 1.5,
            },
        }
        workflow["83"] = {
            "class_type": "ImageDesaturate+",
            "inputs": {
                "image": source_image_node,
                "factor": 1.0,
                "method": "luminance (Rec.709)",
            },
        }
        workflow["84"] = {
            "class_type": "ImageInvert",
            "inputs": {"image": ["83", 0]},
        }
        workflow["76"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "api_albedo", "images": source_image_node}}
        workflow["80"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "api_height", "images": ["78", 0]}}
        workflow["82"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "api_normal", "images": ["81", 0]}}
        workflow["85"] = {"class_type": "SaveImage", "inputs": {"filename_prefix": "api_roughness", "images": ["84", 0]}}


def execute_comfy_workflow_and_download(
    workflow: Dict[str, Any],
    dest_folder: str,
    asset_base_name: str,
    progress_cb: Optional[Callable[[str], None]] = None,
    timeout_sec: int = 600,
) -> Dict[str, str]:
    """
    Submits `workflow` to ComfyUI (`http://127.0.0.1:8188/prompt`), waits for completion,
    and downloads the generated PBR textures (`albedo`, `normal`, `roughness`, `metallic`, `height`)
    into `dest_folder`.
    """
    os.makedirs(dest_folder, exist_ok=True)
    req = urllib.request.Request(
        f"{COMFY_URL}/prompt",
        data=json.dumps({"prompt": workflow}).encode("utf-8"),
        headers=_comfy_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
    prompt_id = res_data["prompt_id"]

    start_t = time.time()
    node_to_kind = {
        "76": "albedo",
        "80": "height",
        "82": "normal",
        "85": "roughness",
        "86": "metallic",
        "91": "albedo",
        "92": "height",
        "93": "normal",
        "94": "roughness",
        "95": "metallic",
    }

    downloaded: Dict[str, str] = {}
    while True:
        elapsed = int(time.time() - start_t)
        if elapsed > timeout_sec:
            raise TimeoutError(f"ComfyUI generation timed out after {timeout_sec}s")
        if progress_cb:
            progress_cb(f"Генерация в ComfyUI... ({elapsed} сек)")

        try:
            with _comfy_get(f"{COMFY_URL}/history/{prompt_id}", timeout=5.0) as h_resp:
                history = json.loads(h_resp.read().decode("utf-8"))
            if prompt_id in history:
                entry = history[prompt_id]
                st_info = entry.get("status", {})
                if st_info.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI internal error: {st_info}")

                outputs = entry.get("outputs", {})
                for nid, node_out in outputs.items():
                    for image in node_out.get("images", []):
                        fname = image["filename"]
                        kind = node_to_kind.get(str(nid))
                        if not kind:
                            low_f = fname.lower()
                            if "normal" in low_f:
                                kind = "normal"
                            elif "rough" in low_f:
                                kind = "roughness"
                            elif "height" in low_f:
                                kind = "height"
                            elif "metal" in low_f:
                                kind = "metallic"
                            else:
                                kind = "albedo"

                        params = urllib.parse.urlencode(
                            {
                                "filename": fname,
                                "subfolder": image.get("subfolder", ""),
                                "type": image.get("type", "output"),
                            }
                        )
                        img_bytes = _comfy_get(f"{COMFY_URL}/view?{params}", timeout=20.0).read()
                        clean_filename = f"T_{asset_base_name}_{kind.capitalize()}.png"
                        local_path = os.path.join(dest_folder, clean_filename)
                        with open(local_path, "wb") as out_f:
                            out_f.write(img_bytes)
                        downloaded[kind] = local_path

                try:
                    free_req = urllib.request.Request(
                        f"{COMFY_URL}/free",
                        data=b'{"unload_models": false, "free_memory": true}',
                        headers=_comfy_headers({"Content-Type": "application/json"}),
                        method="POST",
                    )
                    urllib.request.urlopen(free_req, timeout=3.0).read()
                except Exception:
                    pass
                break
        except RuntimeError:
            raise
        except Exception:
            pass
        time.sleep(1.0)

    enforce_seamless_pbr_maps(downloaded)
    return downloaded


def build_corona_physical_mtl_maxscript(
    material_name: str,
    category: str,
    tex_paths: Dict[str, str],
    medit_slot: int = 1,
    apply_to_selection: bool = True,
    uvw_box_mm: float = 1000.0,
    tiling_uv: float = 1.0,
    bump_strength: float = 1.0,
    enable_displacement: bool = False,
    displacement_max_mm: float = 5.0,
    custom_ior: Optional[float] = None,
    custom_clearcoat: Optional[float] = None,
    custom_metalness: Optional[int] = None,
) -> str:
    """
    Generates MAXScript code that creates a native `CoronaPhysicalMtl` (with fallback to `CoronaLegacyMtl`),
    configures `CoronaBitmap` nodes with physically accurate gamma:
      - BaseColor (Albedo): `gamma = -1.0` (Automatic sRGB)
      - Roughness, Metallic, Normal, Height: `gamma = 1.0` (Linear)
    wires `CoronaNormal` with `additionalBump` (Height map), sets category-specific physical parameters
    (sheen for fabric, clearcoat for wood/stone/tile, metalnessMode for metal/mirror, refraction for glass,
    self-illum for light), assigns to `meditMaterials[medit_slot]`, and optionally applies to `selection`.
    """
    albedo_p = (tex_paths.get("albedo") or "").replace("\\", "/")
    normal_p = (tex_paths.get("normal") or "").replace("\\", "/")
    rough_p = (tex_paths.get("roughness") or "").replace("\\", "/")
    metal_p = (tex_paths.get("metallic") or "").replace("\\", "/")
    height_p = (tex_paths.get("height") or "").replace("\\", "/")

    slot = max(1, min(24, int(medit_slot)))
    cat = (category or "stone").lower()

    # Category-specific physical defaults
    ior = custom_ior if custom_ior is not None else 1.50
    clearcoat = custom_clearcoat if custom_clearcoat is not None else 0.0
    sheen = 0.0
    sheen_rough = 0.5
    metalness_mode = custom_metalness if custom_metalness is not None else 0
    refraction = 0.0
    self_illum = 0.0
    anisotropy = 0.0

    if cat == "wood":
        ior = custom_ior or 1.52
        clearcoat = custom_clearcoat if custom_clearcoat is not None else 0.15
    elif cat in ("stone", "tile"):
        ior = custom_ior or 1.55
        clearcoat = custom_clearcoat if custom_clearcoat is not None else 0.20
    elif cat == "concrete" or cat == "brick":
        ior = custom_ior or 1.50
        clearcoat = 0.0
    elif cat == "fabric":
        ior = custom_ior or 1.35
        sheen = 0.35
        sheen_rough = 0.55
    elif cat == "metal":
        metalness_mode = 1
        anisotropy = 0.25
    elif cat == "mirror":
        metalness_mode = 1
    elif cat == "glass":
        ior = custom_ior or 1.52
        refraction = 1.0
    elif cat == "light":
        self_illum = 5.0

    apply_str = "true" if apply_to_selection else "false"
    disp_str = "true" if enable_displacement else "false"

    ms = f"""(
    try (
        if not (matchPattern (classOf renderers.current as string) pattern:"*Corona*") do (
            renderers.current = Corona()
        )
        if not (matchPattern (classOf renderers.medit as string) pattern:"*Corona*") do (
            renderers.medit_locked = false
            renderers.medit = Corona()
            renderers.medit_locked = true
        )
    ) catch ()
    local matName = "{material_name}"
    local albedoPath = "{albedo_p}"
    local normalPath = "{normal_p}"
    local roughPath = "{rough_p}"
    local metalPath = "{metal_p}"
    local heightPath = "{height_p}"
    local tileUV = {tiling_uv:.3f}
    local uvwSize = {uvw_box_mm:.1f}
    local bumpMult = {bump_strength:.3f}
    local useDisp = {disp_str}
    local dispMax = {displacement_max_mm:.2f}
    local applyToSel = {apply_str}
    local meditIdx = {slot}

    fn makeCoronaTex pathStr isLinear uvwTile = (
        if pathStr == "" or not (doesFileExist pathStr) do return undefined
        local bmp = undefined
        try (
            bmp = CoronaBitmap()
            bmp.filename = pathStr
            bmp.realWorldScale = false
            bmp.uvwScale = [uvwTile, uvwTile, 1.0]
            if isLinear then (
                bmp.gamma = 1.0
            ) else (
                bmp.gamma = -1.0
            )
        ) catch (
            bmp = Bitmaptexture fileName:pathStr
            bmp.coords.realWorldScale = false
            bmp.coords.U_Tiling = uvwTile
            bmp.coords.V_Tiling = uvwTile
        )
        bmp
    )

    local mtl = undefined
    try (
        mtl = CoronaPhysicalMtl name:matName
        mtl.baseLevel = 1.0
        mtl.baseIor = {ior:.3f}
        mtl.roughnessMode = 0 -- 0 = Roughness
        mtl.metalnessMode = {metalness_mode}

        local texAlbedo = makeCoronaTex albedoPath false tileUV
        local texRough  = makeCoronaTex roughPath true tileUV
        local texNormal = makeCoronaTex normalPath true tileUV
        local texHeight = makeCoronaTex heightPath true tileUV
        local texMetal  = makeCoronaTex metalPath true tileUV

        if texAlbedo != undefined do (
            mtl.baseTexmap = texAlbedo
            mtl.baseTexmapOn = true
        )
        if texRough != undefined do (
            mtl.baseRoughnessTexmap = texRough
            mtl.baseRoughnessTexmapOn = true
        )
        if texMetal != undefined and {metalness_mode} == 0 do (
            mtl.metalnessTexmap = texMetal
            mtl.metalnessTexmapOn = true
        )
        if texNormal != undefined do (
            local cNorm = CoronaNormal()
            cNorm.normalMap = texNormal
            cNorm.addGamma = false
            cNorm.multiplier = bumpMult
            if texHeight != undefined do (
                cNorm.additionalBump = texHeight
                cNorm.additionalBumpOn = true
                cNorm.additionalBumpStrength = 0.35
            )
            mtl.baseBumpTexmap = cNorm
            mtl.baseBumpTexmapOn = true
            mtl.baseBumpMapAmount = bumpMult
        )
        if texHeight != undefined do (
            mtl.displacementTexmap = texHeight
            mtl.displacementTexmapOn = useDisp
            mtl.displacementMinimum = 0.0
            mtl.displacementMaximum = dispMax
        )

        -- Category Physical Enhancements
        if {clearcoat:.3f} > 0.0 do (
            mtl.clearcoatAmount = {clearcoat:.3f}
            mtl.clearcoatRoughness = 0.12
        )
        if {sheen:.3f} > 0.0 do (
            mtl.sheenAmount = {sheen:.3f}
            mtl.sheenRoughness = {sheen_rough:.3f}
        )
        if {anisotropy:.3f} > 0.0 do (
            mtl.baseAnisotropy = {anisotropy:.3f}
        )
        if {refraction:.3f} > 0.0 do (
            mtl.refractionAmount = {refraction:.3f}
        )
        if {self_illum:.3f} > 0.0 do (
            mtl.selfIllumLevel = {self_illum:.3f}
            if texAlbedo != undefined do (
                mtl.selfIllumTexmap = texAlbedo
                mtl.selfIllumTexmapOn = true
            )
        )
    ) catch (
        -- Fallback to CoronaLegacyMtl
        mtl = CoronaLegacyMtl name:matName
        local texAlbedo = makeCoronaTex albedoPath false tileUV
        if texAlbedo != undefined do mtl.texmapDiffuse = texAlbedo
    )

    if mtl != undefined do (
        try (meditMaterials[meditIdx] = mtl) catch ()
        try (
            local viewIdx = sme.GetViewByName "ComfyUI_PBR"
            if viewIdx == 0 do viewIdx = sme.CreateView "ComfyUI_PBR"
            local v = sme.GetView viewIdx
            v.CreateNode mtl [50, 50]
            v.LayoutAll()
        ) catch ()
        try (
            if ro_CoronaComfyPBRStudio != undefined do (
                ro_CoronaComfyPBRStudio.lbl_status.text = "Done! " + matName + " -> Slot #" + (meditIdx as string) + " & SME [ComfyUI_PBR]"
            )
        ) catch ()
        if applyToSel and selection.count > 0 do (
            for obj in selection where isValidNode obj and superClassOf obj == GeometryClass do (
                obj.material = mtl
                if uvwSize > 0.0 do (
                    local hasUVW = false
                    for m in obj.modifiers where classOf m == Uvwmap do hasUVW = true
                    if not hasUVW do (
                        try (
                            addModifier obj (Uvwmap maptype:4 length:uvwSize width:uvwSize height:uvwSize)
                        ) catch ()
                    )
                )
            )
        )
        redrawViews()
    )
)
"""
    return ms


def send_maxscript_to_3dsmax(ms_code: str) -> bool:
    """Writes MAXScript code to `bridge_cmd_max.ms` for immediate execution in 3ds Max."""
    try:
        os.makedirs(os.path.dirname(MAX_BRIDGE_CMD_PATH), exist_ok=True)
        with open(MAX_BRIDGE_CMD_PATH, "w", encoding="utf-8") as f:
            f.write(ms_code)
        return True
    except Exception:
        return False


def generate_corona_pbr_from_prompt(
    prompt_text: str,
    res_px: int = 1024,
    pipeline_mode: str = "chord",
    ckpt_name: str = "SDXL\\realvisxlV50_v50Bakedvae.safetensors",
    medit_slot: int = 1,
    apply_to_selection: bool = True,
    uvw_box_mm: float = 1000.0,
    tiling_uv: float = 1.0,
    bump_strength: float = 1.0,
    enable_displacement: bool = False,
    custom_ior: Optional[float] = None,
    custom_clearcoat: Optional[float] = None,
    custom_metalness: Optional[int] = None,
    output_root: str = DEFAULT_OUTPUT_ROOT,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    End-to-end pipeline:
      1. Translates/cleans `prompt_text` and detects category.
      2. Runs SDXL + SeamlessTile + AI 5-Map PBR Engine (or DepthAnything V2) in ComfyUI.
      3. Saves the 5 PBR maps into `D:\\AI\\MyAiAssistant\\3D_Library\\Corona_PBR_Materials\\<category>\\<material_name>\\`.
      4. Builds `CoronaPhysicalMtl` in 3ds Max, puts it in `meditMaterials[medit_slot]`, and applies to `selection`.
    """
    prompt_en = translate_or_clean_prompt(prompt_text)
    category = detect_material_category(prompt_text, prompt_en)
    slug = make_slug(prompt_en)
    res_tag = {512: "512", 1024: "1K", 2048: "2K", 4096: "4K"}.get(res_px, f"{res_px}")
    stamp = random.randint(10, 99)
    asset_base_name = f"{slug}_{res_tag}_{stamp}"
    material_name = f"M_Corona_{category.capitalize()}_{asset_base_name}"
    dest_folder = os.path.join(output_root, category, asset_base_name)

    if progress_cb:
        progress_cb(f"Подготовка воркфлоу [{pipeline_mode.upper()} {res_tag}]: '{prompt_en}'...")

    workflow = _build_txt2pbr_workflow(
        prompt_en=prompt_en,
        res_px=res_px,
        pipeline_mode=pipeline_mode,
        ckpt_name=ckpt_name,
    )
    downloaded = execute_comfy_workflow_and_download(
        workflow=workflow,
        dest_folder=dest_folder,
        asset_base_name=asset_base_name,
        progress_cb=progress_cb,
    )

    if progress_cb:
        progress_cb(f"Создание CoronaPhysicalMtl ({material_name}) в 3ds Max...")

    ms_code = build_corona_physical_mtl_maxscript(
        material_name=material_name,
        category=category,
        tex_paths=downloaded,
        medit_slot=medit_slot,
        apply_to_selection=apply_to_selection,
        uvw_box_mm=uvw_box_mm,
        tiling_uv=tiling_uv,
        bump_strength=bump_strength,
        enable_displacement=enable_displacement,
        custom_ior=custom_ior,
        custom_clearcoat=custom_clearcoat,
        custom_metalness=custom_metalness,
    )
    sent = send_maxscript_to_3dsmax(ms_code)

    return {
        "status": "ok",
        "material_name": material_name,
        "category": category,
        "prompt_en": prompt_en,
        "dest_folder": dest_folder,
        "textures": downloaded,
        "sent_to_max": sent,
    }


def generate_corona_pbr_from_reference(
    reference_image_path: str,
    ref_mode: str = "img2img_seamless",
    prompt_hint: str = "",
    denoise: float = 0.55,
    res_px: int = 1024,
    pipeline_mode: str = "chord",
    ckpt_name: str = "SDXL\\realvisxlV50_v50Bakedvae.safetensors",
    medit_slot: int = 1,
    apply_to_selection: bool = True,
    uvw_box_mm: float = 1000.0,
    tiling_uv: float = 1.0,
    bump_strength: float = 1.0,
    enable_displacement: bool = False,
    output_root: str = DEFAULT_OUTPUT_ROOT,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Generates a Corona PBR material from a Reference Image (`reference_image_path`) in one of 3 modes:
      - `chord_direct`: Direct photo-to-PBR decomposition via AI 5-Map PBR Engine (`ChordMaterialEstimation`).
      - `img2img_seamless`: Uploads reference photo to ComfyUI, runs SeamlessTile SDXL Img2Img (`denoise`),
        then decomposes into 5 PBR maps via AI 5-Map PBR Engine.
      - `ai_vision_pbr`: Uses Gemini Vision to extract the exact material prompt & physical parameters from
        the reference image, then generates seamless 5-map PBR textures in ComfyUI.
    """
    if not os.path.exists(reference_image_path):
        raise FileNotFoundError(f"Файл референса не найден: {reference_image_path}")

    custom_ior = None
    custom_clearcoat = None
    custom_metalness = None

    if ref_mode == "ai_vision_pbr":
        if progress_cb:
            progress_cb("AI Vision анализирует референс-изображение...")
        extracted = extract_materials_from_reference_image(reference_image_path, target_hint=prompt_hint)
        if extracted:
            top = extracted[0]
            prompt_en = top.get("prompt_en") or translate_or_clean_prompt(prompt_hint or "natural stone texture")
            custom_ior = float(top.get("ior", 1.5))
            custom_clearcoat = float(top.get("clearcoat", 0.0))
            custom_metalness = int(top.get("metalness", 0))
        else:
            prompt_en = translate_or_clean_prompt(prompt_hint or "natural architectural surface texture")
        return generate_corona_pbr_from_prompt(
            prompt_text=prompt_en,
            res_px=res_px,
            pipeline_mode=pipeline_mode,
            ckpt_name=ckpt_name,
            medit_slot=medit_slot,
            apply_to_selection=apply_to_selection,
            uvw_box_mm=uvw_box_mm,
            tiling_uv=tiling_uv,
            bump_strength=bump_strength,
            enable_displacement=enable_displacement,
            custom_ior=custom_ior,
            custom_clearcoat=custom_clearcoat,
            custom_metalness=custom_metalness,
            output_root=output_root,
            progress_cb=progress_cb,
        )

    # Pre-process reference image (de-light + 4-way toroidal seamless synthesis) before uploading
    if progress_cb:
        progress_cb("Де-лайтинг и бесшовная подготовка референса + загрузка в ComfyUI...")
    prepped_ref_path = preprocess_reference_for_seamless(reference_image_path, target_size=max(1024, res_px))
    uploaded_name = upload_image_to_comfy(prepped_ref_path)

    prompt_en = translate_or_clean_prompt(prompt_hint) if prompt_hint.strip() else ""
    category = detect_material_category(prompt_hint, prompt_en) if prompt_hint.strip() else "concrete"
    if not prompt_en:
        prompt_en = "homogeneous architectural plaster stone surface texture, uniform flat studio illumination, natural micro-relief"
    slug = make_slug(prompt_en if prompt_hint.strip() else os.path.splitext(os.path.basename(reference_image_path))[0])
    res_tag = {512: "512", 1024: "1K", 2048: "2K", 4096: "4K"}.get(res_px, f"{res_px}")
    stamp = random.randint(10, 99)
    asset_base_name = f"Ref_{slug}_{res_tag}_{stamp}"
    material_name = f"M_Corona_{category.capitalize()}_{asset_base_name}"
    dest_folder = os.path.join(output_root, category, asset_base_name)

    # Save a copy of the reference image inside the material folder for traceability
    os.makedirs(dest_folder, exist_ok=True)
    try:
        shutil.copy2(reference_image_path, os.path.join(dest_folder, "reference_source" + os.path.splitext(reference_image_path)[1]))
    except Exception:
        pass

    workflow = _build_reference_pbr_workflow(
        uploaded_comfy_filename=uploaded_name,
        ref_mode=ref_mode,
        prompt_en=prompt_en,
        denoise=denoise,
        res_px=res_px,
        pipeline_mode=pipeline_mode,
        ckpt_name=ckpt_name,
    )
    downloaded = execute_comfy_workflow_and_download(
        workflow=workflow,
        dest_folder=dest_folder,
        asset_base_name=asset_base_name,
        progress_cb=progress_cb,
    )

    if progress_cb:
        progress_cb(f"Создание CoronaPhysicalMtl ({material_name}) в 3ds Max...")

    ms_code = build_corona_physical_mtl_maxscript(
        material_name=material_name,
        category=category,
        tex_paths=downloaded,
        medit_slot=medit_slot,
        apply_to_selection=apply_to_selection,
        uvw_box_mm=uvw_box_mm,
        tiling_uv=tiling_uv,
        bump_strength=bump_strength,
        enable_displacement=enable_displacement,
    )
    sent = send_maxscript_to_3dsmax(ms_code)

    return {
        "status": "ok",
        "material_name": material_name,
        "category": category,
        "ref_mode": ref_mode,
        "prompt_en": prompt_en,
        "dest_folder": dest_folder,
        "textures": downloaded,
        "sent_to_max": sent,
    }


# ============================================================================
# Standalone / 3ds Max Companion GUI (Tkinter Dark Studio)
# ============================================================================

def launch_corona_pbr_studio() -> None:
    """Launches the dark-themed ComfyUI Corona PBR Studio desktop window."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("ComfyUI Corona PBR Studio — 3ds Max & Corona Renderer")
    root.geometry("1060x820")
    root.configure(bg="#14161d")

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("TFrame", background="#14161d")
    style.configure("Card.TFrame", background="#1d202b")
    style.configure("TLabel", background="#14161d", foreground="#e4e8f2", font=("Segoe UI", 9))
    style.configure("Card.TLabel", background="#1d202b", foreground="#e4e8f2", font=("Segoe UI", 9))
    style.configure("Title.TLabel", background="#14161d", foreground="#67b7ff", font=("Segoe UI", 13, "bold"))
    style.configure("Section.TLabel", background="#1d202b", foreground="#79c0ff", font=("Segoe UI", 10, "bold"))
    style.configure("TButton", background="#2b3142", foreground="#ffffff", font=("Segoe UI", 9, "bold"), padding=5)
    style.map("TButton", background=[("active", "#3b445e")])
    style.configure("Accent.TButton", background="#1f6feb", foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=7)
    style.map("Accent.TButton", background=[("active", "#388bfd")])
    style.configure("Green.TButton", background="#238636", foreground="#ffffff", font=("Segoe UI", 10, "bold"), padding=7)
    style.map("Green.TButton", background=[("active", "#2ea043")])

    # Header
    hdr = ttk.Frame(root)
    hdr.pack(fill="x", padx=14, pady=(10, 6))
    ttk.Label(hdr, text="ComfyUI Corona PBR Studio (3ds Max + CoronaPhysicalMtl)", style="Title.TLabel").pack(side="left")
    status_var = tk.StringVar(value="[Готово] Выберите пресет, введите промпт или загрузите референс-изображение")
    status_lbl = tk.Label(hdr, textvariable=status_var, bg="#14161d", fg="#56d364", font=("Segoe UI", 9, "bold"))
    status_lbl.pack(side="right")

    main_pane = tk.PanedWindow(root, orient="horizontal", bg="#14161d", sashwidth=6, bd=0)
    main_pane.pack(fill="both", expand=True, padx=14, pady=6)

    # Left Column: Prompt + Reference Image + Corona Parameters
    left_frame = ttk.Frame(main_pane, style="Card.TFrame")
    main_pane.add(left_frame, width=540)

    # Right Column: 289 Presets + AI Extracted Reference Materials
    right_frame = ttk.Frame(main_pane, style="Card.TFrame")
    main_pane.add(right_frame, width=480)

    # --- SECTION 1: Prompt & Model Settings ---
    s1 = tk.Frame(left_frame, bg="#1d202b", padx=12, pady=10)
    s1.pack(fill="x", padx=8, pady=(8, 4))
    ttk.Label(s1, text="1. Текстовый промпт материала (RU / EN)", style="Section.TLabel").pack(anchor="w")

    prompt_var = tk.StringVar(value="oak wood parquet floor, classic herringbone pattern, warm natural timber grain")
    prompt_entry = tk.Entry(
        s1,
        textvariable=prompt_var,
        bg="#101218",
        fg="#f0f4fc",
        insertbackground="#ffffff",
        font=("Segoe UI", 10),
        relief="flat",
    )
    prompt_entry.pack(fill="x", pady=(6, 8), ipady=5)

    row_opts = tk.Frame(s1, bg="#1d202b")
    row_opts.pack(fill="x")

    ttk.Label(row_opts, text="Пайплайн:", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
    model_var = tk.StringVar(value=DEFAULT_PBR_MODEL_LABEL)
    model_combo = ttk.Combobox(
        row_opts,
        textvariable=model_var,
        values=[m[0] for m in PBR_MODEL_OPTIONS],
        state="readonly",
        width=36,
    )
    model_combo.grid(row=0, column=1, sticky="w", padx=(0, 12))

    ttk.Label(row_opts, text="Разрешение:", style="Card.TLabel").grid(row=0, column=2, sticky="w", padx=(0, 6))
    res_var = tk.StringVar(value=DEFAULT_RESOLUTION_LABEL)
    res_combo = ttk.Combobox(
        row_opts,
        textvariable=res_var,
        values=[r[0] for r in RESOLUTION_OPTIONS],
        state="readonly",
        width=18,
    )
    res_combo.grid(row=0, column=3, sticky="w")

    btn_gen_prompt = ttk.Button(s1, text="СГЕНЕРИРОВАТЬ CORONA PBR ПО ПРОМПТУ", style="Accent.TButton")
    btn_gen_prompt.pack(fill="x", pady=(10, 2))

    # --- SECTION 2: Reference Image to Corona PBR ---
    s2 = tk.Frame(left_frame, bg="#1d202b", padx=12, pady=10)
    s2.pack(fill="x", padx=8, pady=6)
    ttk.Label(s2, text="2. Генерация материала по РЕФЕРЕНСУ (Фото текстуры или Интерьера)", style="Section.TLabel").pack(anchor="w")

    ref_path_var = tk.StringVar(value="")
    ref_row = tk.Frame(s2, bg="#1d202b")
    ref_row.pack(fill="x", pady=(6, 6))
    ref_entry = tk.Entry(
        ref_row,
        textvariable=ref_path_var,
        bg="#101218",
        fg="#c9d1d9",
        insertbackground="#ffffff",
        font=("Segoe UI", 9),
        relief="flat",
    )
    ref_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))

    def _browse_ref():
        p = filedialog.askopenfilename(
            title="Выберите референс-изображение (текстура или фото интерьера)",
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("All files", "*.*")],
        )
        if p:
            ref_path_var.set(p)

    ttk.Button(ref_row, text="Обзор...", command=_browse_ref).pack(side="right")

    ref_mode_row = tk.Frame(s2, bg="#1d202b")
    ref_mode_row.pack(fill="x", pady=4)
    ttk.Label(ref_mode_row, text="Режим референса:", style="Card.TLabel").pack(side="left", padx=(0, 8))

    REF_MODES = [
        ("Бесшовный по фото (SDXL Img2Img + 5-Map PBR)", "img2img_seamless"),
        ("Прямое извлечение карт из фото (AI 5-Map PBR Engine Direct)", "chord_direct"),
        ("AI Vision описание референса -> 5-Map PBR", "ai_vision_pbr"),
    ]
    ref_mode_var = tk.StringVar(value=REF_MODES[0][0])
    ref_mode_combo = ttk.Combobox(
        ref_mode_row,
        textvariable=ref_mode_var,
        values=[m[0] for m in REF_MODES],
        state="readonly",
        width=46,
    )
    ref_mode_combo.pack(side="left", fill="x", expand=True)

    denoise_row = tk.Frame(s2, bg="#1d202b")
    denoise_row.pack(fill="x", pady=4)
    ttk.Label(denoise_row, text="Сила изм. (Denoise для Img2Img):", style="Card.TLabel").pack(side="left")
    denoise_var = tk.DoubleVar(value=0.52)
    tk.Scale(
        denoise_row,
        variable=denoise_var,
        from_=0.20,
        to=0.90,
        resolution=0.05,
        orient="horizontal",
        bg="#1d202b",
        fg="#e4e8f2",
        highlightthickness=0,
        length=140,
    ).pack(side="left", padx=8)

    ttk.Label(denoise_row, text="Уточнение (напр. 'пол', 'мрамор'):", style="Card.TLabel").pack(side="left", padx=(6, 4))
    ref_hint_var = tk.StringVar(value="")
    tk.Entry(
        denoise_row,
        textvariable=ref_hint_var,
        bg="#101218",
        fg="#f0f4fc",
        insertbackground="#ffffff",
        width=18,
        relief="flat",
    ).pack(side="left", ipady=3)

    ref_btns = tk.Frame(s2, bg="#1d202b")
    ref_btns.pack(fill="x", pady=(8, 2))
    btn_gen_ref = ttk.Button(ref_btns, text="СОЗДАТЬ PBR МАТЕРИАЛ ПО ФОТО-РЕФЕРЕНСУ", style="Green.TButton")
    btn_gen_ref.pack(side="left", fill="x", expand=True, padx=(0, 6))
    btn_extract_room = ttk.Button(ref_btns, text="AI: Найти все материалы интерьера")
    btn_extract_room.pack(side="right")

    # --- SECTION 3: CoronaPhysicalMtl & 3ds Max Assignment Settings ---
    s3 = tk.Frame(left_frame, bg="#1d202b", padx=12, pady=10)
    s3.pack(fill="both", expand=True, padx=8, pady=(4, 8))
    ttk.Label(s3, text="3. Настройки CoronaPhysicalMtl и назначения в 3ds Max", style="Section.TLabel").pack(anchor="w")

    c_grid = tk.Frame(s3, bg="#1d202b")
    c_grid.pack(fill="x", pady=8)

    apply_sel_var = tk.BooleanVar(value=True)
    tk.Checkbutton(
        c_grid,
        text="Назначить выделенным объектам в 3ds Max",
        variable=apply_sel_var,
        bg="#1d202b",
        fg="#e4e8f2",
        selectcolor="#101218",
        activebackground="#1d202b",
        activeforeground="#ffffff",
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=2)

    disp_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        c_grid,
        text="Включить Displacement (Height карта)",
        variable=disp_var,
        bg="#1d202b",
        fg="#e4e8f2",
        selectcolor="#101218",
        activebackground="#1d202b",
        activeforeground="#ffffff",
    ).grid(row=0, column=2, columnspan=2, sticky="w", pady=2)

    ttk.Label(c_grid, text="Слот Material Editor (1-24):", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=6)
    slot_var = tk.IntVar(value=1)
    tk.Spinbox(c_grid, from_=1, to=24, textvariable=slot_var, width=6, bg="#101218", fg="#ffffff", relief="flat").grid(
        row=1, column=1, sticky="w", padx=6
    )

    ttk.Label(c_grid, text="Размер UVW Box (мм):", style="Card.TLabel").grid(row=1, column=2, sticky="w", pady=6)
    uvw_var = tk.DoubleVar(value=1000.0)
    tk.Spinbox(
        c_grid, from_=100, to=10000, increment=100, textvariable=uvw_var, width=8, bg="#101218", fg="#ffffff", relief="flat"
    ).grid(row=1, column=3, sticky="w", padx=6)

    ttk.Label(c_grid, text="Сила Normal/Bump:", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=6)
    bump_var = tk.DoubleVar(value=1.0)
    tk.Spinbox(
        c_grid, from_=0.1, to=5.0, increment=0.1, textvariable=bump_var, width=6, bg="#101218", fg="#ffffff", relief="flat"
    ).grid(row=2, column=1, sticky="w", padx=6)

    ttk.Label(c_grid, text="UV Tiling (повтор):", style="Card.TLabel").grid(row=2, column=2, sticky="w", pady=6)
    tile_var = tk.DoubleVar(value=1.0)
    tk.Spinbox(
        c_grid, from_=0.25, to=20.0, increment=0.25, textvariable=tile_var, width=8, bg="#101218", fg="#ffffff", relief="flat"
    ).grid(row=2, column=3, sticky="w", padx=6)

    # Log output box
    ttk.Label(s3, text="Журнал генерации и пути к картам:", style="Card.TLabel").pack(anchor="w", pady=(6, 2))
    log_text = tk.Text(s3, height=9, bg="#0d0f14", fg="#a5d6ff", font=("Consolas", 9), relief="flat")
    log_text.pack(fill="both", expand=True)

    def _log(msg: str):
        def _append():
            status_var.set(msg[:95])
            log_text.insert("end", msg + "\n")
            log_text.see("end")
        root.after(0, _append)

    # --- RIGHT COLUMN: 289 Presets + AI Extracted Materials ---
    r_top = tk.Frame(right_frame, bg="#1d202b", padx=10, pady=10)
    r_top.pack(fill="both", expand=True)

    ttk.Label(r_top, text="Библиотека из 289 PBR Пресетов (12 категорий) + Материалы из Референса", style="Section.TLabel").pack(
        anchor="w", pady=(0, 6)
    )

    cat_bar = tk.Frame(r_top, bg="#1d202b")
    cat_bar.pack(fill="x", pady=(0, 6))

    preset_list = tk.Listbox(
        r_top,
        bg="#101218",
        fg="#e4e8f2",
        selectbackground="#1f6feb",
        selectforeground="#ffffff",
        font=("Segoe UI", 10),
        relief="flat",
        activestyle="none",
    )
    preset_list.pack(fill="both", expand=True)

    current_presets: List[Tuple[str, str, Optional[Dict[str, Any]]]] = []

    def _load_category(cat_key: str):
        preset_list.delete(0, "end")
        current_presets.clear()
        for title, p_txt in CATEGORY_PRESET_PROMPTS.get(cat_key, []):
            current_presets.append((title, p_txt, None))
            preset_list.insert("end", f"  {title}")

    for idx, (cat_key, cat_label) in enumerate(PRESET_CATEGORIES_ORDER):
        b = tk.Button(
            cat_bar,
            text=cat_label,
            bg="#262c3d",
            fg="#d0d8e8",
            activebackground="#1f6feb",
            activeforeground="#ffffff",
            relief="flat",
            font=("Segoe UI", 8, "bold"),
            padx=6,
            pady=3,
            command=lambda ck=cat_key: _load_category(ck),
        )
        b.grid(row=idx // 6, column=idx % 6, padx=2, pady=2, sticky="ew")

    for c_i in range(6):
        cat_bar.grid_columnconfigure(c_i, weight=1)

    def _on_preset_select(_evt=None):
        sel = preset_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(current_presets):
            _title, p_txt, _meta = current_presets[idx]
            prompt_var.set(p_txt)

    preset_list.bind("<<ListboxSelect>>", _on_preset_select)
    _load_category("wood")

    def _get_selected_res_px() -> int:
        lbl = res_var.get()
        for r_lbl, px, _tag in RESOLUTION_OPTIONS:
            if r_lbl == lbl:
                return px
        return 1024

    def _get_selected_pipe() -> Tuple[str, str]:
        lbl = model_var.get()
        for m_lbl, pipe_mode, ckpt in PBR_MODEL_OPTIONS:
            if m_lbl == lbl:
                return pipe_mode, ckpt
        return "chord", PBR_MODEL_OPTIONS[0][2]

    def _run_prompt_gen():
        p_txt = prompt_var.get().strip()
        if not p_txt:
            messagebox.showwarning("Промпт пуст", "Введите описание материала или выберите пресет.")
            return
        res_px = _get_selected_res_px()
        pipe_mode, ckpt = _get_selected_pipe()
        slot = slot_var.get()
        apply_sel = apply_sel_var.get()
        uvw_mm = uvw_var.get()
        tile_uv = tile_var.get()
        bump_val = bump_var.get()
        use_disp = disp_var.get()

        def _worker():
            try:
                res = generate_corona_pbr_from_prompt(
                    prompt_text=p_txt,
                    res_px=res_px,
                    pipeline_mode=pipe_mode,
                    ckpt_name=ckpt,
                    medit_slot=slot,
                    apply_to_selection=apply_sel,
                    uvw_box_mm=uvw_mm,
                    tiling_uv=tile_uv,
                    bump_strength=bump_val,
                    enable_displacement=use_disp,
                    progress_cb=_log,
                )
                _log(f"[ГОТОВО] Создан материал {res['material_name']} (Слот #{slot}) -> {res['dest_folder']}")
                root.after(0, lambda: slot_var.set(min(24, slot + 1)))
            except Exception as e:
                _log(f"[ОШИБКА] {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def _run_ref_gen():
        ref_p = ref_path_var.get().strip()
        if not ref_p or not os.path.exists(ref_p):
            messagebox.showwarning("Референс не выбран", "Укажите путь к файлу референс-изображения.")
            return
        mode_lbl = ref_mode_var.get()
        ref_mode = "img2img_seamless"
        for m_l, m_code in REF_MODES:
            if m_l == mode_lbl:
                ref_mode = m_code
                break

        res_px = _get_selected_res_px()
        pipe_mode, ckpt = _get_selected_pipe()
        slot = slot_var.get()
        apply_sel = apply_sel_var.get()
        uvw_mm = uvw_var.get()
        tile_uv = tile_var.get()
        bump_val = bump_var.get()
        use_disp = disp_var.get()
        denoise = denoise_var.get()
        hint = ref_hint_var.get().strip()

        def _worker():
            try:
                res = generate_corona_pbr_from_reference(
                    reference_image_path=ref_p,
                    ref_mode=ref_mode,
                    prompt_hint=hint,
                    denoise=denoise,
                    res_px=res_px,
                    pipeline_mode=pipe_mode,
                    ckpt_name=ckpt,
                    medit_slot=slot,
                    apply_to_selection=apply_sel,
                    uvw_box_mm=uvw_mm,
                    tiling_uv=tile_uv,
                    bump_strength=bump_val,
                    enable_displacement=use_disp,
                    progress_cb=_log,
                )
                _log(f"[ГОТОВО ПО РЕФЕРЕНСУ] {res['material_name']} (Слот #{slot}) -> {res['dest_folder']}")
                root.after(0, lambda: slot_var.set(min(24, slot + 1)))
            except Exception as e:
                _log(f"[ОШИБКА РЕФЕРЕНСА] {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def _run_extract_room_materials():
        ref_p = ref_path_var.get().strip()
        if not ref_p or not os.path.exists(ref_p):
            messagebox.showwarning("Референс не выбран", "Выберите фото интерьера в поле Референса.")
            return
        hint = ref_hint_var.get().strip()

        def _worker():
            try:
                _log("AI Vision анализирует фото интерьера и извлекает материалы...")
                items = extract_materials_from_reference_image(ref_p, target_hint=hint)
                if not items:
                    _log("[AI Vision] Не удалось извлечь материалы.")
                    return

                def _populate():
                    preset_list.delete(0, "end")
                    current_presets.clear()
                    for it in items:
                        t_ru = it.get("title_ru", "Материал")
                        surf = it.get("surface_ru", "")
                        p_en = it.get("prompt_en", "")
                        label = f"[РЕФЕРЕНС: {surf}] {t_ru}" if surf else f"[РЕФЕРЕНС] {t_ru}"
                        current_presets.append((label, p_en, it))
                        preset_list.insert("end", f"★ {label}")
                    if current_presets:
                        preset_list.selection_set(0)
                        prompt_var.set(current_presets[0][1])
                    _log(f"[AI Vision] Извлечено материалов из референса: {len(items)}. Выберите любой в списке справа!")

                root.after(0, _populate)
            except Exception as e:
                _log(f"[ОШИБКА AI Vision] {e}")

        threading.Thread(target=_worker, daemon=True).start()

    btn_gen_prompt.configure(command=_run_prompt_gen)
    btn_gen_ref.configure(command=_run_ref_gen)
    btn_extract_room.configure(command=_run_extract_room_materials)

    root.mainloop()


if __name__ == "__main__":
    launch_corona_pbr_studio()
