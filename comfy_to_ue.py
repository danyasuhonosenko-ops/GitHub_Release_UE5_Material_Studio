import builtins
import hashlib
import json
import math
import os
import random
import re
import threading
import time
import traceback
import urllib.parse
import urllib.request

import unreal

COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_UE_FOLDER = "/Game/Textures/ComfyUI"
TEXTURES_SUBFOLDER = "Textures"
MASKS_SUBFOLDER = "Masks"
MATERIAL_CATEGORIES = (
    "wood",
    "stone",
    "concrete",
    "tile",
    "fabric",
    "glass",
    "foliage",
    "mirror",
    "brick",
    "metal",
    "plastic",
    "light",
    "decal",
)

CATEGORY_TO_MASTER_MATERIAL = {
    "wood": "/Game/Textures/ComfyUI/MM_ComfyPBR_Master",
    "stone": "/Game/Textures/ComfyUI/MM_ComfyPBR_Master",
    "concrete": "/Game/Textures/ComfyUI/MM_ComfyPBR_Master",
    "tile": "/Game/Textures/ComfyUI/MM_ComfyPBR_Master",
    "brick": "/Game/Textures/ComfyUI/MM_ComfyPBR_Master",
    "metal": "/Game/Textures/ComfyUI/MM_ComfyPBR_Master",
    "mirror": "/Game/Textures/ComfyUI/MM_ComfyPBR_Master",
    "plastic": "/Game/Textures/ComfyUI/MM_ComfyPBR_Master",
    "fabric": "/Game/Textures/ComfyUI/MM_ArchViz_Fabric",
    "glass": "/Game/Textures/ComfyUI/MM_ArchViz_Glass",
    "foliage": "/Game/Textures/ComfyUI/MM_ArchViz_Foliage",
    "light": "/Game/Textures/ComfyUI/MM_ArchViz_Emissive",
    "decal": "/Game/Textures/ComfyUI/MM_ArchViz_Decal",
}
DEFAULT_MASTER_MAT_NAME = "MM_ComfyPBR_Master"
DEFAULT_MASTER_MAT_PATH = f"{DEFAULT_UE_FOLDER}/{DEFAULT_MASTER_MAT_NAME}"
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else r"D:\AI\PlagimUE_AI"
DEFAULT_JSON_PATH = (
    os.path.join(_SCRIPT_DIR, "UE_plagin.json")
    if os.path.exists(os.path.join(_SCRIPT_DIR, "UE_plagin.json"))
    else r"D:\AI\PlagimUE_AI\UE_plagin.json"
)
PANEL_ASSET_PATH = "/Game/ConfyUI_plagin/BP_ComfyPanel"

# --- AI Generation Credits, Instance Fingerprinting & Ledger Audit Telemetry ---
BUY_GENERATIONS_URL = "https://github.com/DaniilSukhnosenko/UE5-PBR-Material-Studio#get-ai-generation-credits"
DONATE_URL = "https://github.com/DaniilSukhnosenko/UE5-PBR-Material-Studio#donate--support"
TELEMETRY_AUDIT_URL = "http://127.0.0.1:8788/api/audit"  # Audit Scout Dashboard / Cloudflare Worker endpoint
STUDIO_LICENSE_FILE = os.path.join(_SCRIPT_DIR, "studio_license_state.json")
DEFAULT_FREE_GENERATIONS = 25


# Salted SHA-256 digests of promo codes (plaintext promo codes are never stored in source)
_PROMO_HASH_PACKS = {
    "e838fb679ed61e1b": 25,
    "1303347071dde58a": 25,
    "b53590a7be25fa93": 50,
    "1e3abcadd2680918": 100,
    "d7eb7f7176fec5ba": 500,
}


def _hash_promo_token(code_str: str) -> str:
    clean = (code_str or "").strip().upper()
    if clean.startswith("PROMO-") and len(clean) == 22:
        return clean[6:].lower()
    return hashlib.sha256(f"UE5_PBR_PROMO_SALT_V1:{clean}".encode("utf-8")).hexdigest()[:16]


def get_instance_fingerprint() -> str:
    """Returns a deterministic hardware-bound digital copy ID (e.g. 'PBR-8F3A91-C204B7') for this installation."""
    try:
        import platform
        import uuid
        raw_hw = f"UE5_PBR_INSTANCE|{uuid.getnode()}|{platform.node()}|{platform.machine()}"
        h_hex = hashlib.sha256(raw_hw.encode("utf-8")).hexdigest()[:12].upper()
        return f"PBR-{h_hex[:6]}-{h_hex[6:12]}"
    except Exception:
        return "PBR-000000-000000"


def _load_shadow_ledger() -> dict:
    """Reads anti-reset shadow state (`total_spent`, `redeemed_keys`) from Windows Registry / %LOCALAPPDATA%."""
    shadow = {"total_spent": 0, "redeemed_keys": []}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\UE5PBRStudio\Ledger") as rk:
            sp, _ = winreg.QueryValueEx(rk, "TotalSpent")
            rk_str, _ = winreg.QueryValueEx(rk, "RedeemedKeys")
            shadow["total_spent"] = max(0, int(sp))
            if rk_str:
                shadow["redeemed_keys"] = json.loads(rk_str)
    except Exception:
        pass
    return shadow


def _save_shadow_ledger(total_spent: int, redeemed_keys: list) -> None:
    """Persists monotonic `total_spent` and `redeemed_keys` into Windows Registry so deleting JSON cannot reset balance."""
    try:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\UE5PBRStudio\Ledger") as rk:
            winreg.SetValueEx(rk, "TotalSpent", 0, winreg.REG_DWORD, max(0, int(total_spent)))
            winreg.SetValueEx(rk, "RedeemedKeys", 0, winreg.REG_SZ, json.dumps(list(redeemed_keys or [])))
    except Exception:
        pass


def _compute_verified_minted_credits(redeemed_keys: list) -> int:
    """Computes the exact total credits legitimately unlocked by redeemed 12-word seeds & hashed promo codes."""
    tier_map = {
        0: 10, 1: 25, 2: 50, 3: 100, 4: 250,
        5: 500, 6: 1000, 7: 2500, 8: 5000, 9: 10000,
    }
    total_unlocked = DEFAULT_FREE_GENERATIONS
    seen = set()
    for k in (redeemed_keys or []):
        ks = str(k).strip().upper()
        if not ks or ks in seen:
            continue
        seen.add(ks)
        ph = _hash_promo_token(ks)
        if ph in _PROMO_HASH_PACKS:
            total_unlocked += _PROMO_HASH_PACKS[ph]
        elif ks.startswith("SEED12-"):
            parts = ks.split("-")
            if len(parts) == 3:
                try:
                    t_idx = int(parts[1], 16)
                    total_unlocked += tier_map.get(t_idx, 0)
                except Exception:
                    pass
    return total_unlocked


def audit_ledger_integrity(state_dict: dict | None = None) -> dict:
    """
    Audits this digital copy's credit balance against its cryptographic history of redeemed keys & spent generations.
    Detects if a copy somehow acquired unbacked credits without payment/keys.
    """
    st = state_dict if isinstance(state_dict, dict) else _load_studio_license_state()
    inst_id = str(st.get("instance_id") or get_instance_fingerprint())
    cur_credits = max(0, int(st.get("credits", DEFAULT_FREE_GENERATIONS)))
    spent_credits = max(0, int(st.get("total_spent", 0)))
    redeemed = list(st.get("redeemed_keys") or [])
    legit_minted = _compute_verified_minted_credits(redeemed)
    expected_max = max(0, legit_minted - spent_credits)
    unaccounted = max(0, cur_credits - expected_max)
    return {
        "instance_id": inst_id,
        "credits_remaining": cur_credits,
        "legitimate_minted_total": legit_minted,
        "paid_minted_total": max(0, legit_minted - DEFAULT_FREE_GENERATIONS),
        "total_spent": spent_credits,
        "expected_balance": expected_max,
        "unaccounted_credits": unaccounted,
        "anomaly_detected": unaccounted > 0,
        "redeemed_keys": redeemed,
    }


def _apply_server_enforcement(target_credits: int) -> None:
    """Applies a server-mandated credit balance override to JSON, Windows Registry shadow, and UI."""
    st_latest = _load_studio_license_state()
    target_c = max(0, int(target_credits))
    legit_total = _compute_verified_minted_credits(st_latest.get("redeemed_keys") or [])
    st_latest["credits"] = target_c
    st_latest["total_spent"] = max(0, legit_total - target_c)
    _save_studio_license_state(st_latest)
    builtins._COMFY_PENDING_UI_REFRESH = True


def send_ledger_audit_heartbeat(
    event_type: str = "heartbeat",
    extra: dict | None = None,
    sync_now: bool = False,
) -> None:
    """
    Sends a lightweight ledger audit ping to `TELEMETRY_AUDIT_URL` so the owner can:
    1. Compare Total Paid Revenue vs Total Credits in circulation across all digital copies (`instance_id`).
    2. Immediately spot any copy (`instance_id`) with `anomaly_detected == True` or duplicated `SEED12-*` keys.
    3. If `sync_now=True` (used right when pressing GENERATE), waits up to 0.8s for server balance enforcement before starting generation.
    """
    st = _load_studio_license_state()
    audit_url = TELEMETRY_AUDIT_URL.strip()
    report = audit_ledger_integrity(st)
    report["event"] = event_type
    report["timestamp"] = int(time.time())
    if extra:
        report.update(extra)
    if not audit_url:
        return

    def _worker():
        try:
            req = urllib.request.Request(
                audit_url,
                data=json.dumps(report).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "UE5-PBR-Studio-Audit/1.0"},
                method="POST",
            )
            timeout_sec = 0.85 if sync_now else 3.5
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
            if isinstance(resp_data, dict) and resp_data.get("action") == "clamp_to_legitimate":
                _apply_server_enforcement(int(resp_data.get("set_credits", report["expected_balance"])))
        except Exception:
            pass

    if sync_now:
        _worker()
        if getattr(builtins, "_COMFY_PENDING_UI_REFRESH", False):
            builtins._COMFY_PENDING_UI_REFRESH = False
            refresh_generations_ui()
    else:
        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            pass


def _load_studio_license_state() -> dict:
    """Loads persistent generation credits, instance_id, license key, payment URL, and donate URL from studio_license_state.json + Windows Registry shadow."""
    inst_id = get_instance_fingerprint()
    shadow = _load_shadow_ledger()
    default_state = {
        "instance_id": inst_id,
        "credits": max(0, DEFAULT_FREE_GENERATIONS - int(shadow.get("total_spent", 0))),
        "total_spent": int(shadow.get("total_spent", 0)),
        "license_key": "",
        "buy_url": BUY_GENERATIONS_URL,
        "donate_url": DONATE_URL,
        "telemetry_url": TELEMETRY_AUDIT_URL,
        "enforce_limit": True,
        "redeemed_keys": list(shadow.get("redeemed_keys") or []),
    }
    try:
        if os.path.exists(STUDIO_LICENSE_FILE):
            with open(STUDIO_LICENSE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in default_state.items():
                    data.setdefault(k, v)
                data["instance_id"] = inst_id
                data["enforce_limit"] = True
                # Reconcile monotonic total_spent and redeemed_keys with Windows Registry shadow
                data["total_spent"] = max(int(data.get("total_spent", 0)), int(shadow.get("total_spent", 0)))
                merged_keys = list(dict.fromkeys(list(data.get("redeemed_keys") or []) + list(shadow.get("redeemed_keys") or [])))
                data["redeemed_keys"] = merged_keys
                return data
    except Exception:
        pass
    try:
        with open(STUDIO_LICENSE_FILE, "w", encoding="utf-8") as f:
            json.dump(default_state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    return default_state


def _save_studio_license_state(state_dict: dict) -> None:
    """Saves studio_license_state.json to disk and updates Windows Registry shadow."""
    try:
        _save_shadow_ledger(
            int(state_dict.get("total_spent", 0)),
            list(state_dict.get("redeemed_keys") or []),
        )
    except Exception:
        pass
    try:
        with open(STUDIO_LICENSE_FILE, "w", encoding="utf-8") as f:
            json.dump(state_dict, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def get_remaining_generations() -> int:
    """Returns the current remaining AI generation credits count."""
    st = _load_studio_license_state()
    return max(0, int(st.get("credits", DEFAULT_FREE_GENERATIONS)))


def set_remaining_generations(count: int) -> int:
    """Sets the remaining AI generation credits count and updates the Studio UI."""
    st = _load_studio_license_state()
    st["credits"] = max(0, int(count))
    _save_studio_license_state(st)
    refresh_generations_ui()
    return st["credits"]


def add_generations(delta: int) -> int:
    """Adds (or subtracts) AI generation credits and refreshes the Studio UI."""
    return set_remaining_generations(get_remaining_generations() + int(delta))


LOW_GENERATIONS_WARNING_THRESHOLD = 10


def _get_generations_badge_color(credits: int) -> tuple:
    if credits > LOW_GENERATIONS_WARNING_THRESHOLD:
        return (0.42, 0.98, 0.68, 1.0)
    if credits > 0:
        return (1.0, 0.78, 0.24, 1.0)
    return (1.0, 0.42, 0.40, 1.0)


def refresh_generations_ui() -> None:
    """Updates the Generations Counter label in BP_ComfyPanel with color-coded balance and <=10 warning indicator."""
    credits = get_remaining_generations()
    col = _get_generations_badge_color(credits)
    lbl = getattr(builtins, "_COMFY_GEN_COUNT_LBL", None)
    if lbl:
        try:
            if credits <= 0:
                txt = "Credits: 0 left (TOP UP)"
            elif credits <= LOW_GENERATIONS_WARNING_THRESHOLD:
                txt = f"Credits: {credits} left (LOW)"
            else:
                txt = f"Credits: {credits} left"
            lbl.set_text(txt)
            _style_text(lbl, size=8, bold=True, color=col)
        except Exception:
            pass


def open_donate_url() -> str:
    """Opens the configured Donate / Support URL in the user's default web browser."""
    st = _load_studio_license_state()
    target_url = str(st.get("donate_url") or DONATE_URL).strip() or DONATE_URL
    launched = False
    try:
        unreal.SystemLibrary.launch_url(target_url)
        launched = True
    except Exception:
        pass
    if not launched:
        try:
            import webbrowser
            webbrowser.open(target_url)
        except Exception:
            pass
    try:
        _set_panel_status(
            f"[Donate / Support] Thank you for supporting the project! Opened -> {target_url}",
            color=(1.0, 0.62, 0.78, 1.0),
        )
    except Exception:
        pass
    return target_url


def open_buy_generations_url() -> str:
    """Opens the configured payment / Buy Generations URL in the user's default web browser."""
    st = _load_studio_license_state()
    target_url = str(st.get("buy_url") or BUY_GENERATIONS_URL).strip() or BUY_GENERATIONS_URL
    launched = False
    try:
        unreal.SystemLibrary.launch_url(target_url)
        launched = True
    except Exception:
        pass
    if not launched:
        try:
            import webbrowser
            webbrowser.open(target_url)
        except Exception:
            pass
    credits = get_remaining_generations()
    try:
        _set_panel_status(
            f"[Buy Generations] Opened payment page in browser -> {target_url} (Current Balance: {credits} Gens)",
            color=(1.0, 0.86, 0.36, 1.0),
        )
    except Exception:
        pass
    return target_url


# --- 12-Word Wallet-Style Cryptographic Seed Verifier (Public Key Only) ---
_SEED_PUBLIC_N = 0xA0DE037D9C9846C16EA6114D
_SEED_PUBLIC_E = 65537
_SEED_TIER_CREDITS = {
    0: 10,
    1: 25,
    2: 50,
    3: 100,
    4: 250,
    5: 500,
    6: 1000,
    7: 2500,
    8: 5000,
    9: 10000,
}
_SEED_WORDLIST_256 = [
    "abyss", "acorn", "agate", "albedo", "alchemy", "alloy", "alpine", "amber",
    "amethyst", "anchor", "ancient", "anvil", "apex", "apogee", "aqua", "arcade",
    "arch", "arctic", "argon", "armor", "arrow", "aspen", "astral", "atlas",
    "atom", "atrium", "aurora", "autumn", "avalon", "axiom", "axis", "azure",
    "bamboo", "basalt", "bastion", "beacon", "beryl", "bevel", "birch", "blade",
    "blaze", "bloom", "boulder", "breeze", "brick", "bridge", "bronze", "brush",
    "calcite", "calm", "canopy", "canvas", "canyon", "carbon", "carve", "cascade",
    "castle", "catalyst", "cavern", "cedar", "celeste", "ceramic", "chalice", "chalk",
    "channel", "chisel", "chrome", "cinder", "cipher", "circuit", "citadel", "citrine",
    "clay", "cliff", "cloud", "clover", "cobalt", "comet", "compass", "concrete",
    "conduit", "copper", "coral", "corona", "cortex", "cosmos", "crater", "crest",
    "crimson", "crown", "crystal", "cube", "current", "cyber", "cypress", "dawn",
    "delta", "denim", "desert", "dew", "diamond", "diffuse", "digital", "diode",
    "displacement", "dome", "drift", "dune", "dusk", "dynamo", "ebony", "echo",
    "eclipse", "eden", "elm", "ember", "emerald", "empire", "enigma", "epoch",
    "equinox", "essence", "ether", "evergreen", "fabric", "facet", "falcon", "fern",
    "fiber", "fjord", "flame", "flint", "flora", "flux", "foam", "focus",
    "foliage", "forest", "forge", "fossil", "foundry", "fresco", "frost", "fusion",
    "galaxy", "garnet", "gate", "genesis", "geode", "geyser", "glacier", "glade",
    "glass", "gleam", "glint", "globe", "glow", "gold", "granite", "graphite",
    "gravel", "grove", "gypsum", "halo", "harbor", "harmony", "harvest", "haven",
    "hazel", "hearth", "heather", "helix", "hemisphere", "herald", "horizon", "horn",
    "humidity", "hybrid", "hydra", "hyperion", "iceberg", "icon", "igneous", "impulse",
    "indigo", "infinity", "ingot", "inlet", "ion", "iridium", "iris", "iron",
    "island", "ivory", "jade", "jasper", "jet", "jewel", "jungle", "juniper",
    "karma", "keel", "kelp", "kernel", "kiln", "kinetic", "kingdom", "knight",
    "krypton", "lagoon", "lantern", "lapis", "larva", "laser", "lattice", "lava",
    "laurel", "leather", "kevlar", "legend", "lens", "liberty", "lichen", "light",
    "limestone", "linen", "liquid", "lithium", "loam", "lodestar", "lotus", "lumen",
    "lunar", "luster", "lyric", "magma", "magnet", "mahogany", "malachite", "mantle",
    "maple", "marble", "marina", "matrix", "meadow", "mercury", "meridian", "mesa",
    "metal", "meteor", "mica", "mirage", "mirror", "mist", "monolith", "mosaic",
]
_SEED_WORD_TO_IDX = {w: idx for idx, w in enumerate(_SEED_WORDLIST_256)}


def verify_12word_seed_phrase(phrase: str) -> tuple:
    """
    Verifies a 12-word wallet-style seed phrase using RSA-like public verification (`pow(S, 65537, N)`) + SHA-256 tag.
    Returns (is_valid: bool, credits: int, serial_id: int, canonical_id: str, message: str).
    """
    tokens = [t.strip().lower() for t in (phrase or "").replace(",", " ").replace("-", " ").split() if t.strip()]
    if len(tokens) != 12:
        return False, 0, 0, "", f"Expected 12 seed words, got {len(tokens)}."
    sig_val = 0
    for tok in tokens:
        idx = _SEED_WORD_TO_IDX.get(tok)
        if idx is None:
            return False, 0, 0, "", f"Unrecognized seed word '{tok}'."
        sig_val = (sig_val << 8) | idx
    if sig_val >= _SEED_PUBLIC_N:
        return False, 0, 0, "", "Invalid 12-word cryptographic signature range."
    m_val = pow(sig_val, _SEED_PUBLIC_E, _SEED_PUBLIC_N)
    chk62 = m_val & ((1 << 62) - 1)
    ser20 = (m_val >> 62) & ((1 << 20) - 1)
    tier4 = (m_val >> 82) & 0xF
    magic8 = (m_val >> 86) & 0xFF
    if magic8 != 0x50:
        return False, 0, 0, "", "Invalid 12-word seed signature."
    raw = f"UE5_PBR_SEED_V2|{magic8:02X}|{tier4:01X}|{ser20:05X}".encode("utf-8")
    expected_chk62 = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") & ((1 << 62) - 1)
    if chk62 != expected_chk62:
        return False, 0, 0, "", "12-word seed checksum verification failed."
    credits = _SEED_TIER_CREDITS.get(tier4, 0)
    if credits <= 0:
        return False, 0, 0, "", "Unknown generation pack tier in 12-word seed."
    canonical_id = f"SEED12-{tier4:X}-{ser20:05X}"
    return True, credits, ser20, canonical_id, f"Verified 12-word wallet key (#{ser20}): +{credits} AI Generations!"


def activate_license_or_promo_key(key_raw: str) -> tuple:
    """
    Validates a 12-word wallet seed phrase or promo/referral/license key entered into LicenseKeyBox.
    """
    key_clean = (key_raw or "").strip()
    if not key_clean:
        return False, "Enter a 12-word Seed Phrase or Promo Code first, or click '+ Buy Generations'."
    st = _load_studio_license_state()
    redeemed = list(st.get("redeemed_keys") or [])

    # 1. Check if the user entered a multi-word Seed Phrase (e.g. 12 words separated by spaces)
    word_tokens = [t.strip().lower() for t in key_clean.replace(",", " ").replace("-", " ").split() if t.strip()]
    if len(word_tokens) >= 4:
        ok_seed, seed_credits, seed_serial, seed_id, seed_msg = verify_12word_seed_phrase(key_clean)
        if not ok_seed:
            return False, seed_msg
        if seed_id in redeemed:
            return False, f"This 12-word seed key (Serial #{seed_serial}) was already redeemed."
        redeemed.append(seed_id)
        st["redeemed_keys"] = redeemed
        st["license_key"] = seed_id
        st["credits"] = max(0, int(st.get("credits", 0))) + seed_credits
        _save_studio_license_state(st)
        refresh_generations_ui()
        send_ledger_audit_heartbeat(
            "seed_redeemed",
            {"redeemed_id": seed_id, "added_credits": seed_credits},
            sync_now=True,
        )
        return True, f"{seed_msg} (New Balance: {st['credits']} Gens)"

    # 2. Check short promo codes via salted SHA-256 digest (plaintext promo codes are hidden)
    key_up = key_clean.upper()
    promo_digest = _hash_promo_token(key_up)
    promo_canonical = f"PROMO-{promo_digest.upper()}"
    if promo_digest in _PROMO_HASH_PACKS:
        if promo_canonical in redeemed or key_up in redeemed:
            return False, f"Promo code '{key_up}' was already activated on this machine."
        added = _PROMO_HASH_PACKS[promo_digest]
        redeemed.append(promo_canonical)
        st["redeemed_keys"] = redeemed
        st["license_key"] = promo_canonical
        st["credits"] = max(0, int(st.get("credits", 0))) + added
        _save_studio_license_state(st)
        refresh_generations_ui()
        send_ledger_audit_heartbeat(
            "promo_redeemed",
            {"redeemed_id": promo_canonical, "added_credits": added},
            sync_now=True,
        )
        return True, f"Activated '{key_up}'! +{added} AI Generations added (Balance: {st['credits']} Gens)."
    st["license_key"] = key_clean
    _save_studio_license_state(st)
    refresh_generations_ui()
    return True, f"Saved License Key '{key_clean[:12]}...'. Ready for cloud verification (Balance: {st.get('credits', 0)} Gens)."


def copy_instance_id_to_clipboard() -> str:
    """Copies the machine's unique Copy ID (`PBR-XXXXXX-XXXXXX`) to the Windows clipboard for support requests."""
    inst_id = get_instance_fingerprint()
    try:
        import subprocess
        subprocess.run(
            ["clip"],
            input=inst_id.encode("utf-8"),
            check=False,
            creationflags=0x08000000,
        )
    except Exception:
        pass
    try:
        _set_panel_status(
            f"[Support Copy ID] Copied '{inst_id}' to clipboard! Share this ID when contacting support.",
            color=(0.56, 0.88, 1.0, 1.0),
        )
    except Exception:
        pass
    return inst_id


def _show_low_generations_popup(remaining: int) -> None:
    """Shows a native English Unreal Engine warning dialog when credits drop to <= 10."""
    inst_id = get_instance_fingerprint()
    try:
        unreal.EditorDialog.show_message(
            "Low AI Generation Credits Warning",
            (
                f"You have {remaining} AI Generation credits remaining (<= {LOW_GENERATIONS_WARNING_THRESHOLD} left).\n\n"
                "Please make sure you have enough credits to convert all Corona materials from your 3ds Max scene into Unreal Engine.\n\n"
                "You can top up your balance anytime via '+ Buy Generations' or by entering a 12-Word Seed Key.\n\n"
                f"Support Copy ID: {inst_id}"
            ),
            unreal.AppMsgType.OK,
        )
    except Exception:
        pass


def _show_zero_generations_popup() -> None:
    """Shows a native English Unreal Engine modal dialog when 0 generations remain, offering a 1-click redirect to + Buy Generations."""
    inst_id = get_instance_fingerprint()
    try:
        res = unreal.EditorDialog.show_message(
            "Out of AI Generation Credits (0 Left)",
            (
                "You have 0 AI Generation credits remaining!\n\n"
                "Please make sure you have enough credits to convert all Corona materials from your 3ds Max scene into Unreal Engine.\n\n"
                "• Enter a 12-Word Seed Key in the '12-Word Seed / Key...' box\n"
                "• Or click 'Yes' to open the '+ Buy Generations' page in your browser.\n\n"
                f"Support Copy ID: {inst_id}"
            ),
            unreal.AppMsgType.YES_NO,
        )
        if res == unreal.AppReturnType.YES:
            open_buy_generations_url()
    except Exception:
        pass


def consume_generation_credit(cost: int = 1, from_completion: bool = True) -> bool:
    """Decrements generation counter by `cost`, increments `total_spent`, updates the UI, and triggers an audit heartbeat."""
    if from_completion and getattr(builtins, "_COMFY_CREDIT_PREPAID", False):
        builtins._COMFY_CREDIT_PREPAID = False
        refresh_generations_ui()
        send_ledger_audit_heartbeat("credit_confirmed", {"cost": int(cost)})
        return True
    st = _load_studio_license_state()
    cur = max(0, int(st.get("credits", DEFAULT_FREE_GENERATIONS)))
    if bool(st.get("enforce_limit", True)) and cur < cost:
        refresh_generations_ui()
        return False
    new_bal = max(0, cur - int(cost))
    st["credits"] = new_bal
    st["total_spent"] = max(0, int(st.get("total_spent", 0))) + int(cost)
    _save_studio_license_state(st)
    refresh_generations_ui()
    send_ledger_audit_heartbeat("credit_consumed", {"cost": int(cost)})
    if 0 < new_bal <= LOW_GENERATIONS_WARNING_THRESHOLD:
        try:
            _set_panel_status(
                f"[Low Credits Warning: {new_bal} left] Please check that you have enough credits to convert all Corona materials from your 3ds Max scene into Unreal Engine!",
                color=(1.0, 0.78, 0.24, 1.0),
            )
            if cur > LOW_GENERATIONS_WARNING_THRESHOLD or getattr(builtins, "_COMFY_LOW_WARN_SHOWN_AT", None) != new_bal and new_bal in (10, 5, 1):
                builtins._COMFY_LOW_WARN_SHOWN_AT = new_bal
                _show_low_generations_popup(new_bal)
        except Exception:
            pass
    return True


def _check_can_generate_or_prompt_buy(cost: int = 1) -> bool:
    """
    Synchronously syncs balance with the Audit Server right when the GENERATE button is clicked,
    blocks immediately with a popup dialog if 0 credits remain, or deducts `cost` upfront before starting ComfyUI.
    """
    send_ledger_audit_heartbeat("pre_generate_check", sync_now=True)
    st = _load_studio_license_state()
    cur = max(0, int(st.get("credits", DEFAULT_FREE_GENERATIONS)))
    refresh_generations_ui()
    if bool(st.get("enforce_limit", True)) and cur < cost:
        try:
            _set_panel_status(
                "[0 Generations Left] Generation blocked! Click '+ Buy Generations' or enter a 12-Word Seed Key to top up.",
                "0 GENS LEFT",
                color=(1.0, 0.45, 0.40, 1.0),
            )
        except Exception:
            pass
        _show_zero_generations_popup()
        return False
    # Deduct upfront right on button click so the UI counter updates immediately before generation starts
    builtins._COMFY_CREDIT_PREPAID = False
    consume_generation_credit(cost, from_completion=False)
    builtins._COMFY_CREDIT_PREPAID = True
    return True


RESOLUTION_OPTIONS = [
    ("512x512 (0.5K Fast)", 512, "512"),
    ("1024x1024 (1K Standard)", 1024, "1K"),
    ("2048x2048 (2K High)", 2048, "2K"),
    ("4096x4096 (4K Ultra)", 4096, "4K"),
]
DEFAULT_RESOLUTION_LABEL = "1024x1024 (1K Standard)"

PBR_MODEL_OPTIONS = [
    ("Ubisoft CHORD + RealVisXL V5 (True PBR)", "chord", "SDXL\\realvisxlV50_v50Bakedvae.safetensors"),
    ("Ubisoft CHORD + SDXL 1.0 (True PBR)", "chord", "SDXL\\sd_xl_base_1.0.safetensors"),
    ("DepthAnything V2 + RealVisXL V5 (Fast)", "da2", "SDXL\\realvisxlV50_v50Bakedvae.safetensors"),
    ("DepthAnything V2 + SDXL 1.0 (Fast)", "da2", "SDXL\\sd_xl_base_1.0.safetensors"),
]
DEFAULT_PBR_MODEL_LABEL = "Ubisoft CHORD + RealVisXL V5 (True PBR)"

CATEGORY_KEYWORDS = {
    "wood": (
        "wood", "oak", "parquet", "plank", "timber", "pine", "walnut", "mahogany",
        "bamboo", "plywood", "bark", "log", "lumber", "cedar", "birch", "ash", "teak",
        "slab", "tree ring", "end-grain", "cross-section", "stump", "burl", "veneer",
        "chipboard", "particleboard", "osb", "mdf", "hdf", "hardboard", "masonite", "pegboard", "cork", "glulam", "clt", "yakisugi", "shou sugi ban",
        "дерев", "паркет", "дуб", "доск", "сосн", "орех", "фанер", "брус", "кора", "берез",
        "слэб", "спил", "кольц", "торцев", "шпон", "дсп", "двп", "мдф", "хдф", "осп", "осб", "цсп", "фибролит", "пробк",
    ),
    "brick": (
        "brick", "masonry", "clay wall", "brickwork",
        "кирпич", "кладк",
    ),
    "concrete": (
        "concrete", "cement", "asphalt", "plaster", "stucco", "mortar", "screed", "pavement",
        "бетон", "цемент", "асфальт", "штукатурк", "шпаклев", "стяжк",
    ),
    "tile": (
        "tile", "tiled", "ceramic", "porcelain", "mosaic", "terrazzo", "grout", "hexagonal",
        "плитк", "керамик", "кафель", "мозаик", "керамогранит",
    ),
    "fabric": (
        "fabric", "cloth", "textile", "linen", "cotton", "wool", "silk", "velvet",
        "denim", "carpet", "rug", "leather", "suede", "canvas", "weave", "woven", "knitted", "upholstery", "felt",
        "ткан", "текстил", "лен", "льн", "хлопок", "шерст", "шелк", "бархат", "джинс", "ковер", "ковр", "кож", "замш", "холст", "войлок",
    ),
    "glass": (
        "glass", "window", "stained", "frosted", "crystal", "ice", "transparent", "translucent",
        "стекл", "витраж", "хрустал", "лед", "льд",
    ),
    "foliage": (
        "foliage", "leaf", "leaves", "grass", "lawn", "moss", "ivy", "hedge", "fern", "plant", "clover", "bush", "needles",
        "single isolated", "cutout", "botanical", "frond", "sprig", "twig", "monstera", "ficus", "calathea", "eucalyptus", "thuja",
        "soil", "mulch", "humus", "peat", "compost", "chernozem", "loam", "woodchip", "bark nuggets", "forest floor", "litter",
        "листв", "лист", "трав", "газон", "мох", "плющ", "куст", "папоротник", "хвоя", "растен",
        "почв", "земл", "чернозем", "мульч", "перегной", "торф", "щеп", "подстилк",
    ),
    "mirror": (
        "mirror", "chrome", "silvered", "reflective mirror",
        "зеркал", "хром",
    ),
    "metal": (
        "metal", "metallic", "steel", "iron", "copper", "bronze", "brass", "gold", "silver",
        "aluminum", "aluminium", "titanium", "rust", "rusty", "galvanized", "foil", "chainmail",
        "метал", "стал", "желез", "медн", "медь", "бронз", "латун", "золот", "серебр", "алюмин", "титан", "ржав",
    ),
    "plastic": (
        "plastic", "rubber", "vinyl", "acrylic", "silicone", "polymer", "resin", "epoxy",
        "carbon", "carbon fiber", "kevlar", "aramid", "fiberglass", "composite", "fr4", "g10", "garolite", "micarta",
        "delrin", "pom", "peek", "ptfe", "teflon", "hdpe", "ldpe", "polycarbonate", "lexan", "neoprene", "epdm",
        "latex", "foam", "eva", "polystyrene", "nylon", "pvc", "linoleum", "pla", "petg",
        "пластик", "пластмасс", "резин", "винил", "акрил", "силикон", "полимер", "смол", "эпоксид",
        "карбон", "углепластик", "кевлар", "арамид", "стекловолокн", "стеклопластик", "композит", "текстолит", "микарта",
        "капролон", "дерлин", "фторопласт", "тефлон", "поликарбонат", "неопрен", "пена", "нейлон", "пвх", "линолеум",
    ),
    "light": (
        "light", "neon", "glow", "glowing", "emissive", "lamp", "led", "laser", "lava", "fire", "flame", "plasma", "screen",
        "свет", "неон", "свечен", "эмисс", "ламп", "диод", "лав", "огон", "плазм",
    ),
    "decal": (
        "decal", "graffiti", "puddle", "manhole", "road marking", "splatter", "leak stain", "spalling",
        "декал", "декаль", "граффити", "лужа", "люк", "разметк", "подтек", "пятно",
    ),
    "stone": (
        "stone", "marble", "granite", "rock", "cobblestone", "slate", "pebble", "gravel",
        "sandstone", "limestone", "travertine", "cliff", "boulder", "basalt", "onyx", "quartz", "sand", "dirt", "soil", "mud",
        "камен", "мрамор", "гранит", "брусчатк", "скал", "гальк", "щебен", "сланец", "песчаник", "травертин", "базальт", "оникс", "кварц", "песок", "грунт",
    ),
}

RU_TO_EN_MATERIALS = {
    "дубовый паркет": "oak wood parquet floor, herringbone pattern, natural timber grain",
    "паркет": "wooden parquet floor, natural oak timber planks",
    "деревянный пол": "wooden plank floor, natural wood grain",
    "дерево": "natural wood plank surface, fine wood grain",
    "кирпич": "old red clay brick wall with mortar joints",
    "красный кирпич": "weathered red brick wall, rough mortar",
    "белый кирпич": "painted white brick wall texture",
    "белый мрамор": "white Carrara marble with subtle gold and grey veins, polished stone",
    "мрамор": "natural luxury marble stone surface with veins",
    "гранит": "rough granite stone surface, speckled mineral texture",
    "бетон": "architectural exposed concrete surface, subtle pores and weathered details",
    "серый бетон": "architectural exposed grey concrete wall surface with fine pores",
    "штукатурка": "Venetian plaster wall texture, matte stucco finish",
    "брусчатка": "old European stone cobblestone pavement",
    "камень": "natural rough rock stone wall surface",
    "плитка": "ceramic floor tiles with clean grout lines",
    "асфальт": "rough dark asphalt road pavement texture",
    "трава": "lush green grass lawn ground texture",
    "песок": "fine desert sand ripples ground texture",
    "кожа": "fine grained natural brown leather upholstery texture",
    "ткань": "woven linen fabric upholstery textile texture",
    "трещины": "sharp branching surface cracks and fissures, distressed fracture pattern",
    "грязь": "grunge dirt splatters, weathered smudges and dust stains",
    "потертости": "scratched metal edge wear, distressed surface abrasions and scuffs",
    "царапины": "dense fine directional scratches and surface gouges",
    "мох": "organic patchy moss growth clusters and lichen spots",
    "пятна": "organic grunge blotches, damp water stains and weathered patches",
    "ржавчина": "corroded rust patches and flaky oxidation spots",
}

PRESET_CATEGORIES_ORDER = [
    ("wood", "Wood"),
    ("stone", "Stone"),
    ("concrete", "Concrete"),
    ("tile", "Tile"),
    ("brick", "Brick"),
    ("metal", "Metal"),
    ("fabric", "Fabric"),
    ("glass", "Glass"),
    ("foliage", "Foliage"),
    ("plastic", "Plastic"),
    ("light", "Light"),
    ("decal", "Decals"),
    ("bw_mask", "B&W Mask"),
]

CATEGORY_PRESET_PROMPTS = {
    "wood": [
        # --- Live-Edge Slabs & Figured Slabs (Слэбы дерева и каповые спилы) ---
        ("Walnut Live-Edge Slab", "wide natural American walnut timber slab with organic live-edge grain, dark chocolate heartwood, pale sapwood and natural knots"),
        ("Oak Rustic Cracked Slab", "thick aged rustic oak wood slab with heavy cathedral grain, natural radial checks, dark knots and weathered timber fibers"),
        ("Olive Wood Figured Slab", "exotic Mediterranean olive wood slab with dramatic swirling golden-brown and dark chocolate figured grain"),
        ("Walnut & Black Epoxy Slab", "polished dark walnut wood slab with natural cracks and voids filled with black epoxy resin"),
        ("Elm Burl Figured Slab", "richly figured Carpathian elm burl wood slab with dense swirling eye clusters and warm amber grain"),
        ("Suar Acacia Wood Slab", "tropical Suar monkeypod acacia wood slab with rich golden-brown center and contrasting creamy sapwood"),
        ("Spalted Maple Wood Slab", "spalted maple timber slab with intricate black fungal zone lines winding through pale creamy wood grain"),
        # --- Circular Tree Rings & End-Grain Cross-Cuts (Круговые годичные кольца и торцевые спилы) ---
        ("Oak Log Cross-Section Rings", "wood log cross-section end-grain slice showing concentric circular annual growth rings, medullary rays and radial heartwood cracks"),
        ("Pine Tree Trunk Rings", "freshly sawn Nordic pine tree trunk cross-cut with distinct warm golden concentric annual growth rings"),
        ("Aged Weathered Stump Rings", "old weathered silver-grey tree stump cross-section with deep radial shrinkage cracks and concentric growth rings"),
        ("End-Grain Butcher Block Oak", "checkerboard end-grain oak wood butcher block surface showing square-cut circular tree growth rings"),
        ("Hexagon End-Grain Wood Block", "architectural hexagonal end-grain larch wood paving blocks showing concentric circular growth rings"),
        # --- Plywood Sheets & Multi-Layer Plywood Edges (Фанера и фанерные слои) ---
        ("Birch Plywood Sheet Face", "smooth Baltic birch rotary-cut plywood sheet face with warm pale creamy grain and subtle oval wood patches"),
        ("Pine Construction Plywood", "softwood construction pine plywood board surface with prominent wavy warm yellow-orange rotary grain and knots"),
        ("Plywood Multi-Layer Edge Strips", "stacked Baltic birch plywood edge cross-section showing parallel alternating light and dark laminated wood veneer plies"),
        ("Sculpted Layered Plywood Contours", "CNC-carved laminated birch plywood topography showing stepped concentric multi-layer veneer strata"),
        ("Phenolic Film-Faced Plywood", "dark brown waterproof phenolic resin film-faced formwork birch plywood with subtle wire-mesh anti-slip texture"),
        # --- Engineered Wood Boards: DSP, OSB, DVP, MDF, CSP & Cork (ДСП, ОСП, ДВП, МДФ, ЦСП и пробка) ---
        ("Raw Chipboard Particleboard (DSP)", "raw unlaminated industrial wood particleboard chipboard DSP surface made of pressed fine wood sawdust and chips"),
        ("OSB-3 Oriented Strand Board (OSP)", "oriented strand board OSB-3 panel made of compressed rectangular wood flakes and resin binder"),
        ("Raw MDF Fiberboard (MDF)", "uniform smooth raw medium-density fiberboard MDF panel with fine homogeneous tan wood fiber texture"),
        ("Hardboard DVP Smooth Side (DVP)", "dense brown high-density wet-process hardboard DVP Masonite smooth pressed wood fiber surface"),
        ("Hardboard DVP Mesh Back (DVP Mesh)", "reverse side of brown Masonite hardboard DVP fiberboard with fine woven wire-screen mesh impression"),
        ("Perforated Pegboard Hardboard (DVP)", "brown tempered hardboard DVP pegboard sheet with uniform grid of circular tool-hanging perforations"),
        ("Cement-Bonded Particleboard (CSP)", "grey cement-bonded wood particleboard CSP facade panel with mineralized wood chips in Portland cement"),
        ("Wood Wool Acoustic Panel (Fibrolit)", "architectural Heradesign wood-wool magnesite acoustic panel made of compressed long mineralized wood excelsior fibers"),
        ("Natural Cork Bark Sheet (Cork)", "pressed natural Mediterranean cork oak bark sheet with warm cellular granular cork texture"),
        ("Smoked Dark Cork Tile", "charcoal-brown thermally treated dark agglomerated cork wall tile texture"),
        # --- Charred, Reclaimed, Glulam, Brushed & Bark (Обожжённое, амбарное, клеёный брус и кора) ---
        ("Charred Wood Shou Sugi Ban", "Japanese Yakisugi Shou Sugi Ban deeply charred black cedar wood with alligator-skin carbonized crackle texture"),
        ("Brushed Charred Ash Wood", "wire-brushed half-charred Shou Sugi Ban ash wood showing dark carbonized ridges and warm golden grain valleys"),
        ("Reclaimed Silver Barnwood", "weathered rustic silver-grey reclaimed barnwood timber with sun-bleached fibers, nail holes and rough saw marks"),
        ("Glulam Laminated Timber Beam", "structural glued laminated timber Glulam beam showing parallel finger-jointed spruce wood lamellas"),
        ("Cross-Laminated Timber (CLT)", "structural cross-laminated timber CLT panel showing alternating perpendicular spruce board layers"),
        ("Wire-Brushed Aged Oak", "deeply wire-brushed distressed antique oak wood with raised winter grain relief and limed white ceruse pores"),
        ("Rough Sawn Pine Lumber", "raw unplaned rough-sawn construction pine lumber with horizontal circular saw blade kerf marks"),
        ("Natural Pine Tree Bark", "deeply fissured reddish-brown and grey scaly pine tree bark surface"),
        ("White Birch Tree Bark", "natural white papery silver birch tree bark with horizontal dark lenticel markings"),
        # --- Natural Fine Wood Veneers (Натуральный шпон ценных пород) ---
        ("Oak Veneer", "natural oak wood veneer, clean continuous wood grain"),
        ("American Walnut Veneer", "dark American walnut wood veneer, clean continuous wood grain"),
        ("White Ash Veneer", "light white ash wood veneer, clean continuous wood grain"),
        ("Maple Veneer", "pale natural maple wood veneer, clean continuous wood grain"),
        ("Birch Veneer", "smooth light birch wood veneer, clean continuous wood grain"),
        ("Cherry Veneer", "warm American cherry wood veneer, clean continuous wood grain"),
        ("Mahogany Veneer", "reddish-brown mahogany wood veneer, clean continuous wood grain"),
        ("Teak Veneer", "golden-brown teak wood veneer, clean continuous wood grain"),
        ("Rosewood Veneer", "dark Brazilian rosewood veneer, clean continuous wood grain"),
        ("Beech Veneer", "warm light European beech wood veneer, clean continuous wood grain"),
        ("Nordic Pine Veneer", "light Scandinavian pine wood veneer, clean continuous wood grain"),
        ("Cedar Veneer", "warm red cedar wood veneer, clean continuous wood grain"),
        ("Wenge Veneer", "dark espresso wenge wood veneer, clean continuous wood grain"),
        ("Smoked Oak Veneer", "dark smoked oak wood veneer, clean continuous wood grain"),
        ("Zebrano Veneer", "striped exotic zebrano wood veneer, clean continuous wood grain"),
        ("Ebony Veneer", "dark Macassar ebony wood veneer, clean continuous wood grain"),
        ("Elm Veneer", "natural elm wood veneer, clean continuous wood grain"),
        ("Siberian Larch Veneer", "warm Siberian larch wood veneer, clean continuous wood grain"),
        ("Alder Veneer", "warm honey alder wood veneer, clean continuous wood grain"),
        ("Olive Wood Veneer", "Mediterranean olive wood veneer, clean continuous wood grain"),
        ("Sapele Veneer", "warm ribbon-grain sapele wood veneer, clean continuous wood grain"),
        ("Sycamore Veneer", "light figured sycamore wood veneer, clean continuous wood grain"),
        ("Acacia Veneer", "warm golden acacia wood veneer, clean continuous wood grain"),
        ("Bamboo Veneer", "natural caramel bamboo wood veneer, clean continuous wood grain"),
        ("Burl Wood Veneer", "natural amboyna burl wood veneer, clean continuous wood grain"),
    ],
    "stone": [
        ("Grey Granite", "uniform grey granite stone surface, natural speckled mineral grain"),
        ("Black Granite", "uniform black granite stone surface, fine dark mineral texture"),
        ("Red Granite", "uniform red granite stone surface, natural crystalline mineral grain"),
        ("White Marble", "uniform white marble stone surface, subtle natural veins"),
        ("Black Marble", "uniform black marble stone surface, subtle white veins"),
        ("Green Marble", "uniform dark green marble stone surface, natural veining"),
        ("Beige Marble", "uniform warm beige marble stone surface, soft natural veins"),
        ("Beige Travertine", "uniform beige travertine stone surface, natural porous limestone texture"),
        ("Yellow Sandstone", "uniform warm yellow sandstone rock surface, fine sedimentary grain"),
        ("Red Sandstone", "uniform red sandstone rock surface, fine sedimentary stone grain"),
        ("Dark Slate", "uniform dark charcoal slate stone surface, natural cleft rock texture"),
        ("Grey Slate", "uniform medium grey slate stone surface, flat layered rock texture"),
        ("Cream Limestone", "uniform pale cream limestone surface, fine matte stone texture"),
        ("Dark Basalt", "uniform dark volcanic basalt stone surface, dense fine-grained rock"),
        ("Red Clay", "uniform natural red clay surface, smooth matte earthen texture"),
        ("Green Clay", "uniform natural green clay surface, smooth matte mineral earth texture"),
        ("Yellow Clay", "uniform natural yellow ochre clay surface, smooth matte earth texture"),
        ("White Kaolin Clay", "uniform pure white kaolin clay surface, smooth matte ceramic earth"),
        ("Black Clay", "uniform dark black clay surface, smooth matte organic earth texture"),
        ("Grey Clay", "uniform neutral grey clay surface, smooth matte raw earth texture"),
        ("Brown Terracotta Clay", "uniform warm brown terracotta clay surface, natural raw clay texture"),
        ("White Quartzite", "uniform white quartzite stone surface, fine crystalline rock texture"),
        ("Grey Soapstone", "uniform matte grey soapstone surface, smooth steatite mineral texture"),
        ("Volcanic Pumice", "uniform grey volcanic pumice stone surface, fine porous rock"),
        ("Fine Desert Sand", "uniform fine beige desert sand surface, natural granular sand texture"),
    ],
    "concrete": [
        ("Smooth Grey Concrete", "uniform smooth grey architectural concrete surface"),
        ("Light Grey Concrete", "uniform light grey architectural concrete surface, subtle fine pores"),
        ("Dark Charcoal Concrete", "uniform dark charcoal grey concrete surface, matte finish"),
        ("White Concrete", "uniform clean white architectural concrete surface"),
        ("Raw Porous Concrete", "uniform raw cast grey concrete surface with natural micropores"),
        ("Grey Microcement", "uniform seamless grey microcement plaster surface"),
        ("Beige Microcement", "uniform warm beige microcement plaster surface"),
        ("White Microcement", "uniform matte white microcement wall surface"),
        ("White Stucco Plaster", "uniform matte white stucco wall plaster surface"),
        ("Beige Stucco Plaster", "uniform warm beige stucco wall plaster surface"),
        ("Grey Stucco Plaster", "uniform neutral grey stucco wall plaster surface"),
        ("White Venetian Plaster", "uniform smooth polished white Venetian plaster surface"),
        ("Beige Venetian Plaster", "uniform smooth polished ivory Venetian plaster surface"),
        ("Grey Cement Screed", "uniform matte grey sand-cement screed floor surface"),
        ("White Limewash Plaster", "uniform soft chalky white limewash wall plaster surface"),
        ("Beige Limewash Plaster", "uniform earthy beige limewash wall plaster surface"),
        ("Dark Road Asphalt", "uniform dark black road asphalt surface, fine mineral aggregate"),
        ("Weathered Grey Asphalt", "uniform medium grey asphalt pavement surface, fine texture"),
        ("Smooth Gypsum Drywall", "uniform matte white gypsum drywall plasterboard surface"),
        ("Fine Sand Cement Render", "uniform fine-grained grey cement wall render surface"),
    ],
    "tile": [
        ("White Glossy Ceramic", "uniform glossy white glazed ceramic surface"),
        ("White Matte Ceramic", "uniform matte white unglazed ceramic surface"),
        ("Black Matte Porcelain", "uniform matte black porcelain stoneware surface"),
        ("Light Grey Porcelain", "uniform light grey porcelain stoneware surface"),
        ("Anthracite Porcelain", "uniform dark anthracite grey porcelain surface"),
        ("Beige Porcelain", "uniform warm beige porcelain stoneware surface"),
        ("Cream Glazed Ceramic", "uniform glossy cream glazed ceramic surface"),
        ("Emerald Glazed Ceramic", "uniform glossy emerald green glazed ceramic surface"),
        ("Cobalt Blue Ceramic", "uniform glossy cobalt blue glazed ceramic surface"),
        ("Sage Green Ceramic", "uniform matte sage green ceramic surface"),
        ("Turquoise Glazed Ceramic", "uniform glossy turquoise glazed ceramic surface"),
        ("Terracotta Red Ceramic", "uniform matte red terracotta ceramic clay surface"),
        ("Warm Sand Stoneware", "uniform warm sand-colored stoneware ceramic surface"),
        ("Charcoal Stoneware", "uniform dark charcoal matte stoneware ceramic surface"),
        ("Navy Blue Ceramic", "uniform glossy deep navy blue glazed ceramic surface"),
        ("Blush Pink Ceramic", "uniform soft blush pink glazed ceramic surface"),
        ("Mustard Yellow Ceramic", "uniform warm ochre yellow glazed ceramic surface"),
        ("Olive Green Ceramic", "uniform matte olive green ceramic surface"),
        ("Ivory Matte Porcelain", "uniform warm ivory matte porcelain surface"),
        ("Brown Glazed Stoneware", "uniform rich brown glazed stoneware ceramic surface"),
    ],
    "brick": [
        ("Red Brick Clay", "uniform fired red clay brick material surface, fine sandy clay texture"),
        ("Dark Red Brick Clay", "uniform deep dark red fired brick clay surface"),
        ("Yellow Buff Brick Clay", "uniform yellow-buff fired brick clay surface"),
        ("Brown Clinker Clay", "uniform dark brown vitrified clinker brick clay surface"),
        ("Black Clinker Clay", "uniform charcoal-black vitrified clinker brick clay surface"),
        ("Whitewashed Brick Clay", "uniform matte whitewashed clay masonry surface"),
        ("Orange Terracotta Clay", "uniform warm orange fired terracotta brick clay surface"),
        ("Cream Sand-Lime Brick", "uniform pale cream calcium-silicate sand-lime brick surface"),
        ("Grey Concrete Brick", "uniform rough grey concrete masonry brick surface"),
        ("Earth Adobe Clay", "uniform brown sun-dried adobe mud brick clay surface"),
        ("Buff Firebrick Clay", "uniform pale buff refractory fireclay brick surface"),
        ("Smoked Industrial Clay", "uniform dark soot-smoked industrial brick clay surface"),
        ("Salmon Pink Brick Clay", "uniform soft salmon-pink fired clay brick surface"),
        ("Rustic Ochre Brick Clay", "uniform warm ochre-brown handmade brick clay surface"),
        ("Charcoal Fired Clay", "uniform matte dark charcoal fired clay surface"),
        ("Light Grey Masonry Clay", "uniform light grey fired masonry clay surface"),
        ("Warm Umber Brick Clay", "uniform earthy umber-brown fired clay surface"),
        ("Aged Red Terracotta", "uniform weathered red terracotta clay surface"),
        ("Dry Mud Brick Clay", "uniform raw dry desert mud clay surface"),
        ("Matte Red Fired Clay", "uniform smooth matte red engineering brick clay surface"),
    ],
    "metal": [
        # Steel (Сталь)
        ("Steel - Polished", "uniform smooth mirror-polished stainless steel metal surface"),
        ("Steel - Brushed", "uniform fine linear brushed stainless steel metal surface"),
        ("Steel - Scratched / Worn", "uniform industrial stainless steel metal surface with fine micro-scratches and surface wear"),
        ("Steel - Satin Bead-Blasted", "uniform bead-blasted satin matte stainless steel metal surface"),
        ("Steel - Hot-Rolled Mill Scale", "uniform dark grey hot-rolled structural steel metal surface with natural mill scale"),
        ("Steel - Galvanized Zinc", "uniform spangled hot-dip galvanized zinc steel metal surface"),
        # Copper (Медь)
        ("Copper - Polished", "uniform smooth mirror-polished reddish-orange copper metal surface"),
        ("Copper - Brushed", "uniform fine linear brushed satin copper metal surface"),
        ("Copper - Scratched / Worn", "uniform aged copper metal surface with fine micro-scratches and natural wear"),
        ("Copper - Hammered", "uniform artisanal hand-hammered dimpled copper metal surface"),
        ("Copper - Green Patina", "uniform oxidized turquoise-green verdigris patina copper metal surface"),
        # Iron (Железо)
        ("Iron - Polished", "uniform smooth polished bright metallic iron surface"),
        ("Iron - Brushed", "uniform fine linear brushed grey metallic iron surface"),
        ("Iron - Scratched / Worn", "uniform weathered industrial iron metal surface with scratches and worn patina"),
        ("Iron - Forged Wrought", "uniform dark charcoal hand-forged wrought iron metal surface"),
        # Cast Iron (Чугун)
        ("Cast Iron - Polished Machined", "uniform machined and polished grey cast iron metal surface"),
        ("Cast Iron - Brushed", "uniform heavy brushed dark grey cast iron metal surface"),
        ("Cast Iron - Scratched / Pitted", "uniform weathered dark cast iron metal surface with micro-pitting and surface scratches"),
        ("Cast Iron - Raw Sand-Cast", "uniform matte dark grey rough sand-cast iron metal surface"),
        # Bronze (Бронза)
        ("Bronze - Polished", "uniform smooth mirror-polished warm golden-brown bronze metal surface"),
        ("Bronze - Brushed", "uniform fine linear brushed architectural bronze metal surface"),
        ("Bronze - Scratched / Worn", "uniform antique bronze metal surface with fine scratches and worn highlights"),
        ("Bronze - Oil-Rubbed Dark", "uniform dark oil-rubbed blackened architectural bronze metal surface"),
        ("Bronze - Oxidized Patina", "uniform aged bronze metal surface with natural green-brown oxidized patina"),
        # Corten Steel (Кортен)
        ("Corten Steel - Smooth Weathered", "uniform smooth sealed orange-brown Corten weathering rusted steel surface"),
        ("Corten Steel - Brushed Rust", "uniform brushed warm rust-orange Corten weathering steel surface"),
        ("Corten Steel - Scratched / Pitted", "uniform heavily weathered rough pitted Corten rusted steel surface with scratches"),
        # Aluminum (Алюминий)
        ("Aluminum - Polished", "uniform smooth mirror-polished bright silver aluminum metal surface"),
        ("Aluminum - Brushed", "uniform fine linear brushed silver anodized aluminum metal surface"),
        ("Aluminum - Scratched / Worn", "uniform raw industrial aluminum metal surface with fine scratches and scuff marks"),
        ("Aluminum - Bead-Blasted Matte", "uniform bead-blasted matte silver anodized aluminum metal surface"),
        ("Aluminum - Matte Black Anodized", "uniform bead-blasted matte black anodized aluminum metal surface"),
        # Brass, Gold, Chrome, Titanium
        ("Brass - Polished", "uniform smooth mirror-polished warm golden brass metal surface"),
        ("Brass - Brushed", "uniform fine linear brushed satin brass metal surface"),
        ("Brass - Scratched / Aged", "uniform aged antique brass metal surface with fine scratches and tarnish"),
        ("Gold - Polished 24K", "uniform smooth mirror-polished 24k yellow gold metal surface"),
        ("Gold - Brushed Satin", "uniform fine brushed satin champagne gold metal surface"),
        ("Chrome - Mirror Polished", "uniform ultra-smooth mirror-polished chrome metal surface"),
        ("Titanium - Brushed", "uniform warm grey fine brushed titanium metal surface"),
    ],
    "fabric": [
        ("Beige Linen Fabric", "uniform natural beige plain-weave linen fabric textile"),
        ("White Linen Fabric", "uniform crisp white woven linen fabric textile"),
        ("Grey Linen Fabric", "uniform neutral grey woven linen fabric textile"),
        ("White Cotton Fabric", "uniform smooth white woven cotton cloth textile"),
        ("Beige Cotton Canvas", "uniform heavy natural beige cotton canvas fabric"),
        ("Grey Wool Fabric", "uniform soft grey woven merino wool upholstery fabric"),
        ("Charcoal Wool Felt", "uniform dense pressed charcoal grey wool felt fabric"),
        ("Ivory Boucle Fabric", "uniform looped ivory white boucle upholstery fabric"),
        ("Beige Boucle Fabric", "uniform warm beige looped boucle sofa fabric"),
        ("Grey Boucle Fabric", "uniform soft grey looped boucle upholstery textile"),
        ("Royal Blue Velvet", "uniform plush royal blue velvet upholstery fabric"),
        ("Emerald Green Velvet", "uniform plush dark emerald green velvet fabric"),
        ("Burgundy Velvet", "uniform plush deep burgundy red velvet fabric"),
        ("Grey Velvet", "uniform plush silver-grey velvet upholstery fabric"),
        ("White Silk Satin", "uniform smooth lustrous white silk satin fabric"),
        ("Champagne Silk Satin", "uniform lustrous warm champagne silk satin fabric"),
        ("Brown Smooth Leather", "uniform natural saddle-brown fine-grain leather hide"),
        ("Black Smooth Leather", "uniform matte black fine-grain Nappa leather hide"),
        ("Tan Cognac Leather", "uniform warm cognac-tan smooth leather upholstery"),
        ("Tan Suede Alcantara", "uniform soft brushed camel-tan suede Alcantara fabric"),
        ("Grey Suede Alcantara", "uniform soft brushed charcoal-grey suede Alcantara fabric"),
        ("Blue Denim Twill", "uniform indigo blue diagonal twill denim cotton fabric"),
    ],
    "glass": [
        # --- Architectural & Tinted Glass ---
        ("Clear Architectural Glass", "uniform clear transparent architectural float glass surface"),
        ("Frosted Matte Glass", "uniform translucent acid-etched matte frosted glass surface"),
        ("Sandblasted Privacy Glass", "uniform fine sandblasted white translucent privacy glass"),
        # --- Glass Condensation (Запотевание) ---
        ("Foggy Condensation Glass", "steamy fogged window glass surface covered in soft cloudy moisture condensation mist and micro-vapor"),
        ("Wiped Steam Streak Glass", "fogged glass surface with vertical hand-wiped clear paths and warm steam condensation trails"),
        ("Edge Fogged Window Glass", "cold architectural window glass with dense moisture condensation fogging around edges and corners"),
        ("Warm Breath Mist Glass", "translucent misty glass surface with soft warm breath condensation cloud and fine micro-droplet halo"),
        # --- Glass Water Droplets (Капли и дождь) ---
        ("Rain Droplets Window Glass", "clear wet window glass surface covered with sharp scattered rainwater droplets and fine water beads"),
        ("Heavy Rain Streaks Glass", "wet architectural window glass with vertical running rainwater rivulets, sliding drops and water trails"),
        ("Fine Morning Dew Mist Glass", "translucent glass surface covered in dense fine atomized water mist spray and micro dew droplets"),
        ("Shower Steam & Drops Glass", "wet shower enclosure glass with heavy steam condensation beads and vertical gravity water drip tracks"),
        # --- Glass Icing & Frost (Обледенение и мороз) ---
        ("Feathery Ice Fern Glass", "frozen winter window glass covered in intricate feathery dendritic ice crystal fern patterns"),
        ("Frozen Rime Edge Glass", "arctic frozen window glass with heavy crystalline white rime ice crust and frost framing"),
        ("Cracked Glaze Ice Glass", "thick translucent frozen glaze ice sheet glass with crystalline fractures and trapped micro air bubbles"),
        ("Blizzard Hoarfrost Glass", "freezing cold window glass encrusted with dense spiky white hoarfrost needles and snow-ice crystals"),
        # --- Tinted, Textured & Specialty Glass ---
        ("Light Grey Tinted Glass", "uniform smoked light grey tinted architectural glass"),
        ("Dark Anthracite Glass", "uniform dark anthracite tinted solar glass surface"),
        ("Bronze Tinted Glass", "uniform warm bronze tinted architectural glass surface"),
        ("Green Float Glass", "uniform subtle green-tinted clear architectural float glass"),
        ("Blue Tinted Glass", "uniform cool sky-blue tinted architectural glass surface"),
        ("Amber Tinted Glass", "uniform warm amber-gold tinted translucent glass surface"),
        ("Milky Opal Glass", "uniform milky white opalescent diffused glass surface"),
        ("Fluted Reeded Glass", "uniform vertical ribbed reeded architectural privacy glass"),
        ("Hammered Obscure Glass", "uniform dimpled hammered texture obscure privacy glass"),
        ("Rippled Water Glass", "uniform softly wavy water-rippled translucent glass"),
        ("Seeded Bubble Glass", "uniform clear antique glass with fine micro air bubbles"),
        ("Ice Frosted Glass", "uniform cold crystalline frosted ice glass surface"),
        ("Smoked Black Glass", "uniform glossy dark black tinted smoked glass surface"),
        ("Clear Crystal Glass", "uniform high-clarity optical lead crystal glass surface"),
        ("Acid-Etched Matte Glass", "uniform silky smooth acid-etched satin glass surface"),
    ],
    "foliage": [
        # --- Single Isolated Leaf with Opacity Cutout (1 лист с картой Opacity по контуру листа) ---
        ("Single Leaf - Green Oak Leaf (Cutout)", "single isolated fresh green oak tree leaf blade with crisp lobed margin and natural veins on solid pure black background"),
        ("Single Leaf - Tropical Monstera (Cutout)", "single isolated glossy dark green tropical Monstera deliciosa leaf with natural fenestration splits on solid pure black background"),
        ("Single Leaf - Red Autumn Maple (Cutout)", "single isolated vibrant crimson-red autumn sugar maple leaf with pointed lobes and veins on solid pure black background"),
        ("Single Leaf - Yellow Birch Leaf (Cutout)", "single isolated golden-yellow autumn silver birch leaf with serrated edge and fine veins on solid pure black background"),
        ("Single Leaf - Green Maple Leaf (Cutout)", "single isolated fresh summer green maple tree leaf blade with palmate veins on solid pure black background"),
        ("Single Leaf - Woodland Fern Frond (Cutout)", "single isolated green woodland fern frond leaf with symmetrical pinnate leaflets on solid pure black background"),
        ("Single Leaf - Silver Eucalyptus (Cutout)", "single isolated matte silvery-green eucalyptus leaf blade on solid pure black background"),
        ("Single Leaf - English Ivy Leaf (Cutout)", "single isolated dark green five-lobed English ivy leaf with pale veins on solid pure black background"),
        ("Single Leaf - Tropical Palm Frond (Cutout)", "single isolated green tropical palm frond leaf fan with radiating leaflets on solid pure black background"),
        ("Single Leaf - Ficus Lyrata Leaf (Cutout)", "single isolated waxy dark green fiddle-leaf fig Ficus lyrata leaf with prominent light veins on solid pure black background"),
        ("Single Leaf - Calathea Striped Leaf (Cutout)", "single isolated tropical Calathea ornata leaf with dark green blade and pink-white pinstripes on solid pure black background"),
        ("Single Leaf - Banana Plant Leaf (Cutout)", "single isolated wide lush green tropical banana leaf blade with central midrib on solid pure black background"),
        ("Single Leaf - Green Rose Leaf Sprig (Cutout)", "single isolated compound green rosebush leaf sprig with serrated leaflets on solid pure black background"),
        ("Single Leaf - Pine Needle Twig (Cutout)", "single isolated green coniferous pine branchlet twig with needle clusters on solid pure black background"),
        # --- Soil, Earth, Peat & Forest Floor (Земля, почва, чернозём, торф и лесная подстилка) ---
        ("Soil - Dark Rich Garden Loam", "dark fertile organic black chernozem garden loam soil ground with fine crumbly earth clods"),
        ("Soil - Potting Soil & Perlite", "dark brown organic potting soil mix with peat fibers and scattered white perlite granules"),
        ("Soil - Damp Forest Floor Humus", "damp dark woodland humus soil ground with decomposed leaves, tiny twigs and organic litter"),
        ("Soil - Dry Cracked Clay Earth", "sun-baked dry brown clay earth ground with natural shrinkage cracks and dusty soil granules"),
        ("Soil - Wet Muddy Earth Ground", "wet dark brown muddy soil ground with glossy moisture puddles and soft earth texture"),
        ("Soil - Sandy Loam Ground", "warm brown sandy loam topsoil with fine mineral quartz sand grains and small pebbles"),
        ("Soil - Fibrous Brown Peat Moss", "fibrous reddish-brown sphagnum peat moss substrate with organic root fibers"),
        ("Soil - Pine Needle Forest Litter", "dry brown and green pine needles forest floor litter with small pine cones and bark bits"),
        ("Soil - Autumn Fallen Leaf Litter", "dense forest floor covered with dry golden, orange and brown fallen autumn oak and maple leaves"),
        ("Soil - Mossy Woodland Earth", "dark forest soil ground with patches of velvet green moss, small roots and humus"),
        # --- Bark Mulch & Woodchips (Мульча, древесная щепа и кора) ---
        ("Mulch - Coarse Pine Bark Nuggets", "landscaping coarse reddish-brown pine bark mulch nuggets and chunky tree bark chips"),
        ("Mulch - Fine Shredded Pine Bark", "dark brown finely shredded fibrous pine bark garden mulch ground cover"),
        ("Mulch - Red Cedar Woodchips", "vibrant warm reddish-orange shredded cedar woodchip landscaping mulch"),
        ("Mulch - Black Dyed Woodchips", "deep charcoal-black dyed shredded hardwood landscaping woodchip mulch"),
        ("Mulch - Natural Blonde Woodchips", "freshly chipped light golden-blonde natural softwood arborist woodchips mulch"),
        ("Mulch - Dark Composted Bark", "aged dark espresso-brown composted humus bark mulch with fine organic texture"),
        ("Mulch - Larch Bark Landscaping", "Siberian larch tree bark mulch with layered reddish-brown and grey bark flakes"),
        ("Mulch - Cocoa Shell & Husk", "warm chocolate-brown crushed cocoa bean shell organic garden mulch"),
        # --- Dense Canopy Foliage, Hedges, Grass & Moss (Листва, живые изгороди, трава и мох) ---
        ("Green Lawn Grass", "uniform lush green lawn grass blades ground foliage texture"),
        ("Wild Meadow Grass", "uniform natural green meadow grass foliage surface"),
        ("Forest Green Moss", "uniform soft velvet forest green moss carpet foliage"),
        ("Sphagnum Bog Moss Carpet", "lush wet bright green and lime sphagnum bog moss carpet foliage"),
        ("Dark Green Ivy Leaves", "uniform dense dark green English ivy leaf foliage"),
        ("Boxwood Hedge Foliage", "uniform dense small green boxwood hedge leaves foliage"),
        ("Lush Privet Hedge Canopy", "dense clipped green privet ligustrum hedge leaf canopy foliage"),
        ("Conifer Thuja Cypress Foliage", "dense green feathery Thuja occidentalis arborvitae cypress scale-leaf foliage"),
        ("Flowering Jasmine Vine Foliage", "dense dark green star jasmine climbing vine leaves with small white blossoms"),
        ("Green Oak Leaf Surface", "uniform natural green oak tree leaf blade surface texture"),
        ("Tropical Monstera Leaf", "uniform waxy dark green tropical plant leaf surface"),
        ("Green Fern Fronds", "uniform fresh green woodland fern frond leaves foliage"),
        ("Pine Needles Litter", "uniform green and brown pine tree needles foliage texture"),
        ("Eucalyptus Green Leaf", "uniform matte silver-green eucalyptus leaf foliage surface"),
        ("Autumn Red Maple Leaf", "uniform vibrant crimson autumn maple leaf foliage surface"),
        ("Autumn Yellow Birch Leaf", "uniform golden-yellow autumn birch leaf foliage surface"),
        ("Green Bamboo Leaves", "uniform slender fresh green bamboo leaf foliage"),
        ("Olive Tree Foliage", "uniform Mediterranean silvery-green olive tree leaves"),
        ("Green Clover Ground", "uniform dense green three-leaf clover ground cover foliage"),
        ("Dry Golden Grass", "uniform sun-dried golden steppe grass blades foliage"),
        ("Green Lichen Surface", "uniform pale green organic lichen plant growth texture"),
        ("Dense Bush Foliage", "uniform dense green garden shrub leaf foliage"),
    ],
    "plastic": [
        # --- Carbon Fiber, Kevlar & Woven Composites (Карбон, кевлар и волокнистые композиты) ---
        ("Carbon Fiber 3K Twill Gloss", "glossy 3K 2x2 diagonal twill weave black carbon fiber composite under clear epoxy resin coat"),
        ("Carbon Fiber Plain Weave Matte", "matte dry 1x1 plain checkerboard weave black carbon fiber composite surface"),
        ("Forged Chopped Carbon Fiber", "marbled forged composite chopped carbon fiber flakes in glossy black epoxy resin matrix"),
        ("Spread Tow Carbon Weave", "wide flat-tape checkerboard spread-tow carbon fiber composite weave"),
        ("Carbon Kevlar Hybrid Weave", "interlocking black carbon fiber and golden-yellow aramid Kevlar twill hybrid composite weave"),
        ("Yellow Kevlar Aramid Weave", "dense woven golden-yellow ballistic Kevlar aramid fiber composite surface"),
        ("Woven Fiberglass Composite", "translucent amber-green woven E-glass fiberglass cloth in epoxy resin matrix"),
        ("FR4 PCB Epoxy Fiberglass", "industrial emerald-green FR4 woven fiberglass epoxy printed circuit board substrate"),
        ("Black G10 Garolite Composite", "layered matte black G10 phenolic fiberglass epoxy laminate composite"),
        ("Linen Micarta Composite", "layered olive-brown canvas linen Micarta phenolic resin composite texture"),
        # --- Epoxy Resin, Metallic Swirls & Flake Coatings (Эпоксидные смолы и полимерные полы) ---
        ("Clear Cast Epoxy Resin", "smooth high-gloss transparent cast epoxy polymer resin surface"),
        ("Turquoise River Epoxy Swirl", "glossy deep ocean turquoise-blue pearlescent mica swirl epoxy resin pour"),
        ("Emerald Pearl Epoxy Resin", "high-gloss dark emerald green metallic mica pigment swirled epoxy resin"),
        ("Gold & Black Marble Epoxy", "glossy obsidian black epoxy resin with flowing metallic gold mica veins"),
        ("Cobalt Blue Pearl Epoxy", "deep royal cobalt blue shimmering metallic mica swirl epoxy resin surface"),
        ("Amber Fossil Epoxy Resin", "warm golden-orange translucent Baltic amber cast epoxy polymer resin"),
        ("Epoxy Terrazzo Flake Floor", "seamless industrial epoxy resin floor coating with speckled grey, white and black polymer flakes"),
        ("Epoxy Quartz Broadcast Floor", "textured non-slip industrial epoxy resin floor broadcast with fine colored quartz sand granules"),
        # --- Engineering Polymers & 3D Printing (Инженерные пластики и 3D-печать) ---
        ("Matte Black ABS Plastic", "uniform fine-grained matte black injection-molded ABS plastic surface"),
        ("Fine Textured ABS Housing", "micro-stippled VDI-27 Mold-Tech matte dark grey electronics ABS plastic housing"),
        ("Glossy White Acrylic PMMA", "uniform smooth high-gloss white cast acrylic PMMA Perspex polymer surface"),
        ("Frosted Diffuser Acrylic", "uniform matte satin light-diffusing frosted white PMMA acrylic sheet"),
        ("White POM Delrin Polymer", "smooth low-friction machined white polyoxymethylene POM Delrin engineering acetal plastic"),
        ("Natural Beige PEEK Polymer", "smooth high-performance warm beige polyetheretherketone PEEK engineering polymer"),
        ("White PTFE Teflon Surface", "ultra-smooth waxy pure white polytetrafluoroethylene PTFE Teflon fluoropolymer"),
        ("Black Glass-Filled Nylon PA66", "matte black PA66 polyamide nylon reinforced with fine micro glass fibers"),
        ("3D Printed FDM Layer Lines", "matte black FDM 3D-printed PLA PETG polymer with fine horizontal extrusion layer lines"),
        ("3D Printed SLA Grey Resin", "smooth matte neutral grey SLA photopolymer 3D-printed resin surface"),
        ("Recycled Confetti HDPE Plastic", "pressed recycled high-density polyethylene HDPE sheet with melted colorful plastic flakes"),
        # --- Elastomers, Rubbers, Silicones & Foams (Резина, силикон, неопрен и пены) ---
        ("Black Vulcanized Rubber", "uniform matte black vulcanized industrial elastomer rubber surface"),
        ("Diamond Plate Rubber Mat", "heavy-duty black industrial rubber flooring with raised diamond tread pattern"),
        ("Ribbed Anti-Slip Rubber", "black elastomer rubber mat with parallel linear anti-slip ribs"),
        ("Grey Silicone Rubber", "uniform smooth soft-touch matte grey liquid silicone rubber surface"),
        ("Black Neoprene Wetsuit Foam", "micro-textured matte black closed-cell chloroprene neoprene rubber"),
        ("Recycled Crumb Rubber EPDM", "porous black and speckled shock-absorbing recycled EPDM crumb rubber surface"),
        ("Charcoal Acoustic Foam", "uniform open-cell charcoal grey polyurethane studio acoustic foam surface"),
        ("Black EVA Foam", "uniform fine micro-textured black closed-cell EVA polymer foam"),
        ("White Polystyrene Foam", "uniform white expanded polystyrene EPS bead foam surface"),
        # --- PVC, Vinyl, Polycarbonate & Colored Polymers (ПВХ, винил, поликарбонат и цветной пластик) ---
        ("Matte Grey PVC Plastic", "uniform smooth matte grey PVC plastic sheet surface"),
        ("Clear Polycarbonate", "uniform smooth transparent polycarbonate polymer surface"),
        ("Translucent Polyethylene", "uniform milky translucent LDPE polyethylene plastic surface"),
        ("Beige Linoleum PVC", "uniform matte beige architectural linoleum PVC floor sheet"),
        ("Grey Vinyl Sheet", "uniform smooth commercial grey PVC vinyl sheet surface"),
        ("Matte Red Plastic", "uniform smooth matte red injection-molded plastic surface"),
        ("Matte Blue Plastic", "uniform smooth matte royal blue plastic polymer surface"),
        ("Matte Yellow Plastic", "uniform smooth matte industrial yellow plastic surface"),
        ("Matte Green Plastic", "uniform smooth matte green polymer plastic surface"),
    ],
    "light": [
        ("Warm White 2700K Light", "uniform glowing warm white 2700K diffused LED light surface"),
        ("Neutral White 4000K Light", "uniform glowing neutral white 4000K ceiling light panel surface"),
        ("Cool Daylight 6500K Light", "uniform glowing cool daylight 6500K diffused light surface"),
        ("Soft Amber LED Glow", "uniform glowing warm amber-gold diffused light surface"),
        ("Warm Tungsten Glow", "uniform glowing 2200K vintage tungsten orange light surface"),
        ("Backlit Frosted Acrylic", "uniform glowing evenly lit frosted white acrylic diffuser"),
        ("Glowing White Diffuser", "uniform pure white self-illuminated studio softbox light"),
        ("Glowing Cyan Neon", "uniform glowing bright cyan-blue neon light surface"),
        ("Glowing Magenta Neon", "uniform glowing vibrant magenta-pink neon light surface"),
        ("Glowing Blue Light", "uniform glowing deep electric blue emissive light surface"),
        ("Glowing Red Light", "uniform glowing saturated crimson red emissive light surface"),
        ("Glowing Green Light", "uniform glowing bright emerald green emissive light surface"),
        ("Glowing Golden Orange", "uniform glowing warm golden-orange emissive light surface"),
        ("Backlit Honey Onyx Glow", "uniform glowing warm backlit translucent honey onyx light"),
        ("Glowing Violet Light", "uniform glowing deep ultraviolet purple emissive light"),
        ("Warm Candlelight Glow", "uniform glowing soft 1800K warm candlelight emissive surface"),
        ("Glowing Red Hot Ember", "uniform glowing incandescent red-orange thermal light"),
        ("Soft Ice Blue Glow", "uniform glowing pale arctic ice-blue diffused light surface"),
    ],
    "decal": [
        # --- Structural Cracks, Spalling & Damage (Трещины, сколы и разрушения) ---
        ("Deep Concrete Structural Crack", "decal deep branching structural concrete wall crack and jagged fissure centered on neutral background"),
        ("Fine Hairline Plaster Fracture", "decal delicate branching hairline plaster crack network on smooth wall surface"),
        ("Impact Concrete Crater & Spall", "decal chipped concrete impact crater and fractured surface spalling damage"),
        ("Exposed Brick Spalling Plaster", "decal damaged chipped plaster hole revealing weathered red brick masonry underneath"),
        # --- Water Leaks, Puddles, Dampness & Efflorescence (Лужи, подтёки, сырость и высолы) ---
        ("Wet Rainwater Puddle Patch", "decal irregular wet glossy rainwater puddle stain with soft damp dark rim on floor"),
        ("Damp Wall Water Leak Streaks", "decal vertical weathered rainwater leak streaks and dark damp mineral stains"),
        ("Ceiling Damp Water Ring Stain", "decal organic yellowish-brown ceiling water leak ring stain and damp blotch"),
        ("White Salt Efflorescence Crust", "decal chalky white crystalline salt efflorescence mineral deposits on damp masonry"),
        # --- Rust, Corrosion, Oil & Soot Stains (Ржавчина, коррозия, масло и копоть) ---
        ("Rust Drip Stain below Bolts", "decal vertical orange-brown oxidized rust drip streaks and corrosion stain trail"),
        ("Heavy Corroded Rust Flake Patch", "decal blistered flaky dark orange iron rust oxidation and corrosion patch"),
        ("Asphalt Oil & Tire Mark Stain", "decal dark glossy motor oil spill blotch and rubber tire skid marks on pavement"),
        ("Charred Soot & Fire Scorch Mark", "decal black carbon soot smudge and charred thermal burn scorch stain"),
        # --- Road Markings, Manholes & Organic Moss (Дорожная разметка, люки и мох) ---
        ("Weathered White Road Marking", "decal distressed chipped white painted road stripe arrow marking with asphalt wear"),
        ("Yellow Hazard Warning Stripe", "decal worn industrial yellow and black hazard warning floor paint stripe"),
        ("Cast Iron Manhole Cover", "decal round industrial ribbed cast-iron street manhole cover plate"),
        ("Organic Wall Moss & Lichen Patch", "decal organic green moss and lichen colony patch spreading from damp wall crevices"),
        # --- Peeling Paint, Putty & Construction Wear (Облупившаяся краска, шпаклёвка и выбоины) ---
        ("Peeling & Blistered Wall Paint", "decal flaking curled peeling paint patch with blistered edges on weathered wall"),
        ("Drywall Screw & Putty Patch", "decal white gypsum spackle putty repair patch with sanded trowel strokes and drywall screw indents"),
        ("Asphalt Pothole & Gravel Patch", "decal broken asphalt pothole depression exposing crushed gravel aggregate stones"),
        ("Chipped Ceramic Tile Damage", "decal cracked and missing ceramic floor tile patch exposing rough gray mortar adhesive bed"),
        # --- Urban, Street & Industrial Details (Уличные решётки, плакаты, граффити и скотч) ---
        ("Storm Drain Metal Grate", "decal rectangular slotted rusty cast-iron street storm drain water grate"),
        ("Torn Street Poster Remnants", "decal weathered torn layered street paper poster scraps with wheatpaste glue residue"),
        ("Urban Stencil Graffiti Tag", "decal distressed black and red street art spray paint stencil graffiti emblem with paint drips"),
        ("Silver Duct Tape Repair Strip", "decal crossed strips of wrinkled silver reinforced cloth duct tape patch"),
        # --- Footprints, Tracks & Seasonal Nature (Следы обуви, протектор, листья и иней) ---
        ("Muddy Boot Footprints Trail", "decal dirty dried mud workboot sole footprints and mud splatters on floor"),
        ("Heavy Off-Road Tire Mud Track", "decal deep muddy off-road truck tire tread track imprint on ground"),
        ("Wet Autumn Leaves Cluster", "decal scattered wet fallen orange and brown autumn leaves cluster sticking to damp ground"),
        ("Frozen Hoarfrost & Ice Patch", "decal crystalline white winter hoarfrost and cracked translucent ice glaze patch"),
        # --- GameDev: Combat Impacts, Slashes & Destruction (Геймдев: пулевые отверстия, взрывы и удары) ---
        ("Bullet Holes Concrete Cluster", "decal cluster of high-caliber bullet impact holes in concrete with radial fractures and powder soot"),
        ("Metal Armor Bullet Piercing", "decal punctured steel plate bullet hole with peeled jagged metal rim and heat discoloration"),
        ("Explosion Blast Scorch Crater", "decal radial grenade explosion blast crater with charred black soot rays and shattered debris"),
        ("Monster Claw & Blade Slash Marks", "decal three deep parallel monster claw gouge slash marks carved into stone and metal"),
        # --- GameDev: Gore, Acid, Spiderwebs & Fantasy (Геймдев: кровь, кислота, паутина и руны) ---
        ("Dark Crimson Blood Splatter", "decal visceral dark crimson blood splatter drops and coagulation stain on floor"),
        ("Toxic Acid Corrosion Burn", "decal bubbling green-yellow chemical acid melt corrosion puddle eating into metal surface"),
        ("Dusty Cobweb & Spiderweb Patch", "decal thick dusty abandoned corner spiderweb silk threads and tangled cobweb patch"),
        ("Carved Ancient Stone Rune", "decal chiseled sunken ancient mystical Nordic rune symbol carved into weathered stone"),
        # --- GameDev: Sci-Fi, Mecha & Industrial Trim (Геймдев: сварные швы, заклёпки, люки и лава) ---
        ("Industrial Weld Seam & Rivets", "decal heavy steel plate seam with stacked TIG weld bead and oxidized iron bolts"),
        ("Sci-Fi Hull Access Hatch Stencil", "decal futuristic sci-fi spacecraft hull maintenance access hatch plate with warning stencils"),
        ("Glowing Magma Fissure Crack", "decal jagged volcanic ground fissure crack with glowing incandescent orange-red molten lava inside"),
        ("Spilled Industrial Chemical Grunge", "decal dried rainbow iridescent chemical oil slick and industrial grime puddle stain"),
    ],
    "bw_mask": [
        # --- Glass Condensation (Запотевание) ---
        ("Glass - Foggy Condensation Mist", "soft uneven steam condensation mist and cloudy moisture fogging on window glass, smooth transitions from white mist patches to dark clear areas"),
        ("Glass - Edge Condensation Vignette", "heavy steam condensation fogging around window glass edges and corners fading smoothly toward a clear dark center"),
        ("Glass - Wiped Condensation Streaks", "steamy fogged window glass with vertical hand-wiped clear paths and dripping condensation smudge trails"),
        ("Glass - Breath Steam Patch", "soft radial warm breath condensation fog cloud on cold glass with fine micro-droplet halo"),
        # --- Glass Water Droplets (Капли) ---
        ("Glass - Rain Droplets Scattered", "sharp round rainwater droplets and fine micro-beads scattered across window glass surface, crisp white droplets on black background"),
        ("Glass - Heavy Rain Streaks & Rivulets", "vertical running rainwater rivulet trails, sliding water drops and wet gravity streaks on window glass"),
        ("Glass - Fine Mist Spray Drops", "dense fine atomized water mist micro-droplets and morning dew beads evenly distributed on glass surface"),
        ("Glass - Condensation Drip Trails", "saturated steam condensation beads merging into vertical gravity drip trails and wet tracks on glass"),
        # --- Glass Icing & Frost (Обледенение) ---
        ("Glass - Feathery Ice Fern Frost", "intricate feathery dendritic ice crystal fern patterns spreading across frozen window glass"),
        ("Glass - Frozen Window Edge Rime", "heavy crystalline winter frost and frozen rime ice crust framing window glass edges and corners"),
        ("Glass - Cracked Sheet Ice Glaze", "frozen translucent glaze ice sheet with crystalline fractures, air bubbles and hoarfrost patches on glass"),
        ("Glass - Heavy Blizzard Hoarfrost", "dense spiky crystalline hoarfrost needles and dendritic snow-ice buildup on freezing glass"),
        # --- ArchViz Decals (Декали: трещины, лужи, подтёки, ржавчина, мох, разметка) ---
        ("Decal - Deep Concrete Structural Crack", "decal deep branching structural concrete wall crack and jagged fissure centered on neutral background"),
        ("Decal - Wet Rainwater Puddle Patch", "decal irregular wet glossy rainwater puddle stain with soft damp dark rim on floor"),
        ("Decal - Damp Wall Water Leak Streaks", "decal vertical weathered rainwater leak streaks and dark damp mineral efflorescence stains"),
        ("Decal - Rust Drip Stain below Bolts", "decal vertical orange-brown oxidized rust drip streaks and corrosion stain trail"),
        ("Decal - Exposed Brick Spalling Plaster", "decal damaged chipped plaster hole revealing weathered red brick masonry underneath"),
        ("Decal - Asphalt Oil & Tire Mark Stain", "decal dark glossy motor oil spill blotch and rubber tire skid marks on pavement"),
        ("Decal - Weathered White Road Marking", "decal distressed chipped white painted road stripe arrow marking with asphalt wear"),
        ("Decal - Organic Wall Moss & Lichen Patch", "decal organic green moss and lichen colony patch spreading from damp wall crevices"),
        # --- General Surface Wear & Grunge Masks ---
        ("Grunge Dirt Splatters", "grunge dirt splatters, weathered smudges and organic blotches"),
        ("Fine Surface Scratches", "dense fine directional surface scratches and micro-scuffs"),
        ("Branching Cracks", "sharp branching surface cracks and thin fractures"),
        ("Peeling Paint Mask", "cracked peeling paint flakes and chipped coating islands"),
        ("Moss Patches Mask", "organic patchy moss growth clusters and lichen spots"),
        ("Edge Wear Scuffs", "distressed surface abrasions, scuff marks and worn patches"),
        ("Water Leak Stains", "vertical rain leak streaks and damp stain blotches"),
        ("Rust Pits Mask", "pitted oxidation spots and corrosion clusters"),
        ("Concrete Pores Mask", "fine scattered air bubble pinholes and concrete pores"),
        ("Wood Grain Mask", "high-contrast flowing wood grain fibers"),
        ("Marble Veins Mask", "branching natural marble veins on dark background"),
        ("Cloud Noise Mask", "soft organic cloudy Perlin noise gradients"),
        ("Voronoi Cells Mask", "geometric cellular crack polygons"),
        ("Paint Drops Mask", "liquid paint splatters and droplets"),
        ("Dust Smudges Mask", "soft wiped dust marks and surface smudges"),
        ("Woven Threads Mask", "interlocking plain-weave textile threads alpha"),
        ("Hexagon Grid Mask", "clean geometric hexagonal honeycomb grid stencil"),
        ("Perforated Dots Mask", "uniform grid of circular punched dots"),
        ("Frost Crystals Mask", "feathery ice frost crystal patterns"),
        ("Fingerprints Mask", "oily fingerprint smudges and wiped marks"),
        ("Scorch Burn Mask", "irregular charred fire scorch blotches"),
        ("Sand Ripples Mask", "parallel wind-blown sand wave ripples"),
        ("Brush Strokes Mask", "hand-painted coarse bristle brush strokes"),
        ("Speckled Noise Mask", "fine granular speckled mineral noise"),
        ("Worn Grunge Mask", "uniform weathered distressed grunge surface alpha"),
    ],
}

PRESET_BUTTONS = [
    ("Oak Parquet", "oak wood parquet floor, herringbone pattern, natural light oak timber"),
    ("White Marble", "white Carrara marble stone with subtle grey and gold veins"),
    ("Red Brick", "weathered red clay brick wall with rough mortar joints"),
    ("Mask: Grunge/Dirt", "grunge dirt splatters, weathered smudges, dust stains and blotches"),
    ("Mask: Cracks", "sharp branching stone cracks, fractures and crevices"),
]


def _style_text(
    tb: unreal.TextBlock,
    size: int = 9,
    bold: bool = False,
    color: tuple = (0.88, 0.89, 0.92, 1.0),
) -> None:
    """Настраивает аккуратный размер шрифта, начертание и цвет для TextBlock в UMG (с обновлением Slate)."""
    try:
        f = tb.get_editor_property("font")
        f.size = float(size)
        f.typeface_font_name = "Bold" if bold else "Regular"
        if hasattr(tb, "set_font"):
            tb.set_font(f)
        else:
            tb.set_editor_property("font", f)
        tb.set_color_and_opacity(unreal.SlateColor(unreal.LinearColor(*color)))
        if hasattr(tb, "synchronize_properties"):
            tb.synchronize_properties()
    except Exception:
        pass


def _translate_or_clean_prompt(raw_prompt: str) -> str:
    """Переводит русский промпт материала на английский и очищает лишние символы."""
    text = (raw_prompt or "").strip()
    if not text:
        return "oak wood parquet floor, herringbone pattern, natural timber"

    lower = text.lower()
    if lower in RU_TO_EN_MATERIALS:
        return RU_TO_EN_MATERIALS[lower]

    if re.search(r"[а-яА-ЯёЁ]", text):
        for ru_key, en_val in RU_TO_EN_MATERIALS.items():
            if ru_key in lower:
                return en_val
        try:
            q = urllib.parse.quote(text)
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=ru&tl=en&dt=t&q={q}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated = "".join(part[0] for part in data[0] if part and part[0])
                if translated.strip():
                    return translated.strip()
        except Exception:
            pass

    return text


def _make_slug(prompt_en: str) -> str:
    """Формирует короткое имя ассета из английского промпта (например, OakWoodParquet)."""
    words = re.findall(r"[A-Za-z0-9]+", prompt_en)
    stop = {"top", "down", "view", "of", "a", "an", "the", "seamless", "tileable", "texture", "with", "and"}
    filtered = [w.capitalize() for w in words if w.lower() not in stop][:3]
    slug = "".join(filtered) if filtered else "Material"
    return slug[:24]


def _normalize_ue_folder(folder_path: str) -> str:
    """Нормализует путь папки Content Browser без завершающего слэша (по умолчанию /Game/Textures/ComfyUI)."""
    raw = (folder_path or "").strip().replace("\\", "/")
    if not raw or raw in ("/", "/Game", "/Game/"):
        return DEFAULT_UE_FOLDER
    if not raw.startswith("/Game"):
        raw = "/Game/" + raw.lstrip("/")
    raw = raw.rstrip("/")
    return raw if raw != "/Game" else DEFAULT_UE_FOLDER


def _detect_material_category(raw_prompt: str, prompt_en: str = "") -> str:
    """
    Detects the primary material category:
    1) First checks if the prompt matches a curated preset in CATEGORY_PRESET_PROMPTS.
    2) Next finds the earliest word-boundary matching material keyword in the prompt
       (supporting CamelCase slugs like MI_WoodOakParquet as well):
       wood, stone, concrete, tile, fabric, glass, mirror, brick, metal, plastic, light.
    """
    for source_text in (raw_prompt or "", prompt_en or ""):
        clean_src = source_text.strip().lower()
        if not clean_src:
            continue
        for cat_k, items in CATEGORY_PRESET_PROMPTS.items():
            if cat_k == "bw_mask":
                continue
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
                if re.match(r"^[a-z0-9 ]+$", kw):
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


def _set_content_browser_folder_color(
    folder_path: str,
    r: float,
    g: float,
    b: float,
    a: float = 1.0,
    only_if_unset: bool = True,
) -> bool:
    """
    Sets the Content Browser folder icon color in UE5 via AssetViewUtils::SetPathColor
    in UnrealEditor-AssetTools.dll (updating GConfig [PathColor] and broadcasting live to Content Browser).
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _FString(ctypes.Structure):
            _fields_ = [
                ("Data", ctypes.c_wchar_p),
                ("ArrayNum", ctypes.c_int32),
                ("ArrayMax", ctypes.c_int32),
            ]

        class _TOptionalLinearColor(ctypes.Structure):
            _fields_ = [
                ("R", ctypes.c_float),
                ("G", ctypes.c_float),
                ("B", ctypes.c_float),
                ("A", ctypes.c_float),
                ("bIsSet", ctypes.c_bool),
            ]

        k32 = ctypes.WinDLL("kernel32")
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        k32.GetProcAddress.argtypes = [wintypes.HMODULE, ctypes.c_char_p]
        k32.GetProcAddress.restype = ctypes.c_void_p

        h_mod = k32.GetModuleHandleW("UnrealEditor-AssetTools.dll")
        if not h_mod:
            return False
        sym_set = b"?SetPathColor@AssetViewUtils@@YAXAEBVFString@@U?$TOptional@UFLinearColor@@@@@Z"
        sym_get = b"?GetPathColor@AssetViewUtils@@YA?AU?$TOptional@UFLinearColor@@@@AEBVFString@@@Z"
        set_addr = k32.GetProcAddress(h_mod, sym_set)
        get_addr = k32.GetProcAddress(h_mod, sym_get)
        if not set_addr:
            return False

        fstr = _FString(folder_path, len(folder_path) + 1, len(folder_path) + 1)
        if only_if_unset and get_addr:
            get_fn = ctypes.CFUNCTYPE(
                ctypes.POINTER(_TOptionalLinearColor),
                ctypes.POINTER(_TOptionalLinearColor),
                ctypes.POINTER(_FString),
            )(get_addr)
            cur = _TOptionalLinearColor()
            get_fn(ctypes.byref(cur), ctypes.byref(fstr))
            if cur.bIsSet:
                return True

        set_fn = ctypes.CFUNCTYPE(None, ctypes.POINTER(_FString), ctypes.POINTER(_TOptionalLinearColor))(set_addr)
        opt = _TOptionalLinearColor(float(r), float(g), float(b), float(a), True)
        set_fn(ctypes.byref(fstr), ctypes.byref(opt))
        return True
    except Exception:
        return False


def _extract_texture_base_stem(tex_name: str) -> str:
    """Extracts the material base stem from a PBR texture name like T_OldEuropeanStone_1K_80_Albedo -> OldEuropeanStone_1K_80."""
    stem = tex_name[2:] if tex_name.startswith("T_") else tex_name
    for sfx in ("_Albedo", "_Normal", "_Roughness", "_Height", "_Opacity", "_ORM", "_Metallic", "_BaseColor", "_Mask"):
        if stem.endswith(sfx):
            stem = stem[: -len(sfx)]
            break
    return stem


def _ensure_folder_structure(base_folder: str = DEFAULT_UE_FOLDER) -> None:
    """
    Создаёт структуру подпапок внутри базовой директории:
    - <base_folder>/Textures/<category> — для всех PBR-текстур (T_*) по категориям сгенерированного материала [голубой цвет папки]
    - <base_folder>/Masks — для всех Ч/Б масок (T_Mask_*, T_LivePaintMask_*) [фиолетовый цвет папки]
    - <base_folder>/<category> — для материалов (wood, stone, concrete, tile, fabric, glass, foliage, mirror, brick, metal, plastic, light, decal)
    А также автоматически раскладывает лежащие в корне или в общем Textures/ ассеты T_* и MI_* по соответствующим папкам категорий.
    """
    base_folder = _normalize_ue_folder(base_folder)
    while base_folder.split("/")[-1].lower() in [c.lower() for c in MATERIAL_CATEGORIES] or base_folder.split("/")[-1] in (
        TEXTURES_SUBFOLDER,
        MASKS_SUBFOLDER,
        "Meshes",
    ):
        base_folder = "/".join(base_folder.split("/")[:-1]) or DEFAULT_UE_FOLDER
    try:
        tex_dir = f"{base_folder}/{TEXTURES_SUBFOLDER}"
        msk_dir = f"{base_folder}/{MASKS_SUBFOLDER}"
        msh_dir = f"{base_folder}/Meshes"
        unreal.EditorAssetLibrary.make_directory(tex_dir)
        unreal.EditorAssetLibrary.make_directory(msk_dir)
        _set_content_browser_folder_color(msk_dir, 0.58, 0.24, 0.96, 1.0, only_if_unset=True)
        _set_content_browser_folder_color(tex_dir, 0.10, 0.68, 0.96, 1.0, only_if_unset=True)
        _set_content_browser_folder_color(msh_dir, 0.96, 0.52, 0.12, 1.0, only_if_unset=True)
        for cat in MATERIAL_CATEGORIES:
            unreal.EditorAssetLibrary.make_directory(f"{base_folder}/{cat}")
            unreal.EditorAssetLibrary.make_directory(f"{tex_dir}/{cat}")

        all_assets = list(unreal.EditorAssetLibrary.list_assets(base_folder, recursive=True))
        stem_to_cat = {}
        cat_set_lower = {c.lower(): c for c in MATERIAL_CATEGORIES}

        moved_any = False
        # Pass 1: Move root MI_* into <base_folder>/<cat>/ and record <Stem> -> <cat> from all MI_*
        for a_path in all_assets:
            clean = a_path.split(".")[0]
            parent_dir = clean.rsplit("/", 1)[0] if "/" in clean else ""
            name = clean.split("/")[-1]
            if not name.startswith("MI_"):
                continue
            mi_stem = name[3:]
            parent_leaf = parent_dir.split("/")[-1].lower() if parent_dir else ""
            if parent_leaf in cat_set_lower:
                stem_to_cat[mi_stem.lower()] = cat_set_lower[parent_leaf]
            elif parent_dir == base_folder:
                cat = _detect_material_category(name)
                stem_to_cat[mi_stem.lower()] = cat
                dst = f"{base_folder}/{cat}/{name}"
                if clean != dst and not unreal.EditorAssetLibrary.does_asset_exist(dst):
                    if unreal.EditorAssetLibrary.rename_asset(clean, dst):
                        moved_any = True

        # Pass 2: Move T_Mask_* into Masks/, keep T_Default_* in Textures/, and move PBR T_* into Textures/<category>/
        for a_path in all_assets:
            clean = a_path.split(".")[0]
            parent_dir = clean.rsplit("/", 1)[0] if "/" in clean else ""
            name = clean.split("/")[-1]
            if not name.startswith("T_"):
                continue
            if name.startswith(("T_Mask_", "T_LivePaintMask_")):
                dst = f"{base_folder}/{MASKS_SUBFOLDER}/{name}"
                if clean != dst and not unreal.EditorAssetLibrary.does_asset_exist(dst):
                    if unreal.EditorAssetLibrary.rename_asset(clean, dst):
                        moved_any = True
            elif name.startswith("T_Default_"):
                dst = f"{base_folder}/{TEXTURES_SUBFOLDER}/{name}"
                if clean != dst and not unreal.EditorAssetLibrary.does_asset_exist(dst):
                    if unreal.EditorAssetLibrary.rename_asset(clean, dst):
                        moved_any = True
            else:
                parent_leaf = parent_dir.split("/")[-1].lower() if parent_dir else ""
                if parent_dir.startswith(f"{tex_dir}/") and parent_leaf in cat_set_lower:
                    continue
                t_stem = _extract_texture_base_stem(name)
                cat = stem_to_cat.get(t_stem.lower())
                if not cat:
                    # Also handle Decal_ prefix or Baked_ prefix
                    if t_stem.lower().startswith("decal_"):
                        cat = "decal"
                    elif t_stem.lower().startswith("baked_"):
                        inner_stem = re.sub(r"_\d+$", "", t_stem[6:])
                        cat = stem_to_cat.get(inner_stem.lower()) or _detect_material_category(inner_stem)
                    else:
                        cat = _detect_material_category(t_stem)
                dst_cat_dir = f"{tex_dir}/{cat}"
                unreal.EditorAssetLibrary.make_directory(dst_cat_dir)
                dst = f"{dst_cat_dir}/{name}"
                if clean != dst and not unreal.EditorAssetLibrary.does_asset_exist(dst):
                    if unreal.EditorAssetLibrary.rename_asset(clean, dst):
                        moved_any = True
        if moved_any:
            relink_all_material_textures(base_folder)
    except Exception:
        pass


def relink_all_material_textures(base_folder: str = DEFAULT_UE_FOLDER) -> int:
    """
    Перепривязывает пути всех текстур T_<Stem>_Albedo/Normal/Roughness/Height/Opacity
    ко всем инстансам MI_<Stem> в <base_folder>/<category>/ и сохраняет изменения на диск.
    """
    eal = unreal.EditorAssetLibrary
    mel = unreal.MaterialEditingLibrary
    all_assets = list(eal.list_assets(base_folder, recursive=True))
    tex_by_lower = {}
    for a_path in all_assets:
        clean = a_path.split(".")[0]
        name = clean.split("/")[-1]
        if name.startswith("T_"):
            tex_by_lower[name.lower()] = clean

    relinked_count = 0
    suffix_to_param = (
        ("_albedo", "AlbedoTexture"),
        ("_normal", "NormalTexture"),
        ("_roughness", "RoughnessTexture"),
        ("_height", "HeightTexture"),
        ("_opacity", "OpacityMaskTexture"),
    )
    for a_path in all_assets:
        clean = a_path.split(".")[0]
        name = clean.split("/")[-1]
        if not name.startswith("MI_"):
            continue
        mi = eal.load_asset(clean)
        if not mi or not isinstance(mi, unreal.MaterialInstanceConstant):
            continue
        stem = name[3:]
        changed = False
        for sfx, param_name in suffix_to_param:
            cand_key = f"t_{stem.lower()}{sfx}"
            t_path = tex_by_lower.get(cand_key)
            if not t_path and re.search(r"_[sS]?\d+$", stem):
                # Fallback if MI has incremented suffix like _S69044 while texture is _S69043
                base_prefix = re.sub(r"\d+$", "", f"t_{stem.lower()}")
                for k_low, v_path in tex_by_lower.items():
                    if k_low.endswith(sfx) and k_low[:-len(sfx)].startswith(base_prefix):
                        t_path = v_path
                        break
            if t_path:
                cur_val = mel.get_material_instance_texture_parameter_value(
                    mi, param_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
                cur_path = cur_val.get_path_name().split(".")[0] if cur_val else ""
                if cur_path != t_path:
                    t_obj = eal.load_asset(t_path)
                    if t_obj:
                        mel.set_material_instance_texture_parameter_value(
                            mi, param_name, t_obj, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                        changed = True
        if changed:
            mel.update_material_instance(mi)
            eal.save_loaded_asset(mi)
            relinked_count += 1
    return relinked_count


def _ensure_panel_uasset_in_project() -> None:
    """Копирует BP_ComfyPanel.uasset из папки плагина в Content/ConfyUI_plagin/ текущего проекта UE5, если его там ещё нет."""
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(PANEL_ASSET_PATH):
            return
        import shutil
        content_dir = unreal.Paths.project_content_dir()
        dst_dir = os.path.join(content_dir, "ConfyUI_plagin")
        dst_file = os.path.join(dst_dir, "BP_ComfyPanel.uasset")
        if not os.path.exists(dst_file):
            candidates = [
                os.path.join(_SCRIPT_DIR, "Content", "ConfyUI_plagin", "BP_ComfyPanel.uasset"),
                os.path.join(_SCRIPT_DIR, "BP_ComfyPanel.uasset"),
            ]
            for src in candidates:
                if os.path.exists(src):
                    os.makedirs(dst_dir, exist_ok=True)
                    shutil.copy2(src, dst_file)
                    asset_reg = unreal.AssetRegistryHelpers.get_asset_registry()
                    asset_reg.scan_paths_synchronous(["/Game/ConfyUI_plagin"], True)
                    break
    except Exception:
        pass


def _get_open_panel_widget():
    """Возвращает активный экземпляр виджета BP_ComfyPanel."""
    try:
        _ensure_panel_uasset_in_project()
        bp = unreal.EditorAssetLibrary.load_asset(PANEL_ASSET_PATH)
        if bp:
            sub = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
            w = sub.find_utility_widget_from_blueprint(bp)
            if not w:
                w, _ = sub.spawn_and_register_tab_and_get_id(bp)
            if w:
                builtins._COMFY_PANEL_WIDGET = w
                return w
    except Exception:
        pass
    w = getattr(builtins, "_COMFY_PANEL_WIDGET", None)
    if w:
        try:
            _ = w.get_name()
            return w
        except Exception:
            pass
    return None


def _set_panel_status(
    message: str,
    btn_label: str = "GENERATE PBR",
    color: tuple = (0.55, 0.90, 0.65, 1.0),
) -> None:
    """Обновляет текст статуса и надпись на кнопке внутри открытого окна BP_ComfyPanel."""
    w = _get_open_panel_widget()
    if not w:
        return
    try:
        status_tb = getattr(builtins, "_COMFY_STATUS_TB", None) or w.find_child_widget_by_name("ComfyStatusText")
        if status_tb:
            status_tb.set_text(message)
            status_tb.set_color_and_opacity(unreal.SlateColor(unreal.LinearColor(*color)))
        btn = w.find_child_widget_by_name("GenerateBtn")
        if btn and hasattr(btn, "get_all_children"):
            for c in btn.get_all_children():
                if hasattr(c, "set_text"):
                    c.set_text(btn_label)
                    _style_text(c, size=8, bold=True, color=(0.98, 0.98, 1.0, 1.0))
    except Exception:
        pass


def cancel_comfy_generation() -> None:
    """Мгновенно отменяет текущую генерацию в ComfyUI (/interrupt + очистка очереди) и сбрасывает статус в UE5."""
    builtins._COMFY_CANCEL_REQUESTED = True
    builtins._COMFY_JOB_RUNNING = False
    active_h = getattr(builtins, "_COMFY_ACTIVE_TICK_HANDLE", None)
    if active_h is not None:
        try:
            unreal.unregister_slate_post_tick_callback(active_h)
        except Exception:
            pass
        builtins._COMFY_ACTIVE_TICK_HANDLE = None

    def _send_interrupt():
        for path, payload in (("/interrupt", b"{}"), ("/queue", b'{"clear": true}')):
            try:
                req = urllib.request.Request(
                    f"{COMFY_URL}{path}",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=4.0).read()
            except Exception:
                pass

    threading.Thread(target=_send_interrupt, daemon=True).start()
    _set_panel_status("[Cancelled] Generation stopped by user.", "GENERATE PBR", color=(1.0, 0.55, 0.40, 1.0))


def apply_material_to_selected_actors(material_asset, slot_idx: int = None) -> int:
    """
    Назначает созданный PBR-материал или инстанс на выделенные StaticMeshActor или DecalActor на уровне.
    Если у меша несколько Material ID (слотов) и выбран конкретный Target ID (0..7),
    назначает материал именно в этот слот, не перезаписывая остальные полигонные ID.
    """
    if not material_asset:
        return 0
    if slot_idx is None:
        try:
            slot_idx = _get_selected_poly_target_id(default_for_assign=-1)
        except Exception:
            slot_idx = -1
    count = 0
    try:
        actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        selected = actor_sub.get_selected_level_actors()
        for actor in selected:
            decal_comps = actor.get_components_by_class(unreal.DecalComponent)
            for d_comp in decal_comps:
                decal_mat = material_asset
                try:
                    if isinstance(material_asset, unreal.MaterialInstanceConstant):
                        parent_m = material_asset.get_editor_property("parent")
                        if not parent_m or "decal" not in str(parent_m.get_path_name()).lower():
                            conv = create_decal_material_from_mi(material_asset, DEFAULT_UE_FOLDER)
                            if conv:
                                decal_mat = conv
                except Exception:
                    pass
                d_comp.set_decal_material(decal_mat)
                count += 1
            comps = actor.get_components_by_class(unreal.StaticMeshComponent)
            for comp in comps:
                num_mats = max(1, comp.get_num_materials())
                if slot_idx is not None and slot_idx >= 0 and num_mats > 1 and slot_idx < num_mats:
                    comp.set_material(int(slot_idx), material_asset)
                else:
                    for idx in range(num_mats):
                        comp.set_material(idx, material_asset)
                count += 1
    except Exception as exc:
        unreal.log_warning(f"ComfyUI PBR: не удалось назначить материал на выделенный объект: {exc}")
    return count


def _conn_expr(mel, a, out_a: str, b, in_b: str) -> bool:
    """Reliably connects material expressions in UE5 (supporting unnamed pins '' / 'None' / 'Input')."""
    ok = mel.connect_material_expressions(a, out_a, b, in_b)
    if not ok and in_b in ("", "None"):
        for fallback_pin in ("None", "", "Input", "Default", "Value", "A"):
            if fallback_pin != in_b:
                ok = mel.connect_material_expressions(a, out_a, b, fallback_pin)
                if ok:
                    break
    return ok


def _make_clamp_expr(mel, mat, src_expr, src_pin: str, min_val: float, max_val: float, pos_x: int, pos_y: int):
    """Creates a UE5-version-independent Max+Min clamp chain using explicit 'A' pins."""
    max_node = mel.create_material_expression(mat, unreal.MaterialExpressionMax, pos_x, pos_y)
    max_node.set_editor_property("const_b", float(min_val))
    _conn_expr(mel, src_expr, src_pin, max_node, "A")
    min_node = mel.create_material_expression(mat, unreal.MaterialExpressionMin, pos_x + 90, pos_y)
    min_node.set_editor_property("const_b", float(max_val))
    _conn_expr(mel, max_node, "", min_node, "A")
    return min_node


def _make_custom_hlsl_node(
    mel,
    mat,
    desc: str,
    out_type,
    input_names: list,
    hlsl_code: str,
    pos_x: int,
    pos_y: int,
):
    """Creates a MaterialExpressionCustom HLSL node with named input pins."""
    node = mel.create_material_expression(mat, unreal.MaterialExpressionCustom, pos_x, pos_y)
    node.set_editor_property("description", desc)
    node.set_editor_property("output_type", out_type)
    node.set_editor_property("code", hlsl_code)
    inps = []
    for name in input_names:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", name)
        inps.append(ci)
    node.set_editor_property("inputs", inps)
    return node


def create_or_update_master_material(
    ue_folder: str = DEFAULT_UE_FOLDER,
    mm_name: str = DEFAULT_MASTER_MAT_NAME,
):
    """
    Creates or rebuilds the Master Material MM_ComfyPBR_Master:
    - Map strength controls for all 4 PBR maps:
      * Albedo_Strength, Normal_Strength, Roughness_Strength, Roughness_Base
      * Height_Strength (BumpOffset), Height_Displacement_Strength (WPO), Height_AO_Strength (AO)
      * Metallic_Strength, Specular_Strength
    - Full Albedo color grading suite:
      * Albedo_ColorTint (RGB), Albedo_Brightness, Albedo_Desaturation, Albedo_Contrast, Albedo_ContrastPower
    - Group '05 - Substance Seams & Tile Generator' (procedural tile/plank grid, seams, bevels & per-tile UV randomization):
      * Seams_Enable (0 = off, 1 = on)
      * Tiles_Count_X, Tiles_Count_Y (number of tiles/planks along width & length)
      * Row_Shift_Order (0.0 = grid, 0.5 = half-brick bond, 0.33 = parquet) & Row_Shift_Random (random row shift)
      * Seam_Width (aspect-corrected seam thickness), Seam_Bevel_Softness (edge bevel width), Seam_Depth (recess & 3D normal strength)
      * Seam_Color (RGB mortar/grout color) & Seam_Roughness (grout roughness)
      * Tile_Random_UV_Offset (randomizes texture position across seam boundaries)
      * Tile_Random_Flip_Rotate (random mirror/90-deg rotation per tile with normal correction)
      * Tile_Random_Luminance (per-tile brightness variation like Substance Tile Sampler)
    """
    ue_folder = _normalize_ue_folder(ue_folder)
    if ue_folder.split("/")[-1] in MATERIAL_CATEGORIES or ue_folder.split("/")[-1] == TEXTURES_SUBFOLDER:
        ue_folder = "/".join(ue_folder.split("/")[:-1]) or DEFAULT_UE_FOLDER
    _ensure_folder_structure(ue_folder)
    mm_path = f"{ue_folder}/{mm_name}"

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    mel = unreal.MaterialEditingLibrary

    if unreal.EditorAssetLibrary.does_asset_exist(mm_path):
        mat = unreal.EditorAssetLibrary.load_asset(mm_path)
        try:
            mat.set_editor_property("use_material_attributes", False)
        except Exception:
            pass
        mel.delete_all_material_expressions(mat)
        # UE5's delete_all_material_expressions skips MaterialExpressionParameter nodes;
        # explicitly remove any leftover parameter nodes so group names and connections stay 100% clean.
        try:
            if mel.get_num_material_expressions(mat) > 0:
                import tempfile
                tmp_copy = os.path.join(tempfile.gettempdir(), f"_ue_mm_clear_{mm_name}.copy")
                exp_task = unreal.AssetExportTask()
                exp_task.object = mat
                exp_task.filename = tmp_copy
                exp_task.automated = True
                exp_task.prompt = False
                unreal.Exporter.run_asset_export_task(exp_task)
                if os.path.isfile(tmp_copy):
                    with open(tmp_copy, "r", encoding="utf-8", errors="replace") as _tf:
                        _txt = _tf.read()
                    for _ename in re.findall(r'Begin Object Name="(MaterialExpression[^"]+)"', _txt):
                        _eobj = unreal.find_object(mat, _ename)
                        if _eobj:
                            try:
                                mel.delete_material_expression(mat, _eobj)
                            except Exception:
                                pass
                    try:
                        os.remove(tmp_copy)
                    except Exception:
                        pass
        except Exception:
            pass
    else:
        mat = asset_tools.create_asset(mm_name, ue_folder, unreal.Material, unreal.MaterialFactoryNew())
        try:
            mat.set_editor_property("use_material_attributes", False)
        except Exception:
            pass

    default_alb = (
        unreal.EditorAssetLibrary.load_asset("/Engine/EngineResources/WhiteSquareTexture")
        if unreal.EditorAssetLibrary.does_asset_exist("/Engine/EngineResources/WhiteSquareTexture")
        else unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/DefaultDiffuse")
    )
    default_nrm = unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/DefaultNormal")
    default_rgh = unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/BaseFlattenLinearColor")
    default_hgt = unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/BaseFlattenLinearColor")

    # === 0. UV & Tiling ===
    tex_coord = mel.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -2400, 0)
    tiling_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 120)
    tiling_p.set_editor_property("parameter_name", "UV_Tiling")
    tiling_p.set_editor_property("group", "00 - UV & Tiling")
    tiling_p.set_editor_property("default_value", 1.0)

    uv_scaled = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -2160, 40)
    _conn_expr(mel, tex_coord, "", uv_scaled, "A")
    _conn_expr(mel, tiling_p, "", uv_scaled, "B")

    is_decal_mm = (mm_name == "MM_ArchViz_Decal")
    if not is_decal_mm:
        world_pos_trip = mel.create_material_expression(mat, unreal.MaterialExpressionWorldPosition, -2680, 1840)
        vert_nrm_trip = mel.create_material_expression(mat, unreal.MaterialExpressionVertexNormalWS, -2680, 1920)
        tc_uv1_trip = mel.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -2680, 2000)
        tc_uv1_trip.set_editor_property("coordinate_index", 1)
    else:
        world_pos_trip = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -2680, 1840)
        vert_nrm_trip = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -2680, 1920)
        vert_nrm_trip.set_editor_property("constant", unreal.LinearColor(0.0, 0.0, 1.0, 1.0))
        tc_uv1_trip = tex_coord

    hlsl_triplanar_mask_uv = """
if (UseTriplanar < 0.5) return MeshBaseUV;
float3 n = (dot(VertNrmWS, VertNrmWS) > 0.05) ? normalize(VertNrmWS) : normalize(TransformLocalVectorToWorld(Parameters, float3(0.0, 0.0, 1.0)));
float3 an = abs(n);
float3 wp = WorldPos / 200.0;
float2 tripUV;
if (an.z >= an.x && an.z >= an.y) {
    tripUV = wp.xy;
} else if (an.x >= an.y) {
    tripUV = wp.yz;
} else {
    tripUV = wp.xz;
}
return tripUV;
"""
    hlsl_triplanar_seams_uv = """
if (UseTriplanar < 0.5) return MeshBaseUV;
float3 n = (dot(VertNrmWS, VertNrmWS) > 0.05) ? normalize(VertNrmWS) : normalize(TransformLocalVectorToWorld(Parameters, float3(0.0, 0.0, 1.0)));
float3 an = abs(n);
float3 wp = (WorldPos / 200.0) * max(UVTiling, 0.0001);
float2 tripUV;
if (an.z >= an.x && an.z >= an.y) {
    tripUV = wp.xy;
} else if (an.x >= an.y) {
    tripUV = wp.yz;
} else {
    tripUV = wp.xz;
}
return tripUV;
"""
    blend_mask_trip_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, 1860)
    blend_mask_trip_p.set_editor_property("parameter_name", "Blend_Mask_Triplanar")
    blend_mask_trip_p.set_editor_property("group", "06 - Mesh Paint [R] / Layer 1 (Combine & Seams)")
    blend_mask_trip_p.set_editor_property("default_value", 0.0)

    custom_l1_mask_base_uv = _make_custom_hlsl_node(
        mel,
        mat,
        "Layer1TriplanarMaskBaseUV",
        unreal.CustomMaterialOutputType.CMOT_FLOAT2,
        ["MeshBaseUV", "WorldPos", "VertNrmWS", "EncodedNrmUV1", "UVTiling", "UseTriplanar"],
        hlsl_triplanar_mask_uv,
        -2380,
        1840,
    )
    _conn_expr(mel, tex_coord, "", custom_l1_mask_base_uv, "MeshBaseUV")
    _conn_expr(mel, world_pos_trip, "", custom_l1_mask_base_uv, "WorldPos")
    _conn_expr(mel, vert_nrm_trip, "", custom_l1_mask_base_uv, "VertNrmWS")
    _conn_expr(mel, tc_uv1_trip, "", custom_l1_mask_base_uv, "EncodedNrmUV1")
    _conn_expr(mel, tiling_p, "", custom_l1_mask_base_uv, "UVTiling")
    _conn_expr(mel, blend_mask_trip_p, "", custom_l1_mask_base_uv, "UseTriplanar")

    # === 05. Substance Seams & Tile Generator Parameters ===
    grp_seam = "05 - Substance Seams & Tile Generator"

    seams_enable_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 280)
    seams_enable_p.set_editor_property("parameter_name", "Seams_Enable")
    seams_enable_p.set_editor_property("group", grp_seam)
    seams_enable_p.set_editor_property("default_value", 0.0)

    seams_trip_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 330)
    seams_trip_p.set_editor_property("parameter_name", "Seams_Triplanar")
    seams_trip_p.set_editor_property("group", grp_seam)
    seams_trip_p.set_editor_property("default_value", 0.0)

    custom_seams_base_uv = _make_custom_hlsl_node(
        mel,
        mat,
        "SeamsTriplanarBaseUV",
        unreal.CustomMaterialOutputType.CMOT_FLOAT2,
        ["MeshBaseUV", "WorldPos", "VertNrmWS", "EncodedNrmUV1", "UVTiling", "UseTriplanar"],
        hlsl_triplanar_seams_uv,
        -2160,
        320,
    )
    _conn_expr(mel, uv_scaled, "", custom_seams_base_uv, "MeshBaseUV")
    _conn_expr(mel, world_pos_trip, "", custom_seams_base_uv, "WorldPos")
    _conn_expr(mel, vert_nrm_trip, "", custom_seams_base_uv, "VertNrmWS")
    _conn_expr(mel, tc_uv1_trip, "", custom_seams_base_uv, "EncodedNrmUV1")
    _conn_expr(mel, tiling_p, "", custom_seams_base_uv, "UVTiling")
    _conn_expr(mel, seams_trip_p, "", custom_seams_base_uv, "UseTriplanar")

    tiles_x_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 380)
    tiles_x_p.set_editor_property("parameter_name", "Tiles_Count_X")
    tiles_x_p.set_editor_property("group", grp_seam)
    tiles_x_p.set_editor_property("default_value", 4.0)

    tiles_y_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 480)
    tiles_y_p.set_editor_property("parameter_name", "Tiles_Count_Y")
    tiles_y_p.set_editor_property("group", grp_seam)
    tiles_y_p.set_editor_property("default_value", 4.0)

    row_order_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 580)
    row_order_p.set_editor_property("parameter_name", "Row_Shift_Order")
    row_order_p.set_editor_property("group", grp_seam)
    row_order_p.set_editor_property("default_value", 0.5)

    row_rand_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 680)
    row_rand_p.set_editor_property("parameter_name", "Row_Shift_Random")
    row_rand_p.set_editor_property("group", grp_seam)
    row_rand_p.set_editor_property("default_value", 0.0)

    seam_width_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 780)
    seam_width_p.set_editor_property("parameter_name", "Seam_Width")
    seam_width_p.set_editor_property("group", grp_seam)
    seam_width_p.set_editor_property("default_value", 0.04)

    seam_width_v_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 830)
    seam_width_v_p.set_editor_property("parameter_name", "Seam_Width_V")
    seam_width_v_p.set_editor_property("group", grp_seam)
    seam_width_v_p.set_editor_property("default_value", 0.04)

    seam_soft_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 880)
    seam_soft_p.set_editor_property("parameter_name", "Seam_Bevel_Softness")
    seam_soft_p.set_editor_property("group", grp_seam)
    seam_soft_p.set_editor_property("default_value", 0.03)

    seam_wave_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 915)
    seam_wave_p.set_editor_property("parameter_name", "Seam_Line_Waviness")
    seam_wave_p.set_editor_property("group", grp_seam)
    seam_wave_p.set_editor_property("default_value", 0.0)

    seam_irreg_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 945)
    seam_irreg_p.set_editor_property("parameter_name", "Seam_Edge_Irregularity")
    seam_irreg_p.set_editor_property("group", grp_seam)
    seam_irreg_p.set_editor_property("default_value", 0.0)

    seam_nscale_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 975)
    seam_nscale_p.set_editor_property("parameter_name", "Seam_Noise_Scale")
    seam_nscale_p.set_editor_property("group", grp_seam)
    seam_nscale_p.set_editor_property("default_value", 1.0)

    seam_depth_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 1010)
    seam_depth_p.set_editor_property("parameter_name", "Seam_Depth")
    seam_depth_p.set_editor_property("group", grp_seam)
    seam_depth_p.set_editor_property("default_value", 1.0)

    tile_rand_uv_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 1080)
    tile_rand_uv_p.set_editor_property("parameter_name", "Tile_Random_UV_Offset")
    tile_rand_uv_p.set_editor_property("group", grp_seam)
    tile_rand_uv_p.set_editor_property("default_value", 1.0)

    tile_rand_rot_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 1180)
    tile_rand_rot_p.set_editor_property("parameter_name", "Tile_Random_Flip_Rotate")
    tile_rand_rot_p.set_editor_property("group", grp_seam)
    tile_rand_rot_p.set_editor_property("default_value", 0.5)

    tile_rand_lum_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 1280)
    tile_rand_lum_p.set_editor_property("parameter_name", "Tile_Random_Luminance")
    tile_rand_lum_p.set_editor_property("group", grp_seam)
    tile_rand_lum_p.set_editor_property("default_value", 0.10)

    seam_color_p = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -200, -180)
    seam_color_p.set_editor_property("parameter_name", "Seam_Color")
    seam_color_p.set_editor_property("group", grp_seam)
    seam_color_p.set_editor_property("default_value", unreal.LinearColor(0.22, 0.22, 0.23, 1.0))

    seam_rough_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -200, 140)
    seam_rough_p.set_editor_property("parameter_name", "Seam_Roughness")
    seam_rough_p.set_editor_property("group", grp_seam)
    seam_rough_p.set_editor_property("default_value", 0.85)

    seam_mtl_en_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 980)
    seam_mtl_en_p.set_editor_property("parameter_name", "Seam_Mtl_Enable")
    seam_mtl_en_p.set_editor_property("group", grp_seam)
    seam_mtl_en_p.set_editor_property("default_value", 0.0)

    seam_mtl_til_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 1040)
    seam_mtl_til_p.set_editor_property("parameter_name", "Seam_UV_Tiling")
    seam_mtl_til_p.set_editor_property("group", grp_seam)
    seam_mtl_til_p.set_editor_property("default_value", 1.0)

    uv_seam_mtl = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1420, 1020)
    _conn_expr(mel, custom_seams_base_uv, "", uv_seam_mtl, "A")
    _conn_expr(mel, seam_mtl_til_p, "", uv_seam_mtl, "B")

    tex_seam_alb = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1260, 960)
    tex_seam_alb.set_editor_property("parameter_name", "Seam_AlbedoTexture")
    tex_seam_alb.set_editor_property("group", grp_seam)
    if default_alb:
        tex_seam_alb.set_editor_property("texture", default_alb)
    tex_seam_alb.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    tex_seam_alb.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, uv_seam_mtl, "", tex_seam_alb, "UVs")

    seam_tint_p = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -1260, 1140)
    seam_tint_p.set_editor_property("parameter_name", "Seam_ColorTint")
    seam_tint_p.set_editor_property("group", grp_seam)
    seam_tint_p.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))

    alb_seam_tinted = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1080, 1000)
    _conn_expr(mel, tex_seam_alb, "RGB", alb_seam_tinted, "A")
    _conn_expr(mel, seam_tint_p, "RGB", alb_seam_tinted, "B")

    tex_seam_nrm = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1260, 1280)
    tex_seam_nrm.set_editor_property("parameter_name", "Seam_NormalTexture")
    tex_seam_nrm.set_editor_property("group", grp_seam)
    if default_nrm:
        tex_seam_nrm.set_editor_property("texture", default_nrm)
    tex_seam_nrm.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    tex_seam_nrm.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, uv_seam_mtl, "", tex_seam_nrm, "UVs")

    tex_seam_rgh = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1260, 1460)
    tex_seam_rgh.set_editor_property("parameter_name", "Seam_RoughnessTexture")
    tex_seam_rgh.set_editor_property("group", grp_seam)
    if default_rgh:
        tex_seam_rgh.set_editor_property("texture", default_rgh)
    tex_seam_rgh.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tex_seam_rgh.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, uv_seam_mtl, "", tex_seam_rgh, "UVs")

    seam_rgh_mult_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1260, 1640)
    seam_rgh_mult_p.set_editor_property("parameter_name", "Seam_Roughness_Mult")
    seam_rgh_mult_p.set_editor_property("group", grp_seam)
    seam_rgh_mult_p.set_editor_property("default_value", 1.0)

    rgh_seam_scaled = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1080, 1480)
    _conn_expr(mel, tex_seam_rgh, "R", rgh_seam_scaled, "A")
    _conn_expr(mel, seam_rgh_mult_p, "", rgh_seam_scaled, "B")

    seam_met_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1260, 1720)
    seam_met_p.set_editor_property("parameter_name", "Seam_Metallic")
    seam_met_p.set_editor_property("group", grp_seam)
    seam_met_p.set_editor_property("default_value", 0.0)

    tex_seam_hgt = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1260, 1800)
    tex_seam_hgt.set_editor_property("parameter_name", "Seam_HeightTexture")
    tex_seam_hgt.set_editor_property("group", grp_seam)
    if default_hgt:
        tex_seam_hgt.set_editor_property("texture", default_hgt)
    tex_seam_hgt.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tex_seam_hgt.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, uv_seam_mtl, "", tex_seam_hgt, "UVs")

    # Custom Node 0B: Warped Seam Grid UV (applies horizontal & vertical seam line waviness)
    hlsl_warped_seam_uv = """
if (SeamWaviness <= 0.0001) return BaseUV;
float tx = max(TilesX, 0.001);
float ty = max(TilesY, 0.001);
float nFreq = max(SeamNoiseScale, 0.1) * 5.0;
float2 np1 = BaseUV * float2(tx, ty) * nFreq;
float2 i1 = floor(np1);
float2 f1 = frac(np1);
float2 u1 = f1 * f1 * (3.0 - 2.0 * f1);
float a1 = frac(sin(dot(i1, float2(127.1, 311.7))) * 43758.5453);
float b1 = frac(sin(dot(i1 + float2(1.0, 0.0), float2(127.1, 311.7))) * 43758.5453);
float c1 = frac(sin(dot(i1 + float2(0.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
float d1 = frac(sin(dot(i1 + float2(1.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
float n1 = lerp(lerp(a1, b1, u1.x), lerp(c1, d1, u1.x), u1.y) - 0.5;
float2 np2 = np1 * 2.37 + float2(19.7, 41.3);
float2 i2 = floor(np2);
float2 f2 = frac(np2);
float2 u2 = f2 * f2 * (3.0 - 2.0 * f2);
float a2 = frac(sin(dot(i2, float2(269.5, 183.3))) * 43758.5453);
float b2 = frac(sin(dot(i2 + float2(1.0, 0.0), float2(269.5, 183.3))) * 43758.5453);
float c2 = frac(sin(dot(i2 + float2(0.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
float d2 = frac(sin(dot(i2 + float2(1.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
float n2 = lerp(lerp(a2, b2, u2.x), lerp(c2, d2, u2.x), u2.y) - 0.5;
float waveAmp = SeamWaviness * 0.16;
float2 warp = float2(n1 * 0.7 + n2 * 0.3, n2 * 0.7 - n1 * 0.3) * (waveAmp / float2(tx, ty));
return BaseUV + warp;
"""
    custom_seams_grid_uv = _make_custom_hlsl_node(
        mel,
        mat,
        "SubstanceWarpedGridUV",
        unreal.CustomMaterialOutputType.CMOT_FLOAT2,
        ["BaseUV", "TilesX", "TilesY", "SeamWaviness", "SeamNoiseScale"],
        hlsl_warped_seam_uv,
        -2020,
        320,
    )
    _conn_expr(mel, custom_seams_base_uv, "", custom_seams_grid_uv, "BaseUV")
    _conn_expr(mel, tiles_x_p, "", custom_seams_grid_uv, "TilesX")
    _conn_expr(mel, tiles_y_p, "", custom_seams_grid_uv, "TilesY")
    _conn_expr(mel, seam_wave_p, "", custom_seams_grid_uv, "SeamWaviness")
    _conn_expr(mel, seam_nscale_p, "", custom_seams_grid_uv, "SeamNoiseScale")

    # Custom Node 1: Per-Tile Randomized UV
    hlsl_tile_uv = """
float en = saturate(SeamsEnable);
if (en < 0.001) return BaseUV;
float tx = max(TilesX, 0.001);
float ty = max(TilesY, 0.001);
float row = floor(SeamGridUV.y * ty);
float rowHash = frac(sin(row * 127.1 + 311.7) * 43758.5453);
float shift = row * RowShiftOrder + (rowHash - 0.5) * RowShiftRandom;
float2 grid = float2(SeamGridUV.x * tx + shift, SeamGridUV.y * ty);
float2 cell = floor(grid);
float h1 = frac(sin(dot(cell, float2(127.1, 311.7))) * 43758.5453);
float h2 = frac(sin(dot(cell, float2(269.5, 183.3))) * 43758.5453);
float h3 = frac(sin(dot(cell, float2(419.2, 371.9))) * 43758.5453);
float2 uv = UnwarpedSeamUV - 0.5;
if (TileRandRot > 0.2 && h3 > 0.5) uv.x = -uv.x;
if (TileRandRot > 0.5 && frac(h3 * 3.71) > 0.5) uv.y = -uv.y;
if (TileRandRot > 0.8 && frac(h3 * 7.13) > 0.5) uv = float2(-uv.y, uv.x);
float2 rOfs = (float2(h1, h2) - 0.5) * TileRandUV;
return lerp(BaseUV, uv + 0.5 + rOfs, en);
"""
    custom_tile_uv = _make_custom_hlsl_node(
        mel,
        mat,
        "SubstanceTileUV",
        unreal.CustomMaterialOutputType.CMOT_FLOAT2,
        ["BaseUV", "UnwarpedSeamUV", "SeamGridUV", "SeamsEnable", "TilesX", "TilesY", "RowShiftOrder", "RowShiftRandom", "TileRandUV", "TileRandRot"],
        hlsl_tile_uv,
        -1880,
        40,
    )
    _conn_expr(mel, uv_scaled, "", custom_tile_uv, "BaseUV")
    _conn_expr(mel, custom_seams_base_uv, "", custom_tile_uv, "UnwarpedSeamUV")
    _conn_expr(mel, custom_seams_grid_uv, "", custom_tile_uv, "SeamGridUV")
    _conn_expr(mel, seams_enable_p, "", custom_tile_uv, "SeamsEnable")
    _conn_expr(mel, tiles_x_p, "", custom_tile_uv, "TilesX")
    _conn_expr(mel, tiles_y_p, "", custom_tile_uv, "TilesY")
    _conn_expr(mel, row_order_p, "", custom_tile_uv, "RowShiftOrder")
    _conn_expr(mel, row_rand_p, "", custom_tile_uv, "RowShiftRandom")
    _conn_expr(mel, tile_rand_uv_p, "", custom_tile_uv, "TileRandUV")
    _conn_expr(mel, tile_rand_rot_p, "", custom_tile_uv, "TileRandRot")

    # Custom Node 2: Seam Mask (0 = tile, 1 = seam/grout, independent SeamWidth H & V + uneven/chipped SeamEdgeIrreg borders)
    hlsl_seam_mask = """
float en = saturate(SeamsEnable);
if (en < 0.001 || (SeamWidth <= 0.0001 && SeamWidthV <= 0.0001)) return 0.0;
float tx = max(TilesX, 0.001);
float ty = max(TilesY, 0.001);
float row = floor(BaseUV.y * ty);
float rowHash = frac(sin(row * 127.1 + 311.7) * 43758.5453);
float shift = row * RowShiftOrder + (rowHash - 0.5) * RowShiftRandom;
float2 local = frac(float2(BaseUV.x * tx + shift, BaseUV.y * ty));
float dx = min(local.x, 1.0 - local.x);
float dy = min(local.y, 1.0 - local.y);
float refScale = min(tx, ty);
float distX = dx * (refScale / tx);
float distY = dy * (refScale / ty);
float baseWV = max(SeamWidthV, 0.0);
float baseWH = max(SeamWidth, 0.0);
float halfWV = baseWV * 0.5;
float halfWH = baseWH * 0.5;
if (SeamEdgeIrreg > 0.0001)
{
    float nFreq = max(SeamNoiseScale, 0.1) * 7.5;
    float2 np1 = BaseUV * float2(tx, ty) * nFreq;
    float2 i1 = floor(np1);
    float2 f1 = frac(np1);
    float2 u1 = f1 * f1 * (3.0 - 2.0 * f1);
    float a1 = frac(sin(dot(i1, float2(127.1, 311.7))) * 43758.5453);
    float b1 = frac(sin(dot(i1 + float2(1.0, 0.0), float2(127.1, 311.7))) * 43758.5453);
    float c1 = frac(sin(dot(i1 + float2(0.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
    float d1 = frac(sin(dot(i1 + float2(1.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
    float nLow = lerp(lerp(a1, b1, u1.x), lerp(c1, d1, u1.x), u1.y) - 0.5;

    float2 np2 = np1 * 2.83 + float2(37.2, 19.8);
    float2 i2 = floor(np2);
    float2 f2 = frac(np2);
    float2 u2 = f2 * f2 * (3.0 - 2.0 * f2);
    float a2 = frac(sin(dot(i2, float2(269.5, 183.3))) * 43758.5453);
    float b2 = frac(sin(dot(i2 + float2(1.0, 0.0), float2(269.5, 183.3))) * 43758.5453);
    float c2 = frac(sin(dot(i2 + float2(0.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
    float d2 = frac(sin(dot(i2 + float2(1.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
    float nMid = lerp(lerp(a2, b2, u2.x), lerp(c2, d2, u2.x), u2.y) - 0.5;

    float2 np3 = np1 * 6.41 + float2(73.1, 53.9);
    float2 i3 = floor(np3);
    float2 f3 = frac(np3);
    float2 u3 = f3 * f3 * (3.0 - 2.0 * f3);
    float a3 = frac(sin(dot(i3, float2(419.2, 371.9))) * 43758.5453);
    float b3 = frac(sin(dot(i3 + float2(1.0, 0.0), float2(419.2, 371.9))) * 43758.5453);
    float c3 = frac(sin(dot(i3 + float2(0.0, 1.0), float2(419.2, 371.9))) * 43758.5453);
    float d3 = frac(sin(dot(i3 + float2(1.0, 1.0), float2(419.2, 371.9))) * 43758.5453);
    float nHi = lerp(lerp(a3, b3, u3.x), lerp(c3, d3, u3.x), u3.y) - 0.5;

    float sideX = (local.x < 0.5) ? 1.0 : -1.0;
    float sideY = (local.y < 0.5) ? 1.0 : -1.0;
    float edgeV = nLow * 0.45 + sideX * nMid * 0.40 + nHi * 0.35;
    float edgeH = nMid * 0.45 + sideY * nLow * 0.40 - nHi * 0.35;
    float ampV = max(baseWV * 1.65, 0.032) * SeamEdgeIrreg;
    float ampH = max(baseWH * 1.65, 0.032) * SeamEdgeIrreg;
    halfWV = max(0.0004, halfWV + edgeV * ampV);
    halfWH = max(0.0004, halfWH + edgeH * ampH);
}
float soft = max(SeamSoftness, 0.001);
float maskV = (baseWV > 0.0001) ? (1.0 - smoothstep(halfWV, halfWV + soft, distX)) : 0.0;
float maskH = (baseWH > 0.0001) ? (1.0 - smoothstep(halfWH, halfWH + soft, distY)) : 0.0;
return max(maskV, maskH) * en;
"""
    custom_seam_mask = _make_custom_hlsl_node(
        mel,
        mat,
        "SubstanceSeamMask",
        unreal.CustomMaterialOutputType.CMOT_FLOAT1,
        ["BaseUV", "SeamsEnable", "TilesX", "TilesY", "RowShiftOrder", "RowShiftRandom", "SeamWidth", "SeamWidthV", "SeamSoftness", "SeamEdgeIrreg", "SeamNoiseScale"],
        hlsl_seam_mask,
        -1880,
        360,
    )
    _conn_expr(mel, custom_seams_grid_uv, "", custom_seam_mask, "BaseUV")
    _conn_expr(mel, seams_enable_p, "", custom_seam_mask, "SeamsEnable")
    _conn_expr(mel, tiles_x_p, "", custom_seam_mask, "TilesX")
    _conn_expr(mel, tiles_y_p, "", custom_seam_mask, "TilesY")
    _conn_expr(mel, row_order_p, "", custom_seam_mask, "RowShiftOrder")
    _conn_expr(mel, row_rand_p, "", custom_seam_mask, "RowShiftRandom")
    _conn_expr(mel, seam_width_p, "", custom_seam_mask, "SeamWidth")
    _conn_expr(mel, seam_width_v_p, "", custom_seam_mask, "SeamWidthV")
    _conn_expr(mel, seam_soft_p, "", custom_seam_mask, "SeamSoftness")
    _conn_expr(mel, seam_irreg_p, "", custom_seam_mask, "SeamEdgeIrreg")
    _conn_expr(mel, seam_nscale_p, "", custom_seam_mask, "SeamNoiseScale")

    # Custom Node 3: Per-Tile Random Luminance Multiplier
    hlsl_tile_lum = """
float en = saturate(SeamsEnable);
if (en < 0.001 || TileRandLum <= 0.0001) return 1.0;
float tx = max(TilesX, 0.001);
float ty = max(TilesY, 0.001);
float row = floor(BaseUV.y * ty);
float rowHash = frac(sin(row * 127.1 + 311.7) * 43758.5453);
float shift = row * RowShiftOrder + (rowHash - 0.5) * RowShiftRandom;
float2 cell = floor(float2(BaseUV.x * tx + shift, BaseUV.y * ty));
float h1 = frac(sin(dot(cell, float2(127.1, 311.7))) * 43758.5453);
return max(0.05, 1.0 + (h1 - 0.5) * 2.0 * TileRandLum * en);
"""
    custom_tile_lum = _make_custom_hlsl_node(
        mel,
        mat,
        "SubstanceTileLuminance",
        unreal.CustomMaterialOutputType.CMOT_FLOAT1,
        ["BaseUV", "SeamsEnable", "TilesX", "TilesY", "RowShiftOrder", "RowShiftRandom", "TileRandLum"],
        hlsl_tile_lum,
        -1880,
        -240,
    )
    _conn_expr(mel, custom_seams_grid_uv, "", custom_tile_lum, "BaseUV")
    _conn_expr(mel, seams_enable_p, "", custom_tile_lum, "SeamsEnable")
    _conn_expr(mel, tiles_x_p, "", custom_tile_lum, "TilesX")
    _conn_expr(mel, tiles_y_p, "", custom_tile_lum, "TilesY")
    _conn_expr(mel, row_order_p, "", custom_tile_lum, "RowShiftOrder")
    _conn_expr(mel, row_rand_p, "", custom_tile_lum, "RowShiftRandom")
    _conn_expr(mel, tile_rand_lum_p, "", custom_tile_lum, "TileRandLum")

    # === 06. Layer B (Secondary Material & Blend by Substance Seams, Tiles, Mask & Mesh Paint [R]) ===
    grp_layer_b = "06 - Mesh Paint [R] / Layer 1 (Combine & Seams)"

    layer_b_en_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 1420)
    layer_b_en_p.set_editor_property("parameter_name", "LayerB_Enable")
    layer_b_en_p.set_editor_property("group", grp_layer_b)
    layer_b_en_p.set_editor_property("default_value", 0.0)

    layer_b_tiling_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, 1500)
    layer_b_tiling_p.set_editor_property("parameter_name", "LayerB_UV_Tiling")
    layer_b_tiling_p.set_editor_property("group", grp_layer_b)
    layer_b_tiling_p.set_editor_property("default_value", 1.0)

    layer_b_tx_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, 1550)
    layer_b_tx_p.set_editor_property("parameter_name", "LayerB_Tiling_X")
    layer_b_tx_p.set_editor_property("group", grp_layer_b)
    layer_b_tx_p.set_editor_property("default_value", 1.0)

    layer_b_ty_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, 1600)
    layer_b_ty_p.set_editor_property("parameter_name", "LayerB_Tiling_Y")
    layer_b_ty_p.set_editor_property("group", grp_layer_b)
    layer_b_ty_p.set_editor_property("default_value", 1.0)

    layer_b_txy_app = mel.create_material_expression(mat, unreal.MaterialExpressionAppendVector, -2340, 1560)
    _conn_expr(mel, layer_b_tx_p, "", layer_b_txy_app, "A")
    _conn_expr(mel, layer_b_ty_p, "", layer_b_txy_app, "B")

    layer_b_eff_tiling = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -2250, 1530)
    _conn_expr(mel, layer_b_txy_app, "", layer_b_eff_tiling, "A")
    _conn_expr(mel, layer_b_tiling_p, "", layer_b_eff_tiling, "B")

    uv_layer_b = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -2160, 1500)
    _conn_expr(mel, custom_tile_uv, "", uv_layer_b, "A")
    _conn_expr(mel, layer_b_eff_tiling, "", uv_layer_b, "B")

    blend_in_seams_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 1620)
    blend_in_seams_p.set_editor_property("parameter_name", "Blend_In_Seams")
    blend_in_seams_p.set_editor_property("group", grp_layer_b)
    blend_in_seams_p.set_editor_property("default_value", 1.0)

    blend_checker_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 1720)
    blend_checker_p.set_editor_property("parameter_name", "Blend_Checkerboard_Tiles")
    blend_checker_p.set_editor_property("group", grp_layer_b)
    blend_checker_p.set_editor_property("default_value", 0.0)

    blend_rand_tiles_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 1820)
    blend_rand_tiles_p.set_editor_property("parameter_name", "Blend_Random_Tiles")
    blend_rand_tiles_p.set_editor_property("group", grp_layer_b)
    blend_rand_tiles_p.set_editor_property("default_value", 0.0)

    blend_mask_str_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 1920)
    blend_mask_str_p.set_editor_property("parameter_name", "Blend_Mask_Strength")
    blend_mask_str_p.set_editor_property("group", grp_layer_b)
    blend_mask_str_p.set_editor_property("default_value", 0.0)

    blend_mask_tiling_x_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, 1940)
    blend_mask_tiling_x_p.set_editor_property("parameter_name", "Blend_Mask_Tiling_X")
    blend_mask_tiling_x_p.set_editor_property("group", grp_layer_b)
    blend_mask_tiling_x_p.set_editor_property("default_value", 1.0)

    blend_mask_tiling_y_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, 2000)
    blend_mask_tiling_y_p.set_editor_property("parameter_name", "Blend_Mask_Tiling_Y")
    blend_mask_tiling_y_p.set_editor_property("group", grp_layer_b)
    blend_mask_tiling_y_p.set_editor_property("default_value", 1.0)

    blend_mask_tiling_xy = mel.create_material_expression(mat, unreal.MaterialExpressionAppendVector, -2360, 1960)
    _conn_expr(mel, blend_mask_tiling_x_p, "", blend_mask_tiling_xy, "A")
    _conn_expr(mel, blend_mask_tiling_y_p, "", blend_mask_tiling_xy, "B")

    uv_blend_mask = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -2260, 1920)
    _conn_expr(mel, custom_l1_mask_base_uv, "", uv_blend_mask, "A")
    _conn_expr(mel, blend_mask_tiling_xy, "", uv_blend_mask, "B")

    blend_mask_con_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 2020)
    blend_mask_con_p.set_editor_property("parameter_name", "Blend_Mask_Contrast")
    blend_mask_con_p.set_editor_property("group", grp_layer_b)
    blend_mask_con_p.set_editor_property("default_value", 1.0)

    blend_mask_bri_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 2070)
    blend_mask_bri_p.set_editor_property("parameter_name", "Blend_Mask_Brightness")
    blend_mask_bri_p.set_editor_property("group", grp_layer_b)
    blend_mask_bri_p.set_editor_property("default_value", 0.0)

    blend_mask_inv_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 2120)
    blend_mask_inv_p.set_editor_property("parameter_name", "Blend_Mask_Invert")
    blend_mask_inv_p.set_editor_property("group", grp_layer_b)
    blend_mask_inv_p.set_editor_property("default_value", 0.0)

    blend_hgt_sharp_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 2180)
    blend_hgt_sharp_p.set_editor_property("parameter_name", "Blend_Height_Sharpness")
    blend_hgt_sharp_p.set_editor_property("group", grp_layer_b)
    blend_hgt_sharp_p.set_editor_property("default_value", 0.5)

    layer_b_use_mask_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 2240)
    layer_b_use_mask_p.set_editor_property("parameter_name", "LayerB_Use_Mask")
    layer_b_use_mask_p.set_editor_property("group", grp_layer_b)
    layer_b_use_mask_p.set_editor_property("default_value", 1.0)

    tex_blend_mask = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -2160, 1880)
    tex_blend_mask.set_editor_property("parameter_name", "BlendMaskTexture")
    tex_blend_mask.set_editor_property("group", grp_layer_b)
    if default_hgt:
        tex_blend_mask.set_editor_property("texture", default_hgt)
    tex_blend_mask.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tex_blend_mask.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, uv_blend_mask, "", tex_blend_mask, "UVs")

    tex_alb_b = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1560, 1340)
    tex_alb_b.set_editor_property("parameter_name", "LayerB_AlbedoTexture")
    tex_alb_b.set_editor_property("group", grp_layer_b)
    if default_alb:
        tex_alb_b.set_editor_property("texture", default_alb)
    tex_alb_b.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    tex_alb_b.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, uv_layer_b, "", tex_alb_b, "UVs")

    layer_b_tint_p = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -1560, 1560)
    layer_b_tint_p.set_editor_property("parameter_name", "LayerB_ColorTint")
    layer_b_tint_p.set_editor_property("group", grp_layer_b)
    layer_b_tint_p.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))

    alb_b_tinted = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1320, 1400)
    _conn_expr(mel, tex_alb_b, "RGB", alb_b_tinted, "A")
    _conn_expr(mel, layer_b_tint_p, "RGB", alb_b_tinted, "B")

    tex_nrm_b = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1560, 1740)
    tex_nrm_b.set_editor_property("parameter_name", "LayerB_NormalTexture")
    tex_nrm_b.set_editor_property("group", grp_layer_b)
    if default_nrm:
        tex_nrm_b.set_editor_property("texture", default_nrm)
    tex_nrm_b.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    tex_nrm_b.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, uv_layer_b, "", tex_nrm_b, "UVs")

    tex_rgh_b = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1560, 1960)
    tex_rgh_b.set_editor_property("parameter_name", "LayerB_RoughnessTexture")
    tex_rgh_b.set_editor_property("group", grp_layer_b)
    if default_rgh:
        tex_rgh_b.set_editor_property("texture", default_rgh)
    tex_rgh_b.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tex_rgh_b.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, uv_layer_b, "", tex_rgh_b, "UVs")

    layer_b_rgh_mult_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 2180)
    layer_b_rgh_mult_p.set_editor_property("parameter_name", "LayerB_Roughness_Mult")
    layer_b_rgh_mult_p.set_editor_property("group", grp_layer_b)
    layer_b_rgh_mult_p.set_editor_property("default_value", 1.0)

    rgh_b_scaled = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1320, 2000)
    _conn_expr(mel, tex_rgh_b, "R", rgh_b_scaled, "A")
    _conn_expr(mel, layer_b_rgh_mult_p, "", rgh_b_scaled, "B")

    layer_b_met_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 2280)
    layer_b_met_p.set_editor_property("parameter_name", "LayerB_Metallic")
    layer_b_met_p.set_editor_property("group", grp_layer_b)
    layer_b_met_p.set_editor_property("default_value", 0.0)

    tex_hgt_b = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1560, 2400)
    tex_hgt_b.set_editor_property("parameter_name", "LayerB_HeightTexture")
    tex_hgt_b.set_editor_property("group", grp_layer_b)
    if default_hgt:
        tex_hgt_b.set_editor_property("texture", default_hgt)
    tex_hgt_b.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tex_hgt_b.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, uv_layer_b, "", tex_hgt_b, "UVs")

    is_decal_mm = (mm_name == "MM_ArchViz_Decal")

    # === 04. Height Map (BumpOffset Parallax + Seam Recess + WPO Displacement + AO) ===
    tex_height = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1560, 560)
    tex_height.set_editor_property("parameter_name", "HeightTexture")
    tex_height.set_editor_property("group", "04 - Height Map")
    if default_hgt:
        tex_height.set_editor_property("texture", default_hgt)
    tex_height.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tex_height.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, custom_tile_uv, "", tex_height, "UVs")

    vcol_str_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, 2310)
    vcol_str_p.set_editor_property("parameter_name", "Vertex_Paint_Strength")
    vcol_str_p.set_editor_property("group", grp_layer_b)
    vcol_str_p.set_editor_property("default_value", 1.0)

    if not is_decal_mm:
        # UE 5.5 / 5.6 / 5.7 Native Mesh Paint Texture Color Pipeline (per tutorial video):
        # TextureCoordinate(0) + MeshPaintTextureObject -> TextureSample(SAMPLERTYPE_VIRTUAL_COLOR)
        # -> MeshPaintTextureReplace(Default = 0, MeshPaintTexture = TextureSample) -> ComponentMask(R, G, B, A)
        mp_tc0 = mel.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -2880, 2320)
        mp_tc0.set_editor_property("coordinate_index", 0)
        try:
            mp_tc0.set_editor_property("desc", "Mesh Paint UV0")
        except Exception:
            pass

        mp_tex_obj = mel.create_material_expression(mat, unreal.MaterialExpressionMeshPaintTextureObject, -2880, 2440)
        try:
            mp_tex_obj.set_editor_property("desc", "Mesh Paint Texture Object (UE 5.7 VT)")
        except Exception:
            pass

        mp_tex_sample = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSample, -2700, 2390)
        try:
            mp_tex_sample.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_VIRTUAL_COLOR)
            mp_tex_sample.set_editor_property("desc", "Mesh Paint VT Sample (RGBA)")
        except Exception:
            pass
        _conn_expr(mel, mp_tc0, "", mp_tex_sample, "UVs")
        _conn_expr(mel, mp_tex_obj, "", mp_tex_sample, "Tex")

        mp_def_zero = mel.create_material_expression(mat, unreal.MaterialExpressionConstant4Vector, -2700, 2540)
        mp_def_zero.set_editor_property("constant", unreal.LinearColor(0.0, 0.0, 0.0, 0.0))

        mp_tex_rep = mel.create_material_expression(mat, unreal.MaterialExpressionMeshPaintTextureReplace, -2520, 2390)
        try:
            mp_tex_rep.set_editor_property("desc", "Mesh Paint Replace (R=Layer1, G=Layer2, B=Layer3, A=Layer4)")
        except Exception:
            pass
        _conn_expr(mel, mp_def_zero, "", mp_tex_rep, "Default")
        _conn_expr(mel, mp_tex_sample, "RGBA", mp_tex_rep, "MeshPaintTexture")

        mp_channel_masks = {}
        for ch_idx, (ch_key, r_b, g_b, b_b, a_b) in enumerate((
            ("R", True, False, False, False),
            ("G", False, True, False, False),
            ("B", False, False, True, False),
            ("A", False, False, False, True),
        )):
            cm_node = mel.create_material_expression(mat, unreal.MaterialExpressionComponentMask, -2360, 2360 + ch_idx * 65)
            cm_node.set_editor_property("r", r_b)
            cm_node.set_editor_property("g", g_b)
            cm_node.set_editor_property("b", b_b)
            cm_node.set_editor_property("a", a_b)
            try:
                cm_node.set_editor_property("desc", f"Mesh Paint [{ch_key}] -> Layer {ch_idx + 1}")
            except Exception:
                pass
            _conn_expr(mel, mp_tex_rep, "", cm_node, "")
            mp_channel_masks[ch_key] = cm_node
    else:
        vert_col_node = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -2400, 2390)
        vert_col_node.set_editor_property("r", 0.0)
        mp_channel_masks = {"R": vert_col_node, "G": vert_col_node, "B": vert_col_node, "A": vert_col_node}

    # Custom Node 5: Unified Layer B Blend Alpha (Combines by Substance Seam, Checkerboard/Random Tiles, Mask+Height, and MeshPaintTextureReplace.R with HeightLerp transition)
    hlsl_layer_b_mask = """
float enB = saturate(LayerBEnable);
float effVpStr = (VertexPaintStr > 0.001) ? saturate(VertexPaintStr) : 1.0;
bool hasPaint = (VertexColorVal > 0.0005);
if (enB < 0.001 && !hasPaint) return 0.0;
float sharp = saturate(HeightBlendSharpness);
float hDiff = (HeightB - HeightA) * sharp;
float hContrast = 1.0 + sharp * 5.0;
float vcolFactor = 0.0;
if (hasPaint)
{
    float vp = saturate(VertexColorVal * effVpStr);
    float vpH = saturate(((vp * 2.0 - 1.0) + hDiff * 0.85) * hContrast * 0.5 + 0.5);
    vcolFactor = saturate(lerp(vp, vpH, sharp * saturate(vp * 4.0) * saturate((1.0 - vp) * 3.5)));
}
if (enB < 0.001) return vcolFactor;
float seamFactor = (SeamMtlEnable < 0.001) ? saturate(SeamMask * BlendInSeams) : 0.0;
float tileFactor = 0.0;
if (SeamsEnable > 0.001 && (BlendCheckerboard > 0.001 || BlendRandomTiles > 0.001))
{
    float tx = max(TilesX, 0.001);
    float ty = max(TilesY, 0.001);
    float row = floor(BaseUV.y * ty);
    float rowHash = frac(sin(row * 127.1 + 311.7) * 43758.5453);
    float shift = row * RowShiftOrder + (rowHash - 0.5) * RowShiftRandom;
    float2 cell = floor(float2(BaseUV.x * tx + shift, BaseUV.y * ty));
    float checker = fmod(abs(cell.x + cell.y), 2.0);
    float hTile = frac(sin(dot(cell, float2(517.3, 289.1))) * 43758.5453);
    float randTile = (hTile < BlendRandomTiles) ? 1.0 : 0.0;
    float cellSel = max(checker * saturate(BlendCheckerboard), randTile);
    tileFactor = cellSel * saturate(1.0 - SeamMask);
}
float maskFactor = 0.0;
if (LayerBUseMask >= 0.5)
{
    if (BlendMaskStr > 0.001)
    {
        float mRaw = lerp(MaskTexVal, 1.0 - MaskTexVal, saturate(BlendMaskInvert));
        float m = saturate((mRaw - 0.5) * max(BlendMaskContrast, 0.01) + 0.5 + BlendMaskBrightness);
        float mH = saturate(((m * 2.0 - 1.0) + hDiff * 0.85) * hContrast * 0.5 + 0.5);
        maskFactor = saturate(lerp(m, mH, sharp * saturate(m * 4.0) * saturate((1.0 - m) * 3.5)) * BlendMaskStr);
    }
}
else if (!hasPaint && (SeamsEnable < 0.001 || (BlendCheckerboard < 0.001 && BlendRandomTiles < 0.001 && (SeamMtlEnable >= 0.001 || BlendInSeams < 0.001))))
{
    maskFactor = 1.0;
}
float procCombined = max(max(seamFactor, tileFactor), maskFactor) * enB;
return saturate(max(procCombined, vcolFactor));
"""
    custom_layer_b_alpha = _make_custom_hlsl_node(
        mel,
        mat,
        "SubstanceLayerBlendMask",
        unreal.CustomMaterialOutputType.CMOT_FLOAT1,
        [
            "BaseUV",
            "SeamsEnable",
            "TilesX",
            "TilesY",
            "RowShiftOrder",
            "RowShiftRandom",
            "SeamMask",
            "SeamMtlEnable",
            "LayerBEnable",
            "LayerBUseMask",
            "BlendInSeams",
            "BlendCheckerboard",
            "BlendRandomTiles",
            "MaskTexVal",
            "BlendMaskStr",
            "BlendMaskContrast",
            "BlendMaskBrightness",
            "BlendMaskInvert",
            "HeightA",
            "HeightB",
            "HeightBlendSharpness",
            "VertexColorVal",
            "VertexPaintStr",
        ],
        hlsl_layer_b_mask,
        -1280,
        1120,
    )
    _conn_expr(mel, custom_seams_grid_uv, "", custom_layer_b_alpha, "BaseUV")
    _conn_expr(mel, seams_enable_p, "", custom_layer_b_alpha, "SeamsEnable")
    _conn_expr(mel, tiles_x_p, "", custom_layer_b_alpha, "TilesX")
    _conn_expr(mel, tiles_y_p, "", custom_layer_b_alpha, "TilesY")
    _conn_expr(mel, row_order_p, "", custom_layer_b_alpha, "RowShiftOrder")
    _conn_expr(mel, row_rand_p, "", custom_layer_b_alpha, "RowShiftRandom")
    _conn_expr(mel, custom_seam_mask, "", custom_layer_b_alpha, "SeamMask")
    _conn_expr(mel, seam_mtl_en_p, "", custom_layer_b_alpha, "SeamMtlEnable")
    _conn_expr(mel, layer_b_en_p, "", custom_layer_b_alpha, "LayerBEnable")
    _conn_expr(mel, layer_b_use_mask_p, "", custom_layer_b_alpha, "LayerBUseMask")
    _conn_expr(mel, blend_in_seams_p, "", custom_layer_b_alpha, "BlendInSeams")
    _conn_expr(mel, blend_checker_p, "", custom_layer_b_alpha, "BlendCheckerboard")
    _conn_expr(mel, blend_rand_tiles_p, "", custom_layer_b_alpha, "BlendRandomTiles")
    _conn_expr(mel, tex_blend_mask, "R", custom_layer_b_alpha, "MaskTexVal")
    _conn_expr(mel, blend_mask_str_p, "", custom_layer_b_alpha, "BlendMaskStr")
    _conn_expr(mel, blend_mask_con_p, "", custom_layer_b_alpha, "BlendMaskContrast")
    _conn_expr(mel, blend_mask_bri_p, "", custom_layer_b_alpha, "BlendMaskBrightness")
    _conn_expr(mel, blend_mask_inv_p, "", custom_layer_b_alpha, "BlendMaskInvert")
    _conn_expr(mel, tex_height, "R", custom_layer_b_alpha, "HeightA")
    _conn_expr(mel, tex_hgt_b, "R", custom_layer_b_alpha, "HeightB")
    _conn_expr(mel, blend_hgt_sharp_p, "", custom_layer_b_alpha, "HeightBlendSharpness")
    _conn_expr(mel, mp_channel_masks["R"], "", custom_layer_b_alpha, "VertexColorVal")
    _conn_expr(mel, vcol_str_p, "", custom_layer_b_alpha, "VertexPaintStr")

    # Subtract seam depth from height so seams are recessed in Parallax, WPO, and AO
    seam_recess_mul = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1560, 740)
    _conn_expr(mel, custom_seam_mask, "", seam_recess_mul, "A")
    _conn_expr(mel, seam_depth_p, "", seam_recess_mul, "B")

    hgt_minus_seam = mel.create_material_expression(mat, unreal.MaterialExpressionSubtract, -1380, 620)
    _conn_expr(mel, tex_height, "R", hgt_minus_seam, "A")
    _conn_expr(mel, seam_recess_mul, "", hgt_minus_seam, "B")

    hgt_a_clamped = _make_clamp_expr(mel, mat, hgt_minus_seam, "", 0.0, 1.0, -1260, 620)

    hgt_combined = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -1120, 620)
    _conn_expr(mel, hgt_a_clamped, "", hgt_combined, "A")
    _conn_expr(mel, tex_hgt_b, "R", hgt_combined, "B")
    _conn_expr(mel, custom_layer_b_alpha, "", hgt_combined, "Alpha")

    # === 07..09. Additional Hardware Corona Overlay & Tile Variation Layers (Layer 2 = Layer C, Layer 3 = Layer D, Layer 4) ===
    hlsl_multi_layer_mask = """
float enL = saturate(LayerEnable);
float effVpStr = (VertexPaintStr > 0.001) ? saturate(VertexPaintStr) : 1.0;
bool hasPaint = (VertexColorVal > 0.0005);
if (enL < 0.001 && !hasPaint) return 0.0;
float sharp = saturate(HeightBlendSharpness);
float hDiff = (HeightLayer - HeightPrev) * sharp;
float hContrast = 1.0 + sharp * 5.0;
float vcolFactor = 0.0;
if (hasPaint)
{
    float vp = saturate(VertexColorVal * effVpStr);
    float vpH = saturate(((vp * 2.0 - 1.0) + hDiff * 0.85) * hContrast * 0.5 + 0.5);
    vcolFactor = saturate(lerp(vp, vpH, sharp * saturate(vp * 4.0) * saturate((1.0 - vp) * 3.5)));
}
if (enL < 0.001) return vcolFactor;
float tileFactor = 0.0;
if (SeamsEnable > 0.001 && RandomTiles > 0.001)
{
    float tx = max(TilesX, 0.001);
    float ty = max(TilesY, 0.001);
    float row = floor(BaseUV.y * ty);
    float rowHash = frac(sin(row * 127.1 + 311.7) * 43758.5453);
    float shift = row * RowShiftOrder + (rowHash - 0.5) * RowShiftRandom;
    float2 cell = floor(float2(BaseUV.x * tx + shift, BaseUV.y * ty));
    float hBase = frac(sin(dot(cell, float2(517.3, 289.1))) * 43758.5453);
    float hTile = frac(hBase + TilePhaseOffset);
    float randTile = (hTile < RandomTiles) ? 1.0 : 0.0;
    tileFactor = randTile * saturate(1.0 - SeamMask);
}
float maskFactor = 0.0;
if (UseMask >= 0.5)
{
    if (MaskStr > 0.001)
    {
        float mRaw = lerp(MaskTexVal, 1.0 - MaskTexVal, saturate(MaskInvert));
        float m = saturate((mRaw - 0.5) * max(MaskContrast, 0.01) + 0.5 + MaskBrightness);
        float mH = saturate(((m * 2.0 - 1.0) + hDiff * 0.85) * hContrast * 0.5 + 0.5);
        maskFactor = saturate(lerp(m, mH, sharp * saturate(m * 4.0) * saturate((1.0 - m) * 3.5)) * MaskStr);
    }
}
else if (!hasPaint && (SeamsEnable < 0.001 || RandomTiles < 0.001))
{
    maskFactor = 1.0;
}
float procCombined = max(tileFactor, maskFactor) * enL;
return saturate(max(procCombined, vcolFactor));
"""
    extra_layer_nodes = []
    cur_hgt_chain = hgt_combined
    vcol_pin_for_slot = {2: "G", 3: "B", 4: "A"}
    for k_slot in (2, 3, 4):
        ch_lbl = vcol_pin_for_slot.get(k_slot, "G")
        grp_k = f"0{5 + k_slot} - Mesh Paint [{ch_lbl}] / Layer {k_slot} (Overlay)"
        y_off = 1600 + (k_slot - 1) * 1150

        l_en_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, y_off)
        l_en_p.set_editor_property("parameter_name", f"Layer{k_slot}_Enable")
        l_en_p.set_editor_property("group", grp_k)
        l_en_p.set_editor_property("default_value", 0.0)

        l_rnd_tiles_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, y_off + 40)
        l_rnd_tiles_p.set_editor_property("parameter_name", f"Layer{k_slot}_Random_Tiles")
        l_rnd_tiles_p.set_editor_property("group", grp_k)
        l_rnd_tiles_p.set_editor_property("default_value", 0.0)

        l_phase_const = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -2260, y_off + 40)
        l_phase_const.set_editor_property("r", float((k_slot - 1) * 0.25))

        l_til_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, y_off + 70)
        l_til_p.set_editor_property("parameter_name", f"Layer{k_slot}_UV_Tiling")
        l_til_p.set_editor_property("group", grp_k)
        l_til_p.set_editor_property("default_value", 1.0)

        l_tx_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, y_off + 115)
        l_tx_p.set_editor_property("parameter_name", f"Layer{k_slot}_Tiling_X")
        l_tx_p.set_editor_property("group", grp_k)
        l_tx_p.set_editor_property("default_value", 1.0)

        l_ty_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, y_off + 160)
        l_ty_p.set_editor_property("parameter_name", f"Layer{k_slot}_Tiling_Y")
        l_ty_p.set_editor_property("group", grp_k)
        l_ty_p.set_editor_property("default_value", 1.0)

        l_txy_app = mel.create_material_expression(mat, unreal.MaterialExpressionAppendVector, -2340, y_off + 125)
        _conn_expr(mel, l_tx_p, "", l_txy_app, "A")
        _conn_expr(mel, l_ty_p, "", l_txy_app, "B")

        l_eff_til = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -2250, y_off + 95)
        _conn_expr(mel, l_txy_app, "", l_eff_til, "A")
        _conn_expr(mel, l_til_p, "", l_eff_til, "B")

        uv_lk = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -2160, y_off + 60)
        _conn_expr(mel, custom_tile_uv, "", uv_lk, "A")
        _conn_expr(mel, l_eff_til, "", uv_lk, "B")

        l_use_msk_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, y_off + 160)
        l_use_msk_p.set_editor_property("parameter_name", f"Layer{k_slot}_Use_Mask")
        l_use_msk_p.set_editor_property("group", grp_k)
        l_use_msk_p.set_editor_property("default_value", 1.0)

        l_msk_str_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, y_off + 240)
        l_msk_str_p.set_editor_property("parameter_name", f"Layer{k_slot}_Mask_Strength")
        l_msk_str_p.set_editor_property("group", grp_k)
        l_msk_str_p.set_editor_property("default_value", 0.0)

        l_msk_tx_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, y_off + 320)
        l_msk_tx_p.set_editor_property("parameter_name", f"Layer{k_slot}_Mask_Tiling_X")
        l_msk_tx_p.set_editor_property("group", grp_k)
        l_msk_tx_p.set_editor_property("default_value", 1.0)

        l_msk_ty_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, y_off + 380)
        l_msk_ty_p.set_editor_property("parameter_name", f"Layer{k_slot}_Mask_Tiling_Y")
        l_msk_ty_p.set_editor_property("group", grp_k)
        l_msk_ty_p.set_editor_property("default_value", 1.0)

        l_msk_txy = mel.create_material_expression(mat, unreal.MaterialExpressionAppendVector, -2340, y_off + 340)
        _conn_expr(mel, l_msk_tx_p, "", l_msk_txy, "A")
        _conn_expr(mel, l_msk_ty_p, "", l_msk_txy, "B")

        l_msk_trip_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2480, y_off + 420)
        l_msk_trip_p.set_editor_property("parameter_name", f"Layer{k_slot}_Mask_Triplanar")
        l_msk_trip_p.set_editor_property("group", grp_k)
        l_msk_trip_p.set_editor_property("default_value", 0.0)

        custom_lk_mask_base_uv = _make_custom_hlsl_node(
            mel,
            mat,
            f"Layer{k_slot}TriplanarMaskBaseUV",
            unreal.CustomMaterialOutputType.CMOT_FLOAT2,
            ["MeshBaseUV", "WorldPos", "VertNrmWS", "EncodedNrmUV1", "UseTriplanar"],
            hlsl_triplanar_mask_uv,
            -2360,
            y_off + 400,
        )
        _conn_expr(mel, tex_coord, "", custom_lk_mask_base_uv, "MeshBaseUV")
        _conn_expr(mel, world_pos_trip, "", custom_lk_mask_base_uv, "WorldPos")
        _conn_expr(mel, vert_nrm_trip, "", custom_lk_mask_base_uv, "VertNrmWS")
        _conn_expr(mel, tc_uv1_trip, "", custom_lk_mask_base_uv, "EncodedNrmUV1")
        _conn_expr(mel, l_msk_trip_p, "", custom_lk_mask_base_uv, "UseTriplanar")

        uv_l_msk = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -2220, y_off + 340)
        _conn_expr(mel, custom_lk_mask_base_uv, "", uv_l_msk, "A")
        _conn_expr(mel, l_msk_txy, "", uv_l_msk, "B")

        l_msk_con_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, y_off + 460)
        l_msk_con_p.set_editor_property("parameter_name", f"Layer{k_slot}_Mask_Contrast")
        l_msk_con_p.set_editor_property("group", grp_k)
        l_msk_con_p.set_editor_property("default_value", 1.0)

        l_msk_bri_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, y_off + 520)
        l_msk_bri_p.set_editor_property("parameter_name", f"Layer{k_slot}_Mask_Brightness")
        l_msk_bri_p.set_editor_property("group", grp_k)
        l_msk_bri_p.set_editor_property("default_value", 0.0)

        l_msk_inv_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -2400, y_off + 580)
        l_msk_inv_p.set_editor_property("parameter_name", f"Layer{k_slot}_Mask_Invert")
        l_msk_inv_p.set_editor_property("group", grp_k)
        l_msk_inv_p.set_editor_property("default_value", 0.0)

        tex_l_msk = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -2060, y_off + 320)
        tex_l_msk.set_editor_property("parameter_name", f"Layer{k_slot}_MaskTexture")
        tex_l_msk.set_editor_property("group", grp_k)
        if default_hgt:
            tex_l_msk.set_editor_property("texture", default_hgt)
        tex_l_msk.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        tex_l_msk.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
        _conn_expr(mel, uv_l_msk, "", tex_l_msk, "UVs")

        tex_l_alb = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1560, y_off)
        tex_l_alb.set_editor_property("parameter_name", f"Layer{k_slot}_AlbedoTexture")
        tex_l_alb.set_editor_property("group", grp_k)
        if default_alb:
            tex_l_alb.set_editor_property("texture", default_alb)
        tex_l_alb.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
        tex_l_alb.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
        _conn_expr(mel, uv_lk, "", tex_l_alb, "UVs")

        l_tint_p = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -1560, y_off + 200)
        l_tint_p.set_editor_property("parameter_name", f"Layer{k_slot}_ColorTint")
        l_tint_p.set_editor_property("group", grp_k)
        l_tint_p.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))

        alb_l_tinted = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1320, y_off + 60)
        _conn_expr(mel, tex_l_alb, "RGB", alb_l_tinted, "A")
        _conn_expr(mel, l_tint_p, "RGB", alb_l_tinted, "B")

        tex_l_nrm = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1560, y_off + 380)
        tex_l_nrm.set_editor_property("parameter_name", f"Layer{k_slot}_NormalTexture")
        tex_l_nrm.set_editor_property("group", grp_k)
        if default_nrm:
            tex_l_nrm.set_editor_property("texture", default_nrm)
        tex_l_nrm.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
        tex_l_nrm.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
        _conn_expr(mel, uv_lk, "", tex_l_nrm, "UVs")

        tex_l_rgh = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1560, y_off + 580)
        tex_l_rgh.set_editor_property("parameter_name", f"Layer{k_slot}_RoughnessTexture")
        tex_l_rgh.set_editor_property("group", grp_k)
        if default_rgh:
            tex_l_rgh.set_editor_property("texture", default_rgh)
        tex_l_rgh.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        tex_l_rgh.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
        _conn_expr(mel, uv_lk, "", tex_l_rgh, "UVs")

        l_rgh_mult_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, y_off + 760)
        l_rgh_mult_p.set_editor_property("parameter_name", f"Layer{k_slot}_Roughness_Mult")
        l_rgh_mult_p.set_editor_property("group", grp_k)
        l_rgh_mult_p.set_editor_property("default_value", 1.0)

        rgh_l_scaled = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -1320, y_off + 620)
        _conn_expr(mel, tex_l_rgh, "R", rgh_l_scaled, "A")
        _conn_expr(mel, l_rgh_mult_p, "", rgh_l_scaled, "B")

        l_met_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, y_off + 840)
        l_met_p.set_editor_property("parameter_name", f"Layer{k_slot}_Metallic")
        l_met_p.set_editor_property("group", grp_k)
        l_met_p.set_editor_property("default_value", 0.0)

        tex_l_hgt = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1560, y_off + 940)
        tex_l_hgt.set_editor_property("parameter_name", f"Layer{k_slot}_HeightTexture")
        tex_l_hgt.set_editor_property("group", grp_k)
        if default_hgt:
            tex_l_hgt.set_editor_property("texture", default_hgt)
        tex_l_hgt.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        tex_l_hgt.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
        _conn_expr(mel, uv_lk, "", tex_l_hgt, "UVs")

        alpha_lk = _make_custom_hlsl_node(
            mel,
            mat,
            f"CoronaLayer{k_slot}BlendAlpha",
            unreal.CustomMaterialOutputType.CMOT_FLOAT1,
            [
                "BaseUV",
                "SeamsEnable",
                "TilesX",
                "TilesY",
                "RowShiftOrder",
                "RowShiftRandom",
                "SeamMask",
                "RandomTiles",
                "TilePhaseOffset",
                "LayerEnable",
                "UseMask",
                "MaskTexVal",
                "MaskStr",
                "MaskContrast",
                "MaskBrightness",
                "MaskInvert",
                "HeightPrev",
                "HeightLayer",
                "HeightBlendSharpness",
                "VertexColorVal",
                "VertexPaintStr",
            ],
            hlsl_multi_layer_mask,
            -1200,
            y_off + 300,
        )
        _conn_expr(mel, custom_seams_grid_uv, "", alpha_lk, "BaseUV")
        _conn_expr(mel, seams_enable_p, "", alpha_lk, "SeamsEnable")
        _conn_expr(mel, tiles_x_p, "", alpha_lk, "TilesX")
        _conn_expr(mel, tiles_y_p, "", alpha_lk, "TilesY")
        _conn_expr(mel, row_order_p, "", alpha_lk, "RowShiftOrder")
        _conn_expr(mel, row_rand_p, "", alpha_lk, "RowShiftRandom")
        _conn_expr(mel, custom_seam_mask, "", alpha_lk, "SeamMask")
        _conn_expr(mel, l_rnd_tiles_p, "", alpha_lk, "RandomTiles")
        _conn_expr(mel, l_phase_const, "", alpha_lk, "TilePhaseOffset")
        _conn_expr(mel, l_en_p, "", alpha_lk, "LayerEnable")
        _conn_expr(mel, l_use_msk_p, "", alpha_lk, "UseMask")
        _conn_expr(mel, tex_l_msk, "R", alpha_lk, "MaskTexVal")
        _conn_expr(mel, l_msk_str_p, "", alpha_lk, "MaskStr")
        _conn_expr(mel, l_msk_con_p, "", alpha_lk, "MaskContrast")
        _conn_expr(mel, l_msk_bri_p, "", alpha_lk, "MaskBrightness")
        _conn_expr(mel, l_msk_inv_p, "", alpha_lk, "MaskInvert")
        _conn_expr(mel, cur_hgt_chain, "", alpha_lk, "HeightPrev")
        _conn_expr(mel, tex_l_hgt, "R", alpha_lk, "HeightLayer")
        _conn_expr(mel, blend_hgt_sharp_p, "", alpha_lk, "HeightBlendSharpness")
        _conn_expr(mel, mp_channel_masks[vcol_pin_for_slot.get(k_slot, "G")], "", alpha_lk, "VertexColorVal")
        _conn_expr(mel, vcol_str_p, "", alpha_lk, "VertexPaintStr")

        next_hgt = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -980 + (k_slot - 2) * 140, 620)
        _conn_expr(mel, cur_hgt_chain, "", next_hgt, "A")
        _conn_expr(mel, tex_l_hgt, "R", next_hgt, "B")
        _conn_expr(mel, alpha_lk, "", next_hgt, "Alpha")
        cur_hgt_chain = next_hgt

        extra_layer_nodes.append({
            "k": k_slot,
            "alpha": alpha_lk,
            "alb": alb_l_tinted,
            "nrm": tex_l_nrm,
            "rgh": rgh_l_scaled,
            "met": l_met_p,
        })

    height_str = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 880)
    height_str.set_editor_property("parameter_name", "Height_Strength")
    height_str.set_editor_property("group", "04 - Height Map")
    height_str.set_editor_property("default_value", 0.015)

    # Video Displacement S-Curve Refinement Pipeline ([11:32]-[13:26] & [21:52]-[24:35]):
    # Add(Height, Displacement_Center) -> Lerp(1 - Hc, Hc, Displacement_Intensity)
    # -> Add(Displacement_Offset) -> Saturate -> SCurve Power(Displacement_SCurve)
    disp_center_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 940)
    disp_center_p.set_editor_property("parameter_name", "Displacement_Center")
    disp_center_p.set_editor_property("group", "04 - Height Map")
    disp_center_p.set_editor_property("default_value", 0.0)

    disp_intensity_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 1000)
    disp_intensity_p.set_editor_property("parameter_name", "Displacement_Intensity")
    disp_intensity_p.set_editor_property("group", "04 - Height Map")
    disp_intensity_p.set_editor_property("default_value", 1.0)

    disp_offset_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 1060)
    disp_offset_p.set_editor_property("parameter_name", "Displacement_Offset")
    disp_offset_p.set_editor_property("group", "04 - Height Map")
    disp_offset_p.set_editor_property("default_value", 0.0)

    disp_scurve_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 1120)
    disp_scurve_p.set_editor_property("parameter_name", "Displacement_SCurve")
    disp_scurve_p.set_editor_property("group", "04 - Height Map")
    disp_scurve_p.set_editor_property("default_value", 1.0)

    hlsl_refine_disp = """
float hc = HeightIn + DispCenter;
float hi = lerp(1.0 - hc, hc, DispIntensity);
float ho = saturate(hi + DispOffset);
float p = max(DispSCurve, 0.01);
float sc = (ho < 0.5) ? (0.5 * pow(max(ho * 2.0, 0.0), p)) : (1.0 - 0.5 * pow(max((1.0 - ho) * 2.0, 0.0), p));
return saturate(sc);
"""
    refined_hgt_node = _make_custom_hlsl_node(
        mel,
        mat,
        "RefineDisplacementVideoSCurve",
        unreal.CustomMaterialOutputType.CMOT_FLOAT1,
        ["HeightIn", "DispCenter", "DispIntensity", "DispOffset", "DispSCurve"],
        hlsl_refine_disp,
        -1360,
        960,
    )
    _conn_expr(mel, cur_hgt_chain, "", refined_hgt_node, "HeightIn")
    _conn_expr(mel, disp_center_p, "", refined_hgt_node, "DispCenter")
    _conn_expr(mel, disp_intensity_p, "", refined_hgt_node, "DispIntensity")
    _conn_expr(mel, disp_offset_p, "", refined_hgt_node, "DispOffset")
    _conn_expr(mel, disp_scurve_p, "", refined_hgt_node, "DispSCurve")
    cur_hgt_chain = refined_hgt_node

    if not is_decal_mm:
        try:
            mat.set_editor_property("tangent_space_normal", False)
        except Exception:
            pass
        try:
            mat.set_editor_property("enable_tessellation", True)
        except Exception:
            pass
        try:
            mat.set_editor_property("used_with_nanite", True)
        except Exception:
            pass

        vert_nrm = mel.create_material_expression(mat, unreal.MaterialExpressionVertexNormalWS, -1480, 660)
        cam_ws = mel.create_material_expression(mat, unreal.MaterialExpressionCameraVectorWS, -1480, 560)
        uv1_coord = mel.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -1680, 760)
        uv1_coord.set_editor_property("coordinate_index", 1)

        hlsl_decode_subdiv_nrm = """
return float3(0.0, 0.0, 0.0);
"""
        local_to_world_nrm = _make_custom_hlsl_node(
            mel,
            mat,
            "DecodeSubdivWorldNormal",
            unreal.CustomMaterialOutputType.CMOT_FLOAT3,
            ["UV1"],
            hlsl_decode_subdiv_nrm,
            -1380,
            760,
        )
        _conn_expr(mel, uv1_coord, "", local_to_world_nrm, "UV1")

        # === Landscape Lab #01 (POM + Contact Shadows + Camera Distance Fade):
        # Smoothstep(POM_Start_Distance, POM_End_Distance, CameraDistance) fades Parallax & PixelDepthOffset
        # smoothly at distance for maximum FPS and zero horizon artifacts.
        pom_start_dist_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 1180)
        pom_start_dist_p.set_editor_property("parameter_name", "POM_Start_Distance")
        pom_start_dist_p.set_editor_property("group", "04 - Height Map")
        pom_start_dist_p.set_editor_property("default_value", 350.0)

        pom_end_dist_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 1240)
        pom_end_dist_p.set_editor_property("parameter_name", "POM_End_Distance")
        pom_end_dist_p.set_editor_property("group", "04 - Height Map")
        pom_end_dist_p.set_editor_property("default_value", 1800.0)

        cs_len_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1560, 1300)
        cs_len_p.set_editor_property("parameter_name", "Contact_Shadow_Length")
        cs_len_p.set_editor_property("group", "04 - Height Map")
        cs_len_p.set_editor_property("default_value", 0.0)

        cam_pos_ws = mel.create_material_expression(mat, unreal.MaterialExpressionCameraPositionWS, -1560, 1140)
        hlsl_cam_near_fade = """
float dist = length(WorldPos - CamPosWS);
float dMin = max(0.0, StartDist);
float dMax = max(dMin + 1.0, EndDist);
float fade = 1.0 - smoothstep(dMin, dMax, dist);
return saturate(fade);
"""
        cam_near_fade_node = _make_custom_hlsl_node(
            mel,
            mat,
            "CameraNearDistanceFade",
            unreal.CustomMaterialOutputType.CMOT_FLOAT1,
            ["WorldPos", "CamPosWS", "StartDist", "EndDist"],
            hlsl_cam_near_fade,
            -1360,
            1200,
        )
        _conn_expr(mel, world_pos_trip, "", cam_near_fade_node, "WorldPos")
        _conn_expr(mel, cam_pos_ws, "", cam_near_fade_node, "CamPosWS")
        _conn_expr(mel, pom_start_dist_p, "", cam_near_fade_node, "StartDist")
        _conn_expr(mel, pom_end_dist_p, "", cam_near_fade_node, "EndDist")

        hlsl_safe_bump = """
float2 uv = Coordinate;
float h = (Height - 0.5) * HeightRatioInput * saturate(NearFade);
if (abs(h) < 1e-5) return uv;
float decLenSq = dot(DecodedWorldNrm, DecodedWorldNrm);
float vLenSq = dot(VertNrmWS, VertNrmWS);
float tLenSq = dot(Parameters.TangentToWorld[0], Parameters.TangentToWorld[0]);
float bLenSq = dot(Parameters.TangentToWorld[1], Parameters.TangentToWorld[1]);
float3 T, B, N;
if (decLenSq > 0.5) {
    N = normalize(DecodedWorldNrm);
    float3 up = abs(N.z) < 0.99 ? float3(0.0, 0.0, 1.0) : float3(0.0, 1.0, 0.0);
    T = normalize(cross(up, N));
    B = cross(N, T);
} else if (vLenSq > 0.05 && tLenSq > 0.05 && bLenSq > 0.05) {
    T = normalize(Parameters.TangentToWorld[0]);
    B = normalize(Parameters.TangentToWorld[1]);
    N = normalize(Parameters.TangentToWorld[2]);
} else {
    N = normalize(TransformLocalVectorToWorld(Parameters, float3(0.0, 0.0, 1.0)));
    float3 up = abs(N.z) < 0.99 ? float3(0.0, 0.0, 1.0) : float3(0.0, 1.0, 0.0);
    T = normalize(cross(up, N));
    B = cross(N, T);
}
float2 camTS = float2(dot(CamVecWS, T), dot(CamVecWS, B));
float2 resUV = uv + camTS * h;
return any(isnan(resUV)) ? uv : resUV;
"""
        bump_offset = _make_custom_hlsl_node(
            mel,
            mat,
            "SafeParallaxBumpOffset",
            unreal.CustomMaterialOutputType.CMOT_FLOAT2,
            ["Coordinate", "Height", "HeightRatioInput", "NearFade", "VertNrmWS", "DecodedWorldNrm", "CamVecWS"],
            hlsl_safe_bump,
            -1280,
            40,
        )
        _conn_expr(mel, custom_tile_uv, "", bump_offset, "Coordinate")
        _conn_expr(mel, cur_hgt_chain, "", bump_offset, "Height")
        _conn_expr(mel, height_str, "", bump_offset, "HeightRatioInput")
        _conn_expr(mel, cam_near_fade_node, "", bump_offset, "NearFade")
        _conn_expr(mel, vert_nrm, "", bump_offset, "VertNrmWS")
        _conn_expr(mel, local_to_world_nrm, "", bump_offset, "DecodedWorldNrm")
        _conn_expr(mel, cam_ws, "", bump_offset, "CamVecWS")

        # MF_ContactLength (Landscape Lab #01 [12:55]-[15:15]):
        # Reconstructs crisp micro Contact Shadows via PixelDepthOffset = (1.0 - Height) * ContactShadowLength * NearFade * GrazingFactor
        hlsl_pdo_contact = """
if (ContactShadowLen <= 0.001 || HeightRatioInput <= 0.0001) return 0.0;
float decLenSq = dot(DecodedWorldNrm, DecodedWorldNrm);
float vLenSq = dot(VertNrmWS, VertNrmWS);
float3 nWS = (decLenSq > 0.5) ? normalize(DecodedWorldNrm) : ((vLenSq > 0.05) ? normalize(VertNrmWS) : normalize(TransformLocalVectorToWorld(Parameters, float3(0.0, 0.0, 1.0))));
float ndotv = max(abs(dot(nWS, CamVecWS)), 0.25);
float pdo = saturate(1.0 - saturate(HeightVal)) * ContactShadowLen * saturate(NearFade) / ndotv;
return any(isnan(pdo)) ? 0.0 : clamp(pdo, 0.0, 12.0);
"""
        pdo_node = _make_custom_hlsl_node(
            mel,
            mat,
            "ContactShadowPixelDepthOffset",
            unreal.CustomMaterialOutputType.CMOT_FLOAT1,
            ["HeightVal", "HeightRatioInput", "ContactShadowLen", "NearFade", "VertNrmWS", "DecodedWorldNrm", "CamVecWS"],
            hlsl_pdo_contact,
            -680,
            820,
        )
        _conn_expr(mel, cur_hgt_chain, "", pdo_node, "HeightVal")
        _conn_expr(mel, height_str, "", pdo_node, "HeightRatioInput")
        _conn_expr(mel, cs_len_p, "", pdo_node, "ContactShadowLen")
        _conn_expr(mel, cam_near_fade_node, "", pdo_node, "NearFade")
        _conn_expr(mel, vert_nrm, "", pdo_node, "VertNrmWS")
        _conn_expr(mel, local_to_world_nrm, "", pdo_node, "DecodedWorldNrm")
        _conn_expr(mel, cam_ws, "", pdo_node, "CamVecWS")

        wpo_str = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1000, 780)
        wpo_str.set_editor_property("parameter_name", "Height_Displacement_Strength")
        wpo_str.set_editor_property("group", "04 - Height Map")
        wpo_str.set_editor_property("default_value", 0.0)

        hlsl_safe_wpo = """
float decLenSq = dot(DecodedWorldNrm, DecodedWorldNrm);
float vLenSq = dot(VertNrmWS, VertNrmWS);
float3 nWS = (decLenSq > 0.5) ? normalize(DecodedWorldNrm) : ((vLenSq > 0.05) ? normalize(VertNrmWS) : normalize(TransformLocalVectorToWorld(Parameters, float3(0.0, 0.0, 1.0))));
float hc = saturate(HeightVal) + DispCenter;
float hi = lerp(1.0 - hc, hc, DispIntensity);
float ho = saturate(hi + DispOffset);
float p = max(DispSCurve, 0.01);
float sc = (ho < 0.5) ? (0.5 * pow(max(ho * 2.0, 0.0), p)) : (1.0 - 0.5 * pow(max((1.0 - ho) * 2.0, 0.0), p));
float3 disp = nWS * (saturate(sc) * DispStrength);
return any(isnan(disp)) ? float3(0.0, 0.0, 0.0) : disp;
"""
        wpo_node = _make_custom_hlsl_node(
            mel,
            mat,
            "SafeVertexNormalWPO",
            unreal.CustomMaterialOutputType.CMOT_FLOAT3,
            ["VertNrmWS", "DecodedWorldNrm", "HeightVal", "DispStrength", "DispCenter", "DispIntensity", "DispOffset", "DispSCurve"],
            hlsl_safe_wpo,
            -680,
            640,
        )
        _conn_expr(mel, vert_nrm, "", wpo_node, "VertNrmWS")
        _conn_expr(mel, local_to_world_nrm, "", wpo_node, "DecodedWorldNrm")
        _conn_expr(mel, hgt_a_clamped, "", wpo_node, "HeightVal")
        _conn_expr(mel, wpo_str, "", wpo_node, "DispStrength")
        _conn_expr(mel, disp_center_p, "", wpo_node, "DispCenter")
        _conn_expr(mel, disp_intensity_p, "", wpo_node, "DispIntensity")
        _conn_expr(mel, disp_offset_p, "", wpo_node, "DispOffset")
        _conn_expr(mel, disp_scurve_p, "", wpo_node, "DispSCurve")
        mel.connect_material_property(wpo_node, "", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    else:
        bump_offset = custom_tile_uv

    # === 00B. Anti-Tiling Studio (Dual-Scale Rotated Blend + Macro Noise Variation) ===
    grp_antitile = "00B - Anti-Tiling & Macro Variation"
    at_en_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1680, -820)
    at_en_p.set_editor_property("parameter_name", "AntiTile_Enable")
    at_en_p.set_editor_property("group", grp_antitile)
    at_en_p.set_editor_property("default_value", 0.0)

    at_trip_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1680, -760)
    at_trip_p.set_editor_property("parameter_name", "AntiTile_Triplanar")
    at_trip_p.set_editor_property("group", grp_antitile)
    at_trip_p.set_editor_property("default_value", 0.0)

    at_scale_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1680, -700)
    at_scale_p.set_editor_property("parameter_name", "AntiTile_Scale")
    at_scale_p.set_editor_property("group", grp_antitile)
    at_scale_p.set_editor_property("default_value", 0.85)

    at_nscale_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1680, -640)
    at_nscale_p.set_editor_property("parameter_name", "AntiTile_Noise_Scale")
    at_nscale_p.set_editor_property("group", grp_antitile)
    at_nscale_p.set_editor_property("default_value", 1.0)

    at_rot_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1680, -580)
    at_rot_p.set_editor_property("parameter_name", "AntiTile_Rotation")
    at_rot_p.set_editor_property("group", grp_antitile)
    at_rot_p.set_editor_property("default_value", 0.38)

    at_con_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1680, -520)
    at_con_p.set_editor_property("parameter_name", "AntiTile_Contrast")
    at_con_p.set_editor_property("group", grp_antitile)
    at_con_p.set_editor_property("default_value", 1.5)

    at_mvar_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1680, -460)
    at_mvar_p.set_editor_property("parameter_name", "AntiTile_Macro_Var")
    at_mvar_p.set_editor_property("group", grp_antitile)
    at_mvar_p.set_editor_property("default_value", 0.0)

    hlsl_at_uv2 = """
float ang = AntiTileRot * 6.2831853;
float s = sin(ang);
float c = cos(ang);
float2 u = (BaseUV - 0.5) * max(AntiTileScale, 0.01);
float2 rotUV = float2(u.x * c - u.y * s + 0.618034, u.x * s + u.y * c + 0.381966);
float2 warp = float2(
    sin(BaseUV.y * 5.2 + cos(BaseUV.x * 3.7)),
    cos(BaseUV.x * 4.8 - sin(BaseUV.y * 4.1))
) * 0.065;
return rotUV + warp;
"""
    custom_at_uv2 = _make_custom_hlsl_node(
        mel,
        mat,
        "AntiTileRotatedUV",
        unreal.CustomMaterialOutputType.CMOT_FLOAT2,
        ["BaseUV", "AntiTileScale", "AntiTileRot"],
        hlsl_at_uv2,
        -1480,
        -680,
    )
    _conn_expr(mel, bump_offset, "", custom_at_uv2, "BaseUV")
    _conn_expr(mel, at_scale_p, "", custom_at_uv2, "AntiTileScale")
    _conn_expr(mel, at_rot_p, "", custom_at_uv2, "AntiTileRot")

    tex_alb_at2 = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1280, -760)
    tex_alb_at2.set_editor_property("parameter_name", "AlbedoTexture")
    tex_alb_at2.set_editor_property("group", "01 - Albedo (Base Color)")
    if default_alb:
        tex_alb_at2.set_editor_property("texture", default_alb)
    tex_alb_at2.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    tex_alb_at2.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, custom_at_uv2, "", tex_alb_at2, "UVs")

    tex_nrm_at2 = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1280, -580)
    tex_nrm_at2.set_editor_property("parameter_name", "NormalTexture")
    tex_nrm_at2.set_editor_property("group", "02 - Normal Map")
    if default_nrm:
        tex_nrm_at2.set_editor_property("texture", default_nrm)
    tex_nrm_at2.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    tex_nrm_at2.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, custom_at_uv2, "", tex_nrm_at2, "UVs")

    tex_rgh_at2 = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1280, -400)
    tex_rgh_at2.set_editor_property("parameter_name", "RoughnessTexture")
    tex_rgh_at2.set_editor_property("group", "03 - Roughness & Surface")
    if default_rgh:
        tex_rgh_at2.set_editor_property("texture", default_rgh)
    tex_rgh_at2.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tex_rgh_at2.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, custom_at_uv2, "", tex_rgh_at2, "UVs")

    tex_hgt_at2 = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1280, -220)
    tex_hgt_at2.set_editor_property("parameter_name", "HeightTexture")
    tex_hgt_at2.set_editor_property("group", "04 - Height Map")
    if default_hgt:
        tex_hgt_at2.set_editor_property("texture", default_hgt)
    tex_hgt_at2.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tex_hgt_at2.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, custom_at_uv2, "", tex_hgt_at2, "UVs")

    # === 1. Albedo (Strength, Desaturation, Contrast, ContrastPower, Brightness, ColorTint + Tile Luminance, Seam Color & Layers 1..4) ===
    tex_albedo = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -1060, -480)
    tex_albedo.set_editor_property("parameter_name", "AlbedoTexture")
    tex_albedo.set_editor_property("group", "01 - Albedo (Base Color)")
    if default_alb:
        tex_albedo.set_editor_property("texture", default_alb)
    tex_albedo.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
    tex_albedo.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, bump_offset, "", tex_albedo, "UVs")

    hlsl_at_albedo = """
float en = saturate(AntiTileEnable);
float mv = saturate(MacroVar);
if (en < 0.001 && mv < 0.001) return Alb1;
float2 p = (UseTriplanar >= 0.5) ? ((WorldPos.xy + WorldPos.yz * 0.57) / 140.0) : (BaseUV * 1.35);
p *= max(NoiseScale, 0.01);
float2 i1 = floor(p);
float2 f1 = frac(p);
float2 u1 = f1 * f1 * (3.0 - 2.0 * f1);
float a1 = frac(sin(dot(i1, float2(127.1, 311.7))) * 43758.5453);
float b1 = frac(sin(dot(i1 + float2(1.0, 0.0), float2(127.1, 311.7))) * 43758.5453);
float c1 = frac(sin(dot(i1 + float2(0.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
float d1 = frac(sin(dot(i1 + float2(1.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
float n1 = lerp(lerp(a1, b1, u1.x), lerp(c1, d1, u1.x), u1.y);
float2 p2 = p * 2.13 + float2(17.3, 9.2);
float2 i2 = floor(p2);
float2 f2 = frac(p2);
float2 u2 = f2 * f2 * (3.0 - 2.0 * f2);
float a2 = frac(sin(dot(i2, float2(269.5, 183.3))) * 43758.5453);
float b2 = frac(sin(dot(i2 + float2(1.0, 0.0), float2(269.5, 183.3))) * 43758.5453);
float c2 = frac(sin(dot(i2 + float2(0.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
float d2 = frac(sin(dot(i2 + float2(1.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
float n2 = lerp(lerp(a2, b2, u2.x), lerp(c2, d2, u2.x), u2.y);
float2 p3 = p * 0.37 + float2(41.7, 23.9);
float2 i3 = floor(p3);
float2 f3 = frac(p3);
float2 u3 = f3 * f3 * (3.0 - 2.0 * f3);
float a3 = frac(sin(dot(i3, float2(419.2, 371.9))) * 43758.5453);
float b3 = frac(sin(dot(i3 + float2(1.0, 0.0), float2(419.2, 371.9))) * 43758.5453);
float c3 = frac(sin(dot(i3 + float2(0.0, 1.0), float2(419.2, 371.9))) * 43758.5453);
float d3 = frac(sin(dot(i3 + float2(1.0, 1.0), float2(419.2, 371.9))) * 43758.5453);
float n3 = lerp(lerp(a3, b3, u3.x), lerp(c3, d3, u3.x), u3.y);
float n = n1 * 0.52 + n2 * 0.28 + n3 * 0.20;
float2 fuv1 = frac(BaseUV);
float2 d1e = min(fuv1, 1.0 - fuv1);
float w1 = 1.0 - smoothstep(0.0, 0.11, min(d1e.x, d1e.y));
float2 fuv2 = frac(RotUV);
float2 d2e = min(fuv2, 1.0 - fuv2);
float w2 = 1.0 - smoothstep(0.0, 0.11, min(d2e.x, d2e.y));
float seamShield = clamp(w1 * (1.0 - w2 * 0.85) - w2 * (1.0 - w1 * 0.85), -1.0, 1.0);
float blendRaw = saturate((n - 0.5) * max(Contrast, 0.1) + 0.5);
float blendA = saturate(blendRaw + seamShield * 0.88) * en;
float3 mixedAlb = lerp(Alb1, Alb2, blendA);
float l1 = dot(Alb1, float3(0.299, 0.587, 0.114));
float l2 = dot(Alb2, float3(0.299, 0.587, 0.114));
float outlier = saturate(abs(l1 - l2) * 3.5);
float3 harmAlb = (Alb1 * Alb2 * 2.0) / max(Alb1 + Alb2, float3(0.01, 0.01, 0.01));
mixedAlb = lerp(mixedAlb, harmAlb, outlier * saturate(en * 0.55 + mv * 0.85) * 0.72);
float macroMult = lerp(1.0, 0.86 + 0.28 * n3, mv * 0.65);
return mixedAlb * macroMult;
"""
    custom_at_alb = _make_custom_hlsl_node(
        mel,
        mat,
        "AntiTileAlbedoBlend",
        unreal.CustomMaterialOutputType.CMOT_FLOAT3,
        ["Alb1", "Alb2", "BaseUV", "RotUV", "WorldPos", "UseTriplanar", "AntiTileEnable", "MacroVar", "NoiseScale", "Contrast"],
        hlsl_at_albedo,
        -940,
        -520,
    )
    _conn_expr(mel, tex_albedo, "RGB", custom_at_alb, "Alb1")
    _conn_expr(mel, tex_alb_at2, "RGB", custom_at_alb, "Alb2")
    _conn_expr(mel, uv_scaled, "", custom_at_alb, "BaseUV")
    _conn_expr(mel, custom_at_uv2, "", custom_at_alb, "RotUV")
    _conn_expr(mel, world_pos_trip, "", custom_at_alb, "WorldPos")
    _conn_expr(mel, at_trip_p, "", custom_at_alb, "UseTriplanar")
    _conn_expr(mel, at_en_p, "", custom_at_alb, "AntiTileEnable")
    _conn_expr(mel, at_mvar_p, "", custom_at_alb, "MacroVar")
    _conn_expr(mel, at_nscale_p, "", custom_at_alb, "NoiseScale")
    _conn_expr(mel, at_con_p, "", custom_at_alb, "Contrast")

    alb_strength = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -1060, -220)
    alb_strength.set_editor_property("parameter_name", "Albedo_Strength")
    alb_strength.set_editor_property("group", "01 - Albedo (Base Color)")
    alb_strength.set_editor_property("default_value", 1.0)

    alb_lerp_str = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -840, -380)
    alb_lerp_str.set_editor_property("const_a", 0.5)
    _conn_expr(mel, custom_at_alb, "", alb_lerp_str, "B")
    _conn_expr(mel, alb_strength, "", alb_lerp_str, "Alpha")

    alb_desat_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -840, -200)
    alb_desat_p.set_editor_property("parameter_name", "Albedo_Desaturation")
    alb_desat_p.set_editor_property("group", "01 - Albedo (Base Color)")
    alb_desat_p.set_editor_property("default_value", 0.0)

    alb_desat = mel.create_material_expression(mat, unreal.MaterialExpressionDesaturation, -640, -360)
    _conn_expr(mel, alb_lerp_str, "", alb_desat, "")
    _conn_expr(mel, alb_desat_p, "", alb_desat, "Fraction")

    alb_contrast_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -640, -200)
    alb_contrast_p.set_editor_property("parameter_name", "Albedo_Contrast")
    alb_contrast_p.set_editor_property("group", "01 - Albedo (Base Color)")
    alb_contrast_p.set_editor_property("default_value", 1.0)

    alb_contrast = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -450, -360)
    alb_contrast.set_editor_property("const_a", 0.5)
    _conn_expr(mel, alb_desat, "", alb_contrast, "B")
    _conn_expr(mel, alb_contrast_p, "", alb_contrast, "Alpha")

    alb_clamp1 = _make_clamp_expr(mel, mat, alb_contrast, "", 0.0001, 1.0, -320, -360)

    alb_power_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -450, -200)
    alb_power_p.set_editor_property("parameter_name", "Albedo_ContrastPower")
    alb_power_p.set_editor_property("group", "01 - Albedo (Base Color)")
    alb_power_p.set_editor_property("default_value", 1.0)

    alb_power = mel.create_material_expression(mat, unreal.MaterialExpressionPower, -160, -360)
    _conn_expr(mel, alb_clamp1, "", alb_power, "Base")
    _conn_expr(mel, alb_power_p, "", alb_power, "Exp")

    alb_bright_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -160, -200)
    alb_bright_p.set_editor_property("parameter_name", "Albedo_Brightness")
    alb_bright_p.set_editor_property("group", "01 - Albedo (Base Color)")
    alb_bright_p.set_editor_property("default_value", 1.0)

    alb_bright = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 20, -360)
    _conn_expr(mel, alb_power, "", alb_bright, "A")
    _conn_expr(mel, alb_bright_p, "", alb_bright, "B")

    alb_tint_p = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, 20, -200)
    alb_tint_p.set_editor_property("parameter_name", "Albedo_ColorTint")
    alb_tint_p.set_editor_property("group", "01 - Albedo (Base Color)")
    alb_tint_p.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))

    alb_tinted = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 180, -360)
    _conn_expr(mel, alb_bright, "", alb_tinted, "A")
    _conn_expr(mel, alb_tint_p, "", alb_tinted, "B")

    # Apply per-tile luminance variation, blend with Seam_Color, then blend with Layer B & Layers 2..4 Albedo
    alb_tile_lum = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 320, -360)
    _conn_expr(mel, alb_tinted, "", alb_tile_lum, "A")
    _conn_expr(mel, custom_tile_lum, "", alb_tile_lum, "B")

    is_glass_mm = (mm_name == "MM_ArchViz_Glass")
    if is_glass_mm:
        mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
        try:
            mat.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
        except Exception:
            try:
                mat.set_editor_property("translucency_lighting_mode", unreal.TranslucencyLightingMode.TLM_SURFACE)
            except Exception:
                pass
        try:
            mat.set_editor_property("use_hq_forward_reflections", True)
        except Exception:
            pass
        try:
            mat.set_editor_property("refraction_method", unreal.RefractionMode.RM_INDEX_OF_REFRACTION)
        except Exception:
            pass
        mat.set_editor_property("two_sided", True)

        grp_glass = "00 - Corona Glass Parameters"
        glass_col_p = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, 180, -540)
        glass_col_p.set_editor_property("parameter_name", "Glass_Color")
        glass_col_p.set_editor_property("group", grp_glass)
        glass_col_p.set_editor_property("default_value", unreal.LinearColor(0.04, 0.08, 0.10, 1.0))

        glass_alb_mix_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 180, -640)
        glass_alb_mix_p.set_editor_property("parameter_name", "Glass_Texture_Tint_Amount")
        glass_alb_mix_p.set_editor_property("group", grp_glass)
        glass_alb_mix_p.set_editor_property("default_value", 0.08)

        base_alb_for_seams = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 340, -520)
        _conn_expr(mel, glass_col_p, "RGB", base_alb_for_seams, "A")
        _conn_expr(mel, alb_tile_lum, "", base_alb_for_seams, "B")
        _conn_expr(mel, glass_alb_mix_p, "", base_alb_for_seams, "Alpha")
    else:
        base_alb_for_seams = alb_tile_lum

    seam_mtl_blend_raw = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 320, -240)
    _conn_expr(mel, seam_mtl_en_p, "", seam_mtl_blend_raw, "A")
    _conn_expr(mel, blend_in_seams_p, "", seam_mtl_blend_raw, "B")
    seam_mtl_blend_w = _make_clamp_expr(mel, mat, seam_mtl_blend_raw, "", 0.0, 1.0, 380, -240)

    seam_eff_alb = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 400, -180)
    _conn_expr(mel, seam_color_p, "RGB", seam_eff_alb, "A")
    _conn_expr(mel, alb_seam_tinted, "", seam_eff_alb, "B")
    _conn_expr(mel, seam_mtl_blend_w, "", seam_eff_alb, "Alpha")

    alb_with_seams = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 460, -360)
    _conn_expr(mel, base_alb_for_seams, "", alb_with_seams, "A")
    _conn_expr(mel, seam_eff_alb, "", alb_with_seams, "B")
    _conn_expr(mel, custom_seam_mask, "", alb_with_seams, "Alpha")

    alb_with_layer_b = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 600, -360)
    _conn_expr(mel, alb_with_seams, "", alb_with_layer_b, "A")
    _conn_expr(mel, alb_b_tinted, "", alb_with_layer_b, "B")
    _conn_expr(mel, custom_layer_b_alpha, "", alb_with_layer_b, "Alpha")

    cur_alb_chain = alb_with_layer_b
    for ex_n in extra_layer_nodes:
        next_alb = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 600 + (ex_n["k"] - 1) * 140, -360)
        _conn_expr(mel, cur_alb_chain, "", next_alb, "A")
        _conn_expr(mel, ex_n["alb"], "", next_alb, "B")
        _conn_expr(mel, ex_n["alpha"], "", next_alb, "Alpha")
        cur_alb_chain = next_alb

    alb_final = _make_clamp_expr(mel, mat, cur_alb_chain, "", 0.0, 1.0, 1160, -360)
    mel.connect_material_property(alb_final, "", unreal.MaterialProperty.MP_BASE_COLOR)

    # === 2. Normal Map + Normal_Strength + Anti-Tile Normal Blend + 3D Seam Bevel Normal + Layer B & Layers 2..4 Normal ===
    tex_normal = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -840, 280)
    tex_normal.set_editor_property("parameter_name", "NormalTexture")
    tex_normal.set_editor_property("group", "02 - Normal Map")
    if default_nrm:
        tex_normal.set_editor_property("texture", default_nrm)
    tex_normal.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    tex_normal.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, bump_offset, "", tex_normal, "UVs")

    hlsl_at_normal = """
float en = saturate(AntiTileEnable);
if (en < 0.001) return Nrm1;
float2 p = (UseTriplanar >= 0.5) ? ((WorldPos.xy + WorldPos.yz * 0.57) / 140.0) : (BaseUV * 1.35);
p *= max(NoiseScale, 0.01);
float2 i1 = floor(p);
float2 f1 = frac(p);
float2 u1 = f1 * f1 * (3.0 - 2.0 * f1);
float a1 = frac(sin(dot(i1, float2(127.1, 311.7))) * 43758.5453);
float b1 = frac(sin(dot(i1 + float2(1.0, 0.0), float2(127.1, 311.7))) * 43758.5453);
float c1 = frac(sin(dot(i1 + float2(0.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
float d1 = frac(sin(dot(i1 + float2(1.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
float n1 = lerp(lerp(a1, b1, u1.x), lerp(c1, d1, u1.x), u1.y);
float2 p2 = p * 2.13 + float2(17.3, 9.2);
float2 i2 = floor(p2);
float2 f2 = frac(p2);
float2 u2 = f2 * f2 * (3.0 - 2.0 * f2);
float a2 = frac(sin(dot(i2, float2(269.5, 183.3))) * 43758.5453);
float b2 = frac(sin(dot(i2 + float2(1.0, 0.0), float2(269.5, 183.3))) * 43758.5453);
float c2 = frac(sin(dot(i2 + float2(0.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
float d2 = frac(sin(dot(i2 + float2(1.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
float n2 = lerp(lerp(a2, b2, u2.x), lerp(c2, d2, u2.x), u2.y);
float n = n1 * 0.65 + n2 * 0.35;
float2 fuv1 = frac(BaseUV);
float2 d1e = min(fuv1, 1.0 - fuv1);
float w1 = 1.0 - smoothstep(0.0, 0.11, min(d1e.x, d1e.y));
float2 fuv2 = frac(RotUV);
float2 d2e = min(fuv2, 1.0 - fuv2);
float w2 = 1.0 - smoothstep(0.0, 0.11, min(d2e.x, d2e.y));
float seamShield = clamp(w1 * (1.0 - w2 * 0.85) - w2 * (1.0 - w1 * 0.85), -1.0, 1.0);
float blendRaw = saturate((n - 0.5) * max(Contrast, 0.1) + 0.5);
float blendA = saturate(blendRaw + seamShield * 0.88) * en;
float ang = AntiTileRot * 6.2831853;
float s = sin(ang);
float c = cos(ang);
float3 n2Rot = float3(Nrm2.x * c + Nrm2.y * s, -Nrm2.x * s + Nrm2.y * c, Nrm2.z);
return normalize(lerp(Nrm1, n2Rot, blendA));
"""
    custom_at_nrm = _make_custom_hlsl_node(
        mel,
        mat,
        "AntiTileNormalBlend",
        unreal.CustomMaterialOutputType.CMOT_FLOAT3,
        ["Nrm1", "Nrm2", "BaseUV", "RotUV", "WorldPos", "UseTriplanar", "AntiTileEnable", "NoiseScale", "Contrast", "AntiTileRot"],
        hlsl_at_normal,
        -680,
        280,
    )
    _conn_expr(mel, tex_normal, "RGB", custom_at_nrm, "Nrm1")
    _conn_expr(mel, tex_nrm_at2, "RGB", custom_at_nrm, "Nrm2")
    _conn_expr(mel, uv_scaled, "", custom_at_nrm, "BaseUV")
    _conn_expr(mel, custom_at_uv2, "", custom_at_nrm, "RotUV")
    _conn_expr(mel, world_pos_trip, "", custom_at_nrm, "WorldPos")
    _conn_expr(mel, at_trip_p, "", custom_at_nrm, "UseTriplanar")
    _conn_expr(mel, at_en_p, "", custom_at_nrm, "AntiTileEnable")
    _conn_expr(mel, at_nscale_p, "", custom_at_nrm, "NoiseScale")
    _conn_expr(mel, at_con_p, "", custom_at_nrm, "Contrast")
    _conn_expr(mel, at_rot_p, "", custom_at_nrm, "AntiTileRot")

    nrm_str = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -840, 520)
    nrm_str.set_editor_property("parameter_name", "Normal_Strength")
    nrm_str.set_editor_property("group", "02 - Normal Map")
    nrm_str.set_editor_property("default_value", 1.0)

    nrm_z = mel.create_material_expression(mat, unreal.MaterialExpressionConstant, -840, 620)
    nrm_z.set_editor_property("r", 1.0)

    nrm_xy = mel.create_material_expression(mat, unreal.MaterialExpressionAppendVector, -620, 520)
    _conn_expr(mel, nrm_str, "", nrm_xy, "A")
    _conn_expr(mel, nrm_str, "", nrm_xy, "B")

    nrm_xyz = mel.create_material_expression(mat, unreal.MaterialExpressionAppendVector, -440, 520)
    _conn_expr(mel, nrm_xy, "", nrm_xyz, "A")
    _conn_expr(mel, nrm_z, "", nrm_xyz, "B")

    nrm_mul = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -240, 320)
    _conn_expr(mel, custom_at_nrm, "", nrm_mul, "A")
    _conn_expr(mel, nrm_xyz, "", nrm_mul, "B")

    # Custom Node 4: 3D Seam Bevel Normal + Per-Tile Normal Orientation (Independent SeamWidth H & V + uneven SeamEdgeIrreg borders)
    hlsl_seam_normal = """
float en = saturate(SeamsEnable);
if (en < 0.001) return BaseNormal;
float tx = max(TilesX, 0.001);
float ty = max(TilesY, 0.001);
float row = floor(BaseUV.y * ty);
float rowHash = frac(sin(row * 127.1 + 311.7) * 43758.5453);
float shift = row * RowShiftOrder + (rowHash - 0.5) * RowShiftRandom;
float2 grid = float2(BaseUV.x * tx + shift, BaseUV.y * ty);
float2 cell = floor(grid);
float2 local = frac(grid);
float h3 = frac(sin(dot(cell, float2(419.2, 371.9))) * 43758.5453);
float3 n = BaseNormal;
if (TileRandRot > 0.2 && h3 > 0.5) n.x = -n.x;
if (TileRandRot > 0.5 && frac(h3 * 3.71) > 0.5) n.y = -n.y;
if (TileRandRot > 0.8 && frac(h3 * 7.13) > 0.5) n.xy = float2(-n.y, n.x);
float dx = min(local.x, 1.0 - local.x);
float dy = min(local.y, 1.0 - local.y);
float refScale = min(tx, ty);
float distX = dx * (refScale / tx);
float distY = dy * (refScale / ty);
float baseWH = max(SeamWidth, 0.0);
float baseWV = max(SeamWidthV, 0.0);
float halfWH = baseWH * 0.5;
float halfWV = baseWV * 0.5;
float2 irregBevelPerturb = float2(0.0, 0.0);
if (SeamEdgeIrreg > 0.0001)
{
    float nFreq = max(SeamNoiseScale, 0.1) * 7.5;
    float2 np1 = BaseUV * float2(tx, ty) * nFreq;
    float2 i1 = floor(np1);
    float2 f1 = frac(np1);
    float2 u1 = f1 * f1 * (3.0 - 2.0 * f1);
    float a1 = frac(sin(dot(i1, float2(127.1, 311.7))) * 43758.5453);
    float b1 = frac(sin(dot(i1 + float2(1.0, 0.0), float2(127.1, 311.7))) * 43758.5453);
    float c1 = frac(sin(dot(i1 + float2(0.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
    float d1 = frac(sin(dot(i1 + float2(1.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
    float nLow = lerp(lerp(a1, b1, u1.x), lerp(c1, d1, u1.x), u1.y) - 0.5;

    float2 np2 = np1 * 2.83 + float2(37.2, 19.8);
    float2 i2 = floor(np2);
    float2 f2 = frac(np2);
    float2 u2 = f2 * f2 * (3.0 - 2.0 * f2);
    float a2 = frac(sin(dot(i2, float2(269.5, 183.3))) * 43758.5453);
    float b2 = frac(sin(dot(i2 + float2(1.0, 0.0), float2(269.5, 183.3))) * 43758.5453);
    float c2 = frac(sin(dot(i2 + float2(0.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
    float d2 = frac(sin(dot(i2 + float2(1.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
    float nMid = lerp(lerp(a2, b2, u2.x), lerp(c2, d2, u2.x), u2.y) - 0.5;

    float2 np3 = np1 * 6.41 + float2(73.1, 53.9);
    float2 i3 = floor(np3);
    float2 f3 = frac(np3);
    float2 u3 = f3 * f3 * (3.0 - 2.0 * f3);
    float a3 = frac(sin(dot(i3, float2(419.2, 371.9))) * 43758.5453);
    float b3 = frac(sin(dot(i3 + float2(1.0, 0.0), float2(419.2, 371.9))) * 43758.5453);
    float c3 = frac(sin(dot(i3 + float2(0.0, 1.0), float2(419.2, 371.9))) * 43758.5453);
    float d3 = frac(sin(dot(i3 + float2(1.0, 1.0), float2(419.2, 371.9))) * 43758.5453);
    float nHi = lerp(lerp(a3, b3, u3.x), lerp(c3, d3, u3.x), u3.y) - 0.5;

    float sideX = (local.x < 0.5) ? 1.0 : -1.0;
    float sideY = (local.y < 0.5) ? 1.0 : -1.0;
    float edgeV = nLow * 0.45 + sideX * nMid * 0.40 + nHi * 0.35;
    float edgeH = nMid * 0.45 + sideY * nLow * 0.40 - nHi * 0.35;
    float ampV = max(baseWV * 1.65, 0.032) * SeamEdgeIrreg;
    float ampH = max(baseWH * 1.65, 0.032) * SeamEdgeIrreg;
    halfWV = max(0.0004, halfWV + edgeV * ampV);
    halfWH = max(0.0004, halfWH + edgeH * ampH);
    irregBevelPerturb = float2(edgeH, edgeV) * SeamEdgeIrreg * 0.65;
}
float soft = max(SeamSoftness, 0.001);
float sx = (baseWV > 0.0001) ? smoothstep(halfWV, halfWV + soft, distX) : 1.0;
float sy = (baseWH > 0.0001) ? smoothstep(halfWH, halfWH + soft, distY) : 1.0;
float bevelX = ((sx * (1.0 - sx) * 4.0) * (local.x < 0.5 ? -1.0 : 1.0) + (sx * (1.0 - sx) * 4.0) * irregBevelPerturb.x) * sy;
float bevelY = ((sy * (1.0 - sy) * 4.0) * (local.y < 0.5 ? -1.0 : 1.0) + (sy * (1.0 - sy) * 4.0) * irregBevelPerturb.y) * sx;
float2 bevelXY = float2(bevelX, bevelY) * SeamDepth * 1.8 * en;
return normalize(float3(n.xy + bevelXY, max(n.z, 0.25)));
"""
    custom_seam_nrm = _make_custom_hlsl_node(
        mel,
        mat,
        "SubstanceSeamBevelNormal",
        unreal.CustomMaterialOutputType.CMOT_FLOAT3,
        [
            "BaseNormal",
            "BaseUV",
            "SeamsEnable",
            "TilesX",
            "TilesY",
            "RowShiftOrder",
            "RowShiftRandom",
            "SeamWidth",
            "SeamWidthV",
            "SeamSoftness",
            "SeamEdgeIrreg",
            "SeamNoiseScale",
            "SeamDepth",
            "TileRandRot",
        ],
        hlsl_seam_normal,
        120,
        320,
    )
    _conn_expr(mel, nrm_mul, "", custom_seam_nrm, "BaseNormal")
    _conn_expr(mel, custom_seams_grid_uv, "", custom_seam_nrm, "BaseUV")
    _conn_expr(mel, seams_enable_p, "", custom_seam_nrm, "SeamsEnable")
    _conn_expr(mel, tiles_x_p, "", custom_seam_nrm, "TilesX")
    _conn_expr(mel, tiles_y_p, "", custom_seam_nrm, "TilesY")
    _conn_expr(mel, row_order_p, "", custom_seam_nrm, "RowShiftOrder")
    _conn_expr(mel, row_rand_p, "", custom_seam_nrm, "RowShiftRandom")
    _conn_expr(mel, seam_width_p, "", custom_seam_nrm, "SeamWidth")
    _conn_expr(mel, seam_width_v_p, "", custom_seam_nrm, "SeamWidthV")
    _conn_expr(mel, seam_soft_p, "", custom_seam_nrm, "SeamSoftness")
    _conn_expr(mel, seam_irreg_p, "", custom_seam_nrm, "SeamEdgeIrreg")
    _conn_expr(mel, seam_nscale_p, "", custom_seam_nrm, "SeamNoiseScale")
    _conn_expr(mel, seam_depth_p, "", custom_seam_nrm, "SeamDepth")
    _conn_expr(mel, tile_rand_rot_p, "", custom_seam_nrm, "TileRandRot")

    seam_nrm_alpha = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 240, 260)
    _conn_expr(mel, custom_seam_mask, "", seam_nrm_alpha, "A")
    _conn_expr(mel, seam_mtl_blend_w, "", seam_nrm_alpha, "B")

    nrm_with_seam_mtl = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 300, 320)
    _conn_expr(mel, custom_seam_nrm, "", nrm_with_seam_mtl, "A")
    _conn_expr(mel, tex_seam_nrm, "RGB", nrm_with_seam_mtl, "B")
    _conn_expr(mel, seam_nrm_alpha, "", nrm_with_seam_mtl, "Alpha")

    nrm_with_layer_b = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 420, 320)
    _conn_expr(mel, nrm_with_seam_mtl, "", nrm_with_layer_b, "A")
    _conn_expr(mel, tex_nrm_b, "RGB", nrm_with_layer_b, "B")
    _conn_expr(mel, custom_layer_b_alpha, "", nrm_with_layer_b, "Alpha")

    cur_nrm_chain = nrm_with_layer_b
    for ex_n in extra_layer_nodes:
        next_nrm = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 420 + (ex_n["k"] - 1) * 140, 320)
        _conn_expr(mel, cur_nrm_chain, "", next_nrm, "A")
        _conn_expr(mel, ex_n["nrm"], "RGB", next_nrm, "B")
        _conn_expr(mel, ex_n["alpha"], "", next_nrm, "Alpha")
        cur_nrm_chain = next_nrm
    if not is_decal_mm:
        hlsl_t2w_safe = """
float3 tn = TangentNormal;
if (any(isnan(tn))) tn = float3(0.0, 0.0, 1.0);
tn = normalize(float3(tn.xy, max(tn.z, 0.05)));
float decLenSq = dot(DecodedWorldNrm, DecodedWorldNrm);
float vLenSq = dot(VertNrmWS, VertNrmWS);
float tLenSq = dot(Parameters.TangentToWorld[0], Parameters.TangentToWorld[0]);
float bLenSq = dot(Parameters.TangentToWorld[1], Parameters.TangentToWorld[1]);
float3 T, B, N;
if (decLenSq > 0.5) {
    N = normalize(DecodedWorldNrm);
    float3 up = abs(N.z) < 0.99 ? float3(0.0, 0.0, 1.0) : float3(0.0, 1.0, 0.0);
    T = normalize(cross(up, N));
    B = cross(N, T);
} else if (vLenSq > 0.05 && tLenSq > 0.05 && bLenSq > 0.05) {
    T = normalize(Parameters.TangentToWorld[0]);
    B = normalize(Parameters.TangentToWorld[1]);
    N = normalize(Parameters.TangentToWorld[2]);
} else {
    N = normalize(TransformLocalVectorToWorld(Parameters, float3(0.0, 0.0, 1.0)));
    float3 up = abs(N.z) < 0.99 ? float3(0.0, 0.0, 1.0) : float3(0.0, 1.0, 0.0);
    T = normalize(cross(up, N));
    B = cross(N, T);
}
float3 outN = normalize(T * tn.x + B * tn.y + N * tn.z);
return any(isnan(outN)) ? float3(0.0, 0.0, 1.0) : outN;
"""
        t2w_safe_node = _make_custom_hlsl_node(
            mel,
            mat,
            "TangentToWorldSafe",
            unreal.CustomMaterialOutputType.CMOT_FLOAT3,
            ["TangentNormal", "VertNrmWS", "DecodedWorldNrm"],
            hlsl_t2w_safe,
            980,
            320,
        )
        _conn_expr(mel, cur_nrm_chain, "", t2w_safe_node, "TangentNormal")
        _conn_expr(mel, vert_nrm, "", t2w_safe_node, "VertNrmWS")
        _conn_expr(mel, local_to_world_nrm, "", t2w_safe_node, "DecodedWorldNrm")
        mel.connect_material_property(t2w_safe_node, "", unreal.MaterialProperty.MP_NORMAL)
    else:
        mel.connect_material_property(cur_nrm_chain, "", unreal.MaterialProperty.MP_NORMAL)

    # === 3. Roughness Map + Anti-Tile Roughness Blend + Roughness_Strength + Seam_Roughness + Layer B & Layers 2..4 Roughness & Metallic ===
    tex_rough = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, -840, -20)
    tex_rough.set_editor_property("parameter_name", "RoughnessTexture")
    tex_rough.set_editor_property("group", "03 - Roughness & Surface")
    if default_rgh:
        tex_rough.set_editor_property("texture", default_rgh)
    tex_rough.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    tex_rough.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
    _conn_expr(mel, bump_offset, "", tex_rough, "UVs")

    hlsl_at_rough = """
float en = saturate(AntiTileEnable);
float mv = saturate(MacroVar);
if (en < 0.001 && mv < 0.001) return Rgh1;
float2 p = (UseTriplanar >= 0.5) ? ((WorldPos.xy + WorldPos.yz * 0.57) / 140.0) : (BaseUV * 1.35);
p *= max(NoiseScale, 0.01);
float2 i1 = floor(p);
float2 f1 = frac(p);
float2 u1 = f1 * f1 * (3.0 - 2.0 * f1);
float a1 = frac(sin(dot(i1, float2(127.1, 311.7))) * 43758.5453);
float b1 = frac(sin(dot(i1 + float2(1.0, 0.0), float2(127.1, 311.7))) * 43758.5453);
float c1 = frac(sin(dot(i1 + float2(0.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
float d1 = frac(sin(dot(i1 + float2(1.0, 1.0), float2(127.1, 311.7))) * 43758.5453);
float n1 = lerp(lerp(a1, b1, u1.x), lerp(c1, d1, u1.x), u1.y);
float2 p2 = p * 2.13 + float2(17.3, 9.2);
float2 i2 = floor(p2);
float2 f2 = frac(p2);
float2 u2 = f2 * f2 * (3.0 - 2.0 * f2);
float a2 = frac(sin(dot(i2, float2(269.5, 183.3))) * 43758.5453);
float b2 = frac(sin(dot(i2 + float2(1.0, 0.0), float2(269.5, 183.3))) * 43758.5453);
float c2 = frac(sin(dot(i2 + float2(0.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
float d2 = frac(sin(dot(i2 + float2(1.0, 1.0), float2(269.5, 183.3))) * 43758.5453);
float n2 = lerp(lerp(a2, b2, u2.x), lerp(c2, d2, u2.x), u2.y);
float n = n1 * 0.65 + n2 * 0.35;
float2 fuv1 = frac(BaseUV);
float2 d1e = min(fuv1, 1.0 - fuv1);
float w1 = 1.0 - smoothstep(0.0, 0.11, min(d1e.x, d1e.y));
float2 fuv2 = frac(RotUV);
float2 d2e = min(fuv2, 1.0 - fuv2);
float w2 = 1.0 - smoothstep(0.0, 0.11, min(d2e.x, d2e.y));
float seamShield = clamp(w1 * (1.0 - w2 * 0.85) - w2 * (1.0 - w1 * 0.85), -1.0, 1.0);
float blendRaw = saturate((n - 0.5) * max(Contrast, 0.1) + 0.5);
float blendA = saturate(blendRaw + seamShield * 0.88) * en;
float rMix = lerp(Rgh1, Rgh2, blendA);
return saturate(rMix + (0.5 - n) * 0.14 * mv);
"""
    custom_at_rgh = _make_custom_hlsl_node(
        mel,
        mat,
        "AntiTileRoughnessBlend",
        unreal.CustomMaterialOutputType.CMOT_FLOAT1,
        ["Rgh1", "Rgh2", "BaseUV", "RotUV", "WorldPos", "UseTriplanar", "AntiTileEnable", "MacroVar", "NoiseScale", "Contrast"],
        hlsl_at_rough,
        -680,
        -40,
    )
    _conn_expr(mel, tex_rough, "R", custom_at_rgh, "Rgh1")
    _conn_expr(mel, tex_rgh_at2, "R", custom_at_rgh, "Rgh2")
    _conn_expr(mel, uv_scaled, "", custom_at_rgh, "BaseUV")
    _conn_expr(mel, custom_at_uv2, "", custom_at_rgh, "RotUV")
    _conn_expr(mel, world_pos_trip, "", custom_at_rgh, "WorldPos")
    _conn_expr(mel, at_trip_p, "", custom_at_rgh, "UseTriplanar")
    _conn_expr(mel, at_en_p, "", custom_at_rgh, "AntiTileEnable")
    _conn_expr(mel, at_mvar_p, "", custom_at_rgh, "MacroVar")
    _conn_expr(mel, at_nscale_p, "", custom_at_rgh, "NoiseScale")
    _conn_expr(mel, at_con_p, "", custom_at_rgh, "Contrast")

    rgh_str = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -600, 120)
    rgh_str.set_editor_property("parameter_name", "Roughness_Strength")
    rgh_str.set_editor_property("group", "03 - Roughness & Surface")
    rgh_str.set_editor_property("default_value", 1.0)

    rgh_base = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -600, 20)
    rgh_base.set_editor_property("parameter_name", "Roughness_Base")
    rgh_base.set_editor_property("group", "03 - Roughness & Surface")
    rgh_base.set_editor_property("default_value", 0.5)

    rgh_mul = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, -400, -20)
    _conn_expr(mel, custom_at_rgh, "", rgh_mul, "A")
    _conn_expr(mel, rgh_str, "", rgh_mul, "B")

    rgh_lerp = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -200, 20)
    _conn_expr(mel, rgh_base, "", rgh_lerp, "A")
    _conn_expr(mel, rgh_mul, "", rgh_lerp, "B")
    _conn_expr(mel, rgh_str, "", rgh_lerp, "Alpha")

    seam_eff_rgh = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -80, 80)
    _conn_expr(mel, seam_rough_p, "", seam_eff_rgh, "A")
    _conn_expr(mel, rgh_seam_scaled, "", seam_eff_rgh, "B")
    _conn_expr(mel, seam_mtl_blend_w, "", seam_eff_rgh, "Alpha")

    rgh_with_seams = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 0, 20)
    _conn_expr(mel, rgh_lerp, "", rgh_with_seams, "A")
    _conn_expr(mel, seam_eff_rgh, "", rgh_with_seams, "B")
    _conn_expr(mel, custom_seam_mask, "", rgh_with_seams, "Alpha")

    rgh_with_layer_b = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 180, 20)
    _conn_expr(mel, rgh_with_seams, "", rgh_with_layer_b, "A")
    _conn_expr(mel, rgh_b_scaled, "", rgh_with_layer_b, "B")
    _conn_expr(mel, custom_layer_b_alpha, "", rgh_with_layer_b, "Alpha")

    cur_rgh_chain = rgh_with_layer_b
    for ex_n in extra_layer_nodes:
        next_rgh = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 180 + (ex_n["k"] - 1) * 140, 20)
        _conn_expr(mel, cur_rgh_chain, "", next_rgh, "A")
        _conn_expr(mel, ex_n["rgh"], "", next_rgh, "B")
        _conn_expr(mel, ex_n["alpha"], "", next_rgh, "Alpha")
        cur_rgh_chain = next_rgh

    rgh_clamp = _make_clamp_expr(mel, mat, cur_rgh_chain, "", 0.0, 1.0, 740, 20)
    mel.connect_material_property(rgh_clamp, "", unreal.MaterialProperty.MP_ROUGHNESS)

    metallic_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 180, 140)
    metallic_p.set_editor_property("parameter_name", "Metallic_Strength")
    metallic_p.set_editor_property("group", "03 - Roughness & Surface")
    metallic_p.set_editor_property("default_value", 0.0)

    met_with_seams = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 260, 140)
    _conn_expr(mel, metallic_p, "", met_with_seams, "A")
    _conn_expr(mel, seam_met_p, "", met_with_seams, "B")
    _conn_expr(mel, seam_nrm_alpha, "", met_with_seams, "Alpha")

    met_with_layer_b = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 360, 140)
    _conn_expr(mel, met_with_seams, "", met_with_layer_b, "A")
    _conn_expr(mel, layer_b_met_p, "", met_with_layer_b, "B")
    _conn_expr(mel, custom_layer_b_alpha, "", met_with_layer_b, "Alpha")

    cur_met_chain = met_with_layer_b
    for ex_n in extra_layer_nodes:
        next_met = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 360 + (ex_n["k"] - 1) * 140, 140)
        _conn_expr(mel, cur_met_chain, "", next_met, "A")
        _conn_expr(mel, ex_n["met"], "", next_met, "B")
        _conn_expr(mel, ex_n["alpha"], "", next_met, "Alpha")
        cur_met_chain = next_met
    mel.connect_material_property(cur_met_chain, "", unreal.MaterialProperty.MP_METALLIC)

    specular_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 180, 240)
    specular_p.set_editor_property("parameter_name", "Glass_Specular" if is_glass_mm else "Specular_Strength")
    specular_p.set_editor_property("group", "00 - Corona Glass Parameters" if is_glass_mm else "03 - Roughness & Surface")
    specular_p.set_editor_property("default_value", 1.0 if is_glass_mm else 0.5)
    mel.connect_material_property(specular_p, "", unreal.MaterialProperty.MP_SPECULAR)

    if is_glass_mm:
        grp_glass = "00 - Corona Glass Parameters"
        rgh_base.set_editor_property("parameter_name", "Glass_Roughness")
        rgh_base.set_editor_property("group", grp_glass)
        rgh_base.set_editor_property("default_value", 0.015)
        rgh_str.set_editor_property("default_value", 0.15)
        nrm_str.set_editor_property("default_value", 0.25)
        metallic_p.set_editor_property("parameter_name", "Glass_Metallic")
        metallic_p.set_editor_property("group", grp_glass)

        opac_base = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 560)
        opac_base.set_editor_property("parameter_name", "Glass_Opacity")
        opac_base.set_editor_property("group", grp_glass)
        opac_base.set_editor_property("default_value", 0.06)

        opac_fres = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 660)
        opac_fres.set_editor_property("parameter_name", "Glass_Fresnel_Opacity")
        opac_fres.set_editor_property("group", grp_glass)
        opac_fres.set_editor_property("default_value", 0.45)

        fres_exp = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 760)
        fres_exp.set_editor_property("parameter_name", "Glass_Fresnel_Exponent")
        fres_exp.set_editor_property("group", grp_glass)
        fres_exp.set_editor_property("default_value", 4.5)

        fresnel_g = mel.create_material_expression(mat, unreal.MaterialExpressionFresnel, 640, 700)
        _conn_expr(mel, fres_exp, "", fresnel_g, "ExponentIn")
        _conn_expr(mel, cur_nrm_chain, "", fresnel_g, "Normal")

        glass_opac_lerp = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 840, 620)
        _conn_expr(mel, opac_base, "", glass_opac_lerp, "A")
        _conn_expr(mel, opac_fres, "", glass_opac_lerp, "B")
        _conn_expr(mel, fresnel_g, "", glass_opac_lerp, "Alpha")

        # Wherever Seams or Overlay Layers 1..4 are active, Opacity transitions to Layer{k}_Opacity (1.0 for solid PBR, translucent for Glass layers)
        cur_opac_chain = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 980, 620)
        cur_opac_chain.set_editor_property("const_b", 1.0)
        _conn_expr(mel, glass_opac_lerp, "", cur_opac_chain, "A")
        _conn_expr(mel, custom_seam_mask, "", cur_opac_chain, "Alpha")

        lb_opac_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 980, 740)
        lb_opac_p.set_editor_property("parameter_name", "LayerB_Opacity")
        lb_opac_p.set_editor_property("group", grp_layer_b)
        lb_opac_p.set_editor_property("default_value", 1.0)

        opac_with_lb = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 1120, 620)
        _conn_expr(mel, cur_opac_chain, "", opac_with_lb, "A")
        _conn_expr(mel, lb_opac_p, "", opac_with_lb, "B")
        _conn_expr(mel, custom_layer_b_alpha, "", opac_with_lb, "Alpha")
        cur_opac_chain = opac_with_lb

        for ex_n in extra_layer_nodes:
            ch_lbl_op = vcol_pin_for_slot.get(ex_n["k"], "G")
            lk_opac_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 1120 + (ex_n["k"] - 1) * 140, 740)
            lk_opac_p.set_editor_property("parameter_name", f"Layer{ex_n['k']}_Opacity")
            lk_opac_p.set_editor_property("group", f"0{5 + ex_n['k']} - Mesh Paint [{ch_lbl_op}] / Layer {ex_n['k']} (Overlay)")
            lk_opac_p.set_editor_property("default_value", 1.0)

            next_opac = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 1120 + (ex_n["k"] - 1) * 140, 620)
            _conn_expr(mel, cur_opac_chain, "", next_opac, "A")
            _conn_expr(mel, lk_opac_p, "", next_opac, "B")
            _conn_expr(mel, ex_n["alpha"], "", next_opac, "Alpha")
            cur_opac_chain = next_opac

        mel.connect_material_property(cur_opac_chain, "", unreal.MaterialProperty.MP_OPACITY)

        ior_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 640, 860)
        ior_p.set_editor_property("parameter_name", "Glass_IOR")
        ior_p.set_editor_property("group", grp_glass)
        ior_p.set_editor_property("default_value", 1.52)

        ior_fres_lerp = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 880, 840)
        ior_fres_lerp.set_editor_property("const_a", 1.0)
        _conn_expr(mel, ior_p, "", ior_fres_lerp, "B")
        _conn_expr(mel, fresnel_g, "", ior_fres_lerp, "Alpha")
        try:
            mel.connect_material_property(ior_fres_lerp, "", unreal.MaterialProperty.MP_REFRACTION)
        except Exception:
            pass

    is_foliage_mm = (mm_name == "MM_ArchViz_Foliage")
    if is_foliage_mm:
        mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
        try:
            mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
        except Exception:
            pass
        mat.set_editor_property("two_sided", True)
        try:
            mat.set_editor_property("opacity_mask_clip_value", 0.33)
        except Exception:
            pass

        grp_fol = "00 - Corona Foliage & Cutout"
        tex_opac_mask = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, 420, 620)
        tex_opac_mask.set_editor_property("parameter_name", "OpacityMaskTexture")
        tex_opac_mask.set_editor_property("group", grp_fol)
        if default_rgh:
            tex_opac_mask.set_editor_property("texture", default_rgh)
        tex_opac_mask.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        tex_opac_mask.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
        _conn_expr(mel, custom_tile_uv, "", tex_opac_mask, "UVs")

        use_opac_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 820)
        use_opac_p.set_editor_property("parameter_name", "Use_Opacity_Mask")
        use_opac_p.set_editor_property("group", grp_fol)
        use_opac_p.set_editor_property("default_value", 0.0)

        opac_mask_lerp = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, 700, 660)
        opac_mask_lerp.set_editor_property("const_a", 1.0)
        _conn_expr(mel, tex_opac_mask, "R", opac_mask_lerp, "B")
        _conn_expr(mel, use_opac_p, "", opac_mask_lerp, "Alpha")
        mel.connect_material_property(opac_mask_lerp, "", unreal.MaterialProperty.MP_OPACITY_MASK)

        sss_col_p = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, 700, -680)
        sss_col_p.set_editor_property("parameter_name", "Foliage_Subsurface_Color")
        sss_col_p.set_editor_property("group", grp_fol)
        sss_col_p.set_editor_property("default_value", unreal.LinearColor(0.45, 0.72, 0.18, 1.0))

        sss_str_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 700, -540)
        sss_str_p.set_editor_property("parameter_name", "Foliage_Subsurface_Strength")
        sss_str_p.set_editor_property("group", grp_fol)
        sss_str_p.set_editor_property("default_value", 0.55)

        sss_tinted = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 840, -580)
        _conn_expr(mel, alb_final, "", sss_tinted, "A")
        _conn_expr(mel, sss_col_p, "RGB", sss_tinted, "B")

        sss_mul = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 960, -520)
        _conn_expr(mel, sss_tinted, "", sss_mul, "A")
        _conn_expr(mel, sss_str_p, "", sss_mul, "B")
        mel.connect_material_property(sss_mul, "", unreal.MaterialProperty.MP_SUBSURFACE_COLOR)

    is_fabric_mm = (mm_name == "MM_ArchViz_Fabric")
    if is_fabric_mm:
        try:
            mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_SUBSURFACE)
        except Exception:
            pass
        grp_fab = "00 - Corona Fabric & Sheen"
        fab_col_p = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, 700, -660)
        fab_col_p.set_editor_property("parameter_name", "Fabric_Sheen_Color")
        fab_col_p.set_editor_property("group", grp_fab)
        fab_col_p.set_editor_property("default_value", unreal.LinearColor(0.85, 0.85, 0.88, 1.0))

        fab_amt_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 700, -520)
        fab_amt_p.set_editor_property("parameter_name", "Fabric_Sheen_Amount")
        fab_amt_p.set_editor_property("group", grp_fab)
        fab_amt_p.set_editor_property("default_value", 0.35)

        fab_sss = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 940, -560)
        _conn_expr(mel, fab_col_p, "RGB", fab_sss, "A")
        _conn_expr(mel, fab_amt_p, "", fab_sss, "B")
        mel.connect_material_property(fab_sss, "", unreal.MaterialProperty.MP_SUBSURFACE_COLOR)

    is_emissive_mm = (mm_name == "MM_ArchViz_Emissive")
    if is_emissive_mm:
        grp_emi = "00 - Corona Light / Emissive"
        emi_col_p = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, 700, -660)
        emi_col_p.set_editor_property("parameter_name", "Emissive_Color")
        emi_col_p.set_editor_property("group", grp_emi)
        emi_col_p.set_editor_property("default_value", unreal.LinearColor(1.0, 0.92, 0.80, 1.0))

        emi_int_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 700, -520)
        emi_int_p.set_editor_property("parameter_name", "Emissive_Intensity")
        emi_int_p.set_editor_property("group", grp_emi)
        emi_int_p.set_editor_property("default_value", 5.0)

        emi_tinted = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 860, -600)
        _conn_expr(mel, alb_final, "", emi_tinted, "A")
        _conn_expr(mel, emi_col_p, "RGB", emi_tinted, "B")

        emi_out = mel.create_material_expression(mat, unreal.MaterialExpressionMultiply, 980, -540)
        _conn_expr(mel, emi_tinted, "", emi_out, "A")
        _conn_expr(mel, emi_int_p, "", emi_out, "B")
        mel.connect_material_property(emi_out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    if is_decal_mm:
        mat.set_editor_property("material_domain", unreal.MaterialDomain.MD_DEFERRED_DECAL)
        mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
        try:
            mat.set_editor_property("decal_blend_mode", unreal.DecalBlendMode.DBM_TRANSLUCENT)
        except Exception:
            pass

        grp_decal = "00 - ArchViz Decal Parameters"
        dec_opac_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 620)
        dec_opac_p.set_editor_property("parameter_name", "Decal_Opacity")
        dec_opac_p.set_editor_property("group", grp_decal)
        dec_opac_p.set_editor_property("default_value", 1.0)

        dec_fade_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 700)
        dec_fade_p.set_editor_property("parameter_name", "Decal_Edge_Fade")
        dec_fade_p.set_editor_property("group", grp_decal)
        dec_fade_p.set_editor_property("default_value", 0.16)

        dec_use_opac_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 780)
        dec_use_opac_p.set_editor_property("parameter_name", "Use_Opacity_Mask")
        dec_use_opac_p.set_editor_property("group", grp_decal)
        dec_use_opac_p.set_editor_property("default_value", 0.0)

        tex_dec_opac = mel.create_material_expression(mat, unreal.MaterialExpressionTextureSampleParameter2D, 420, 860)
        tex_dec_opac.set_editor_property("parameter_name", "OpacityMaskTexture")
        tex_dec_opac.set_editor_property("group", grp_decal)
        if default_rgh:
            tex_dec_opac.set_editor_property("texture", default_rgh)
        tex_dec_opac.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        tex_dec_opac.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_WRAP_WORLD_GROUP_SETTINGS)
        _conn_expr(mel, custom_tile_uv, "", tex_dec_opac, "UVs")

        dec_auto_luma_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 1060)
        dec_auto_luma_p.set_editor_property("parameter_name", "Decal_Auto_Luma_Mask")
        dec_auto_luma_p.set_editor_property("group", grp_decal)
        dec_auto_luma_p.set_editor_property("default_value", 0.0)

        dec_luma_inv_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 1140)
        dec_luma_inv_p.set_editor_property("parameter_name", "Decal_Luma_Invert")
        dec_luma_inv_p.set_editor_property("group", grp_decal)
        dec_luma_inv_p.set_editor_property("default_value", 1.0)

        dec_mask_con_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 1220)
        dec_mask_con_p.set_editor_property("parameter_name", "Decal_Mask_Contrast")
        dec_mask_con_p.set_editor_property("group", grp_decal)
        dec_mask_con_p.set_editor_property("default_value", 2.2)

        dec_mask_bias_p = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, 420, 1300)
        dec_mask_bias_p.set_editor_property("parameter_name", "Decal_Mask_Bias")
        dec_mask_bias_p.set_editor_property("group", grp_decal)
        dec_mask_bias_p.set_editor_property("default_value", 0.0)

        hlsl_decal_opac = """
float2 uv01 = frac(RawUV);
float2 d = min(uv01, 1.0 - uv01);
float edgeDist = min(d.x, d.y);
float borderMask = (EdgeFade > 0.001) ? smoothstep(0.0, max(EdgeFade, 0.001), edgeDist) : 1.0;
float maskAlpha = 1.0;
if (UseOpacityTex >= 0.5)
{
    maskAlpha = OpacityTexVal;
}
else if (BlendMaskStr > 0.001 && LayerBEnable < 0.001)
{
    float mRaw = lerp(BlendMaskVal, 1.0 - BlendMaskVal, saturate(BlendMaskInv));
    maskAlpha = saturate((mRaw - 0.5) * max(MaskContrast, 0.1) + 0.5 + MaskBias);
}
if (AutoLumaMask > 0.001 && UseOpacityTex < 0.5)
{
    float lum = max(dot(BaseColorRGB, float3(0.299, 0.587, 0.114)), 0.0001);
    float lumSrgb = pow(lum, 0.4545);
    float rawL = lerp(lumSrgb, 1.0 - lumSrgb, saturate(LumaInvert));
    float thresh = 0.54 - MaskBias * 0.35;
    float width = clamp(0.22 / max(MaskContrast, 0.25), 0.015, 0.28);
    float lMask = smoothstep(thresh - width * 0.5, thresh + width * 0.5, rawL);
    maskAlpha *= lerp(1.0, lMask, saturate(AutoLumaMask));
}
float overAll = max(max(OverlayAlpha, Layer2Alpha), max(Layer3Alpha, Layer4Alpha));
maskAlpha = max(maskAlpha, saturate(overAll));
return saturate(DecalOpacity * borderMask * maskAlpha);
"""
        custom_dec_opac = _make_custom_hlsl_node(
            mel,
            mat,
            "ArchVizDecalOpacity",
            unreal.CustomMaterialOutputType.CMOT_FLOAT1,
            [
                "RawUV",
                "DecalOpacity",
                "EdgeFade",
                "UseOpacityTex",
                "OpacityTexVal",
                "BlendMaskVal",
                "BlendMaskStr",
                "BlendMaskInv",
                "LayerBEnable",
                "OverlayAlpha",
                "Layer2Alpha",
                "Layer3Alpha",
                "Layer4Alpha",
                "BaseColorRGB",
                "AutoLumaMask",
                "LumaInvert",
                "MaskContrast",
                "MaskBias",
            ],
            hlsl_decal_opac,
            780,
            720,
        )
        _conn_expr(mel, tex_coord, "", custom_dec_opac, "RawUV")
        _conn_expr(mel, dec_opac_p, "", custom_dec_opac, "DecalOpacity")
        _conn_expr(mel, dec_fade_p, "", custom_dec_opac, "EdgeFade")
        _conn_expr(mel, dec_use_opac_p, "", custom_dec_opac, "UseOpacityTex")
        _conn_expr(mel, tex_dec_opac, "R", custom_dec_opac, "OpacityTexVal")
        _conn_expr(mel, tex_blend_mask, "R", custom_dec_opac, "BlendMaskVal")
        _conn_expr(mel, blend_mask_str_p, "", custom_dec_opac, "BlendMaskStr")
        _conn_expr(mel, blend_mask_inv_p, "", custom_dec_opac, "BlendMaskInv")
        _conn_expr(mel, layer_b_en_p, "", custom_dec_opac, "LayerBEnable")
        _conn_expr(mel, custom_layer_b_alpha, "", custom_dec_opac, "OverlayAlpha")
        _conn_expr(mel, extra_layer_nodes[0]["alpha"], "", custom_dec_opac, "Layer2Alpha")
        _conn_expr(mel, extra_layer_nodes[1]["alpha"], "", custom_dec_opac, "Layer3Alpha")
        _conn_expr(mel, extra_layer_nodes[2]["alpha"], "", custom_dec_opac, "Layer4Alpha")
        _conn_expr(mel, alb_final, "", custom_dec_opac, "BaseColorRGB")
        _conn_expr(mel, dec_auto_luma_p, "", custom_dec_opac, "AutoLumaMask")
        _conn_expr(mel, dec_luma_inv_p, "", custom_dec_opac, "LumaInvert")
        _conn_expr(mel, dec_mask_con_p, "", custom_dec_opac, "MaskContrast")
        _conn_expr(mel, dec_mask_bias_p, "", custom_dec_opac, "MaskBias")
        mel.connect_material_property(custom_dec_opac, "", unreal.MaterialProperty.MP_OPACITY)
    else:
        custom_at_hgt = _make_custom_hlsl_node(
            mel,
            mat,
            "AntiTileHeightAOBlend",
            unreal.CustomMaterialOutputType.CMOT_FLOAT1,
            ["Rgh1", "Rgh2", "BaseUV", "RotUV", "WorldPos", "UseTriplanar", "AntiTileEnable", "MacroVar", "NoiseScale", "Contrast"],
            hlsl_at_rough,
            -420,
            560,
        )
        _conn_expr(mel, cur_hgt_chain, "", custom_at_hgt, "Rgh1")
        _conn_expr(mel, tex_hgt_at2, "R", custom_at_hgt, "Rgh2")
        _conn_expr(mel, uv_scaled, "", custom_at_hgt, "BaseUV")
        _conn_expr(mel, custom_at_uv2, "", custom_at_hgt, "RotUV")
        _conn_expr(mel, world_pos_trip, "", custom_at_hgt, "WorldPos")
        _conn_expr(mel, at_trip_p, "", custom_at_hgt, "UseTriplanar")
        _conn_expr(mel, at_en_p, "", custom_at_hgt, "AntiTileEnable")
        _conn_expr(mel, at_mvar_p, "", custom_at_hgt, "MacroVar")
        _conn_expr(mel, at_nscale_p, "", custom_at_hgt, "NoiseScale")
        _conn_expr(mel, at_con_p, "", custom_at_hgt, "Contrast")

        ao_str = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -400, 680)
        ao_str.set_editor_property("parameter_name", "Height_AO_Strength")
        ao_str.set_editor_property("group", "04 - Height Map")
        ao_str.set_editor_property("default_value", 0.35)

        ao_lerp = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -180, 620)
        ao_lerp.set_editor_property("const_a", 1.0)
        _conn_expr(mel, custom_at_hgt, "", ao_lerp, "B")
        _conn_expr(mel, ao_str, "", ao_lerp, "Alpha")
        mel.connect_material_property(ao_lerp, "", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)

    try:
        mat.set_editor_property("use_material_attributes", False)
    except Exception:
        pass

    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    builtins._COMFY_MASTER_MAT_PATH = mm_path

    # Обновляем все дочерние Material Instances в папке и подпапках, чтобы они сразу подхватили перекомпилированный Мастер-Материал
    try:
        for a_path in unreal.EditorAssetLibrary.list_assets(ue_folder, recursive=True):
            clean = a_path.split(".")[0]
            name = clean.split("/")[-1]
            if name.startswith("MI_"):
                mi_obj = unreal.EditorAssetLibrary.load_asset(clean)
                if mi_obj and isinstance(mi_obj, unreal.MaterialInstanceConstant):
                    if mi_obj.get_editor_property("parent") == mat:
                        mel.update_material_instance(mi_obj)
                        unreal.EditorAssetLibrary.save_loaded_asset(mi_obj)
    except Exception:
        pass

    return mat


def _prepare_pbr_textures(tex_map: dict) -> None:
    """Выставляет правильные цветовые профили (sRGB / Linear / TC_Normalmap) для импортированных карт."""
    t_albedo = tex_map.get("albedo")
    t_normal = tex_map.get("normal")
    t_rough = tex_map.get("roughness")
    t_height = tex_map.get("height")
    t_metal = tex_map.get("metallic")
    t_opacity = tex_map.get("opacity")
    has_opacity_cutout = bool(t_opacity)

    for tex_obj in (t_albedo, t_normal, t_rough, t_height, t_metal, t_opacity):
        if tex_obj and has_opacity_cutout:
            try:
                tex_obj.set_editor_property("address_x", unreal.TextureAddress.TA_CLAMP)
                tex_obj.set_editor_property("address_y", unreal.TextureAddress.TA_CLAMP)
            except Exception:
                pass

    if t_albedo:
        t_albedo.set_editor_property("srgb", True)
        unreal.EditorAssetLibrary.save_loaded_asset(t_albedo)
    if t_normal:
        t_normal.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
        t_normal.set_editor_property("srgb", False)
        unreal.EditorAssetLibrary.save_loaded_asset(t_normal)
    if t_rough:
        t_rough.set_editor_property("srgb", False)
        unreal.EditorAssetLibrary.save_loaded_asset(t_rough)
    if t_height:
        t_height.set_editor_property("srgb", False)
        unreal.EditorAssetLibrary.save_loaded_asset(t_height)
    if t_metal:
        t_metal.set_editor_property("srgb", False)
        unreal.EditorAssetLibrary.save_loaded_asset(t_metal)
    if t_opacity:
        t_opacity.set_editor_property("srgb", False)
        unreal.EditorAssetLibrary.save_loaded_asset(t_opacity)


def _get_selected_prompt_master_material_path(ue_folder: str = DEFAULT_UE_FOLDER) -> str:
    """Возвращает Мастер-Материал, выбранный в выпадающем списке блока Prompt (PromptMasterMatCombo)."""
    p_combo = getattr(builtins, "_COMFY_PROMPT_MM_COMBO", None)
    mm_map = getattr(builtins, "_COMFY_MM_MAP", {})
    if p_combo:
        try:
            sel = str(p_combo.get_selected_option() or "").strip()
            resolved = mm_map.get(sel, f"{DEFAULT_UE_FOLDER}/{sel}" if sel.startswith("MM_") else sel)
            if resolved and unreal.EditorAssetLibrary.does_asset_exist(resolved):
                asset_obj = unreal.EditorAssetLibrary.load_asset(resolved)
                if isinstance(asset_obj, unreal.Material):
                    builtins._COMFY_PROMPT_MASTER_MAT_PATH = resolved
                    builtins._COMFY_MASTER_MAT_PATH = resolved
                    return resolved
        except Exception:
            pass
    saved_p = getattr(builtins, "_COMFY_PROMPT_MASTER_MAT_PATH", None)
    if saved_p and unreal.EditorAssetLibrary.does_asset_exist(saved_p):
        return saved_p
    return _get_selected_master_material_path(ue_folder)


def _get_selected_master_material_path(ue_folder: str = DEFAULT_UE_FOLDER) -> str:
    """Возвращает путь к выбранному в интерфейсе Мастер-Материалу (или родителю выбранного MI_*)."""
    p_combo = getattr(builtins, "_COMFY_PROMPT_MM_COMBO", None)
    mm_map = getattr(builtins, "_COMFY_MM_MAP", {})
    if p_combo:
        try:
            sel_p = str(p_combo.get_selected_option() or "").strip()
            res_p = mm_map.get(sel_p, f"{DEFAULT_UE_FOLDER}/{sel_p}" if sel_p.startswith("MM_") else sel_p)
            if res_p and unreal.EditorAssetLibrary.does_asset_exist(res_p):
                obj_p = unreal.EditorAssetLibrary.load_asset(res_p)
                if isinstance(obj_p, unreal.Material):
                    builtins._COMFY_MASTER_MAT_PATH = res_p
                    return res_p
        except Exception:
            pass
    combo = getattr(builtins, "_COMFY_MASTER_COMBO", None)
    if combo:
        try:
            sel = str(combo.get_selected_option() or "").strip()
            resolved = mm_map.get(sel, sel)
            if resolved and unreal.EditorAssetLibrary.does_asset_exist(resolved):
                asset_obj = unreal.EditorAssetLibrary.load_asset(resolved)
                if isinstance(asset_obj, unreal.MaterialInstanceConstant):
                    parent_m = asset_obj.get_editor_property("parent")
                    if parent_m:
                        p_path = parent_m.get_path_name().split(".")[0]
                        builtins._COMFY_MASTER_MAT_PATH = p_path
                        return p_path
                elif isinstance(asset_obj, unreal.Material):
                    builtins._COMFY_MASTER_MAT_PATH = resolved
                    return resolved
        except Exception:
            pass
    saved = getattr(builtins, "_COMFY_MASTER_MAT_PATH", None)
    if saved:
        saved = mm_map.get(saved, saved)
        if unreal.EditorAssetLibrary.does_asset_exist(saved):
            asset_obj = unreal.EditorAssetLibrary.load_asset(saved)
            if isinstance(asset_obj, unreal.MaterialInstanceConstant):
                parent_m = asset_obj.get_editor_property("parent")
                if parent_m:
                    return parent_m.get_path_name().split(".")[0]
            return saved
    base_dir = _normalize_ue_folder(ue_folder)
    if base_dir.split("/")[-1] in MATERIAL_CATEGORIES or base_dir.split("/")[-1] == TEXTURES_SUBFOLDER:
        base_dir = "/".join(base_dir.split("/")[:-1]) or DEFAULT_UE_FOLDER
    mm_path = f"{base_dir}/{DEFAULT_MASTER_MAT_NAME}"
    if not unreal.EditorAssetLibrary.does_asset_exist(mm_path):
        create_or_update_master_material(base_dir, DEFAULT_MASTER_MAT_NAME)
    return mm_path


def _build_pbr_material_instance(
    ue_folder: str,
    instance_name: str,
    tex_map: dict,
    master_mat_path: str = "",
):
    """
    Создаёт или обновляет MaterialInstanceConstant (MI_<Name>) на базе выбранного Мастер-Материала
    и назначает в него сгенерированные текстуры (Albedo, Normal, Roughness, Height).
    """
    _prepare_pbr_textures(tex_map)
    if tex_map:
        builtins._COMFY_LAST_TEX_MAP = dict(tex_map)

    mm_path = (master_mat_path or "").strip() or _get_selected_master_material_path(ue_folder)
    master_mat = unreal.EditorAssetLibrary.load_asset(mm_path)
    mel = unreal.MaterialEditingLibrary
    if (
        not master_mat
        or mel.get_statistics(master_mat).num_pixel_shader_instructions == 0
        or (
            master_mat.get_name() == DEFAULT_MASTER_MAT_NAME
            and "Displacement_SCurve" not in [str(p) for p in mel.get_scalar_parameter_names(master_mat)]
        )
    ):
        master_mat = create_or_update_master_material(ue_folder, DEFAULT_MASTER_MAT_NAME)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

    mi_full_path = f"{ue_folder}/{instance_name}"
    if unreal.EditorAssetLibrary.does_asset_exist(mi_full_path):
        mi = unreal.EditorAssetLibrary.load_asset(mi_full_path)
    else:
        mi = asset_tools.create_asset(
            instance_name,
            ue_folder,
            unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew(),
        )

    mel.set_material_instance_parent(mi, master_mat)

    # Сопоставляем текстурные параметры выбранного Мастер-Материала (поддерживает и кастомные Мастер-Материалы)
    param_names = [str(p) for p in mel.get_texture_parameter_names(master_mat)]
    default_mapping = {
        "albedo": "AlbedoTexture",
        "normal": "NormalTexture",
        "roughness": "RoughnessTexture",
        "height": "HeightTexture",
        "opacity": "OpacityMaskTexture",
    }
    for kind, tex_obj in tex_map.items():
        if not tex_obj:
            continue
        target_param = default_mapping.get(kind, "")
        if target_param not in param_names:
            for p_name in param_names:
                low_p = p_name.lower()
                if kind == "albedo" and any(k in low_p for k in ("albedo", "basecolor", "base_color", "diffuse", "color")):
                    target_param = p_name
                    break
                elif kind == "normal" and "normal" in low_p:
                    target_param = p_name
                    break
                elif kind == "roughness" and "rough" in low_p:
                    target_param = p_name
                    break
                elif kind == "height" and any(k in low_p for k in ("height", "disp", "bump")):
                    target_param = p_name
                    break
                elif kind == "opacity" and any(k in low_p for k in ("opacity", "alpha", "mask")):
                    target_param = p_name
                    break
        if target_param:
            mel.set_material_instance_texture_parameter_value(
                mi,
                target_param,
                tex_obj,
                unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
            )

    if ue_folder.lower().split("/")[-1] in ("metal", "mirror"):
        try:
            low_n = instance_name.lower()
            if any(k in low_n for k in ("corten", "patina", "rust", "oxidized")):
                met_val, alb_b, rgh_s, rgh_b = 0.35, 1.15, 0.85, 0.65
            elif any(k in low_n for k in ("polished", "mirror", "chrome")):
                met_val, alb_b, rgh_s, rgh_b = 1.0, 1.75, 0.25, 0.08
            elif any(k in low_n for k in ("scratched", "worn", "pitted", "castiron", "sandcast", "forged", "hammered", "rolled")):
                met_val, alb_b, rgh_s, rgh_b = 0.92, 1.45, 0.70, 0.38
            else:
                met_val, alb_b, rgh_s, rgh_b = 1.0, 1.65, 0.45, 0.24
            mel.set_material_instance_scalar_parameter_value(
                mi, "Metallic_Strength", met_val, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            mel.set_material_instance_scalar_parameter_value(
                mi, "Albedo_Brightness", alb_b, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            mel.set_material_instance_scalar_parameter_value(
                mi, "Roughness_Strength", rgh_s, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            mel.set_material_instance_scalar_parameter_value(
                mi, "Roughness_Base", rgh_b, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
        except Exception:
            pass
    elif ue_folder.lower().split("/")[-1] == "glass" or "glass" in str(mm_path).lower():
        try:
            low_n = instance_name.lower()
            g_ior = 1.52
            g_tex_tint = 0.08
            if any(k in low_n for k in ("condens", "foggy", "fogged", "steam", "breath", "wiped")):
                g_col = unreal.LinearColor(0.12, 0.17, 0.20, 1.0)
                g_opac, g_fres, g_rgh, nrm_s, rgh_s = 0.18, 0.58, 0.22, 0.30, 0.45
                g_tex_tint = 0.24
                g_ior = 1.50
            elif any(k in low_n for k in ("droplet", "rain", "rivulet", "dew", "shower", "streak")):
                g_col = unreal.LinearColor(0.04, 0.08, 0.11, 1.0)
                g_opac, g_fres, g_rgh, nrm_s, rgh_s = 0.08, 0.50, 0.02, 0.85, 0.35
                g_tex_tint = 0.12
                g_ior = 1.52
            elif any(k in low_n for k in ("ice", "frost", "rime", "hoarfrost", "glaze", "frozen", "fern", "blizzard")):
                g_col = unreal.LinearColor(0.15, 0.24, 0.30, 1.0)
                g_opac, g_fres, g_rgh, nrm_s, rgh_s = 0.26, 0.68, 0.20, 0.75, 0.50
                g_tex_tint = 0.38
                g_ior = 1.31
            elif any(k in low_n for k in ("frosted", "acid", "sandblast", "matte")):
                g_col = unreal.LinearColor(0.08, 0.14, 0.17, 1.0)
                g_opac, g_fres, g_rgh, nrm_s, rgh_s = 0.14, 0.55, 0.16, 0.30, 0.35
                g_tex_tint = 0.15
            elif any(k in low_n for k in ("ribbed", "fluted", "reeded", "hammered", "wave", "rippled")):
                g_col = unreal.LinearColor(0.04, 0.08, 0.10, 1.0)
                g_opac, g_fres, g_rgh, nrm_s, rgh_s = 0.07, 0.48, 0.03, 0.65, 0.20
            elif any(k in low_n for k in ("smoked", "dark", "tinted", "bronze", "anthracite")):
                g_col = unreal.LinearColor(0.02, 0.03, 0.04, 1.0)
                g_opac, g_fres, g_rgh, nrm_s, rgh_s = 0.22, 0.60, 0.015, 0.15, 0.10
            else:
                g_col = unreal.LinearColor(0.04, 0.08, 0.10, 1.0)
                g_opac, g_fres, g_rgh, nrm_s, rgh_s = 0.06, 0.45, 0.015, 0.20, 0.10
            mel.set_material_instance_vector_parameter_value(
                mi, "Glass_Color", g_col, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            for k_p, v_p in (
                ("Glass_Opacity", g_opac),
                ("Glass_Fresnel_Opacity", g_fres),
                ("Glass_Roughness", g_rgh),
                ("Glass_Texture_Tint_Amount", g_tex_tint),
                ("Glass_Specular", 1.0),
                ("Glass_IOR", g_ior),
                ("Normal_Strength", nrm_s),
                ("Roughness_Strength", rgh_s),
            ):
                mel.set_material_instance_scalar_parameter_value(
                    mi, k_p, v_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
        except Exception:
            pass
    elif ue_folder.lower().split("/")[-1] == "plastic":
        try:
            low_n = instance_name.lower()
            met_val, alb_b, rgh_s, rgh_b, spec_s, nrm_s = 0.0, 1.0, 0.45, 0.40, 0.55, 0.45
            if any(k in low_n for k in ("epoxy", "resin", "swirl", "pearl", "amber", "acrylic", "pmma", "polycarbonate", "lexan")):
                if any(k in low_n for k in ("pearl", "swirl", "gold", "emerald", "turquoise", "cobalt")):
                    met_val, alb_b, rgh_s, rgh_b, spec_s, nrm_s = 0.28, 1.18, 0.20, 0.06, 0.90, 0.25
                elif any(k in low_n for k in ("quartz", "flake", "terrazzo", "frosted", "sla")):
                    met_val, alb_b, rgh_s, rgh_b, spec_s, nrm_s = 0.04, 1.05, 0.40, 0.22, 0.72, 0.55
                else:
                    met_val, alb_b, rgh_s, rgh_b, spec_s, nrm_s = 0.02, 1.08, 0.16, 0.05, 0.88, 0.20
            elif any(k in low_n for k in ("carbon", "kevlar", "aramid", "fiberglass", "fr4", "g10", "garolite", "micarta", "forged")):
                if "matte" in low_n or "plain" in low_n or "micarta" in low_n or "g10" in low_n:
                    met_val, alb_b, rgh_s, rgh_b, spec_s, nrm_s = 0.16, 1.10, 0.50, 0.36, 0.62, 0.75
                else:
                    met_val, alb_b, rgh_s, rgh_b, spec_s, nrm_s = 0.22, 1.15, 0.32, 0.12, 0.85, 0.68
            elif any(k in low_n for k in ("rubber", "silicone", "neoprene", "epdm", "foam", "eva", "polystyrene", "eps")):
                met_val, alb_b, rgh_s, rgh_b, spec_s, nrm_s = 0.0, 1.0, 0.65, 0.76, 0.30, 0.65
            elif any(k in low_n for k in ("glossy", "gloss", "ptfe", "teflon", "delrin", "pom")):
                met_val, alb_b, rgh_s, rgh_b, spec_s, nrm_s = 0.0, 1.05, 0.22, 0.12, 0.75, 0.25
            for k_p, v_p in (
                ("Metallic_Strength", met_val),
                ("Albedo_Brightness", alb_b),
                ("Roughness_Strength", rgh_s),
                ("Roughness_Base", rgh_b),
                ("Specular_Strength", spec_s),
                ("Normal_Strength", nrm_s),
            ):
                mel.set_material_instance_scalar_parameter_value(
                    mi, k_p, v_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
        except Exception:
            pass
    elif ue_folder.lower().split("/")[-1] == "wood":
        try:
            low_n = instance_name.lower()
            rgh_s, rgh_b, spec_s, nrm_s = 0.45, 0.35, 0.52, 0.45
            if any(k in low_n for k in ("chipboard", "particleboard", "dsp", "mdf", "dvp", "hardboard", "pegboard", "cork", "csp", "woodwool", "barnwood", "roughsawn")):
                rgh_s, rgh_b, spec_s, nrm_s = 0.65, 0.72, 0.32, 0.62
            elif any(k in low_n for k in ("osb", "plywood", "glulam", "clt", "layered", "multi")):
                rgh_s, rgh_b, spec_s, nrm_s = 0.55, 0.50, 0.45, 0.60
            elif any(k in low_n for k in ("rings", "cross", "stump", "endgrain", "butcher", "hexagon", "charred", "shousugiban", "brushed", "bark")):
                rgh_s, rgh_b, spec_s, nrm_s = 0.65, 0.58, 0.42, 0.82
            elif any(k in low_n for k in ("slab", "burl", "olive", "epoxy", "rosewood", "ebony", "mahogany", "teak", "walnut")):
                rgh_s, rgh_b, spec_s, nrm_s = 0.38, 0.22, 0.68, 0.50
            for k_p, v_p in (
                ("Roughness_Strength", rgh_s),
                ("Roughness_Base", rgh_b),
                ("Specular_Strength", spec_s),
                ("Normal_Strength", nrm_s),
            ):
                mel.set_material_instance_scalar_parameter_value(
                    mi, k_p, v_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
        except Exception:
            pass
    elif ue_folder.lower().split("/")[-1] == "foliage" or "foliage" in str(mm_path).lower():
        try:
            low_n = instance_name.lower()
            has_opac_tex = bool(tex_map.get("opacity"))
            use_opac = 1.0 if (has_opac_tex or any(k in low_n for k in ("singleisolated", "singleleaf", "cutout"))) else 0.0
            if use_opac >= 0.5:
                sss_val, rgh_s, rgh_b, spec_s, nrm_s = 0.65, 0.45, 0.36, 0.55, 0.60
            elif any(k in low_n for k in ("soil", "mulch", "loam", "humus", "clay", "mud", "peat", "litter", "woodchip", "bark", "cocoa", "perlite", "earth")):
                sss_val, rgh_s, rgh_b, spec_s, nrm_s = 0.0, 0.72, 0.84, 0.24, 0.85
            else:
                sss_val, rgh_s, rgh_b, spec_s, nrm_s = 0.50, 0.50, 0.48, 0.45, 0.65
            for k_p, v_p in (
                ("Use_Opacity_Mask", use_opac),
                ("Foliage_Subsurface_Strength", sss_val),
                ("Roughness_Strength", rgh_s),
                ("Roughness_Base", rgh_b),
                ("Specular_Strength", spec_s),
                ("Normal_Strength", nrm_s),
            ):
                mel.set_material_instance_scalar_parameter_value(
                    mi, k_p, v_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
        except Exception:
            pass
    elif ue_folder.lower().split("/")[-1] == "decal" or "decal" in str(mm_path).lower():
        try:
            low_n = instance_name.lower()
            has_opac_tex = bool(tex_map.get("opacity"))
            use_opac = 1.0 if has_opac_tex else 0.0
            auto_luma = 0.0 if has_opac_tex else 1.0
            luma_inv = 0.0 if any(k in low_n for k in ("stripe", "white", "marking", "arrow", "line", "chalk")) else 1.0
            rgh_b = 0.06 if any(k in low_n for k in ("puddle", "wet", "water", "oil", "leak")) else 0.62
            for k_p, v_p in (
                ("Decal_Opacity", 1.0),
                ("Decal_Edge_Fade", 0.18),
                ("Use_Opacity_Mask", use_opac),
                ("Decal_Auto_Luma_Mask", auto_luma),
                ("Decal_Luma_Invert", luma_inv),
                ("Decal_Mask_Contrast", 2.4),
                ("Decal_Mask_Bias", 0.0),
                ("Roughness_Base", rgh_b),
                ("Roughness_Strength", 0.55),
                ("Normal_Strength", 0.90),
            ):
                mel.set_material_instance_scalar_parameter_value(
                    mi, k_p, v_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
        except Exception:
            pass
    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    builtins._COMFY_LAST_MATERIAL = mi
    return mi


def combine_material_into_layer_slot(
    target_mi,
    source_mi,
    slot_idx: int = 1,
    enable_seams: bool = False,
    update_and_save: bool = False,
) -> bool:
    """
    Copies the 4 PBR textures (Albedo, Normal, Roughness, Height) and surface scalar/vector parameters
    (Metallic, Roughness_Strength, UV_Tiling, Albedo_ColorTint * Albedo_Brightness) from source_mi into
    hardware layer slot `slot_idx` (0 = Seam_*, 1 = LayerB_*, 2..4 = Layer2_*..Layer4_*) of target_mi.
    """
    if not target_mi or not source_mi:
        return False
    mel = unreal.MaterialEditingLibrary
    if slot_idx == 0:
        pfx = "Seam"
        en_param = "Seam_Mtl_Enable"
    elif slot_idx == 1:
        pfx = "LayerB"
        en_param = "LayerB_Enable"
    else:
        pfx = f"Layer{slot_idx}"
        en_param = f"Layer{slot_idx}_Enable"
    pair_map = (
        ("AlbedoTexture", f"{pfx}_AlbedoTexture"),
        ("NormalTexture", f"{pfx}_NormalTexture"),
        ("RoughnessTexture", f"{pfx}_RoughnessTexture"),
        ("HeightTexture", f"{pfx}_HeightTexture"),
    )
    copied = 0
    for src_param, dst_param in pair_map:
        try:
            tex = mel.get_material_instance_texture_parameter_value(
                source_mi,
                src_param,
                unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
            )
            if tex:
                mel.set_material_instance_texture_parameter_value(
                    target_mi,
                    dst_param,
                    tex,
                    unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
                )
                copied += 1
        except Exception:
            pass

    if copied > 0:
        is_src_glass = False
        try:
            src_parent = source_mi.get_editor_property("parent")
            if src_parent and "glass" in str(src_parent.get_path_name()).lower():
                is_src_glass = True
        except Exception:
            pass
        try:
            src_met = float(
                mel.get_material_instance_scalar_parameter_value(
                    source_mi,
                    "Glass_Metallic" if is_src_glass else "Metallic_Strength",
                    unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
                )
            )
            mel.set_material_instance_scalar_parameter_value(
                target_mi, f"{pfx}_Metallic", max(0.0, min(1.0, src_met)), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
        except Exception:
            pass
        try:
            src_rgh = float(
                mel.get_material_instance_scalar_parameter_value(
                    source_mi, "Roughness_Strength", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            )
            mel.set_material_instance_scalar_parameter_value(
                target_mi, f"{pfx}_Roughness_Mult", src_rgh if src_rgh > 0.0 else 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
        except Exception:
            pass
        try:
            src_til = float(
                mel.get_material_instance_scalar_parameter_value(
                    source_mi, "UV_Tiling", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            )
            mel.set_material_instance_scalar_parameter_value(
                target_mi, f"{pfx}_UV_Tiling", src_til if src_til > 0.0 else 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
        except Exception:
            pass
        if slot_idx >= 1:
            try:
                if is_src_glass:
                    src_fres = float(
                        mel.get_material_instance_scalar_parameter_value(
                            source_mi, "Glass_Fresnel_Opacity", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                    )
                    layer_opac = max(0.22, min(0.88, src_fres if src_fres > 0.0 else 0.55))
                else:
                    layer_opac = 1.0
                mel.set_material_instance_scalar_parameter_value(
                    target_mi, f"{pfx}_Opacity", layer_opac, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            except Exception:
                pass
        try:
            src_bri = float(
                mel.get_material_instance_scalar_parameter_value(
                    source_mi, "Albedo_Brightness", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            )
            if src_bri <= 0.0:
                src_bri = 1.0
            src_tint = mel.get_material_instance_vector_parameter_value(
                source_mi, "Albedo_ColorTint", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            r_c = (src_tint.r if src_tint else 1.0) * src_bri
            g_c = (src_tint.g if src_tint else 1.0) * src_bri
            b_c = (src_tint.b if src_tint else 1.0) * src_bri
            mel.set_material_instance_vector_parameter_value(
                target_mi,
                f"{pfx}_ColorTint",
                unreal.LinearColor(r_c, g_c, b_c, 1.0),
                unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
            )
        except Exception:
            pass

        mel.set_material_instance_scalar_parameter_value(
            target_mi,
            en_param,
            1.0,
            unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
        )
        if enable_seams and slot_idx <= 1:
            mel.set_material_instance_scalar_parameter_value(
                target_mi,
                "Seams_Enable",
                1.0,
                unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
            )
        if update_and_save:
            mel.update_material_instance(target_mi)
            unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
        return True
    return False


def combine_material_into_layer_b(target_mi, source_mi, enable_seams: bool = True) -> bool:
    """
    Copies the 4 PBR textures (Albedo, Normal, Roughness, Height) and surface properties from source_mi
    into LayerB_* parameters of target_mi and enables LayerB_Enable = 1.0.
    """
    return combine_material_into_layer_slot(
        target_mi, source_mi, slot_idx=1, enable_seams=enable_seams, update_and_save=True
    )


SUBSTANCE_AND_BLEND_DEFAULTS = {
    "Seams_Enable": 0.0,
    "Seams_Triplanar": 0.0,
    "Tiles_Count_X": 4.0,
    "Tiles_Count_Y": 4.0,
    "Row_Shift_Order": 0.5,
    "Row_Shift_Random": 0.0,
    "Seam_Width": 0.04,
    "Seam_Width_V": 0.04,
    "Seam_Bevel_Softness": 0.03,
    "Seam_Depth": 1.0,
    "Seam_Line_Waviness": 0.0,
    "Seam_Edge_Irregularity": 0.0,
    "Seam_Noise_Scale": 1.0,
    "Seam_Mtl_Enable": 0.0,
    "Seam_UV_Tiling": 1.0,
    "Tile_Random_UV_Offset": 1.0,
    "Tile_Random_Flip_Rotate": 0.5,
    "Tile_Random_Luminance": 0.10,
    "LayerB_Enable": 0.0,
    "LayerB_Use_Mask": 1.0,
    "LayerB_UV_Tiling": 1.0,
    "LayerB_Tiling_X": 1.0,
    "LayerB_Tiling_Y": 1.0,
    "Blend_In_Seams": 1.0,
    "Blend_Checkerboard_Tiles": 0.0,
    "Blend_Random_Tiles": 0.0,
    "Blend_Mask_Strength": 0.0,
    "Blend_Mask_Tiling_X": 1.0,
    "Blend_Mask_Tiling_Y": 1.0,
    "Blend_Mask_Brightness": 0.0,
    "Blend_Mask_Contrast": 1.0,
    "Blend_Mask_Invert": 0.0,
    "Blend_Mask_Triplanar": 0.0,
    "Blend_Height_Sharpness": 0.5,
    "Layer2_Enable": 0.0,
    "Layer2_Use_Mask": 1.0,
    "Layer2_UV_Tiling": 1.0,
    "Layer2_Tiling_X": 1.0,
    "Layer2_Tiling_Y": 1.0,
    "Layer2_Random_Tiles": 0.0,
    "Layer2_Mask_Strength": 0.0,
    "Layer2_Mask_Tiling_X": 1.0,
    "Layer2_Mask_Tiling_Y": 1.0,
    "Layer2_Mask_Brightness": 0.0,
    "Layer2_Mask_Contrast": 1.0,
    "Layer2_Mask_Invert": 0.0,
    "Layer2_Mask_Triplanar": 0.0,
    "Layer3_Enable": 0.0,
    "Layer3_Use_Mask": 1.0,
    "Layer3_UV_Tiling": 1.0,
    "Layer3_Tiling_X": 1.0,
    "Layer3_Tiling_Y": 1.0,
    "Layer3_Random_Tiles": 0.0,
    "Layer3_Mask_Strength": 0.0,
    "Layer3_Mask_Tiling_X": 1.0,
    "Layer3_Mask_Tiling_Y": 1.0,
    "Layer3_Mask_Brightness": 0.0,
    "Layer3_Mask_Contrast": 1.0,
    "Layer3_Mask_Invert": 0.0,
    "Layer3_Mask_Triplanar": 0.0,
    "Layer4_Enable": 0.0,
    "Layer4_Use_Mask": 1.0,
    "Layer4_UV_Tiling": 1.0,
    "Layer4_Tiling_X": 1.0,
    "Layer4_Tiling_Y": 1.0,
    "Layer4_Random_Tiles": 0.0,
    "Layer4_Mask_Strength": 0.0,
    "Layer4_Mask_Tiling_X": 1.0,
    "Layer4_Mask_Tiling_Y": 1.0,
    "Layer4_Mask_Brightness": 0.0,
    "Layer4_Mask_Contrast": 1.0,
    "Layer4_Mask_Invert": 0.0,
    "Layer4_Mask_Triplanar": 0.0,
    "AntiTile_Enable": 0.0,
    "AntiTile_Triplanar": 0.0,
    "AntiTile_Scale": 0.27,
    "AntiTile_Noise_Scale": 1.0,
    "AntiTile_Rotation": 0.38,
    "AntiTile_Contrast": 1.5,
    "AntiTile_Macro_Var": 0.0,
    "Vertex_Paint_Strength": 1.0,
    "Height_Displacement_Strength": 0.0,
    "Height_Strength": 0.015,
    "Displacement_Center": 0.0,
    "Displacement_Intensity": 1.0,
    "Displacement_Offset": 0.0,
    "Displacement_SCurve": 1.0,
}


def reset_substance_and_blend_parameters(target_mi) -> bool:
    """Resets all Substance Seams, Layer B/C/D, Anti-Tiling, and B&W Mask scalar/texture/vector parameters on target_mi to their defaults."""
    if not target_mi:
        return False
    mel = unreal.MaterialEditingLibrary
    for param_name, def_val in SUBSTANCE_AND_BLEND_DEFAULTS.items():
        try:
            mel.set_material_instance_scalar_parameter_value(
                target_mi,
                param_name,
                float(def_val),
                unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
            )
        except Exception:
            pass
    try:
        def_w = unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_White")
        def_n = unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_Normal")
        def_r = unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_Roughness")
        def_h = unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_Height")
        for pfx in ("Seam", "LayerB", "Layer2", "Layer3", "Layer4"):
            if def_w:
                mel.set_material_instance_texture_parameter_value(
                    target_mi, f"{pfx}_AlbedoTexture", def_w, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            if def_n:
                mel.set_material_instance_texture_parameter_value(
                    target_mi, f"{pfx}_NormalTexture", def_n, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            if def_r:
                mel.set_material_instance_texture_parameter_value(
                    target_mi, f"{pfx}_RoughnessTexture", def_r, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            if def_h:
                mel.set_material_instance_texture_parameter_value(
                    target_mi, f"{pfx}_HeightTexture", def_h, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            def_col = unreal.LinearColor(0.22, 0.21, 0.20, 1.0) if pfx == "Seam" else unreal.LinearColor(1.0, 1.0, 1.0, 1.0)
            mel.set_material_instance_vector_parameter_value(
                target_mi, f"{pfx}_ColorTint", def_col, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
        if def_h:
            for t_msk_p in ("BlendMaskTexture", "Layer2_MaskTexture", "Layer3_MaskTexture", "Layer4_MaskTexture"):
                mel.set_material_instance_texture_parameter_value(
                    target_mi, t_msk_p, def_h, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
    except Exception:
        pass
    mel.update_material_instance(target_mi)
    unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
    return True


def _export_ue_texture_to_png(tex_asset, out_png_path: str) -> bool:
    """Exports a UE Texture2D asset to a local PNG file using AssetExportTask."""
    if not tex_asset:
        return False
    try:
        task = unreal.AssetExportTask()
        task.object = tex_asset
        task.filename = out_png_path
        task.automated = True
        task.replace_identical = True
        task.prompt = False
        unreal.Exporter.run_asset_export_task(task)
        return os.path.exists(out_png_path)
    except Exception:
        return False


def bake_layered_material_to_new_mi(ue_folder: str = DEFAULT_UE_FOLDER, assign_to_actor: bool = True):
    """
    Bakes the active multi-layer blended Material Instance (Base mtl + Corona Layers 1..10 with their B&W Masks,
    Height-Lerp, Tiling, Brightness/Contrast/Invert, and optional Seams/Tiles) into 4 standalone 2D PBR textures
    (T_Baked_<Name>_Albedo/Normal/Roughness/Height) and creates a new clean MaterialInstanceConstant (MI_Baked_<Name>)
    that can be used directly as Base mtl, Seam Mtl, or Layer B / C / D Mtl in Substance Seams & Tile Generator!
    """
    import subprocess

    folder_now = _normalize_ue_folder(ue_folder)
    target_mi = _get_selected_actor_active_mi() or _get_active_layer_a_mi(folder_now)
    if not target_mi or not isinstance(target_mi, unreal.MaterialInstanceConstant):
        _set_panel_status("[!] Select a Base mtl or Viewport Actor first to bake!", color=(1.0, 0.72, 0.3, 1.0))
        return None

    mel = unreal.MaterialEditingLibrary
    mi_path = target_mi.get_path_name().split(".")[0]
    mi_folder = "/".join(mi_path.split("/")[:-1]) or folder_now
    mi_short = target_mi.get_name()
    base_stem = mi_short[3:] if mi_short.startswith("MI_") else mi_short
    if base_stem.startswith("Baked_"):
        base_stem = base_stem[6:]
    short_stem = re.sub(r"[^A-Za-z0-9_]", "_", base_stem)[:28].strip("_") or "LayeredMtl"
    stamp = int(time.time()) % 10000
    baked_stem = f"Baked_{short_stem}_{stamp}"

    tmp_dir = os.path.join(_SCRIPT_DIR, "_bake_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    def _get_sc(m_obj, p_n: str, def_v: float) -> float:
        try:
            v = float(mel.get_material_instance_scalar_parameter_value(m_obj, p_n, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
            return v
        except Exception:
            return def_v

    def _get_vec_rgb(m_obj, p_n: str, def_rgb=(1.0, 1.0, 1.0)):
        try:
            c = mel.get_material_instance_vector_parameter_value(m_obj, p_n, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
            if c:
                return [float(c.r), float(c.g), float(c.b)]
        except Exception:
            pass
        return list(def_rgb)

    def _export_mi_pbr_dict(m_obj, tag_prefix: str) -> dict:
        d = {}
        for kind, p_name in (
            ("albedo", "AlbedoTexture"),
            ("normal", "NormalTexture"),
            ("roughness", "RoughnessTexture"),
            ("height", "HeightTexture"),
        ):
            tex = mel.get_material_instance_texture_parameter_value(
                m_obj, p_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            out_p = os.path.join(tmp_dir, f"{tag_prefix}_{kind}.png")
            if tex and _export_ue_texture_to_png(tex, out_p):
                d[kind] = out_p
            else:
                d[kind] = ""
        d["uv_tiling"] = max(0.01, _get_sc(m_obj, "UV_Tiling", 1.0))
        d["albedo_str"] = _get_sc(m_obj, "Albedo_Strength", 1.0)
        d["desaturation"] = _get_sc(m_obj, "Albedo_Desaturation", 0.0)
        c_val = _get_sc(m_obj, "Albedo_Contrast", 1.0)
        if c_val <= 0.001 and str(m_obj.get_name()).startswith("MI_Baked_"):
            c_val = 1.0
            try:
                mel.set_material_instance_scalar_parameter_value(
                    m_obj, "Albedo_Contrast", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            except Exception:
                pass
        d["contrast"] = c_val
        d["contrast_pow"] = _get_sc(m_obj, "Albedo_ContrastPower", 1.0)
        d["brightness"] = max(0.01, _get_sc(m_obj, "Albedo_Brightness", 1.0))
        d["color_tint"] = _get_vec_rgb(m_obj, "Albedo_ColorTint", (1.0, 1.0, 1.0))
        d["rough_str"] = _get_sc(m_obj, "Roughness_Strength", 0.5)
        d["rough_base"] = _get_sc(m_obj, "Roughness_Base", 0.35)
        d["rough_mode"] = "base"
        d["norm_str"] = _get_sc(m_obj, "Normal_Strength", 0.45)
        return d

    _set_panel_status(f"[...] Baking multi-layer material from '{mi_short}'...", color=(0.55, 0.88, 1.0, 1.0))
    base_data = _export_mi_pbr_dict(target_mi, "base")
    height_sharpness = _get_sc(target_mi, "Blend_Height_Sharpness", 0.5)

    layers_spec = []
    ui_rows = getattr(builtins, "_COMFY_CORONA_LAYER_ROWS", [])
    ui_by_idx = {r_d["idx"]: r_d for r_d in ui_rows if isinstance(r_d, dict) and "idx" in r_d}
    st_all = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
    st_mi = st_all.get(mi_path, {})

    handled_slots = set()
    # 1. Read hardware slots 1..4 directly from target_mi when active on the shader
    for slot_k, pfx, en_p, m_tex_p, m_str_p, rgh_mult_p in (
        (1, "LayerB", "LayerB_Enable", "BlendMaskTexture", "Blend_Mask_Strength", "LayerB_Roughness_Mult"),
        (2, "Layer2", "Layer2_Enable", "Layer2_MaskTexture", "Layer2_Mask_Strength", "Layer2_Roughness_Mult"),
        (3, "Layer3", "Layer3_Enable", "Layer3_MaskTexture", "Layer3_Mask_Strength", "Layer3_Roughness_Mult"),
        (4, "Layer4", "Layer4_Enable", "Layer4_MaskTexture", "Layer4_Mask_Strength", "Layer4_Roughness_Mult"),
    ):
        w_en = _get_sc(target_mi, en_p, 0.0)
        r_d = ui_by_idx.get(slot_k)
        if r_d is not None:
            try:
                if not bool(r_d["mtl_check"].is_checked()):
                    w_en = 0.0
            except Exception:
                pass
        if w_en <= 0.005:
            continue
        l_dict = {}
        has_any_tex = False
        for kind, sfx in (
            ("albedo", "AlbedoTexture"),
            ("normal", "NormalTexture"),
            ("roughness", "RoughnessTexture"),
            ("height", "HeightTexture"),
        ):
            tex = mel.get_material_instance_texture_parameter_value(
                target_mi, f"{pfx}_{sfx}", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            out_p = os.path.join(tmp_dir, f"slot_{slot_k}_{kind}.png")
            if tex and not str(tex.get_name()).startswith("T_Default_") and _export_ue_texture_to_png(tex, out_p):
                l_dict[kind] = out_p
                has_any_tex = True
            else:
                l_dict[kind] = ""
        if not has_any_tex:
            continue
        l_dict["uv_tiling"] = max(0.01, _get_sc(target_mi, f"{pfx}_UV_Tiling", 1.0))
        l_dict["albedo_str"] = 1.0
        l_dict["desaturation"] = 0.0
        l_dict["contrast"] = 1.0
        l_dict["contrast_pow"] = 1.0
        l_dict["brightness"] = 1.0
        l_dict["color_tint"] = _get_vec_rgb(target_mi, f"{pfx}_ColorTint", (1.0, 1.0, 1.0))
        r_m = _get_sc(target_mi, rgh_mult_p, 1.0)
        l_dict["rough_str"] = r_m if r_m > 0.001 else 1.0
        l_dict["rough_base"] = 0.5
        l_dict["rough_mode"] = "mult"
        l_dict["norm_str"] = 1.0
        l_dict["mtl_weight"] = max(0.0, min(1.0, w_en))
        l_dict["use_mask"] = _get_sc(target_mi, f"{pfx}_Use_Mask", 1.0)
        m_tex = mel.get_material_instance_texture_parameter_value(
            target_mi, m_tex_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
        )
        m_out = os.path.join(tmp_dir, f"slot_{slot_k}_mask.png")
        if m_tex and not str(m_tex.get_name()).startswith("T_Default_") and _export_ue_texture_to_png(m_tex, m_out):
            l_dict["mask_path"] = m_out
        else:
            l_dict["mask_path"] = ""
        hw_m_w = _get_sc(target_mi, m_str_p, 0.0)
        ui_m_w = 0.0
        if r_d is not None:
            try:
                if bool(r_d["mask_check"].is_checked()):
                    ui_m_w = max(0.0, min(1.0, float(r_d["mask_amt"].get_value()) / 100.0))
            except Exception:
                pass
        l_dict["mask_weight"] = max(hw_m_w, ui_m_w) if l_dict["mask_path"] else hw_m_w
        l_dict["mask_tx"] = max(0.01, _get_sc(target_mi, "Blend_Mask_Tiling_X" if slot_k == 1 else f"Layer{slot_k}_Mask_Tiling_X", 1.0))
        l_dict["mask_ty"] = max(0.01, _get_sc(target_mi, "Blend_Mask_Tiling_Y" if slot_k == 1 else f"Layer{slot_k}_Mask_Tiling_Y", 1.0))
        l_dict["mask_bri"] = _get_sc(target_mi, "Blend_Mask_Brightness" if slot_k == 1 else f"Layer{slot_k}_Mask_Brightness", 0.0)
        l_dict["mask_con"] = max(0.05, _get_sc(target_mi, "Blend_Mask_Contrast" if slot_k == 1 else f"Layer{slot_k}_Mask_Contrast", 1.0))
        l_dict["mask_inv"] = _get_sc(target_mi, "Blend_Mask_Invert" if slot_k == 1 else f"Layer{slot_k}_Mask_Invert", 0.0)
        layers_spec.append(l_dict)
        handled_slots.add(slot_k)

    # 2. Read any additional UI rows (e.g. rows 5..10 or rows not yet flushed to hardware slots)
    for r_d in ui_rows:
        l_idx = r_d["idx"]
        if l_idx in handled_slots:
            continue
        sel_mtl = str(r_d["mtl_combo"].get_selected_option() or "None").strip()
        sel_msk = str(r_d["mask_combo"].get_selected_option() or "No Map").strip()
        mtl_amt = float(r_d["mtl_amt"].get_value())
        msk_amt = float(r_d["mask_amt"].get_value())
        mtl_on = bool(r_d["mtl_check"].is_checked())
        msk_on = bool(r_d["mask_check"].is_checked())
        if not sel_mtl or sel_mtl.startswith("None") or not mtl_on or mtl_amt <= 0.01:
            continue
        resolved_b = _resolve_mi_path(sel_mtl)
        src_mi = unreal.EditorAssetLibrary.load_asset(resolved_b) if resolved_b else None
        if not src_mi or not isinstance(src_mi, unreal.MaterialInstanceConstant):
            continue
        l_dict = _export_mi_pbr_dict(src_mi, f"layer_{l_idx}")
        l_dict["mtl_weight"] = max(0.0, min(1.0, mtl_amt / 100.0))
        has_valid_mask = bool(sel_msk and sel_msk != "No Map")
        l_dict["use_mask"] = 1.0 if (has_valid_mask or not msk_on) else 0.0
        l_dict["mask_path"] = ""
        if has_valid_mask and msk_on:
            resolved_m = _resolve_mask_path(sel_msk)
            m_tex = unreal.EditorAssetLibrary.load_asset(resolved_m) if resolved_m else None
            m_out = os.path.join(tmp_dir, f"layer_{l_idx}_mask.png")
            if m_tex and _export_ue_texture_to_png(m_tex, m_out):
                l_dict["mask_path"] = m_out
        l_dict["mask_weight"] = (max(0.0, min(1.0, msk_amt / 100.0)) if msk_on else 0.0) if has_valid_mask else (1.0 if msk_on else 0.0)
        st_l = st_mi.get(l_idx, {})
        l_dict["mask_tx"] = max(0.01, float(st_l.get("Blend_Mask_Tiling_X", _get_sc(target_mi, "Blend_Mask_Tiling_X" if l_idx == 1 else f"Layer{min(l_idx,4)}_Mask_Tiling_X", 1.0))))
        l_dict["mask_ty"] = max(0.01, float(st_l.get("Blend_Mask_Tiling_Y", _get_sc(target_mi, "Blend_Mask_Tiling_Y" if l_idx == 1 else f"Layer{min(l_idx,4)}_Mask_Tiling_Y", 1.0))))
        l_dict["mask_bri"] = float(st_l.get("Blend_Mask_Brightness", _get_sc(target_mi, "Blend_Mask_Brightness" if l_idx == 1 else f"Layer{min(l_idx,4)}_Mask_Brightness", 0.0)))
        l_dict["mask_con"] = max(0.05, float(st_l.get("Blend_Mask_Contrast", _get_sc(target_mi, "Blend_Mask_Contrast" if l_idx == 1 else f"Layer{min(l_idx,4)}_Mask_Contrast", 1.0))))
        l_dict["mask_inv"] = float(st_l.get("Blend_Mask_Invert", _get_sc(target_mi, "Blend_Mask_Invert" if l_idx == 1 else f"Layer{min(l_idx,4)}_Mask_Invert", 0.0)))
        layers_spec.append(l_dict)

    out_alb = os.path.join(tmp_dir, f"T_{baked_stem}_Albedo.png")
    out_nrm = os.path.join(tmp_dir, f"T_{baked_stem}_Normal.png")
    out_rgh = os.path.join(tmp_dir, f"T_{baked_stem}_Roughness.png")
    out_hgt = os.path.join(tmp_dir, f"T_{baked_stem}_Height.png")
    spec_json_p = os.path.join(tmp_dir, "bake_spec.json")

    with open(spec_json_p, "w", encoding="utf-8") as f:
        json.dump(
            {
                "base": base_data,
                "height_sharpness": height_sharpness,
                "layers": layers_spec,
                "out": {
                    "albedo": out_alb,
                    "normal": out_nrm,
                    "roughness": out_rgh,
                    "height": out_hgt,
                },
            },
            f,
            indent=2,
        )

    baker_py = r"""
import sys, os, json, cv2, numpy as np

with open(sys.argv[1], "r", encoding="utf-8") as f:
    spec = json.load(f)

base = spec["base"]
H, W = 1024, 1024
if base.get("albedo") and os.path.exists(base["albedo"]):
    im0 = cv2.imread(base["albedo"], cv2.IMREAD_COLOR)
    if im0 is not None:
        H, W = im0.shape[:2]

yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
u_grid = xx / float(W)
v_grid = yy / float(H)

def sample_tiled(img, tx, ty):
    if abs(tx - 1.0) < 1e-3 and abs(ty - 1.0) < 1e-3 and img.shape[0] == H and img.shape[1] == W:
        return img
    ih, iw = img.shape[:2]
    mx = np.mod(u_grid * tx, 1.0) * float(iw)
    my = np.mod(v_grid * ty, 1.0) * float(ih)
    return cv2.remap(img, mx, my, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)

def load_pbr_layer(d, base_uv):
    rel_til = max(0.01, float(d.get("uv_tiling", 1.0)) / max(0.01, base_uv))
    # Albedo (sRGB PNG -> Linear RGB float 0..1 to match UE5 shader math)
    if d.get("albedo") and os.path.exists(d["albedo"]):
        alb_bgr = cv2.imread(d["albedo"], cv2.IMREAD_COLOR)
        alb_bgr = sample_tiled(alb_bgr, rel_til, rel_til).astype(np.float32) / 255.0
        alb_srgb = np.clip(alb_bgr[:, :, ::-1].copy(), 0.0, 1.0)
        alb_lin = np.power(alb_srgb, 2.2)
    else:
        alb_lin = np.ones((H, W, 3), dtype=np.float32)

    a_str = float(d.get("albedo_str", 1.0))
    if abs(a_str - 1.0) > 1e-4:
        alb_lin = (1.0 - a_str) * 0.5 + a_str * alb_lin
    desat = float(d.get("desaturation", 0.0))
    if abs(desat) > 1e-4:
        lum = alb_lin[:, :, 0:1] * 0.2126 + alb_lin[:, :, 1:2] * 0.7152 + alb_lin[:, :, 2:3] * 0.0722
        alb_lin = alb_lin * (1.0 - desat) + lum * desat
    con_amt = float(d.get("contrast", 1.0))
    if abs(con_amt - 1.0) > 1e-4:
        alb_lin = (1.0 - con_amt) * 0.5 + con_amt * alb_lin
    con_pow = max(0.01, float(d.get("contrast_pow", 1.0)))
    if abs(con_pow - 1.0) > 1e-4:
        alb_lin = np.power(np.clip(alb_lin, 1e-4, 1.0), con_pow)

    tint = np.array(d.get("color_tint", [1.0, 1.0, 1.0]), dtype=np.float32).reshape(1, 1, 3) * float(d.get("brightness", 1.0))
    alb_lin = np.clip(alb_lin * tint, 0.0, 1.0)

    # Roughness (Linear 0..1)
    if d.get("roughness") and os.path.exists(d["roughness"]):
        r_im = cv2.imread(d["roughness"], cv2.IMREAD_GRAYSCALE)
        r_val = sample_tiled(r_im, rel_til, rel_til).astype(np.float32) / 255.0
    else:
        r_val = np.full((H, W), 0.5, dtype=np.float32)
    r_str = float(d.get("rough_str", 0.5))
    r_base = float(d.get("rough_base", 0.35))
    if d.get("rough_mode") == "mult":
        r_val = np.clip(r_val * r_str, 0.02, 0.98)
    else:
        r_val = np.clip((1.0 - r_str) * r_base + r_str * (r_val * r_str), 0.02, 0.98)

    # Height (Linear 0..1)
    if d.get("height") and os.path.exists(d["height"]):
        h_im = cv2.imread(d["height"], cv2.IMREAD_GRAYSCALE)
        h_val = sample_tiled(h_im, rel_til, rel_til).astype(np.float32) / 255.0
    else:
        h_val = np.full((H, W), 0.5, dtype=np.float32)

    # Normal (-1..1 XYZ)
    if d.get("normal") and os.path.exists(d["normal"]):
        n_bgr = cv2.imread(d["normal"], cv2.IMREAD_COLOR)
        n_bgr = sample_tiled(n_bgr, rel_til, rel_til).astype(np.float32) / 255.0
        n_rgb = n_bgr[:, :, ::-1] * 2.0 - 1.0
    else:
        n_rgb = np.zeros((H, W, 3), dtype=np.float32)
        n_rgb[:, :, 2] = 1.0
    n_str = float(d.get("norm_str", 0.45))
    n_rgb[:, :, 0] *= n_str
    n_rgb[:, :, 1] *= n_str
    norm_len = np.maximum(np.linalg.norm(n_rgb, axis=2, keepdims=True), 1e-5)
    n_rgb = n_rgb / norm_len
    return alb_lin, n_rgb, r_val, h_val

base_uv = float(base.get("uv_tiling", 1.0))
alb_cur, nrm_cur, rgh_cur, hgt_cur = load_pbr_layer(base, base_uv)
h_sharp = np.clip(float(spec.get("height_sharpness", 0.5)), 0.0, 1.0)

for l_d in spec.get("layers", []):
    l_alb, l_nrm, l_rgh, l_hgt = load_pbr_layer(l_d, base_uv)
    mtl_w = np.clip(float(l_d.get("mtl_weight", 1.0)), 0.0, 1.0)
    use_m = float(l_d.get("use_mask", 1.0))
    m_w = np.clip(float(l_d.get("mask_weight", 1.0)), 0.0, 1.0)
    m_path = l_d.get("mask_path", "")
    h_diff = (l_hgt - hgt_cur) * h_sharp
    if use_m >= 0.5:
        if m_path and os.path.exists(m_path) and m_w > 0.001:
            m_im = cv2.imread(m_path, cv2.IMREAD_GRAYSCALE)
            tx = float(l_d.get("mask_tx", 1.0))
            ty = float(l_d.get("mask_ty", 1.0))
            m_raw = sample_tiled(m_im, tx, ty).astype(np.float32) / 255.0
            inv_v = np.clip(float(l_d.get("mask_inv", 0.0)), 0.0, 1.0)
            m_raw = m_raw * (1.0 - inv_v) + (1.0 - m_raw) * inv_v
            con = max(0.01, float(l_d.get("mask_con", 1.0)))
            bri = float(l_d.get("mask_bri", 0.0))
            m_adj = np.clip((m_raw - 0.5) * con + 0.5 + bri, 0.0, 1.0)
            alpha = np.clip((m_adj + h_diff) * m_w, 0.0, 1.0)
        else:
            alpha = np.full((H, W), m_w if not m_path else 0.0, dtype=np.float32)
    else:
        alpha = np.clip(0.5 + h_diff, 0.0, 1.0)

    final_a = np.clip(alpha * mtl_w, 0.0, 1.0)
    a3 = final_a[:, :, np.newaxis]
    alb_cur = alb_cur * (1.0 - a3) + l_alb * a3
    rgh_cur = rgh_cur * (1.0 - final_a) + l_rgh * final_a
    hgt_cur = hgt_cur * (1.0 - final_a) + l_hgt * final_a
    nrm_cur = nrm_cur * (1.0 - a3) + l_nrm * a3
    n_len = np.maximum(np.linalg.norm(nrm_cur, axis=2, keepdims=True), 1e-5)
    nrm_cur = nrm_cur / n_len

out_d = spec["out"]
alb_srgb_out = np.power(np.clip(alb_cur, 0.0, 1.0), 1.0 / 2.2)
cv2.imwrite(out_d["albedo"], np.clip(alb_srgb_out[:, :, ::-1] * 255.0, 0, 255).astype(np.uint8))
cv2.imwrite(out_d["roughness"], np.clip(rgh_cur * 255.0, 0, 255).astype(np.uint8))
cv2.imwrite(out_d["height"], np.clip(hgt_cur * 255.0, 0, 255).astype(np.uint8))
nrm_u8 = np.clip((nrm_cur[:, :, ::-1] * 0.5 + 0.5) * 255.0, 0, 255).astype(np.uint8)
cv2.imwrite(out_d["normal"], nrm_u8)
"""
    py_exe = COMFY_EMBEDDED_PYTHON if os.path.exists(COMFY_EMBEDDED_PYTHON) else "python"
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    res = subprocess.run(
        [py_exe, "-c", baker_py, spec_json_p],
        capture_output=True,
        text=True,
        timeout=45,
        creationflags=cflags,
    )
    if res.returncode != 0 or not os.path.exists(out_alb):
        unreal.log_error(f"ComfyUI Bake Layered Mtl Error: {res.stderr}")
        _set_panel_status("[!] Failed to bake layered textures!", color=(1.0, 0.45, 0.45, 1.0))
        return None

    root_folder = DEFAULT_UE_FOLDER
    baked_cat = mi_folder.split("/")[-1].lower()
    if baked_cat not in [c.lower() for c in MATERIAL_CATEGORIES]:
        baked_cat = _detect_material_category(short_stem)
    tex_dest_folder = f"{root_folder}/{TEXTURES_SUBFOLDER}/{baked_cat}"
    unreal.EditorAssetLibrary.make_directory(tex_dest_folder)
    unreal.EditorAssetLibrary.make_directory(mi_folder)

    tasks = []
    kind_to_asset = {}
    for kind, f_p in (
        ("albedo", out_alb),
        ("normal", out_nrm),
        ("roughness", out_rgh),
        ("height", out_hgt),
    ):
        t = unreal.AssetImportTask()
        t.filename = f_p
        t.destination_path = tex_dest_folder
        t.replace_existing = True
        t.save = True
        t.automated = True
        tasks.append(t)
        kind_to_asset[kind] = os.path.splitext(os.path.basename(f_p))[0]

    atools = unreal.AssetToolsHelpers.get_asset_tools()
    if hasattr(atools, "import_asset_tools_tasks"):
        atools.import_asset_tools_tasks(tasks)
    else:
        atools.import_asset_tasks(tasks)

    tex_map = {}
    for kind, a_name in kind_to_asset.items():
        tex_obj = unreal.EditorAssetLibrary.load_asset(f"{tex_dest_folder}/{a_name}")
        if tex_obj:
            tex_map[kind] = tex_obj

    baked_mi_name = f"MI_{baked_stem}"
    baked_mi = _build_pbr_material_instance(
        mi_folder,
        baked_mi_name,
        tex_map,
        master_mat_path=f"{DEFAULT_UE_FOLDER}/{DEFAULT_MASTER_MAT_NAME}",
    )
    # Since Roughness_Strength/Roughness_Base and Normal_Strength were already baked into the maps,
    # set 1:1 pass-through parameters on the baked MI so it matches the viewport blend 1:1
    for k_p, v_p in (
        ("UV_Tiling", float(base_data.get("uv_tiling", 1.0))),
        ("Albedo_Strength", 1.0),
        ("Albedo_Brightness", 1.0),
        ("Albedo_Desaturation", 0.0),
        ("Albedo_Contrast", 1.0),
        ("Albedo_ContrastPower", 1.0),
        ("Roughness_Strength", 1.0),
        ("Roughness_Base", 0.5),
        ("Normal_Strength", 1.0),
    ):
        try:
            mel.set_material_instance_scalar_parameter_value(
                baked_mi, k_p, float(v_p), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
        except Exception:
            pass
    try:
        mel.set_material_instance_vector_parameter_value(
            baked_mi, "Albedo_ColorTint", unreal.LinearColor(1.0, 1.0, 1.0, 1.0), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
        )
    except Exception:
        pass
    mel.update_material_instance(baked_mi)
    unreal.EditorAssetLibrary.save_loaded_asset(baked_mi)

    baked_full_path = baked_mi.get_path_name().split(".")[0]
    mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
    if not isinstance(mi_map, dict):
        mi_map = {}
    mi_map[baked_mi_name] = baked_full_path
    builtins._COMFY_MI_MAP = mi_map
    builtins._COMFY_LAST_MATERIAL = baked_mi

    if assign_to_actor:
        slot_id = _get_selected_poly_target_id(default_for_assign=-1)
        apply_material_to_selected_actors(baked_mi, slot_idx=slot_id)

    try:
        unreal.EditorAssetLibrary.sync_browser_to_objects([baked_mi.get_path_name()])
    except Exception:
        pass

    _set_panel_status(
        f"[Baked OK!] Created '{baked_mi_name}' ({len(layers_spec)} layer(s) baked) -> Ready in Base mtl, Seam Mtl & Layer B/C/D!",
        color=(0.45, 0.98, 0.72, 1.0),
    )
    return baked_mi


def _discover_master_materials(ue_folder: str = DEFAULT_UE_FOLDER) -> list:
    """Находит все 6 базовых Мастер-Материалов в /Game/Textures/ComfyUI (Master, Decal, Glass, Fabric, Foliage, Emissive) и кастомные MM_."""
    ue_folder = _normalize_ue_folder(ue_folder)
    mm_default = f"{ue_folder}/{DEFAULT_MASTER_MAT_NAME}"
    found = [
        mm_default,
        f"{DEFAULT_UE_FOLDER}/MM_ArchViz_Decal",
        f"{DEFAULT_UE_FOLDER}/MM_ArchViz_Glass",
        f"{DEFAULT_UE_FOLDER}/MM_ArchViz_Fabric",
        f"{DEFAULT_UE_FOLDER}/MM_ArchViz_Foliage",
        f"{DEFAULT_UE_FOLDER}/MM_ArchViz_Emissive",
    ]
    for search_dir in (ue_folder, DEFAULT_UE_FOLDER, "/Game"):
        try:
            assets = unreal.EditorAssetLibrary.list_assets(search_dir, recursive=(search_dir != "/Game"))
            for a_path in assets:
                clean = a_path.split(".")[0]
                name = clean.split("/")[-1]
                if name.startswith("MM_") or name.startswith("M_Master") or clean == mm_default:
                    if clean not in found:
                        found.append(clean)
        except Exception:
            pass
    return found


def _style_combo_box(combo: unreal.EditorUtilityComboBoxString) -> None:
    """Applies white foreground and item styles to an EditorUtilityComboBoxString before adding to canvas."""
    try:
        white_sc = unreal.SlateColor(unreal.LinearColor(0.95, 0.96, 1.0, 1.0))
        cf = combo.get_editor_property("font")
        cf.size = 9.0
        combo.set_editor_property("font", cf)
        combo.set_editor_property("foreground_color", white_sc)

        ist = combo.get_editor_property("item_style")
        ist.set_editor_property("text_color", white_sc)
        ist.set_editor_property("selected_text_color", white_sc)
        combo.set_editor_property("item_style", ist)

        wst = combo.get_editor_property("widget_style")
        cbs = wst.get_editor_property("combo_button_style")
        bs = cbs.get_editor_property("button_style")
        bs.set_editor_property("normal_foreground", white_sc)
        bs.set_editor_property("hovered_foreground", white_sc)
        bs.set_editor_property("pressed_foreground", white_sc)
        cbs.set_editor_property("button_style", bs)
        wst.set_editor_property("combo_button_style", cbs)
        combo.set_editor_property("widget_style", wst)
    except Exception:
        pass


def _get_selected_resolution() -> tuple:
    """Returns (resolution_px, resolution_tag) from the Resolution dropdown (default: 1024, '1K')."""
    combo = getattr(builtins, "_COMFY_RES_COMBO", None)
    selected_label = ""
    if combo:
        try:
            selected_label = str(combo.get_selected_option() or "").strip()
        except Exception:
            pass
    if not selected_label:
        selected_label = getattr(builtins, "_COMFY_RESOLUTION_LABEL", DEFAULT_RESOLUTION_LABEL)
    for label, px, tag in RESOLUTION_OPTIONS:
        if label == selected_label or str(px) in selected_label:
            return px, tag
    return 1024, "1K"


def _get_selected_pbr_model() -> tuple:
    """Returns (model_label, pipeline_mode, ckpt_name) from the AI PBR Model dropdown."""
    combo = getattr(builtins, "_COMFY_MODEL_COMBO", None)
    selected_label = ""
    if combo:
        try:
            selected_label = str(combo.get_selected_option() or "").strip()
        except Exception:
            pass
    if not selected_label:
        selected_label = getattr(builtins, "_COMFY_MODEL_LABEL", DEFAULT_PBR_MODEL_LABEL)
    for label, pipe_mode, ckpt_name in PBR_MODEL_OPTIONS:
        if label == selected_label:
            return label, pipe_mode, ckpt_name
    return PBR_MODEL_OPTIONS[0]


DEFAULT_SEED_VALUE = 100001


def _get_selected_seed() -> int:
    """Returns the active integer Seed from the Seed input box (or builtins._COMFY_CURRENT_SEED)."""
    sb = getattr(builtins, "_COMFY_SEED_BOX", None)
    if sb:
        try:
            raw = str(sb.get_text() or "").strip()
            digits = re.sub(r"[^0-9]", "", raw)
            if digits:
                val = int(digits) % (2**31 - 1)
                if val <= 0:
                    val = 1
                builtins._COMFY_CURRENT_SEED = val
                return val
        except Exception:
            pass
    val = int(getattr(builtins, "_COMFY_CURRENT_SEED", DEFAULT_SEED_VALUE))
    return max(1, val)


def _set_selected_seed(new_seed: int) -> int:
    """Updates builtins._COMFY_CURRENT_SEED and the Seed input box in BP_ComfyPanel."""
    val = max(1, int(new_seed) % (2**31 - 1))
    builtins._COMFY_CURRENT_SEED = val
    sb = getattr(builtins, "_COMFY_SEED_BOX", None)
    if sb:
        builtins._COMFY_SYNCING_UI = True
        try:
            sb.set_text(str(val))
        except Exception:
            pass
        finally:
            builtins._COMFY_SYNCING_UI = False
    return val


POLY_ID_SLOT_OPTIONS = [
    ("ID 1 (Slot 2)", 1),
    ("ID 2 (Slot 3)", 2),
    ("ID 3 (Slot 4)", 3),
    ("ID 4 (Slot 5)", 4),
    ("ID 5 (Slot 6)", 5),
    ("ID 6 (Slot 7)", 6),
    ("ID 7 (Slot 8)", 7),
    ("ID 0 (Base Slot)", 0),
    ("All IDs (Whole Mesh)", -1),
]

POLY_SELECT_MODE_OPTIONS = [
    ("Coplanar Face (<= 25 deg)", "coplanar"),
    ("Single Quad (2 Tris)", "quad"),
    ("Single Polygon (1 Tri)", "single"),
    ("Smooth Island (<= 60 deg)", "smooth"),
    ("Connected Element", "element"),
]


def _get_selected_poly_target_id(default_for_assign: int = 1) -> int:
    """Returns the selected Target Material ID slot (0..7), or default_for_assign when 'All IDs' is selected."""
    combo = getattr(builtins, "_COMFY_POLY_ID_COMBO", None)
    sel_txt = ""
    if combo:
        try:
            sel_txt = str(combo.get_selected_option() or "").strip()
        except Exception:
            pass
    if not sel_txt:
        sel_txt = str(getattr(builtins, "_COMFY_POLY_ID_LABEL", "ID 1 (Slot 2)"))
    for lbl, slot_id in POLY_ID_SLOT_OPTIONS:
        if lbl == sel_txt:
            return default_for_assign if (slot_id < 0 and default_for_assign >= 0) else slot_id
    return default_for_assign


def _get_selected_poly_mode() -> tuple:
    """Returns (mode_label, mode_key) from PolySelectModeCombo."""
    combo = getattr(builtins, "_COMFY_POLY_MODE_COMBO", None)
    sel_txt = ""
    if combo:
        try:
            sel_txt = str(combo.get_selected_option() or "").strip()
        except Exception:
            pass
    if not sel_txt:
        sel_txt = str(getattr(builtins, "_COMFY_POLY_MODE_LABEL", POLY_SELECT_MODE_OPTIONS[0][0]))
    for lbl, m_key in POLY_SELECT_MODE_OPTIONS:
        if lbl == sel_txt:
            return lbl, m_key
    return POLY_SELECT_MODE_OPTIONS[0]


def _ensure_static_mesh_uv1_channel(sm) -> bool:
    """
    Ensures LOD 0 of `sm` has at least 2 UV channels via `StaticMeshEditorSubsystem`
    and configures `LODBuildSettings` (`recompute_normals=True, recompute_tangents=True, generate_lightmap_u_vs=False`)
    BEFORE calling `sm.get_static_mesh_description(0)`, preventing both the C++ assertion crash
    in `SetVertexInstanceUV(..., 1)` and Lightmap UV / AutoUV overwrites of UV1 or zeroed vertex normals.
    """
    if not sm:
        return False
    try:
        sm_sub = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        if not sm_sub:
            return False
        try:
            bs = sm_sub.get_lod_build_settings(sm, 0)
            bs.recompute_normals = True
            bs.recompute_tangents = True
            bs.generate_lightmap_u_vs = False
            sm_sub.set_lod_build_settings(sm, 0, bs)
        except Exception:
            pass
        while sm_sub.get_num_uv_channels(sm, 0) < 2:
            if not sm_sub.add_uv_channel(sm, 0):
                break
        return sm_sub.get_num_uv_channels(sm, 0) >= 2
    except Exception:
        return False


def _encode_uv1_normals_on_mesh_description(md, max_slots: int = 8):
    """
    Encodes local geometric face normals into UV1 (`[1..3]` range) on any polygon in `md`
    that does not already have a valid encoded normal. Must only be called when `md` was
    obtained after `_ensure_static_mesh_uv1_channel(sm) == True`.
    """
    if not md:
        return
    for gid in range(max(1, max_slots)):
        pg = unreal.PolygonGroupID(gid)
        if not md.is_polygon_group_valid(pg):
            continue
        for pid in list(md.get_polygon_group_polygons(pg)):
            vis = list(md.get_polygon_vertex_instances(pid))
            if len(vis) < 3:
                continue
            u1_chk = md.get_vertex_instance_uv(vis[0], 1)
            ux, uy = float(u1_chk.x), float(u1_chk.y)
            if 0.999 <= abs(ux) <= 3.001 and 0.999 <= uy <= 3.001:
                dx = (ux - 2.0) if ux >= 0.0 else (ux + 2.0)
                dy = uy - 2.0
                if (dx * dx + dy * dy) <= 1.005:
                    continue
            pts = [md.get_vertex_position(md.get_vertex_instance_vertex(v_i)) for v_i in vis[:3]]
            e1x, e1y, e1z = float(pts[1].x - pts[0].x), float(pts[1].y - pts[0].y), float(pts[1].z - pts[0].z)
            e2x, e2y, e2z = float(pts[2].x - pts[0].x), float(pts[2].y - pts[0].y), float(pts[2].z - pts[0].z)
            nx = e2y * e1z - e2z * e1y
            ny = e2z * e1x - e2x * e1z
            nz = e2x * e1y - e2y * e1x
            n_len = math.sqrt(nx * nx + ny * ny + nz * nz)
            if n_len > 1e-8:
                nx, ny, nz = nx / n_len, ny / n_len, nz / n_len
            else:
                nx, ny, nz = 0.0, 0.0, 1.0
            enc_x = (nx + 2.0) if nz >= 0.0 else (nx - 2.0)
            enc_y = ny + 2.0
            for v_i in vis:
                md.set_vertex_instance_uv(v_i, unreal.Vector2D(enc_x, enc_y), 1)


def _ensure_editable_static_mesh_for_component(comp, ue_folder: str = DEFAULT_UE_FOLDER):
    """
    Ensures that `comp.static_mesh` is a writable project StaticMesh inside `<ue_folder>/Meshes`
    uniquely owned by this actor/component, so editing Polygon IDs works on `/Engine/BasicShapes/*`
    and never mutates unrelated actors sharing the same base mesh.
    """
    if not comp:
        return None
    sm = comp.static_mesh
    if not sm:
        return None
    base_dir = _normalize_ue_folder(ue_folder)
    if base_dir.split("/")[-1] in MATERIAL_CATEGORIES or base_dir.split("/")[-1] == TEXTURES_SUBFOLDER:
        base_dir = "/".join(base_dir.split("/")[:-1]) or DEFAULT_UE_FOLDER
    meshes_dir = f"{base_dir}/Meshes"
    sm_path = sm.get_path_name().split(".")[0]

    actor = comp.get_owner()
    actor_label = re.sub(r"[^A-Za-z0-9_]", "_", actor.get_actor_label() if actor else "Mesh")
    actor_id_sfx = re.sub(r"[^A-Za-z0-9_]", "_", actor.get_name() if actor else "0")[-8:]
    target_name = f"SM_{actor_label}_{actor_id_sfx}_PolyID"
    target_path = f"{meshes_dir}/{target_name}"

    if sm_path == target_path:
        _ensure_static_mesh_uv1_channel(sm)
        return sm

    # Check if sm is already inside Meshes/ and not used by any other actor in the level
    if sm_path.startswith(f"{meshes_dir}/"):
        try:
            actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            users = 0
            for lvl_act in actor_sub.get_all_level_actors():
                for c in lvl_act.get_components_by_class(unreal.StaticMeshComponent):
                    if c.static_mesh and c.static_mesh.get_path_name().split(".")[0] == sm_path:
                        users += 1
            if users <= 1:
                _ensure_static_mesh_uv1_channel(sm)
                return sm
        except Exception:
            _ensure_static_mesh_uv1_channel(sm)
            return sm

    unreal.EditorAssetLibrary.make_directory(meshes_dir)
    saved_mats = [comp.get_material(i) for i in range(comp.get_num_materials())]

    if unreal.EditorAssetLibrary.does_asset_exist(target_path):
        unreal.EditorAssetLibrary.delete_asset(target_path)
    new_sm = unreal.EditorAssetLibrary.duplicate_asset(sm_path, target_path)
    if not new_sm:
        _ensure_static_mesh_uv1_channel(sm)
        return sm

    _ensure_static_mesh_uv1_channel(new_sm)
    comp.modify()
    comp.set_static_mesh(new_sm)
    for idx, m_obj in enumerate(saved_mats):
        if m_obj:
            comp.set_material(idx, m_obj)
            try:
                new_sm.set_material(idx, m_obj)
            except Exception:
                pass
    unreal.EditorAssetLibrary.save_loaded_asset(new_sm)
    return new_sm


def _build_mesh_topology_cache(sm, force_rebuild: bool = False) -> dict:
    """
    Builds and caches polygon topology (vertices, outward normals, centers, groups, and spatial adjacency)
    for `sm` (`unreal.StaticMesh`) from `StaticMeshDescription` (LOD 0).
    """
    if not sm:
        return {}
    sm_path = sm.get_path_name().split(".")[0]
    cache_all = getattr(builtins, "_COMFY_MESH_TOPO_CACHE", {})
    if not isinstance(cache_all, dict):
        cache_all = {}

    md = sm.get_static_mesh_description(0)
    if not md:
        return {}
    poly_cnt = int(md.get_polygon_count())
    num_sec = int(sm.get_num_sections(0))
    cache_key = (sm_path, poly_cnt, num_sec)
    if not force_rebuild and cache_key in cache_all:
        return cache_all[cache_key]

    poly_verts = {}
    poly_normals = {}
    poly_centers = {}
    poly_groups = {}
    vert_to_polys = {}
    edge_to_polys = {}

    pg_max = max(16, int(md.get_polygon_group_count()) + 8)
    for gi in range(pg_max):
        pg = unreal.PolygonGroupID(gi)
        if not md.is_polygon_group_valid(pg):
            continue
        for p in md.get_polygon_group_polygons(pg):
            pid = int(p.id_value)
            v_ids = md.get_polygon_vertices(p)
            pts = []
            for vid in v_ids:
                pos = md.get_vertex_position(vid)
                pts.append((float(pos.x), float(pos.y), float(pos.z)))
            if len(pts) < 3:
                continue
            poly_verts[pid] = pts
            poly_groups[pid] = gi

            n_pts = len(pts)
            cx = sum(pt[0] for pt in pts) / n_pts
            cy = sum(pt[1] for pt in pts) / n_pts
            cz = sum(pt[2] for pt in pts) / n_pts
            poly_centers[pid] = (cx, cy, cz)

            # Outward geometric normal in Unreal's left-handed coordinate system: (v2 - v0) x (v1 - v0)
            v0, v1, v2 = pts[0], pts[1], pts[2]
            e1x, e1y, e1z = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
            e2x, e2y, e2z = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
            nx = e2y * e1z - e2z * e1y
            ny = e2z * e1x - e2x * e1z
            nz = e2x * e1y - e2y * e1x
            n_len = math.sqrt(nx * nx + ny * ny + nz * nz)
            if n_len > 1e-8:
                nx, ny, nz = nx / n_len, ny / n_len, nz / n_len
            else:
                nx, ny, nz = 0.0, 0.0, 1.0
            poly_normals[pid] = (nx, ny, nz)

            q_pts = [(round(pt[0], 2), round(pt[1], 2), round(pt[2], 2)) for pt in pts]
            for qp in q_pts:
                vert_to_polys.setdefault(qp, []).append(pid)
            for idx_e in range(n_pts):
                qa = q_pts[idx_e]
                qb = q_pts[(idx_e + 1) % n_pts]
                ek = (qa, qb) if qa < qb else (qb, qa)
                edge_to_polys.setdefault(ek, []).append(pid)

    topo = {
        "poly_verts": poly_verts,
        "poly_normals": poly_normals,
        "poly_centers": poly_centers,
        "poly_groups": poly_groups,
        "vert_to_polys": vert_to_polys,
        "edge_to_polys": edge_to_polys,
    }
    cache_all[cache_key] = topo
    builtins._COMFY_MESH_TOPO_CACHE = cache_all
    return topo


def _expand_polygon_selection(topo: dict, seed_pid: int, mode_key: str = "coplanar") -> list:
    """
    Expands `seed_pid` into a list of PolygonIDs based on `mode_key`:
    - 'single': single polygon (1 triangle/ngon)
    - 'quad': seed polygon + its coplanar twin sharing the longest edge (1 rectangular quad)
    - 'coplanar': connected coplanar island (normal angle <= 25 deg & coplanar distance <= 2.5 cm)
    - 'smooth': connected smooth island (neighbor normal angle <= 60 deg)
    - 'element': entire connected 3D mesh element sharing vertices
    """
    poly_verts = topo.get("poly_verts", {})
    poly_normals = topo.get("poly_normals", {})
    poly_centers = topo.get("poly_centers", {})
    vert_to_polys = topo.get("vert_to_polys", {})
    edge_to_polys = topo.get("edge_to_polys", {})

    if seed_pid not in poly_verts:
        return []
    if mode_key == "single":
        return [seed_pid]

    seed_n = poly_normals[seed_pid]
    seed_c = poly_centers[seed_pid]

    if mode_key == "quad":
        pts = poly_verts[seed_pid]
        if len(pts) >= 4:
            return [seed_pid]
        q_pts = [(round(pt[0], 2), round(pt[1], 2), round(pt[2], 2)) for pt in pts]
        best_nb = None
        best_len_sq = -1.0
        for idx_e in range(len(q_pts)):
            qa = q_pts[idx_e]
            qb = q_pts[(idx_e + 1) % len(q_pts)]
            ek = (qa, qb) if qa < qb else (qb, qa)
            dx, dy, dz = pts[(idx_e + 1) % len(pts)][0] - pts[idx_e][0], pts[(idx_e + 1) % len(pts)][1] - pts[idx_e][1], pts[(idx_e + 1) % len(pts)][2] - pts[idx_e][2]
            l_sq = dx * dx + dy * dy + dz * dz
            for nb_pid in edge_to_polys.get(ek, []):
                if nb_pid == seed_pid:
                    continue
                nb_n = poly_normals.get(nb_pid, (0.0, 0.0, 1.0))
                dot_v = seed_n[0] * nb_n[0] + seed_n[1] * nb_n[1] + seed_n[2] * nb_n[2]
                if dot_v >= 0.985 and l_sq > best_len_sq:
                    best_len_sq = l_sq
                    best_nb = nb_pid
        return [seed_pid, best_nb] if best_nb is not None else [seed_pid]

    cos_thresh = math.cos(math.radians(25.0)) if mode_key == "coplanar" else (
        math.cos(math.radians(60.0)) if mode_key == "smooth" else -2.0
    )
    visited = {seed_pid}
    queue = [seed_pid]
    while queue:
        cur_pid = queue.pop(0)
        cur_n = poly_normals[cur_pid]
        cur_pts = poly_verts[cur_pid]
        for pt in cur_pts:
            qp = (round(pt[0], 2), round(pt[1], 2), round(pt[2], 2))
            for nb_pid in vert_to_polys.get(qp, []):
                if nb_pid in visited:
                    continue
                nb_n = poly_normals[nb_pid]
                if mode_key == "coplanar":
                    dot_seed = seed_n[0] * nb_n[0] + seed_n[1] * nb_n[1] + seed_n[2] * nb_n[2]
                    if dot_seed < cos_thresh:
                        continue
                    nb_c = poly_centers[nb_pid]
                    plane_dist = abs(
                        seed_n[0] * (nb_c[0] - seed_c[0])
                        + seed_n[1] * (nb_c[1] - seed_c[1])
                        + seed_n[2] * (nb_c[2] - seed_c[2])
                    )
                    if plane_dist > 2.5:
                        continue
                elif mode_key == "smooth":
                    dot_cur = cur_n[0] * nb_n[0] + cur_n[1] * nb_n[1] + cur_n[2] * nb_n[2]
                    if dot_cur < cos_thresh:
                        continue
                visited.add(nb_pid)
                queue.append(nb_pid)
    return sorted(visited)


def _draw_polygon_selection_outline(
    comp,
    topo: dict,
    pids: list,
    color: tuple = (0.0, 0.95, 1.0, 1.0),
    duration: float = 0.22,
    thickness: float = 2.6,
) -> None:
    """Draws the outer boundary edges of `pids` in 3D world space on `comp` using `SystemLibrary.draw_debug_line`."""
    if not comp or not topo or not pids:
        return
    try:
        u_sub = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        world = u_sub.get_editor_world()
        if not world:
            return
        tf = comp.get_world_transform()
        poly_verts = topo.get("poly_verts", {})
        poly_normals = topo.get("poly_normals", {})
        poly_groups = topo.get("poly_groups", {})

        wpo_lift = 0.0
        try:
            gid0 = int(poly_groups.get(pids[0], 0))
            if 0 <= gid0 < comp.get_num_materials():
                m_slot = comp.get_material(gid0)
                if isinstance(m_slot, unreal.MaterialInstanceConstant):
                    wpo_lift = max(
                        0.0,
                        float(
                            unreal.MaterialEditingLibrary.get_material_instance_scalar_parameter_value(
                                m_slot,
                                "Height_Displacement_Strength",
                                unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
                            )
                        ),
                    )
        except Exception:
            wpo_lift = 0.0

        lift = 0.28 + wpo_lift * 0.92
        edge_counts = {}
        edge_world_pts = {}
        for pid in pids:
            pts = poly_verts.get(pid, [])
            n_loc = poly_normals.get(pid, (0.0, 0.0, 1.0))
            n_pts = len(pts)
            for i in range(n_pts):
                p1 = pts[i]
                p2 = pts[(i + 1) % n_pts]
                q1 = (round(p1[0], 2), round(p1[1], 2), round(p1[2], 2))
                q2 = (round(p2[0], 2), round(p2[1], 2), round(p2[2], 2))
                ek = (q1, q2) if q1 < q2 else (q2, q1)
                edge_counts[ek] = edge_counts.get(ek, 0) + 1
                if ek not in edge_world_pts:
                    v1_l = unreal.Vector(p1[0] + n_loc[0] * lift, p1[1] + n_loc[1] * lift, p1[2] + n_loc[2] * lift)
                    v2_l = unreal.Vector(p2[0] + n_loc[0] * lift, p2[1] + n_loc[1] * lift, p2[2] + n_loc[2] * lift)
                    edge_world_pts[ek] = (tf.transform_location(v1_l), tf.transform_location(v2_l))

        lin_col = unreal.LinearColor(*color)
        border_keys = [ek for ek, cnt in edge_counts.items() if cnt == 1]
        if not border_keys:
            border_keys = list(edge_counts.keys())[:64]
        for ek in border_keys[:600]:
            w1, w2 = edge_world_pts[ek]
            unreal.SystemLibrary.draw_debug_line(world, w1, w2, lin_col, duration, thickness)
        try:
            unreal.EditorLevelLibrary.editor_invalidate_viewports()
        except Exception:
            pass
    except Exception:
        pass


def _pick_polygon_under_camera_ray() -> dict:
    """
    Casts a ray from the center of the active Level Viewport camera and finds the exact hit
    `StaticMeshComponent`, `PolygonID`, current `PolygonGroupID`, and expanded `selected_pids`.
    """
    try:
        u_sub = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        world = u_sub.get_editor_world()
        cam_loc, cam_rot = u_sub.get_level_viewport_camera_info()
        fwd = unreal.MathLibrary.get_forward_vector(cam_rot)

        candidate_comps = []
        hit = unreal.SystemLibrary.line_trace_single(
            world,
            cam_loc,
            cam_loc + fwd * 50000.0,
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
            True,
            [],
            unreal.DrawDebugTrace.NONE,
            True,
        )
        if hit:
            hit_tup = hit.to_tuple()
            if hit_tup[0] and len(hit_tup) > 10:
                hit_comp = hit_tup[10]
                if isinstance(hit_comp, unreal.StaticMeshComponent) and hit_comp.static_mesh:
                    candidate_comps.append(hit_comp)

        for act in (a_sub.get_selected_level_actors() if a_sub else []):
            for comp in act.get_components_by_class(unreal.StaticMeshComponent):
                if comp.static_mesh and comp not in candidate_comps:
                    candidate_comps.append(comp)

        if not candidate_comps and a_sub:
            for act in a_sub.get_all_level_actors():
                for comp in act.get_components_by_class(unreal.StaticMeshComponent):
                    if comp.static_mesh and comp not in candidate_comps:
                        candidate_comps.append(comp)

        best_res = None
        best_world_dist = 1e18

        for comp in candidate_comps:
            sm = comp.static_mesh
            if not sm:
                continue
            topo = _build_mesh_topology_cache(sm)
            poly_verts = topo.get("poly_verts", {})
            if not poly_verts:
                continue

            tf = comp.get_world_transform()
            lo = tf.inverse_transform_location(cam_loc)
            lp2 = tf.inverse_transform_location(cam_loc + fwd * 1000.0)
            ld = lp2 - lo
            ld_len = math.sqrt(ld.x * ld.x + ld.y * ld.y + ld.z * ld.z)
            if ld_len < 1e-8:
                continue
            rx, ry, rz = ld.x / ld_len, ld.y / ld_len, ld.z / ld_len
            ox, oy, oz = lo.x, lo.y, lo.z

            best_t = 1e18
            best_pid = -1
            for pid, pts in poly_verts.items():
                v0 = pts[0]
                for i in range(1, len(pts) - 1):
                    v1 = pts[i]
                    v2 = pts[i + 1]
                    e1x, e1y, e1z = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
                    e2x, e2y, e2z = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
                    hx = ry * e2z - rz * e2y
                    hy = rz * e2x - rx * e2z
                    hz = rx * e2y - ry * e2x
                    a = e1x * hx + e1y * hy + e1z * hz
                    if abs(a) < 1e-7:
                        continue
                    f = 1.0 / a
                    sx, sy, sz = ox - v0[0], oy - v0[1], oz - v0[2]
                    u = f * (sx * hx + sy * hy + sz * hz)
                    if u < 0.0 or u > 1.0:
                        continue
                    qx = sy * e1z - sz * e1y
                    qy = sz * e1x - sx * e1z
                    qz = sx * e1y - sy * e1x
                    v_b = f * (rx * qx + ry * qy + rz * qz)
                    if v_b < 0.0 or u + v_b > 1.0:
                        continue
                    t = f * (e2x * qx + e2y * qy + e2z * qz)
                    if 1e-3 < t < best_t:
                        best_t = t
                        best_pid = pid

            if best_pid >= 0:
                hit_local = unreal.Vector(ox + rx * best_t, oy + ry * best_t, oz + rz * best_t)
                hit_world = tf.transform_location(hit_local)
                w_dist = (hit_world - cam_loc).length()
                if w_dist < best_world_dist:
                    best_world_dist = w_dist
                    mode_lbl, mode_key = _get_selected_poly_mode()
                    eff_mode_key = "coplanar" if (len(poly_verts) > 200 and mode_key in ("single", "quad")) else mode_key
                    sel_pids = _expand_polygon_selection(topo, best_pid, eff_mode_key)
                    cur_gid = topo.get("poly_groups", {}).get(best_pid, 0)
                    best_res = {
                        "actor": comp.get_owner(),
                        "comp": comp,
                        "sm": sm,
                        "topo": topo,
                        "hit_pid": best_pid,
                        "cur_gid": cur_gid,
                        "selected_pids": sel_pids,
                        "mode_label": mode_lbl,
                        "mode_key": mode_key,
                        "hit_world": hit_world,
                    }

        return best_res or {}
    except Exception:
        return {}


def _rebuild_static_mesh_with_exact_slots(
    comp,
    sm,
    md,
    compacted_mats: list,
    ue_folder: str = DEFAULT_UE_FOLDER,
):
    """
    Safely builds `md` into `sm` (or a clean 1-slot StaticMesh clone if slot count decreased)
    using `fast_build=True` without ever calling `sm.set_editor_property("static_materials", ...)`
    or `comp.set_static_mesh(None)` (which crashes UE 5.7 `UnrealEditor-MeshPaintingToolset.dll`
    at `0x7b0` if Mesh Paint Mode is active!).
    Guarantees `len(sm.static_materials) == len(compacted_mats) == sm.get_num_sections(0)`.
    """
    target_slot_count = max(1, len(compacted_mats))
    base_mat = compacted_mats[0] if compacted_mats else sm.get_material(0)
    old_sm_to_cleanup = None

    if len(sm.static_materials) > target_slot_count:
        meshes_dir = f"{ue_folder}/Meshes"
        unreal.EditorAssetLibrary.make_directory(meshes_dir)
        old_path = sm.get_path_name().split(".")[0]
        base_path = re.sub(r"_v\d+$", "", old_path)
        if not base_path.startswith(f"{meshes_dir}/"):
            actor = comp.get_owner() if comp else None
            actor_label = re.sub(r"[^A-Za-z0-9_]", "_", actor.get_actor_label() if actor else "Mesh")
            actor_id_sfx = re.sub(r"[^A-Za-z0-9_]", "_", actor.get_name() if actor else "0")[-8:]
            base_path = f"{meshes_dir}/SM_{actor_label}_{actor_id_sfx}_PolyID"

        new_path = base_path
        v_idx = 1
        while new_path == old_path or unreal.EditorAssetLibrary.does_asset_exist(new_path):
            new_path = f"{base_path}_v{v_idx}"
            v_idx += 1

        fresh_sm = unreal.EditorAssetLibrary.duplicate_asset("/Engine/BasicShapes/Cube", new_path)
        if fresh_sm:
            if old_path.startswith(f"{meshes_dir}/"):
                old_sm_to_cleanup = old_path
            sm = fresh_sm

    has_uv1_ch = _ensure_static_mesh_uv1_channel(sm)

    while len(sm.static_materials) < target_slot_count:
        m_add = compacted_mats[len(sm.static_materials)] or base_mat
        sm.add_material(m_add)

    for gi in range(target_slot_count):
        pg = unreal.PolygonGroupID(gi)
        if not md.is_polygon_group_valid(pg):
            md.create_polygon_group_with_id(pg)
        if gi < len(sm.static_materials):
            md.set_polygon_group_material_slot_name(pg, sm.static_materials[gi].material_slot_name)

    if has_uv1_ch:
        try:
            _encode_uv1_normals_on_mesh_description(md, target_slot_count)
        except Exception:
            pass

    sm.modify()
    try:
        sm.set_editor_property("mesh_paint_texture_coordinate_index", 0)
    except Exception:
        pass
    sm.build_from_static_mesh_descriptions([md], build_simple_collision=False, fast_build=False)

    active_sections = max(1, min(len(compacted_mats), sm.get_num_sections(0)))
    for idx in range(active_sections):
        mat_to_use = compacted_mats[idx] or base_mat
        if mat_to_use:
            try:
                sm.set_material(idx, mat_to_use)
            except Exception:
                pass

    if comp:
        comp.modify()
        try:
            comp.set_editor_property("override_materials", [])
        except Exception:
            pass
        if comp.static_mesh != sm:
            comp.set_static_mesh(sm)
        for idx in range(active_sections):
            mat_to_use = compacted_mats[idx] or base_mat
            if mat_to_use:
                comp.set_material(idx, mat_to_use)

    unreal.EditorAssetLibrary.save_loaded_asset(sm)
    if old_sm_to_cleanup and old_sm_to_cleanup != sm.get_path_name().split(".")[0]:
        try:
            unreal.EditorAssetLibrary.delete_asset(old_sm_to_cleanup)
        except Exception:
            pass
    return sm


def assign_polygon_id_to_mesh_polygons(
    comp,
    target_pids: list,
    target_slot_id: int,
    apply_mat=None,
    ue_folder: str = DEFAULT_UE_FOLDER,
) -> dict:
    """
    Assigns `PolygonGroupID(target_slot_id)` to all polygons in `target_pids` on `comp`,
    automatically adding Material Slots up to `target_slot_id` if needed, rebuilding the StaticMesh,
    and optionally applying `apply_mat` to `target_slot_id`.
    """
    if not comp or not target_pids:
        return {"ok": False, "error": "No target polygons"}
    target_slot_id = max(0, min(7, int(target_slot_id)))
    sm = _ensure_editable_static_mesh_for_component(comp, ue_folder)
    if not sm:
        return {"ok": False, "error": "Could not prepare editable StaticMesh"}

    saved_mats = [comp.get_material(i) for i in range(comp.get_num_materials())]
    base_mat = saved_mats[0] if saved_mats and saved_mats[0] else sm.get_material(0)

    while len(sm.static_materials) <= target_slot_id:
        sm.add_material(base_mat)

    md = sm.get_static_mesh_description(0)
    if not md:
        return {"ok": False, "error": "StaticMesh has no StaticMeshDescription (LOD 0)"}

    num_slots = len(sm.static_materials)
    for gi in range(num_slots):
        pg = unreal.PolygonGroupID(gi)
        if not md.is_polygon_group_valid(pg):
            md.create_polygon_group_with_id(pg)
        md.set_polygon_group_material_slot_name(pg, sm.static_materials[gi].material_slot_name)

    target_pg = unreal.PolygonGroupID(target_slot_id)
    changed_count = 0
    for pid in target_pids:
        poly_id_struct = unreal.PolygonID(int(pid))
        if md.is_polygon_valid(poly_id_struct):
            md.set_polygon_polygon_group(poly_id_struct, target_pg)
            changed_count += 1

    # Compact non-empty PolygonGroups so StaticMesh.static_materials and Component.override_materials
    # never exceed LODModel.Sections.Num() (prevents UE 5.7 UTexturePaintToolset::GenerateSeamMask out-of-bounds crash!)
    slot_mats_by_old_gid = {}
    for gi in range(num_slots):
        m_g = saved_mats[gi] if gi < len(saved_mats) and saved_mats[gi] else sm.get_material(gi)
        if gi == target_slot_id and apply_mat is not None:
            m_g = apply_mat
        slot_mats_by_old_gid[gi] = m_g or base_mat

    used_gids = []
    for gi in range(num_slots):
        pg = unreal.PolygonGroupID(gi)
        if md.is_polygon_group_valid(pg):
            pids_in_g = list(md.get_polygon_group_polygons(pg))
            if pids_in_g:
                used_gids.append(gi)

    if not used_gids:
        used_gids = [0]

    compacted_mats = [slot_mats_by_old_gid.get(old_gi, base_mat) for old_gi in used_gids]
    if used_gids != list(range(len(used_gids))):
        for new_idx, old_gi in enumerate(used_gids):
            if new_idx != old_gi:
                new_pg = unreal.PolygonGroupID(new_idx)
                if not md.is_polygon_group_valid(new_pg):
                    md.create_polygon_group_with_id(new_pg)
                old_pg = unreal.PolygonGroupID(old_gi)
                for p_id in list(md.get_polygon_group_polygons(old_pg)):
                    md.set_polygon_polygon_group(p_id, new_pg)

    for gi in range(len(used_gids), num_slots):
        pg = unreal.PolygonGroupID(gi)
        if md.is_polygon_group_valid(pg) and not list(md.get_polygon_group_polygons(pg)):
            try:
                md.delete_polygon_group(pg)
            except Exception:
                pass

    sm = _rebuild_static_mesh_with_exact_slots(comp, sm, md, compacted_mats, ue_folder)
    topo = _build_mesh_topology_cache(sm, force_rebuild=True)
    _draw_polygon_selection_outline(comp, topo, target_pids, color=(0.20, 1.0, 0.45, 1.0), duration=1.5, thickness=2.6)
    return {
        "ok": True,
        "changed_polys": changed_count,
        "total_polys": len(topo.get("poly_verts", {})),
        "num_slots": len(sm.static_materials),
        "num_sections": sm.get_num_sections(0),
        "mesh_name": sm.get_name(),
        "target_slot_id": target_slot_id,
    }


def _get_active_viewport_material(ue_folder: str = DEFAULT_UE_FOLDER, avoid_same_as_mat=None):
    """
    Returns the active MaterialInstanceConstant or Material selected in Section 3 (MasterMatComboBox)
    or Section 4 (LayerAComboBox). If `avoid_same_as_mat` is provided (e.g. Slot 0's material when splitting
    polygons into ID 1..7) and the currently active material is identical to `avoid_same_as_mat`,
    automatically picks a distinct MaterialInstanceConstant so the new Polygon ID is immediately visible!
    """
    chosen = None
    mm_combo = getattr(builtins, "_COMFY_MASTER_COMBO", None)
    mm_map = getattr(builtins, "_COMFY_MM_MAP", {})
    if mm_combo:
        try:
            sel = str(mm_combo.get_selected_option() or "").strip()
            resolved = mm_map.get(sel, _resolve_mi_path(sel))
            if resolved and unreal.EditorAssetLibrary.does_asset_exist(resolved):
                obj = unreal.EditorAssetLibrary.load_asset(resolved)
                if isinstance(obj, unreal.MaterialInstanceConstant):
                    chosen = obj
        except Exception:
            pass

    if not chosen:
        chosen = _get_active_layer_a_mi(ue_folder)

    if not chosen and mm_combo:
        try:
            sel = str(mm_combo.get_selected_option() or "").strip()
            resolved = mm_map.get(sel, sel)
            if resolved and unreal.EditorAssetLibrary.does_asset_exist(resolved):
                obj = unreal.EditorAssetLibrary.load_asset(resolved)
                if isinstance(obj, unreal.MaterialInterface):
                    chosen = obj
        except Exception:
            pass

    if avoid_same_as_mat is not None and chosen is not None:
        try:
            avoid_path = avoid_same_as_mat.get_path_name().split(".")[0]
            chosen_path = chosen.get_path_name().split(".")[0]
            if avoid_path == chosen_path:
                for cand_path in _discover_material_instances(ue_folder):
                    if cand_path != avoid_path:
                        cand_obj = unreal.EditorAssetLibrary.load_asset(cand_path)
                        if isinstance(cand_obj, unreal.MaterialInstanceConstant):
                            chosen = cand_obj
                            builtins._COMFY_LAST_MATERIAL = cand_obj
                            short_n = cand_path.split("/")[-1]
                            builtins._COMFY_SYNCING_UI = True
                            try:
                                if mm_combo:
                                    mm_map[short_n] = cand_path
                                    builtins._COMFY_MM_MAP = mm_map
                                    mm_combo.add_option(short_n)
                                    mm_combo.set_selected_option(short_n)
                                la_c = getattr(builtins, "_COMFY_LAYER_A_COMBO", None)
                                if la_c:
                                    la_c.add_option(short_n)
                                    la_c.set_selected_option(short_n)
                            finally:
                                builtins._COMFY_SYNCING_UI = False
                            break
        except Exception:
            pass

    return chosen


def assign_poly_id_to_aimed_face(ue_folder: str = DEFAULT_UE_FOLDER) -> dict:
    """Picks the polygon / island under the viewport camera crosshair and assigns the selected Target Material ID."""
    pick = _pick_polygon_under_camera_ray()
    if not pick or not pick.get("selected_pids"):
        _set_panel_status(
            "[!] Aim the viewport camera at a mesh surface first (or select an actor) and click 'Assign ID to Aimed Face'!",
            color=(1.0, 0.72, 0.3, 1.0),
        )
        return {"ok": False}

    target_slot_id = _get_selected_poly_target_id(default_for_assign=1)
    comp = pick["comp"]
    actor = pick["actor"]
    sel_pids = pick["selected_pids"]
    slot0_mat = comp.get_material(0) if comp and comp.get_num_materials() > 0 else None
    active_mi = _get_active_viewport_material(
        ue_folder, avoid_same_as_mat=(slot0_mat if target_slot_id > 0 else None)
    )

    try:
        a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        if actor and a_sub and actor not in a_sub.get_selected_level_actors():
            a_sub.set_selected_level_actors([actor])
    except Exception:
        pass

    res = assign_polygon_id_to_mesh_polygons(
        comp, sel_pids, target_slot_id=target_slot_id, apply_mat=active_mi, ue_folder=ue_folder
    )
    if res.get("ok"):
        act_lbl = actor.get_actor_label() if actor else res.get("mesh_name", "Mesh")
        mat_name = active_mi.get_name() if active_mi else "Current Slot Mtl"
        _set_panel_status(
            f"[Polygon ID -> ID {target_slot_id}] '{act_lbl}': {res['changed_polys']} polys ({pick['mode_label']}) -> Slot ID {target_slot_id} ({mat_name})!",
            color=(0.45, 0.96, 0.65, 1.0),
        )
    else:
        _set_panel_status(f"[Polygon ID Error] {res.get('error')}", color=(1.0, 0.45, 0.40, 1.0))
    return res


def assign_poly_id_by_direction(direction_key: str, ue_folder: str = DEFAULT_UE_FOLDER) -> int:
    """
    Assigns the selected Target Material ID to polygons of all selected actors matching `direction_key`:
    - 'top': world/local normal Z > 0.65 (Top +Z faces)
    - 'bottom': normal Z < -0.65 (Bottom -Z faces)
    - 'sides': abs(normal Z) <= 0.45 (Vertical / Side XY faces)
    """
    target_slot_id = _get_selected_poly_target_id(default_for_assign=1)
    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    sel_actors = a_sub.get_selected_level_actors() if a_sub else []
    if not sel_actors:
        _set_panel_status("[!] Select a mesh actor in the viewport first!", color=(1.0, 0.72, 0.3, 1.0))
        return 0

    first_comp = None
    for act in sel_actors:
        comps = act.get_components_by_class(unreal.StaticMeshComponent)
        if comps:
            first_comp = comps[0]
            break
    slot0_mat = first_comp.get_material(0) if first_comp and first_comp.get_num_materials() > 0 else None
    active_mi = _get_active_viewport_material(
        ue_folder, avoid_same_as_mat=(slot0_mat if target_slot_id > 0 else None)
    )

    total_changed = 0
    for act in sel_actors:
        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
            if not comp.static_mesh:
                continue
            topo = _build_mesh_topology_cache(comp.static_mesh)
            poly_normals = topo.get("poly_normals", {})
            matched_pids = []
            for pid, (nx, ny, nz) in poly_normals.items():
                if direction_key == "top" and nz > 0.65:
                    matched_pids.append(pid)
                elif direction_key == "bottom" and nz < -0.65:
                    matched_pids.append(pid)
                elif direction_key == "sides" and abs(nz) <= 0.45:
                    matched_pids.append(pid)
            if matched_pids:
                res = assign_polygon_id_to_mesh_polygons(
                    comp, matched_pids, target_slot_id=target_slot_id, apply_mat=active_mi, ue_folder=ue_folder
                )
                if res.get("ok"):
                    total_changed += res.get("changed_polys", 0)

    if total_changed > 0:
        dir_title = {"top": "Top (+Z)", "bottom": "Bottom (-Z)", "sides": "Sides (XY)"}.get(direction_key, direction_key)
        mat_name = active_mi.get_name() if active_mi else "Current Mtl"
        _set_panel_status(
            f"[Polygon ID: {dir_title} -> ID {target_slot_id}] Assigned {total_changed} polygons to Slot ID {target_slot_id} ({mat_name})!",
            color=(0.45, 0.96, 0.65, 1.0),
        )
    else:
        _set_panel_status(
            f"[!] No polygons matched direction '{direction_key}' on selected actor(s).",
            color=(1.0, 0.72, 0.3, 1.0),
        )
    return total_changed


def reset_selected_actor_poly_ids(ue_folder: str = DEFAULT_UE_FOLDER) -> int:
    """Resets all polygons on selected actors back to PolygonGroupID(0) (single unified Material ID 0)."""
    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    sel_actors = a_sub.get_selected_level_actors() if a_sub else []
    if not sel_actors:
        _set_panel_status("[!] Select a mesh actor in the viewport first!", color=(1.0, 0.72, 0.3, 1.0))
        return 0
    active_mi = _get_active_layer_a_mi(ue_folder)
    reset_count = 0
    for act in sel_actors:
        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
            sm = comp.static_mesh
            if not sm:
                continue
            topo = _build_mesh_topology_cache(sm)
            all_pids = list(topo.get("poly_verts", {}).keys())
            if all_pids:
                res = assign_polygon_id_to_mesh_polygons(
                    comp, all_pids, target_slot_id=0, apply_mat=active_mi, ue_folder=ue_folder
                )
                if res.get("ok"):
                    reset_count += 1
    if reset_count > 0:
        _set_panel_status(
            f"[Polygon ID Reset] Merged all polygons back to Material ID 0 on {reset_count} mesh(es).",
            color=(0.55, 0.88, 1.0, 1.0),
        )
    return reset_count


# ==============================================================================
# === 6. ARCHVIZ DECAL STUDIO, NANITE DISPLACEMENT, VIEWPORT PAINT & LIBRARY ===
# ==============================================================================
PRESET_LIBRARY_JSON_PATH = os.path.join(_SCRIPT_DIR, "studio_material_library.json")

BUILTIN_STUDIO_LIBRARY_PRESETS = {
    "1. [Studio] Weathered Brick + Moss & Grout": {
        "description": "Substance brick grid with recessed mortar seams and organic moss blend",
        "scalars": {
            "Seams_Enable": 1.0,
            "Tiles_Count_X": 4.0,
            "Tiles_Count_Y": 8.0,
            "Row_Shift_Order": 0.5,
            "Seam_Width": 0.045,
            "Seam_Depth": 1.35,
            "LayerB_Enable": 1.0,
            "Blend_In_Seams": 1.0,
            "Blend_Random_Tiles": 0.25,
            "Blend_Mask_Strength": 0.65,
            "Height_Strength": 0.03,
            "Height_Displacement_Strength": 2.5,
        },
    },
    "2. [Studio] Luxury Parquet 2x10 + Bevel": {
        "description": "Architectural herringbone/staggered wood planks with per-plank UV & luminance randomization",
        "scalars": {
            "Seams_Enable": 1.0,
            "Tiles_Count_X": 2.0,
            "Tiles_Count_Y": 10.0,
            "Row_Shift_Order": 0.33,
            "Row_Shift_Random": 0.25,
            "Seam_Width": 0.02,
            "Seam_Depth": 0.85,
            "Tile_Random_UV_Offset": 1.0,
            "Tile_Random_Luminance": 0.12,
            "Height_Strength": 0.018,
        },
    },
    "3. [Studio] Nanite Deep Stone Relief (4cm)": {
        "description": "High-depth Nanite & Parallax stone/rock displacement preset",
        "scalars": {
            "Seams_Enable": 0.0,
            "Height_Strength": 0.045,
            "Height_Displacement_Strength": 4.0,
            "Height_AO_Strength": 0.65,
            "Normal_Strength": 1.25,
        },
    },
    "4. [Decal] Wall Crack / Stain (Auto Luma Alpha)": {
        "description": "Soft-edged architectural decal extracting alpha from dark cracks/stains",
        "scalars": {
            "Decal_Opacity": 1.0,
            "Decal_Edge_Fade": 0.20,
            "Decal_Auto_Luma_Mask": 1.0,
            "Decal_Luma_Invert": 1.0,
            "Decal_Mask_Contrast": 2.6,
            "Normal_Strength": 1.15,
        },
    },
}


def ensure_decal_master_material(ue_folder: str = DEFAULT_UE_FOLDER):
    """Creates or loads the dedicated Deferred Decal Master Material MM_ArchViz_Decal."""
    base_dir = _normalize_ue_folder(ue_folder)
    if base_dir.split("/")[-1].lower() in [c.lower() for c in MATERIAL_CATEGORIES] or base_dir.split("/")[-1] == TEXTURES_SUBFOLDER:
        base_dir = "/".join(base_dir.split("/")[:-1]) or DEFAULT_UE_FOLDER
    decal_mm_path = f"{base_dir}/MM_ArchViz_Decal"
    mel = unreal.MaterialEditingLibrary
    if unreal.EditorAssetLibrary.does_asset_exist(decal_mm_path):
        mm = unreal.EditorAssetLibrary.load_asset(decal_mm_path)
        if mm and mel.get_statistics(mm).num_pixel_shader_instructions > 0:
            return mm
    return create_or_update_master_material(base_dir, "MM_ArchViz_Decal")


def create_decal_material_from_mi(source_mi=None, ue_folder: str = DEFAULT_UE_FOLDER):
    """
    Creates or updates a Deferred Decal Material Instance (MI_Decal_<Name>) parented to MM_ArchViz_Decal,
    copying Albedo, Normal, Roughness, Height, and Opacity/BlendMask textures from source_mi (or active Base mtl).
    """
    base_dir = _normalize_ue_folder(ue_folder)
    if base_dir.split("/")[-1].lower() in [c.lower() for c in MATERIAL_CATEGORIES] or base_dir.split("/")[-1] == TEXTURES_SUBFOLDER:
        base_dir = "/".join(base_dir.split("/")[:-1]) or DEFAULT_UE_FOLDER
    _ensure_folder_structure(base_dir)
    decal_mm = ensure_decal_master_material(base_dir)
    if not decal_mm:
        return None

    if source_mi is None:
        source_mi = _get_active_layer_a_mi(base_dir)
    mel = unreal.MaterialEditingLibrary

    if isinstance(source_mi, unreal.MaterialInstanceConstant):
        try:
            parent_m = source_mi.get_editor_property("parent")
            if parent_m and "decal" in str(parent_m.get_path_name()).lower():
                return source_mi
        except Exception:
            pass

    src_name = source_mi.get_name() if source_mi else "ArchVizDecal"
    clean_stem = re.sub(r"^MI_(?:Decal_)?", "", src_name)
    decal_mi_name = f"MI_Decal_{clean_stem}"
    decal_folder = f"{base_dir}/decal"
    unreal.EditorAssetLibrary.make_directory(decal_folder)
    decal_mi_path = f"{decal_folder}/{decal_mi_name}"

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    if unreal.EditorAssetLibrary.does_asset_exist(decal_mi_path):
        decal_mi = unreal.EditorAssetLibrary.load_asset(decal_mi_path)
    else:
        decal_mi = asset_tools.create_asset(
            decal_mi_name,
            decal_folder,
            unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew(),
        )
    mel.set_material_instance_parent(decal_mi, decal_mm)

    has_mask = False
    if source_mi and isinstance(source_mi, unreal.MaterialInstanceConstant):
        for t_param in [str(p) for p in mel.get_texture_parameter_names(decal_mm)]:
            try:
                tex = mel.get_material_instance_texture_parameter_value(
                    source_mi, t_param, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
                if tex and not str(tex.get_name()).startswith(("WhiteSquare", "Default", "BaseFlatten", "T_Default_")):
                    mel.set_material_instance_texture_parameter_value(
                        decal_mi, t_param, tex, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                    if t_param == "OpacityMaskTexture":
                        has_mask = True
            except Exception:
                pass
        for s_param in [str(p) for p in mel.get_scalar_parameter_names(source_mi)]:
            if s_param.startswith(("LayerB_", "Layer2_", "Layer3_", "Layer4_", "Blend_", "Seams_", "Tiles_", "Row_", "Seam_", "Tile_", "AntiTile_", "UV_Tiling")):
                try:
                    s_val = float(
                        mel.get_material_instance_scalar_parameter_value(
                            source_mi, s_param, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                    )
                    mel.set_material_instance_scalar_parameter_value(
                        decal_mi, s_param, s_val, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                except Exception:
                    pass
        for v_param in ("Albedo_ColorTint", "LayerB_ColorTint", "Layer2_ColorTint", "Layer3_ColorTint", "Layer4_ColorTint", "Seam_Color"):
            try:
                v_val = mel.get_material_instance_vector_parameter_value(
                    source_mi, v_param, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
                if v_val:
                    mel.set_material_instance_vector_parameter_value(
                        decal_mi, v_param, v_val, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
            except Exception:
                pass
        try:
            src_key = source_mi.get_path_name().split(".")[0]
            c_state = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
            if isinstance(c_state, dict) and src_key in c_state:
                c_state[decal_mi_path] = dict(c_state[src_key])
                builtins._COMFY_CORONA_LAYER_STATE = c_state
        except Exception:
            pass

    for k_p, v_p in (
        ("Decal_Opacity", 1.0),
        ("Decal_Edge_Fade", 0.18),
        ("Use_Opacity_Mask", 1.0 if has_mask else 0.0),
        ("Decal_Auto_Luma_Mask", 0.0 if has_mask else 0.85),
        ("Decal_Luma_Invert", 1.0),
        ("Decal_Mask_Contrast", 2.4),
        ("Decal_Mask_Bias", 0.0),
        ("Normal_Strength", 1.0),
    ):
        try:
            mel.set_material_instance_scalar_parameter_value(
                decal_mi, k_p, float(v_p), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
        except Exception:
            pass

    mel.update_material_instance(decal_mi)
    unreal.EditorAssetLibrary.save_loaded_asset(decal_mi)

    mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
    mi_map[decal_mi_name] = decal_mi_path
    builtins._COMFY_MI_MAP = mi_map
    mm_map = getattr(builtins, "_COMFY_MM_MAP", {})
    mm_map[decal_mi_name] = decal_mi_path
    builtins._COMFY_MM_MAP = mm_map
    builtins._COMFY_LAST_MATERIAL = decal_mi
    return decal_mi


def spawn_decal_actor_in_viewport(ue_folder: str = DEFAULT_UE_FOLDER):
    """
    Creates/converts a Deferred Decal Material Instance (MI_Decal_*) from the active material
    and spawns a DecalActor projected onto the aimed surface under the Viewport Camera Crosshair!
    """
    decal_mi = create_decal_material_from_mi(None, ue_folder)
    if not decal_mi:
        _set_panel_status("[!] Failed to create Decal Material Instance!", color=(1.0, 0.45, 0.40, 1.0))
        return None

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    cam = les.get_level_viewport_camera_info() if les else None
    spawn_loc = unreal.Vector(0.0, 0.0, 50.0)
    spawn_rot = unreal.Rotator(0.0, -90.0, 0.0)

    pick = _pick_polygon_under_camera_ray()
    if pick and pick.get("comp") is not None:
        comp = pick["comp"]
        topo = pick["topo"]
        pid = pick["hit_pid"]
        n_local = topo.get("poly_normals", {}).get(pid, (0.0, 0.0, 1.0))
        tr = comp.get_world_transform()
        w_nrm = tr.transform_direction(unreal.Vector(float(n_local[0]), float(n_local[1]), float(n_local[2]))).normal()
        if pick.get("hit_world"):
            spawn_loc = pick["hit_world"]
        elif cam:
            cam_loc, cam_rot = cam
            ray_dir = cam_rot.get_forward_vector().normal()
            spawn_loc = cam_loc + ray_dir * 200.0
        else:
            spawn_loc = comp.get_owner().get_actor_location()
        # Decal projects along its local +X axis, so orient +X along -w_nrm (into the surface)
        proj_dir = unreal.Vector(-w_nrm.x, -w_nrm.y, -w_nrm.z)
        try:
            spawn_rot = unreal.MathLibrary.make_rot_from_x(proj_dir)
        except Exception:
            pass
    elif cam:
        cam_loc, cam_rot = cam
        ray_dir = cam_rot.get_forward_vector().normal()
        spawn_loc = cam_loc + ray_dir * 220.0
        try:
            spawn_rot = unreal.MathLibrary.make_rot_from_x(ray_dir)
        except Exception:
            spawn_rot = cam_rot

    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    decal_actor = a_sub.spawn_actor_from_class(unreal.DecalActor, spawn_loc, spawn_rot)
    if decal_actor:
        decal_actor.set_actor_label(f"Decal_{decal_mi.get_name().replace('MI_Decal_', '')}")
        for d_comp in decal_actor.get_components_by_class(unreal.DecalComponent):
            try:
                d_comp.set_editor_property("decal_size", unreal.Vector(32.0, 120.0, 120.0))
            except Exception:
                pass
            d_comp.set_decal_material(decal_mi)
        try:
            a_sub.set_selected_level_actors([decal_actor])
        except Exception:
            pass
        _set_panel_status(
            f"[Decal Spawned] Placed '{decal_actor.get_actor_label()}' with '{decal_mi.get_name()}' (MM_ArchViz_Decal)!",
            color=(0.45, 0.96, 0.65, 1.0),
        )
    return decal_actor


DISP_TECH_OPTIONS = [
    ("Geometric 3D (Subdiv + WPO)", "geometric"),
    ("Parallax Only (No Subdiv)", "parallax"),
]


def subdivide_polygon_group_for_displacement(
    comp,
    slot_id: int = -1,
    min_tris: int = 2048,
    ue_folder: str = DEFAULT_UE_FOLDER,
) -> int:
    """
    Subdivides the triangles of `PolygonGroupID(slot_id)` (or all polygon groups if `slot_id < 0`)
    on `comp`'s StaticMesh using midpoint 1-to-4 subdivision until the slot has at least `min_tris`
    welded triangles, enabling true 3D vertex displacement (WPO) even on low-poly primitives like Cubes/Walls.
    """
    if not comp:
        return 0
    sm = _ensure_editable_static_mesh_for_component(comp, ue_folder)
    if not sm:
        return 0

    try:
        sm_sub = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
        if sm_sub:
            bs = sm_sub.get_lod_build_settings(sm, 0)
            bs.recompute_normals = True
            bs.recompute_tangents = True
            sm_sub.set_lod_build_settings(sm, 0, bs)
    except Exception:
        pass

    has_uv1_ch = _ensure_static_mesh_uv1_channel(sm)

    md = sm.get_static_mesh_description(0)
    if not md:
        return 0

    saved_mats = [comp.get_material(i) for i in range(comp.get_num_materials())]
    num_slots = max(1, len(sm.static_materials))
    target_groups = [int(slot_id)] if (slot_id >= 0 and slot_id < num_slots) else list(range(num_slots))

    total_new_tris = 0
    modified_any = False

    for gid in target_groups:
        pg = unreal.PolygonGroupID(gid)
        if not md.is_polygon_group_valid(pg):
            continue
        orig_pids = list(md.get_polygon_group_polygons(pg))
        if not orig_pids:
            continue
        if len(orig_pids) >= min_tris:
            has_uv1_nrm = False
            if has_uv1_ch:
                try:
                    vis0 = list(md.get_polygon_vertex_instances(orig_pids[0]))
                    if vis0:
                        u1 = md.get_vertex_instance_uv(vis0[0], 1)
                        if abs(float(u1.x)) >= 0.999 and abs(float(u1.x)) <= 3.001 and abs(float(u1.y) - 2.0) <= 1.005:
                            has_uv1_nrm = True
                except Exception:
                    pass
            if not has_uv1_nrm and has_uv1_ch:
                modified_any = True
            total_new_tris += len(orig_pids)
            continue

        tris = []
        for pid in orig_pids:
            vis = list(md.get_polygon_vertex_instances(pid))
            if len(vis) >= 3:
                pts = []
                uvs = []
                for vi in vis:
                    v = md.get_vertex_instance_vertex(vi)
                    p = md.get_vertex_position(v)
                    uv = md.get_vertex_instance_uv(vi, 0)
                    pts.append((float(p.x), float(p.y), float(p.z)))
                    uvs.append((float(uv.x), float(uv.y)))
                v0, v1, v2 = pts[0], pts[1], pts[2]
                e1x, e1y, e1z = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
                e2x, e2y, e2z = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
                nx = e2y * e1z - e2z * e1y
                ny = e2z * e1x - e2x * e1z
                nz = e2x * e1y - e2y * e1x
                n_len = math.sqrt(nx * nx + ny * ny + nz * nz)
                if n_len > 1e-8:
                    nx, ny, nz = nx / n_len, ny / n_len, nz / n_len
                else:
                    nx, ny, nz = 0.0, 0.0, 1.0
                for k in range(1, len(vis) - 1):
                    tris.append(((pts[0], uvs[0]), (pts[k], uvs[k]), (pts[k + 1], uvs[k + 1]), (nx, ny, nz)))

        if not tris:
            continue

        backup_all = getattr(builtins, "_COMFY_PRE_SUBDIV_BACKUP", {})
        if not isinstance(backup_all, dict):
            backup_all = {}
        b_key = (sm.get_path_name(), int(gid))
        if b_key not in backup_all:
            backup_all[b_key] = list(tris)
        builtins._COMFY_PRE_SUBDIV_BACKUP = backup_all

        while len(tris) < min_tris:
            new_tris = []
            for (p0, uv0), (p1, uv1), (p2, uv2), nrm in tris:
                m01 = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5, (p0[2] + p1[2]) * 0.5)
                m12 = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5, (p1[2] + p2[2]) * 0.5)
                m20 = ((p2[0] + p0[0]) * 0.5, (p2[1] + p0[1]) * 0.5, (p2[2] + p0[2]) * 0.5)
                u01 = ((uv0[0] + uv1[0]) * 0.5, (uv0[1] + uv1[1]) * 0.5)
                u12 = ((uv1[0] + uv2[0]) * 0.5, (uv1[1] + uv2[1]) * 0.5)
                u20 = ((uv2[0] + uv0[0]) * 0.5, (uv2[1] + uv0[1]) * 0.5)
                new_tris.append(((p0, uv0), (m01, u01), (m20, u20), nrm))
                new_tris.append(((p1, uv1), (m12, u12), (m01, u01), nrm))
                new_tris.append(((p2, uv2), (m20, u20), (m12, u12), nrm))
                new_tris.append(((m01, u01), (m12, u12), (m20, u20), nrm))
            tris = new_tris

        vert_map = {}
        vi_map = {}
        md.reserve_new_vertices(len(tris) * 2)
        md.reserve_new_vertex_instances(len(tris) * 3)
        md.reserve_new_polygons(len(tris))
        md.reserve_new_triangles(len(tris))

        for (p0, uv0), (p1, uv1), (p2, uv2), (nx, ny, nz) in tris:
            enc_x = (nx + 2.0) if nz >= 0.0 else (nx - 2.0)
            enc_y = ny + 2.0
            tri_vis = []
            for p, uv in ((p0, uv0), (p1, uv1), (p2, uv2)):
                pk = (round(p[0], 3), round(p[1], 3), round(p[2], 3))
                vid = vert_map.get(pk)
                if vid is None:
                    vid = md.create_vertex()
                    md.set_vertex_position(vid, unreal.Vector(p[0], p[1], p[2]))
                    vert_map[pk] = vid
                vik = (pk, round(uv[0], 4), round(uv[1], 4), round(enc_x, 3), round(enc_y, 3))
                vi_id = vi_map.get(vik)
                if vi_id is None:
                    vi_id = md.create_vertex_instance(vid)
                    md.set_vertex_instance_uv(vi_id, unreal.Vector2D(uv[0], uv[1]), 0)
                    if has_uv1_ch:
                        md.set_vertex_instance_uv(vi_id, unreal.Vector2D(enc_x, enc_y), 1)
                    vi_map[vik] = vi_id
                tri_vis.append(vi_id)
            md.create_triangle(pg, tri_vis)

        for pid in orig_pids:
            md.delete_polygon(pid)

        total_new_tris += len(tris)
        modified_any = True

    if modified_any:
        if has_uv1_ch:
            try:
                _encode_uv1_normals_on_mesh_description(md, num_slots)
            except Exception:
                pass
        sm.modify()
        try:
            sm.set_editor_property("mesh_paint_texture_coordinate_index", 0)
        except Exception:
            pass
        sm.build_from_static_mesh_descriptions([md], build_simple_collision=False, fast_build=False)
        comp.modify()
        try:
            comp.set_editor_property("override_mesh_paint_texture_coordinate_index", True)
            comp.set_editor_property("overridden_mesh_paint_texture_coordinate_index", 0)
        except Exception:
            pass
        for idx in range(len(sm.static_materials)):
            mat_to_use = saved_mats[idx] if idx < len(saved_mats) and saved_mats[idx] else sm.get_material(idx)
            if mat_to_use:
                comp.set_material(idx, mat_to_use)
        unreal.EditorAssetLibrary.save_loaded_asset(sm)
        _build_mesh_topology_cache(sm, force_rebuild=True)

    return total_new_tris


def _enhance_height_map_contrast_and_blend(
    height_png_path: str,
    macro_depth_png_path: str = "",
    albedo_png_path: str = "",
) -> bool:
    """
    Stretches the dynamic range of `height_png_path` (1st..99th percentile -> 0..255),
    optionally fuses circularly de-domed macro depth (`macro_depth_png_path` from DepthAnything V2)
    with micro-detail (`height_png_path` or circular high-pass luminance from `albedo_png_path`),
    enforces seamless periodic boundaries, and writes the crisp 8-bit grayscale displacement map back.
    """
    import subprocess

    py_exe = COMFY_EMBEDDED_PYTHON if os.path.exists(COMFY_EMBEDDED_PYTHON) else "python"
    if not height_png_path or not os.path.exists(height_png_path):
        return False

    script = r"""
import sys, os, cv2, numpy as np

h_path, m_path, a_path = sys.argv[1:4]
h_img = cv2.imread(h_path, cv2.IMREAD_GRAYSCALE)
if h_img is None:
    sys.exit(1)

H, W = h_img.shape[:2]

def norm01(arr):
    f = arr.astype(np.float32)
    p1, p99 = np.percentile(f, (1.0, 99.0))
    if p99 - p1 < 1e-4:
        return np.clip(f / 255.0, 0.0, 1.0)
    return np.clip((f - p1) / (p99 - p1), 0.0, 1.0)

def circular_dedome_and_seamlock(arr01):
    ch = arr01.astype(np.float32).copy()
    pad = max(32, int(min(H, W) * 0.08))
    ch_p = cv2.copyMakeBorder(ch, pad, pad, pad, pad, cv2.BORDER_WRAP)
    low = cv2.GaussianBlur(ch_p, (0, 0), sigmaX=float(pad * 0.75), sigmaY=float(pad * 0.75))[pad:-pad, pad:-pad]
    ch = ch - low + float(np.median(ch))
    B = max(16, int(min(H, W) * 0.024))
    ref_w = max(8, B // 2)
    flat = B // 2
    taper = max(1, B - flat)
    w_d = np.ones((B, 1), dtype=np.float32)
    t_idx = np.arange(taper, dtype=np.float32)[:, None]
    w_d[flat:] = 0.5 * (1.0 + np.cos(np.pi * t_idx / float(taper)))
    w_dx = w_d.T
    sig_par = max(32.0, float(min(H, W)) * 0.08)
    p_par = int(sig_par * 2)
    ch_px = cv2.copyMakeBorder(ch, 0, 0, p_par, p_par, cv2.BORDER_WRAP)
    prof_tb = cv2.GaussianBlur(ch_px, (0, 0), sigmaX=sig_par, sigmaY=0.8)[:, p_par:-p_par]
    ref_tb = 0.5 * (np.mean(prof_tb[B:B+ref_w, :], axis=0, keepdims=True) + np.mean(prof_tb[H-B-ref_w:H-B, :], axis=0, keepdims=True))
    ch[:B, :] -= w_d * (prof_tb[:B, :] - ref_tb)
    ch[H-B:, :] -= w_d[::-1] * (prof_tb[H-B:, :] - ref_tb)
    ch_py = cv2.copyMakeBorder(ch, p_par, p_par, 0, 0, cv2.BORDER_WRAP)
    prof_lr = cv2.GaussianBlur(ch_py, (0, 0), sigmaX=0.8, sigmaY=sig_par)[p_par:-p_par, :]
    ref_lr = 0.5 * (np.mean(prof_lr[:, B:B+ref_w], axis=1, keepdims=True) + np.mean(prof_lr[:, W-B-ref_w:W-B], axis=1, keepdims=True))
    ch[:, :B] -= w_dx * (prof_lr[:, :B] - ref_lr)
    ch[:, W-B:] -= w_dx[:, ::-1] * (prof_lr[:, W-B:] - ref_lr)
    M = max(24, int(min(H, W) * 0.04))
    m_idx = np.arange(M, dtype=np.float32)[:, None]
    ramp_m = 0.5 * (0.5 * (1.0 + np.cos(np.pi * m_idx / float(M))))
    diff_tb = ch[0:1, :] - ch[H-1:H, :]
    diff_tb_s = cv2.GaussianBlur(cv2.copyMakeBorder(diff_tb, 0, 0, 32, 32, cv2.BORDER_WRAP), (0, 0), sigmaX=1.5, sigmaY=0.5)[:, 32:-32]
    ch[:M, :] -= ramp_m * diff_tb_s
    ch[H-M:, :] += ramp_m[::-1] * diff_tb_s
    diff_lr = ch[:, 0:1] - ch[:, W-1:W]
    diff_lr_s = cv2.GaussianBlur(cv2.copyMakeBorder(diff_lr, 32, 32, 0, 0, cv2.BORDER_WRAP), (0, 0), sigmaX=0.5, sigmaY=1.5)[32:-32, :]
    ramp_mx = ramp_m.T
    ch[:, :M] -= ramp_mx * diff_lr_s
    ch[:, W-M:] += ramp_mx[:, ::-1] * diff_lr_s
    return norm01(ch)

h_f = circular_dedome_and_seamlock(norm01(h_img))

if m_path and os.path.exists(m_path):
    m_img = cv2.imread(m_path, cv2.IMREAD_GRAYSCALE)
    if m_img is not None:
        if m_img.shape[:2] != (H, W):
            m_img = cv2.resize(m_img, (W, H), interpolation=cv2.INTER_CUBIC)
        m_f = circular_dedome_and_seamlock(norm01(m_img))
        h_f = norm01(m_f * 0.50 + h_f * 0.50)

if a_path and os.path.exists(a_path):
    a_img = cv2.imread(a_path, cv2.IMREAD_GRAYSCALE)
    if a_img is not None:
        if a_img.shape[:2] != (H, W):
            a_img = cv2.resize(a_img, (W, H), interpolation=cv2.INTER_CUBIC)
        a_f = norm01(a_img)
        a_pad = cv2.copyMakeBorder(a_f, 24, 24, 24, 24, cv2.BORDER_WRAP)
        blur = cv2.GaussianBlur(a_pad, (0, 0), sigmaX=6.0, sigmaY=6.0)[24:-24, 24:-24]
        hi_pass = np.clip((a_f - blur) * 1.5 + 0.5, 0.0, 1.0)
        h_f = norm01(h_f * 0.78 + hi_pass * 0.22)

h_f = circular_dedome_and_seamlock(h_f)
out_u8 = np.clip(h_f * 255.0, 0.0, 255.0).astype(np.uint8)
cv2.imwrite(h_path, out_u8)
"""
    try:
        cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.run(
            [py_exe, "-c", script, height_png_path, macro_depth_png_path or "", albedo_png_path or ""],
            check=False,
            timeout=25,
            creationflags=cflags,
        )
        return os.path.exists(height_png_path)
    except Exception:
        return False


def _enforce_seamless_pbr_maps(
    downloaded_dict: dict,
    is_cutout_or_decal: bool = False,
    deblotch_macro: bool = True,
) -> bool:
    """
    Eliminates outer 0..24px convolutional border roll-off (bright/dark edge halos in Albedo/Roughness,
    edge bevels in Normal, and edge steps/domes in Height) AND removes SDXL low-frequency macro blotches
    via circular LAB de-blotching & local contrast equalization while preserving 100% of micro-grain phase.
    Runs via COMFY_EMBEDDED_PYTHON using OpenCV + NumPy.
    """
    import subprocess

    if is_cutout_or_decal or not downloaded_dict:
        return False

    py_exe = COMFY_EMBEDDED_PYTHON if os.path.exists(COMFY_EMBEDDED_PYTHON) else "python"
    payload = {"__deblotch__": bool(deblotch_macro)}
    for k in ("albedo", "normal", "roughness", "metallic", "height"):
        p = downloaded_dict.get(k, "")
        if p and os.path.exists(p):
            payload[k] = p
    if len(payload) <= 1:
        return False

    script = r"""
import sys, os, json, cv2, numpy as np

payload = json.loads(sys.argv[1])
do_deblotch = bool(payload.pop("__deblotch__", True))

def circ_blur_2d(arr, sig_x, sig_y):
    px = max(16, int(sig_x * 2.5)) if sig_x > 0 else 0
    py = max(16, int(sig_y * 2.5)) if sig_y > 0 else 0
    padded = cv2.copyMakeBorder(arr, py, py, px, px, cv2.BORDER_WRAP)
    blurred = cv2.GaussianBlur(
        padded,
        (0, 0),
        sigmaX=float(max(sig_x, 1e-4)),
        sigmaY=float(max(sig_y, 1e-4)),
    )
    if py > 0 and px > 0:
        return blurred[py:-py, px:-px]
    elif py > 0:
        return blurred[py:-py, :]
    elif px > 0:
        return blurred[:, px:-px]
    return blurred

def fix_map(path, kind):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return
    is_2d = (img.ndim == 2)
    out = img.astype(np.float32)
    if is_2d:
        out = out[:, :, None]
    H, W, C = out.shape
    if H < 64 or W < 64:
        return
    proc_c = min(3, C)
    is_normal = (kind == "normal")
    is_height = (kind == "height")

    if do_deblotch and kind == "albedo" and proc_c >= 3:
        bgr_u8 = np.clip(out[:, :, :3], 0.0, 255.0).astype(np.uint8)
        frac_bgr = out[:, :, :3] - bgr_u8.astype(np.float32)
        lab = cv2.cvtColor(bgr_u8, cv2.COLOR_BGR2Lab).astype(np.float32)
        sig_m = max(24.0, float(min(H, W)) * 0.05)
        for lc, st_m in ((0, 0.88), (1, 0.85), (2, 0.85)):
            ch_l = lab[:, :, lc]
            m_val = float(np.mean(ch_l))
            low_l = circ_blur_2d(ch_l, sig_m, sig_m)
            ch_f = ch_l - st_m * (low_l - m_val)
            if lc == 0:
                res = ch_f - m_val
                loc_var = circ_blur_2d(res * res, sig_m, sig_m)
                loc_std = np.sqrt(np.maximum(loc_var, 1e-4))
                glob_std = float(np.std(res))
                if glob_std > 0.3:
                    scale_c = np.clip(glob_std / loc_std, 0.55, 1.45)
                    ch_f = m_val + res * (0.25 + 0.75 * scale_c)
            lab[:, :, lc] = np.clip(ch_f, 0.0, 255.0)
        bgr_clean = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_Lab2BGR).astype(np.float32) + frac_bgr
        out[:, :, :3] = np.clip(bgr_clean, 0.0, 255.0)
    elif do_deblotch and kind in ("roughness", "height"):
        sig_m = max(20.0, float(min(H, W)) * (0.045 if is_height else 0.05))
        st_m = 0.92 if is_height else 0.85
        for rc in range(proc_c):
            ch_r = out[:, :, rc]
            m_val = float(np.mean(ch_r))
            low_r = circ_blur_2d(ch_r, sig_m, sig_m)
            ch_f = ch_r - st_m * (low_r - m_val)
            res = ch_f - m_val
            loc_var = circ_blur_2d(res * res, sig_m, sig_m)
            loc_std = np.sqrt(np.maximum(loc_var, 1e-4))
            glob_std = float(np.std(res))
            if glob_std > 0.3:
                scale_c = np.clip(glob_std / loc_std, 0.55, 1.45)
                ch_f = m_val + res * (0.25 + 0.75 * scale_c)
            out[:, :, rc] = np.clip(ch_f, 0.0, 255.0)

    B = min(64, min(H, W) // 6)
    ref_w = max(24, B // 2)
    flat = B // 3
    taper = max(1, B - flat)
    w_d = np.ones((B, 1), dtype=np.float32)
    t_idx = np.arange(taper, dtype=np.float32)[:, None]
    w_d[flat:] = 0.5 * (1.0 + np.cos(np.pi * t_idx / float(taper)))
    w_dx = w_d.T
    sig_par = max(36.0, float(min(H, W)) * 0.06)
    M = min(16, B // 3)
    m_idx = np.arange(M, dtype=np.float32)
    alpha_1d = 0.5 * 0.5 * (1.0 + np.cos(np.pi * m_idx / float(M)))

    for c in range(proc_c):
        ch = out[:, :, c].copy()

        prof_tb = circ_blur_2d(ch, sig_par, 0.001)
        ref_t = np.mean(prof_tb[B:B+ref_w, :], axis=0, keepdims=True)
        ref_b = np.mean(prof_tb[H-B-ref_w:H-B, :], axis=0, keepdims=True)
        target_tb = 0.5 * (ref_t + ref_b)
        ch[:B, :] -= w_d * (prof_tb[:B, :] - target_tb)
        ch[H-B:, :] -= w_d[::-1] * (prof_tb[H-B:, :] - target_tb)

        prof_lr = circ_blur_2d(ch, 0.001, sig_par)
        ref_l = np.mean(prof_lr[:, B:B+ref_w], axis=1, keepdims=True)
        ref_r = np.mean(prof_lr[:, W-B-ref_w:W-B], axis=1, keepdims=True)
        target_lr = 0.5 * (ref_l + ref_r)
        ch[:, :B] -= w_dx * (prof_lr[:, :B] - target_lr)
        ch[:, W-B:] -= w_dx[:, ::-1] * (prof_lr[:, W-B:] - target_lr)

        low_tb = circ_blur_2d(ch, 3.0, 3.0)
        high_tb = ch - low_tb
        diff_low_tb = low_tb[0:1, :] - low_tb[H-1:H, :]
        a_y = alpha_1d[:, None]
        low_tb[:M, :] -= a_y * diff_low_tb
        low_tb[H-M:, :] += a_y[::-1] * diff_low_tb
        h_top = high_tb[:M, :].copy()
        h_bot = high_tb[H-M:, :][::-1, :].copy()
        norm_y = np.sqrt((1.0 - a_y) ** 2 + a_y ** 2)
        high_tb[:M, :] = ((1.0 - a_y) * h_top + a_y * h_bot) / norm_y
        high_tb[H-M:, :] = (((1.0 - a_y) * h_bot + a_y * h_top) / norm_y)[::-1, :]
        ch = low_tb + high_tb

        low_lr = circ_blur_2d(ch, 3.0, 3.0)
        high_lr = ch - low_lr
        diff_low_lr = low_lr[:, 0:1] - low_lr[:, W-1:W]
        a_x = alpha_1d[None, :]
        low_lr[:, :M] -= a_x * diff_low_lr
        low_lr[:, W-M:] += a_x[:, ::-1] * diff_low_lr
        h_left = high_lr[:, :M].copy()
        h_right = high_lr[:, W-M:][:, ::-1].copy()
        norm_x = np.sqrt((1.0 - a_x) ** 2 + a_x ** 2)
        high_lr[:, :M] = ((1.0 - a_x) * h_left + a_x * h_right) / norm_x
        high_lr[:, W-M:] = (((1.0 - a_x) * h_right + a_x * h_left) / norm_x)[:, ::-1]
        ch = low_lr + high_lr

        int_mean = float(np.mean(ch[B:H-B, B:W-B]))
        for _ in range(2):
            row_means = np.mean(ch, axis=1, keepdims=True)
            ch[:B, :] -= w_d * (row_means[:B, :] - int_mean)
            ch[H-B:, :] -= w_d[::-1] * (row_means[H-B:, :] - int_mean)
            col_means = np.mean(ch, axis=0, keepdims=True)
            ch[:, :B] -= w_dx * (col_means[:, :B] - int_mean)
            ch[:, W-B:] -= w_dx[:, ::-1] * (col_means[:, W-B:] - int_mean)

        out[:, :, c] = ch

    if is_normal and proc_c >= 3:
        for c_xy in (1, 2):
            ch_n = out[:, :, c_xy]
            low_n = circ_blur_2d(ch_n, 36.0, 36.0)
            ch_n = ch_n - low_n + 128.0
            for _ in range(2):
                ch_n -= (np.mean(ch_n, axis=1, keepdims=True) - 128.0)
                ch_n -= (np.mean(ch_n, axis=0, keepdims=True) - 128.0)
            out[:, :, c_xy] = ch_n
        nx = (out[:, :, 2] / 255.0) * 2.0 - 1.0
        ny = (out[:, :, 1] / 255.0) * 2.0 - 1.0
        nz = np.sqrt(np.maximum(1.0 - nx * nx - ny * ny, 0.02))
        norm = np.sqrt(nx * nx + ny * ny + nz * nz + 1e-8)
        out[:, :, 2] = ((nx / norm) * 0.5 + 0.5) * 255.0
        out[:, :, 1] = ((ny / norm) * 0.5 + 0.5) * 255.0
        out[:, :, 0] = ((nz / norm) * 0.5 + 0.5) * 255.0

    out_u8 = np.clip(np.round(out), 0.0, 255.0).astype(np.uint8)
    if is_2d:
        out_u8 = out_u8[:, :, 0]
    cv2.imwrite(path, out_u8)

for k, p in payload.items():
    fix_map(p, k)
"""
    try:
        cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.run(
            [py_exe, "-c", script, json.dumps(payload)],
            check=False,
            timeout=30,
            creationflags=cflags,
        )
        return True
    except Exception:
        return False


def _import_texture(
    file_path: str,
    dest_folder: str,
    asset_name: str = "",
    is_linear: bool = False,
    is_normal: bool = False,
):
    if not file_path or not os.path.exists(file_path):
        return None
    if not asset_name:
        asset_name = os.path.splitext(os.path.basename(file_path))[0]
    t = unreal.AssetImportTask()
    t.filename = file_path
    t.destination_path = dest_folder
    t.destination_name = asset_name
    t.replace_existing = True
    t.save = True
    t.automated = True
    at = unreal.AssetToolsHelpers.get_asset_tools()
    if hasattr(at, "import_asset_tools_tasks"):
        at.import_asset_tools_tasks([t])
    else:
        at.import_asset_tasks([t])
    tex_obj = unreal.EditorAssetLibrary.load_asset(f"{dest_folder}/{asset_name}")
    if tex_obj:
        try:
            if is_normal:
                tex_obj.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
                tex_obj.set_editor_property("srgb", False)
            elif is_linear:
                tex_obj.set_editor_property("srgb", False)
            else:
                tex_obj.set_editor_property("srgb", True)
            unreal.EditorAssetLibrary.save_loaded_asset(tex_obj)
        except Exception:
            pass
    return tex_obj


def repair_seamless_borders_on_active_material(ue_folder: str = DEFAULT_UE_FOLDER) -> int:
    """
    Exports all PBR texture maps (Albedo, Normal, Roughness, Metallic, Height) from the active
    Material Instance, runs `_enforce_seamless_pbr_maps` to eliminate any outer 0..24px border halo,
    normal bevel, or height discontinuity, and reimports the repaired textures back into UE5.
    """
    import tempfile

    mi = _get_active_layer_a_mi(ue_folder)
    if not mi:
        _set_panel_status("[!] Select an Actor or Base Material Instance first!", color=(1.0, 0.72, 0.3, 1.0))
        return 0

    mel = unreal.MaterialEditingLibrary
    tex_param_map = [
        ("AlbedoTexture", "albedo", False, False),
        ("NormalTexture", "normal", False, True),
        ("RoughnessTexture", "roughness", True, False),
        ("MetallicTexture", "metallic", True, False),
        ("HeightTexture", "height", True, False),
    ]
    tmp_dir = tempfile.mkdtemp(prefix="comfy_fix_borders_")
    downloaded = {}
    tex_info = []
    for p_name, kind, is_lin, is_nrm in tex_param_map:
        tex_obj = mel.get_material_instance_texture_parameter_value(
            mi, p_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
        )
        if not tex_obj:
            continue
        t_path = tex_obj.get_path_name().split(".")[0]
        t_folder = "/".join(t_path.split("/")[:-1])
        t_name = t_path.split("/")[-1]
        png_p = os.path.join(tmp_dir, f"{t_name}.png")
        task = unreal.AssetExportTask()
        task.object = tex_obj
        task.filename = png_p
        task.automated = True
        task.prompt = False
        task.replace_identical = True
        task.exporter = unreal.TextureExporterPNG()
        if unreal.Exporter.run_asset_export_task(task) and os.path.exists(png_p):
            downloaded[kind] = png_p
            tex_info.append((png_p, t_folder, t_name, is_lin, is_nrm))

    if not downloaded:
        _set_panel_status(f"[!] No PBR textures found on '{mi.get_name()}'.", color=(1.0, 0.72, 0.3, 1.0))
        return 0

    _enforce_seamless_pbr_maps(downloaded, is_cutout_or_decal=False)

    repaired_count = 0
    for png_p, t_folder, t_name, is_lin, is_nrm in tex_info:
        if os.path.exists(png_p):
            reimp = _import_texture(png_p, t_folder, t_name, is_linear=is_lin, is_normal=is_nrm)
            if reimp:
                repaired_count += 1
        try:
            os.remove(png_p)
        except Exception:
            pass
    try:
        os.rmdir(tmp_dir)
    except Exception:
        pass

    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    _set_panel_status(
        f"[Seamless Borders Fixed] Repaired {repaired_count} PBR maps on '{mi.get_name()}' (0 border halo/bevel)!",
        color=(0.45, 0.96, 0.78, 1.0),
    )
    return repaired_count


def ensure_directional_light_contact_shadows(contact_shadow_length: float = 0.0) -> int:
    """
    Configures all DirectionalLight actors in the active level with clean `contact_shadow_length = 0.0`
    (avoiding screen-space contact shadow banding/blotches on curved meshes under VSM & Lumen).
    """
    updated_lights = 0
    try:
        a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        for act in (a_sub.get_all_level_actors() if a_sub else []):
            for l_comp in act.get_components_by_class(unreal.DirectionalLightComponent):
                try:
                    cur_len = float(l_comp.get_editor_property("contact_shadow_length"))
                except Exception:
                    cur_len = 0.0
                if abs(cur_len - float(contact_shadow_length)) > 1e-4:
                    try:
                        l_comp.modify()
                        l_comp.set_editor_property("contact_shadow_length", float(contact_shadow_length))
                        l_comp.set_editor_property("contact_shadow_length_in_ws", False)
                        updated_lights += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return updated_lights


def setup_nanite_displacement_on_selected(
    ue_folder: str = DEFAULT_UE_FOLDER,
    displacement_cm: float = 4.0,
    parallax_depth: float = 0.035,
    disp_mode: str = None,
) -> int:
    """
    Configures either:
    - 'geometric' (Geometric 3D (Subdiv + WPO)): Subdivides the target polygon slot into a dense welded grid (~2048 tris),
      and activates Height_Displacement_Strength (WPO) + Parallax + Contact Shadows (DirectionalLight ContactShadowLength = 0.4).
    - 'parallax' (Parallax Only (No Subdiv)): Sets Height_Displacement_Strength = 0.0 (no geometry deformation) and
      boosts Height_Strength (BumpOffset Parallax) + Contact Shadows (PixelDepthOffset) on the target slot's Material Instance.
    """
    ensure_directional_light_contact_shadows(0.0)
    if not disp_mode:
        lbl_m = getattr(builtins, "_COMFY_DISP_TECH_LABEL", DISP_TECH_OPTIONS[0][0])
        disp_mode = "parallax" if "parallax" in str(lbl_m).lower() else "geometric"

    is_geometric = (disp_mode != "parallax")

    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    sel_actors = a_sub.get_selected_level_actors() if a_sub else []
    slot_id = _get_selected_poly_target_id(default_for_assign=-1)
    pick = _pick_polygon_under_camera_ray()
    if pick and pick.get("comp") is not None and pick.get("cur_gid") is not None:
        if slot_id >= 0 or getattr(builtins, "_COMFY_POLY_AIM_ACTIVE", False):
            slot_id = int(pick["cur_gid"])
            for p_lbl, p_slot in POLY_ID_SLOT_OPTIONS:
                if p_slot == slot_id:
                    builtins._COMFY_POLY_ID_LABEL = p_lbl
                    pid_c = getattr(builtins, "_COMFY_POLY_ID_COMBO", None)
                    if pid_c:
                        builtins._COMFY_SYNCING_UI = True
                        try:
                            pid_c.set_selected_option(p_lbl)
                        finally:
                            builtins._COMFY_SYNCING_UI = False
                    break
    nanite_meshes = 0
    subdiv_tris = 0
    target_mis = []
    for act in sel_actors:
        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
            if is_geometric:
                try:
                    subdiv_tris += subdivide_polygon_group_for_displacement(
                        comp, slot_id=slot_id, min_tris=2048, ue_folder=ue_folder
                    )
                except Exception:
                    pass
            sm = comp.static_mesh
            if sm:
                try:
                    ns = sm.get_editor_property("nanite_settings")
                    if ns.get_editor_property("enabled"):
                        ns.set_editor_property("enabled", False)
                        sm.set_editor_property("nanite_settings", ns)
                        unreal.EditorAssetLibrary.save_loaded_asset(sm)
                    nanite_meshes += 1
                except Exception:
                    pass
            try:
                num_m = comp.get_num_materials()
                if slot_id >= 0 and slot_id < num_m:
                    m_slot = comp.get_material(slot_id)
                    if isinstance(m_slot, unreal.MaterialInstanceConstant) and m_slot not in target_mis:
                        target_mis.append(m_slot)
                elif slot_id < 0:
                    for idx_m in range(num_m):
                        m_slot = comp.get_material(idx_m)
                        if isinstance(m_slot, unreal.MaterialInstanceConstant) and m_slot not in target_mis:
                            target_mis.append(m_slot)
            except Exception:
                pass

    if not target_mis:
        fallback_mi = _get_active_layer_a_mi(ue_folder)
        if fallback_mi and isinstance(fallback_mi, unreal.MaterialInstanceConstant):
            target_mis.append(fallback_mi)

    eff_wpo = float(displacement_cm) if is_geometric else 0.0
    eff_parallax = float(parallax_depth) if is_geometric else max(float(parallax_depth), 0.045)

    mel = unreal.MaterialEditingLibrary
    updated_names = []
    for mi in target_mis:
        for k_p, v_p in (
            ("Height_Displacement_Strength", eff_wpo),
            ("Height_Strength", eff_parallax),
            ("Height_AO_Strength", 0.55),
            ("Contact_Shadow_Length", 0.0),
            ("POM_Start_Distance", 350.0),
            ("POM_End_Distance", 1800.0),
        ):
            try:
                mel.set_material_instance_scalar_parameter_value(
                    mi, k_p, v_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            except Exception:
                pass
        mel.update_material_instance(mi)
        unreal.EditorAssetLibrary.save_loaded_asset(mi)
        updated_names.append(mi.get_name())

    if target_mis:
        primary_mi = target_mis[0]
        builtins._COMFY_LAST_MATERIAL = primary_mi
        sync_fn = getattr(builtins, "_COMFY_SYNC_PANEL_FROM_ACTOR_FN", None)
        if sync_fn:
            try:
                sync_fn(primary_mi)
            except Exception:
                _sync_spinboxes_from_mi(primary_mi)
        else:
            _sync_spinboxes_from_mi(primary_mi)

    mi_lbl = ", ".join(updated_names) if updated_names else "None"
    slot_tag = f"Slot ID {slot_id}" if slot_id >= 0 else "All Slots"
    if is_geometric:
        _set_panel_status(
            f"[Geometric 3D Disp ({slot_tag})] Subdivided ({subdiv_tris} tris), WPO={eff_wpo:.1f}cm, Parallax={eff_parallax:.3f} on [{mi_lbl}]!",
            color=(0.45, 0.96, 0.65, 1.0),
        )
    else:
        _set_panel_status(
            f"[Parallax Only ({slot_tag})] WPO=0.0cm (Flat Geometry), Parallax Depth={eff_parallax:.3f} on [{mi_lbl}]!",
            color=(0.55, 0.88, 1.0, 1.0),
        )
    return nanite_meshes


def remove_displacement_on_selected(ue_folder: str = DEFAULT_UE_FOLDER) -> int:
    """
    Removes 3D Displacement (Height_Displacement_Strength = 0.0) and Parallax (Height_Strength = 0.0)
    from the Material Instance on the cyan-highlighted viewport face (cur_gid), selected Target ID slot,
    or Base mtl, and restores original un-subdivided mesh polygons for that slot if a backup exists.
    """
    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    sel_actors = a_sub.get_selected_level_actors() if a_sub else []
    slot_id = _get_selected_poly_target_id(default_for_assign=-1)
    pick = _pick_polygon_under_camera_ray()
    if pick and pick.get("comp") is not None and pick.get("cur_gid") is not None:
        if slot_id >= 0 or getattr(builtins, "_COMFY_POLY_AIM_ACTIVE", False):
            slot_id = int(pick["cur_gid"])
            for p_lbl, p_slot in POLY_ID_SLOT_OPTIONS:
                if p_slot == slot_id:
                    builtins._COMFY_POLY_ID_LABEL = p_lbl
                    pid_c = getattr(builtins, "_COMFY_POLY_ID_COMBO", None)
                    if pid_c:
                        builtins._COMFY_SYNCING_UI = True
                        try:
                            pid_c.set_selected_option(p_lbl)
                        finally:
                            builtins._COMFY_SYNCING_UI = False
                    break

    backup_all = getattr(builtins, "_COMFY_PRE_SUBDIV_BACKUP", {})
    target_mis = []
    restored_meshes = 0

    for act in sel_actors:
        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
            sm = comp.static_mesh
            if sm and isinstance(backup_all, dict):
                try:
                    has_uv1_ch = _ensure_static_mesh_uv1_channel(sm)
                    md = sm.get_static_mesh_description(0)
                    num_slots = max(1, len(sm.static_materials))
                    t_groups = [int(slot_id)] if (slot_id >= 0 and slot_id < num_slots) else list(range(num_slots))
                    saved_mats = [comp.get_material(i) for i in range(comp.get_num_materials())]
                    restored_any = False
                    for gid in t_groups:
                        b_key = (sm.get_path_name(), int(gid))
                        orig_tris = backup_all.get(b_key)
                        if not orig_tris or not md:
                            continue
                        pg = unreal.PolygonGroupID(gid)
                        if not md.is_polygon_group_valid(pg):
                            continue
                        old_pids = list(md.get_polygon_group_polygons(pg))
                        vert_map = {}
                        vi_map = {}
                        for tri_item in orig_tris:
                            if len(tri_item) == 4:
                                (p0, uv0), (p1, uv1), (p2, uv2), (nx, ny, nz) = tri_item
                            else:
                                (p0, uv0), (p1, uv1), (p2, uv2) = tri_item
                                nx, ny, nz = 0.0, 0.0, 1.0
                            enc_x = (nx + 2.0) if nz >= 0.0 else (nx - 2.0)
                            enc_y = ny + 2.0
                            tri_vis = []
                            for p, uv in ((p0, uv0), (p1, uv1), (p2, uv2)):
                                pk = (round(p[0], 3), round(p[1], 3), round(p[2], 3))
                                vid = vert_map.get(pk)
                                if vid is None:
                                    vid = md.create_vertex()
                                    md.set_vertex_position(vid, unreal.Vector(p[0], p[1], p[2]))
                                    vert_map[pk] = vid
                                vik = (pk, round(uv[0], 4), round(uv[1], 4), round(enc_x, 3), round(enc_y, 3))
                                vi_id = vi_map.get(vik)
                                if vi_id is None:
                                    vi_id = md.create_vertex_instance(vid)
                                    md.set_vertex_instance_uv(vi_id, unreal.Vector2D(uv[0], uv[1]), 0)
                                    if has_uv1_ch:
                                        md.set_vertex_instance_uv(vi_id, unreal.Vector2D(enc_x, enc_y), 1)
                                    vi_map[vik] = vi_id
                                tri_vis.append(vi_id)
                            md.create_triangle(pg, tri_vis)
                        for pid in old_pids:
                            md.delete_polygon(pid)
                        backup_all.pop(b_key, None)
                        restored_any = True
                    if restored_any or md:
                        if has_uv1_ch and md:
                            try:
                                _encode_uv1_normals_on_mesh_description(md, num_slots)
                            except Exception:
                                pass
                        if md:
                            sm.modify()
                            sm.build_from_static_mesh_descriptions([md], build_simple_collision=False, fast_build=False)
                            comp.modify()
                            for idx in range(len(sm.static_materials)):
                                mat_to_use = saved_mats[idx] if idx < len(saved_mats) and saved_mats[idx] else sm.get_material(idx)
                                if mat_to_use:
                                    comp.set_material(idx, mat_to_use)
                            unreal.EditorAssetLibrary.save_loaded_asset(sm)
                            _build_mesh_topology_cache(sm, force_rebuild=True)
                            restored_meshes += 1
                except Exception:
                    pass
            try:
                num_m = comp.get_num_materials()
                if slot_id >= 0 and slot_id < num_m:
                    m_slot = comp.get_material(slot_id)
                    if isinstance(m_slot, unreal.MaterialInstanceConstant) and m_slot not in target_mis:
                        target_mis.append(m_slot)
                elif slot_id < 0:
                    for idx_m in range(num_m):
                        m_slot = comp.get_material(idx_m)
                        if isinstance(m_slot, unreal.MaterialInstanceConstant) and m_slot not in target_mis:
                            target_mis.append(m_slot)
            except Exception:
                pass

    if not target_mis:
        fallback_mi = _get_active_layer_a_mi(ue_folder)
        if fallback_mi and isinstance(fallback_mi, unreal.MaterialInstanceConstant):
            target_mis.append(fallback_mi)

    mel = unreal.MaterialEditingLibrary
    updated_names = []
    for mi in target_mis:
        for k_p, v_p in (
            ("Height_Displacement_Strength", 0.0),
            ("Height_Strength", 0.0),
            ("Height_AO_Strength", 0.0),
            ("Contact_Shadow_Length", 0.0),
        ):
            try:
                mel.set_material_instance_scalar_parameter_value(
                    mi, k_p, v_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            except Exception:
                pass
        mel.update_material_instance(mi)
        unreal.EditorAssetLibrary.save_loaded_asset(mi)
        updated_names.append(mi.get_name())

    if target_mis:
        primary_mi = target_mis[0]
        builtins._COMFY_LAST_MATERIAL = primary_mi
        sync_fn = getattr(builtins, "_COMFY_SYNC_PANEL_FROM_ACTOR_FN", None)
        if sync_fn:
            try:
                sync_fn(primary_mi)
            except Exception:
                _sync_spinboxes_from_mi(primary_mi)
        else:
            _sync_spinboxes_from_mi(primary_mi)

    mi_lbl = ", ".join(updated_names) if updated_names else "None"
    slot_tag = f"Slot ID {slot_id}" if slot_id >= 0 else "All Slots"
    _set_panel_status(
        f"[Displacement Removed ({slot_tag})] Reset WPO=0.0cm & Parallax=0.0 on [{mi_lbl}]!",
        color=(1.0, 0.75, 0.50, 1.0),
    )
    return len(updated_names)


def generate_displacement_in_comfy_for_active_mi(
    ue_folder: str = DEFAULT_UE_FOLDER,
    json_path: str = DEFAULT_JSON_PATH,
) -> bool:
    """
    Generates / regenerates a high-contrast 3D Displacement map (`T_<Name>_Height`) in ComfyUI
    using `DepthAnything_V2` (`depth_anything_v2_vitl_fp16.safetensors`, fp32) from the `AlbedoTexture`
    of the active Material Instance (on the cyan-highlighted viewport face or Base mtl), imports it
    into UE5 (`sRGB=False`), assigns it to `HeightTexture`, and applies the active Displacement Mode.
    """
    if getattr(builtins, "_COMFY_JOB_RUNNING", False):
        _set_panel_status(
            "[...] ComfyUI generation is already running, please wait...",
            "WAIT...",
            color=(1.0, 0.80, 0.35, 1.0),
        )
        return

    if not _check_can_generate_or_prompt_buy(1):
        return False

    ue_import_path = _normalize_ue_folder(ue_folder)
    if ue_import_path.split("/")[-1].lower() in [c.lower() for c in MATERIAL_CATEGORIES]:
        ue_import_path = "/".join(ue_import_path.split("/")[:-1]) or DEFAULT_UE_FOLDER

    slot_id = _get_selected_poly_target_id(default_for_assign=-1)
    pick = _pick_polygon_under_camera_ray()
    if pick and pick.get("comp") is not None and pick.get("cur_gid") is not None:
        if slot_id >= 0 or getattr(builtins, "_COMFY_POLY_AIM_ACTIVE", False):
            slot_id = int(pick["cur_gid"])

    target_mi = None
    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for act in (a_sub.get_selected_level_actors() if a_sub else []):
        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
            num_m = comp.get_num_materials()
            if slot_id >= 0 and slot_id < num_m:
                m_slot = comp.get_material(slot_id)
                if isinstance(m_slot, unreal.MaterialInstanceConstant):
                    target_mi = m_slot
                    break
        if target_mi:
            break

    if not target_mi:
        target_mi = _get_active_layer_a_mi(ue_import_path)
    if not target_mi or not isinstance(target_mi, unreal.MaterialInstanceConstant):
        _set_panel_status("[!] Select an actor/face or Base mtl first to generate Displacement!", color=(1.0, 0.65, 0.35, 1.0))
        return False

    mel = unreal.MaterialEditingLibrary
    alb_tex = mel.get_material_instance_texture_parameter_value(
        target_mi, "AlbedoTexture", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
    )
    if not alb_tex:
        _set_panel_status(f"[!] '{target_mi.get_name()}' has no AlbedoTexture!", color=(1.0, 0.65, 0.35, 1.0))
        return False

    comfy_input_dir = r"D:\AI\ComfyUI_windows_portable\ComfyUI\input"
    os.makedirs(comfy_input_dir, exist_ok=True)
    input_fname = f"comfy_disp_src_{target_mi.get_name()}.png"
    exported_alb_path = os.path.join(comfy_input_dir, input_fname)

    exp_task = unreal.AssetExportTask()
    exp_task.object = alb_tex
    exp_task.filename = exported_alb_path
    exp_task.automated = True
    exp_task.replace_identical = True
    exp_task.prompt = False
    if not unreal.Exporter.run_asset_export_task(exp_task) or not os.path.exists(exported_alb_path):
        _set_panel_status("[!] Failed to export AlbedoTexture to ComfyUI input folder!", color=(1.0, 0.45, 0.45, 1.0))
        return False

    mi_short = target_mi.get_name()
    stem = mi_short[3:] if mi_short.startswith("MI_") else mi_short
    height_asset_name = f"T_{stem}_Height"
    temp_dir = os.path.dirname(json_path) if os.path.exists(json_path) else comfy_input_dir

    disp_workflow = {
        "1": {
            "class_type": "LoadImage",
            "inputs": {
                "image": input_fname,
            },
        },
        "2": {
            "class_type": "DownloadAndLoadDepthAnythingV2Model",
            "inputs": {
                "model": "depth_anything_v2_vitl_fp16.safetensors",
                "precision": "fp32",
            },
        },
        "3": {
            "class_type": "DepthAnything_V2",
            "inputs": {
                "da_model": ["2", 0],
                "images": ["1", 0],
            },
        },
        "4": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "api_regen_height",
                "images": ["3", 0],
            },
        },
    }

    state = {
        "done": False,
        "error": None,
        "local_path": None,
        "start_time": time.time(),
        "target_mi": target_mi,
        "height_asset_name": height_asset_name,
        "ue_import_path": ue_import_path,
        "exported_alb_path": exported_alb_path,
    }
    builtins._COMFY_CANCEL_REQUESTED = False
    builtins._COMFY_JOB_RUNNING = True
    _set_panel_status(
        f"[...] Generating Deep Displacement Map (DepthAnything V2) in ComfyUI for '{mi_short}'...",
        "WAIT...",
        color=(0.55, 0.88, 1.0, 1.0),
    )

    def _disp_worker():
        try:
            req = urllib.request.Request(
                f"{COMFY_URL}/prompt",
                data=json.dumps({"prompt": disp_workflow}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
            prompt_id = res_data["prompt_id"]

            while True:
                if getattr(builtins, "_COMFY_CANCEL_REQUESTED", False):
                    state["error"] = "__CANCELLED__"
                    break
                if time.time() - state["start_time"] > 300:
                    state["error"] = "ComfyUI displacement generation timed out (300 sec)"
                    break
                try:
                    with urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}", timeout=5.0) as h_resp:
                        history = json.loads(h_resp.read().decode("utf-8"))
                    if prompt_id in history:
                        entry = history[prompt_id]
                        st_info = entry.get("status", {})
                        if st_info.get("status_str") == "error":
                            state["error"] = f"ComfyUI error: {st_info}"
                            break
                        outputs = entry.get("outputs", {})
                        for _nid, node_out in outputs.items():
                            for image in node_out.get("images", []):
                                fname = image["filename"]
                                params = urllib.parse.urlencode(
                                    {
                                        "filename": fname,
                                        "subfolder": image.get("subfolder", ""),
                                        "type": image.get("type", "output"),
                                    }
                                )
                                img_bytes = urllib.request.urlopen(f"{COMFY_URL}/view?{params}", timeout=15.0).read()
                                local_path = os.path.join(temp_dir, f"{height_asset_name}.png")
                                with open(local_path, "wb") as out_f:
                                    out_f.write(img_bytes)
                                _enhance_height_map_contrast_and_blend(
                                    local_path,
                                    macro_depth_png_path="",
                                    albedo_png_path=exported_alb_path,
                                )
                                state["local_path"] = local_path
                                break
                        break
                except Exception:
                    pass
                time.sleep(0.5)
        except Exception as e:
            state["error"] = str(e)
        finally:
            state["done"] = True

    threading.Thread(target=_disp_worker, daemon=True).start()
    tick_box = {"handle": None, "last_sec": -1}

    def _on_disp_tick(_delta_time: float):
        if getattr(builtins, "_COMFY_CANCEL_REQUESTED", False):
            if tick_box["handle"] is not None:
                try:
                    unreal.unregister_slate_post_tick_callback(tick_box["handle"])
                except Exception:
                    pass
                tick_box["handle"] = None
            builtins._COMFY_JOB_RUNNING = False
            return

        elapsed = int(time.time() - state["start_time"])
        if not state["done"]:
            if elapsed != tick_box["last_sec"]:
                tick_box["last_sec"] = elapsed
                _set_panel_status(
                    f"[...] ComfyUI DepthAnything V2 Displacement for '{mi_short}' ({elapsed}s)...",
                    f"WAIT ({elapsed}s)",
                    color=(1.0, 0.82, 0.35, 1.0),
                )
            return

        if tick_box["handle"] is not None:
            try:
                unreal.unregister_slate_post_tick_callback(tick_box["handle"])
            except Exception:
                pass
            tick_box["handle"] = None
        builtins._COMFY_ACTIVE_TICK_HANDLE = None
        builtins._COMFY_JOB_RUNNING = False

        try:
            if os.path.exists(state["exported_alb_path"]):
                os.remove(state["exported_alb_path"])
        except Exception:
            pass

        if state["error"] or not state["local_path"]:
            err = state["error"] or "No displacement map returned"
            _set_panel_status(f"[Disp Error] {err}", "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))
            return

        try:
            mi_parent_cat = state["target_mi"].get_path_name().split(".")[0].split("/")[-2].lower()
            if mi_parent_cat not in [c.lower() for c in MATERIAL_CATEGORIES]:
                mi_parent_cat = _detect_material_category(state["target_mi"].get_name())
            tex_dest_folder = f"{state['ue_import_path']}/{TEXTURES_SUBFOLDER}/{mi_parent_cat}"
            unreal.EditorAssetLibrary.make_directory(tex_dest_folder)

            t = unreal.AssetImportTask()
            t.filename = state["local_path"]
            t.destination_path = tex_dest_folder
            t.replace_existing = True
            t.save = True
            t.automated = True

            asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
            if hasattr(asset_tools, "import_asset_tools_tasks"):
                asset_tools.import_asset_tools_tasks([t])
            else:
                asset_tools.import_asset_tasks([t])

            try:
                os.remove(state["local_path"])
            except Exception:
                pass

            h_ue_path = f"{tex_dest_folder}/{state['height_asset_name']}"
            h_tex = unreal.EditorAssetLibrary.load_asset(h_ue_path)
            if h_tex:
                h_tex.set_editor_property("srgb", False)
                unreal.EditorAssetLibrary.save_loaded_asset(h_tex)
                mel.set_material_instance_texture_parameter_value(
                    state["target_mi"],
                    "HeightTexture",
                    h_tex,
                    unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
                )
                mel.update_material_instance(state["target_mi"])
                unreal.EditorAssetLibrary.save_loaded_asset(state["target_mi"])

            setup_nanite_displacement_on_selected(state["ue_import_path"])
            _set_panel_status(
                f"[ComfyUI Displacement Ready] Generated '{state['height_asset_name']}' ({elapsed}s) & applied to '{mi_short}'!",
                "GENERATE PBR",
                color=(0.45, 0.96, 0.65, 1.0),
            )
        except Exception as exc:
            _set_panel_status(f"[Disp Import Error] {exc}", "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))

    tick_box["handle"] = unreal.register_slate_post_tick_callback(_on_disp_tick)
    builtins._COMFY_ACTIVE_TICK_HANDLE = tick_box["handle"]
    return True


def _pick_uv_under_camera_ray():
    """
    Raycasts from the active Level Viewport camera onto the selected (or aimed) StaticMeshComponent
    and interpolates the exact UV0 coordinate (hit_u, hit_v) at the ray-triangle intersection!
    """
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les:
        return None
    cam = les.get_level_viewport_camera_info()
    if not cam:
        return None
    cam_loc, cam_rot = cam
    ray_dir = cam_rot.get_forward_vector().normal()
    ro = (float(cam_loc.x), float(cam_loc.y), float(cam_loc.z))
    rd = (float(ray_dir.x), float(ray_dir.y), float(ray_dir.z))

    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    sel_actors = a_sub.get_selected_level_actors() if a_sub else []
    candidates = list(sel_actors) if sel_actors else list(a_sub.get_all_level_actors() if a_sub else [])

    best_hit = None
    best_t = 1e18

    for act in candidates:
        if not act:
            continue
        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
            sm = comp.static_mesh
            if not sm:
                continue
            try:
                smd = sm.get_static_mesh_description(0)
            except Exception:
                smd = None
            if not smd:
                continue
            tr = comp.get_world_transform()
            pg_cnt = smd.get_polygon_group_count()
            poly_cnt = smd.get_polygon_count()
            v_cnt = smd.get_vertex_count()

            w_verts = {}
            for vi in range(max(v_cnt * 2, 64)):
                vid = unreal.VertexID(vi)
                if smd.is_vertex_valid(vid):
                    p = smd.get_vertex_position(vid)
                    wp = tr.transform_location(p)
                    w_verts[vi] = (float(wp.x), float(wp.y), float(wp.z))

            for pi in range(max(poly_cnt * 2, 128)):
                pid = unreal.PolygonID(pi)
                if not smd.is_polygon_valid(pid):
                    continue
                vis = list(smd.get_polygon_vertex_instances(pid))
                if len(vis) < 3:
                    continue
                for k in range(1, len(vis) - 1):
                    vi0, vi1, vi2 = vis[0], vis[k], vis[k + 1]
                    v0 = w_verts.get(int(smd.get_vertex_instance_vertex(vi0).id_value))
                    v1 = w_verts.get(int(smd.get_vertex_instance_vertex(vi1).id_value))
                    v2 = w_verts.get(int(smd.get_vertex_instance_vertex(vi2).id_value))
                    if not (v0 and v1 and v2):
                        continue
                    e1 = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
                    e2 = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
                    h = (
                        rd[1] * e2[2] - rd[2] * e2[1],
                        rd[2] * e2[0] - rd[0] * e2[2],
                        rd[0] * e2[1] - rd[1] * e2[0],
                    )
                    det = e1[0] * h[0] + e1[1] * h[1] + e1[2] * h[2]
                    if abs(det) < 1e-7:
                        continue
                    inv_det = 1.0 / det
                    s = (ro[0] - v0[0], ro[1] - v0[1], ro[2] - v0[2])
                    u_b = inv_det * (s[0] * h[0] + s[1] * h[1] + s[2] * h[2])
                    if u_b < 0.0 or u_b > 1.0:
                        continue
                    q = (
                        s[1] * e1[2] - s[2] * e1[1],
                        s[2] * e1[0] - s[0] * e1[2],
                        s[0] * e1[1] - s[1] * e1[0],
                    )
                    v_b = inv_det * (rd[0] * q[0] + rd[1] * q[1] + rd[2] * q[2])
                    if v_b < 0.0 or u_b + v_b > 1.0:
                        continue
                    t_val = inv_det * (e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2])
                    if 1.0 < t_val < best_t:
                        best_t = t_val
                        w0 = 1.0 - u_b - v_b
                        uv0 = smd.get_vertex_instance_uv(vi0, 0)
                        uv1 = smd.get_vertex_instance_uv(vi1, 0)
                        uv2 = smd.get_vertex_instance_uv(vi2, 0)
                        hit_u = (w0 * float(uv0.x) + u_b * float(uv1.x) + v_b * float(uv2.x)) % 1.0
                        hit_v = (w0 * float(uv0.y) + u_b * float(uv1.y) + v_b * float(uv2.y)) % 1.0
                        hit_world = unreal.Vector(
                            ro[0] + rd[0] * t_val,
                            ro[1] + rd[1] * t_val,
                            ro[2] + rd[2] * t_val,
                        )
                        best_hit = {
                            "actor": act,
                            "component": comp,
                            "u": hit_u,
                            "v": hit_v,
                            "world_pos": hit_world,
                            "dist": t_val,
                        }
    return best_hit


def paint_layer_mask_at_aimed_uv(
    ue_folder: str = DEFAULT_UE_FOLDER,
    erase: bool = False,
    radius_uv: float = 0.14,
) -> bool:
    """
    Per-pixel Viewport Mask Painter: raycasts from the Viewport Camera onto the aimed mesh surface,
    computes the exact UV coordinate, paints a soft organic brush stroke into a persistent 512x512
    mask texture (T_LivePaintMask_<MI>_L<k>), imports it into UE5, and binds it to the active Corona Layer!
    """
    hit = _pick_uv_under_camera_ray()
    if not hit:
        _set_panel_status(
            "[!] Aim the Viewport Camera crosshair at a mesh surface to paint its layer mask!",
            color=(1.0, 0.72, 0.3, 1.0),
        )
        return False

    base_dir = _normalize_ue_folder(ue_folder)
    if base_dir.split("/")[-1].lower() in [c.lower() for c in MATERIAL_CATEGORIES] or base_dir.split("/")[-1] == TEXTURES_SUBFOLDER:
        base_dir = "/".join(base_dir.split("/")[:-1]) or DEFAULT_UE_FOLDER
    mi = _get_active_layer_a_mi(base_dir)
    if not mi:
        _set_panel_status("[!] Select or generate a Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
        return False

    l_idx = 1
    try:
        ed_c = getattr(builtins, "_COMFY_EDIT_MASK_LAYER_COMBO", None)
        if ed_c:
            m = re.search(r"(\d+)", str(ed_c.get_selected_option() or "1"))
            if m:
                l_idx = max(1, min(10, int(m.group(1))))
    except Exception:
        l_idx = 1

    clean_mi = re.sub(r"[^A-Za-z0-9_]", "_", mi.get_name())
    mask_name = f"T_LivePaintMask_{clean_mi}_L{l_idx}"
    paint_dir = os.path.join(_SCRIPT_DIR, "LivePaintMasks")
    os.makedirs(paint_dir, exist_ok=True)
    png_path = os.path.join(paint_dir, f"{mask_name}.png")

    u_hit = float(hit["u"])
    v_hit = float(hit["v"])
    try:
        world = unreal.EditorLevelLibrary.get_editor_world()
        unreal.SystemLibrary.draw_debug_sphere(
            world,
            hit["world_pos"],
            12.0,
            16,
            unreal.LinearColor(1.0, 0.35, 0.25, 1.0) if erase else unreal.LinearColor(0.25, 1.0, 0.55, 1.0),
            0.45,
            1.8,
        )
    except Exception:
        pass

    import subprocess
    py_exe = r"D:\AI\ComfyUI_windows_portable\python_embeded\python.exe"
    if not os.path.exists(py_exe):
        py_exe = "python"

    paint_script = r"""
import os, sys, cv2, numpy as np
png_p, u_s, v_s, rad_s, erase_s = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
sz = 512
if os.path.exists(png_p):
    img = cv2.imread(png_p, cv2.IMREAD_GRAYSCALE)
    if img is None or img.shape != (sz, sz):
        img = np.zeros((sz, sz), dtype=np.uint8)
else:
    img = np.zeros((sz, sz), dtype=np.uint8)

yy, xx = np.mgrid[0:sz, 0:sz].astype(np.float32) / float(sz)
# Tile-aware shortest UV distance
dx = np.minimum(np.abs(xx - u_s), 1.0 - np.abs(xx - u_s))
dy = np.minimum(np.abs(yy - v_s), 1.0 - np.abs(yy - v_s))
dist = np.sqrt(dx * dx + dy * dy)
falloff = np.clip(1.0 - (dist / max(rad_s, 0.01)), 0.0, 1.0)
falloff = falloff * falloff * (3.0 - 2.0 * falloff)
brush = (falloff * 235.0).astype(np.float32)
cur = img.astype(np.float32)
if erase_s:
    out = np.clip(cur - brush, 0.0, 255.0).astype(np.uint8)
else:
    out = np.clip(np.maximum(cur, cur * 0.35 + brush), 0.0, 255.0).astype(np.uint8)
cv2.imwrite(png_p, out)
"""
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    subprocess.run(
        [py_exe, "-c", paint_script, png_path, str(u_hit), str(v_hit), str(radius_uv), "1" if erase else "0"],
        capture_output=True,
        timeout=10,
        creationflags=cflags,
    )

    if not os.path.exists(png_path):
        return False

    tex_dest = f"{base_dir}/{MASKS_SUBFOLDER}"
    unreal.EditorAssetLibrary.make_directory(tex_dest)
    task = unreal.AssetImportTask()
    task.filename = png_path
    task.destination_path = tex_dest
    task.destination_name = mask_name
    task.replace_existing = True
    task.save = True
    task.automated = True
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    if hasattr(asset_tools, "import_asset_tools_tasks"):
        asset_tools.import_asset_tools_tasks([task])
    else:
        asset_tools.import_asset_tasks([task])

    mask_ue_path = f"{tex_dest}/{mask_name}"
    mask_tex = unreal.EditorAssetLibrary.load_asset(mask_ue_path)
    if mask_tex:
        mask_tex.set_editor_property("srgb", False)
        unreal.EditorAssetLibrary.save_loaded_asset(mask_tex)

        mk_map = getattr(builtins, "_COMFY_MASK_MAP", {})
        mk_map[mask_name] = mask_ue_path
        builtins._COMFY_MASK_MAP = mk_map

        mel = unreal.MaterialEditingLibrary
        param_tex = "BlendMaskTexture" if l_idx == 1 else f"Layer{min(l_idx, 4)}_MaskTexture"
        param_en = "LayerB_Enable" if l_idx == 1 else f"Layer{min(l_idx, 4)}_Enable"
        param_use = "LayerB_Use_Mask" if l_idx == 1 else f"Layer{min(l_idx, 4)}_Use_Mask"
        param_str = "Blend_Mask_Strength" if l_idx == 1 else f"Layer{min(l_idx, 4)}_Mask_Strength"

        mel.set_material_instance_texture_parameter_value(
            mi, param_tex, mask_tex, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
        )
        mel.set_material_instance_scalar_parameter_value(
            mi, param_en, 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
        )
        mel.set_material_instance_scalar_parameter_value(
            mi, param_use, 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
        )
        mel.set_material_instance_scalar_parameter_value(
            mi, param_str, 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
        )
        mel.update_material_instance(mi)
        unreal.EditorAssetLibrary.save_loaded_asset(mi)

    act_mode = "Erased" if erase else "Painted"
    _set_panel_status(
        f"[Viewport Mask Paint] {act_mode} Layer {l_idx} mask '{mask_name}' at UV ({u_hit:.2f}, {v_hit:.2f})!",
        color=(0.45, 0.96, 0.65, 1.0),
    )
    return True


def enable_vertex_paint_on_selected(ue_folder: str = DEFAULT_UE_FOLDER) -> int:
    """
    Enables UE 5.5–5.7 Texture Color & Vertex Color Mesh Painting on selected StaticMeshComponents
    (with 256px MeshPaintVirtualTexture resolution override and UV channel 0 override) and activates
    Vertex_Paint_Strength = 1.0 on the active Material Instance (R = Layer 1, G = Layer 2, B = Layer 3, A = Layer 4).
    """
    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    sel_actors = a_sub.get_selected_level_actors() if a_sub else []
    target_actors = list(sel_actors) if sel_actors else (a_sub.get_all_level_actors() if a_sub else [])
    cnt = 0
    for act in target_actors:
        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
            try:
                comp.set_editor_property("enable_vertex_color_mesh_painting", True)
                comp.set_editor_property("enable_texture_color_mesh_painting", True)
                comp.set_editor_property("override_mesh_paint_texture_coordinate_index", True)
                comp.set_editor_property("overridden_mesh_paint_texture_coordinate_index", 0)
                comp.set_editor_property("override_mesh_paint_texture_resolution", True)
                comp.set_editor_property("overridden_mesh_paint_texture_resolution", 256)
                cnt += 1
            except Exception:
                pass

    mi = _get_active_layer_a_mi(ue_folder)
    if mi and isinstance(mi, unreal.MaterialInstanceConstant):
        mel = unreal.MaterialEditingLibrary
        for k_p, v_p in (
            ("Vertex_Paint_Strength", 1.0),
            ("LayerB_Enable", 1.0),
        ):
            try:
                mel.set_material_instance_scalar_parameter_value(
                    mi, k_p, v_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            except Exception:
                pass
        mel.update_material_instance(mi)
        unreal.EditorAssetLibrary.save_loaded_asset(mi)
        _sync_spinboxes_from_mi(mi)

    _set_panel_status(
        f"[Mesh Paint Ready] Texture Color (UV0, 256px) & Vertex Paint enabled on {cnt} mesh(es) (R=Layer1, G=Layer2, B=Layer3, A=Layer4)!",
        color=(0.45, 0.96, 0.65, 1.0),
    )
    return cnt


def _load_preset_library_dict() -> dict:
    """Loads saved studio presets from studio_material_library.json merged with built-in studio presets."""
    lib = dict(BUILTIN_STUDIO_LIBRARY_PRESETS)
    if os.path.exists(PRESET_LIBRARY_JSON_PATH):
        try:
            with open(PRESET_LIBRARY_JSON_PATH, "r", encoding="utf-8") as f:
                user_lib = json.load(f)
            if isinstance(user_lib, dict):
                lib.update(user_lib)
        except Exception:
            pass
    return lib


def save_material_preset_to_library(ue_folder: str = DEFAULT_UE_FOLDER) -> str:
    """
    Saves the active Material Instance's complete scalar, vector, texture, and 10-layer Corona state
    into studio_material_library.json so it can be reused across projects or batch-exported.
    """
    mi = _get_active_layer_a_mi(ue_folder)
    if not mi or not isinstance(mi, unreal.MaterialInstanceConstant):
        _set_panel_status("[!] Select or generate a Material Instance first to save a preset!", color=(1.0, 0.72, 0.3, 1.0))
        return ""

    mel = unreal.MaterialEditingLibrary
    parent_m = mi.get_editor_property("parent")
    parent_path = parent_m.get_path_name().split(".")[0] if parent_m else DEFAULT_MASTER_MAT_PATH

    scalars = {}
    for p_name in mel.get_scalar_parameter_names(mi):
        s_key = str(p_name)
        try:
            val = float(mel.get_material_instance_scalar_parameter_value(mi, s_key, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
            scalars[s_key] = round(val, 4)
        except Exception:
            pass

    textures = {}
    for t_name in mel.get_texture_parameter_names(mi):
        t_key = str(t_name)
        try:
            tex = mel.get_material_instance_texture_parameter_value(mi, t_key, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
            if tex:
                textures[t_key] = tex.get_path_name().split(".")[0]
        except Exception:
            pass

    mi_key = mi.get_path_name().split(".")[0]
    corona_layers = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {}).get(mi_key, {})

    preset_title = f"[Saved] {mi.get_name()}"
    lib = _load_preset_library_dict()
    lib[preset_title] = {
        "mi_name": mi.get_name(),
        "mi_path": mi_key,
        "master_material": parent_path,
        "scalars": scalars,
        "textures": textures,
        "corona_layers": {str(k): v for k, v in corona_layers.items()} if isinstance(corona_layers, dict) else {},
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    user_only = {k: v for k, v in lib.items() if k not in BUILTIN_STUDIO_LIBRARY_PRESETS}
    try:
        with open(PRESET_LIBRARY_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(user_only, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        unreal.log_warning(f"ComfyUI Preset Library Save Error: {exc}")

    lib_c = getattr(builtins, "_COMFY_PRESET_LIB_COMBO", None)
    if lib_c:
        builtins._COMFY_SYNCING_UI = True
        try:
            lib_c.add_option(preset_title)
            lib_c.set_selected_option(preset_title)
        finally:
            builtins._COMFY_SYNCING_UI = False

    _set_panel_status(
        f"[Library Saved] Saved '{preset_title}' ({len(scalars)} params, {len(textures)} maps) to studio_material_library.json!",
        color=(0.45, 0.96, 0.65, 1.0),
    )
    return preset_title


def load_material_preset_from_library(preset_name: str, ue_folder: str = DEFAULT_UE_FOLDER) -> bool:
    """Applies a saved or built-in Studio Library preset onto the active Material Instance and selected actor."""
    lib = _load_preset_library_dict()
    entry = lib.get(preset_name)
    if not entry:
        _set_panel_status(f"[!] Library preset '{preset_name}' not found!", color=(1.0, 0.72, 0.3, 1.0))
        return False

    mi = _get_active_layer_a_mi(ue_folder)
    if not mi or not isinstance(mi, unreal.MaterialInstanceConstant):
        _set_panel_status("[!] Select or generate a Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
        return False

    mel = unreal.MaterialEditingLibrary
    for t_key, t_path in entry.get("textures", {}).items():
        try:
            if t_path and unreal.EditorAssetLibrary.does_asset_exist(t_path):
                tex_obj = unreal.EditorAssetLibrary.load_asset(t_path)
                if tex_obj:
                    mel.set_material_instance_texture_parameter_value(
                        mi, t_key, tex_obj, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
        except Exception:
            pass

    for s_key, s_val in entry.get("scalars", {}).items():
        try:
            mel.set_material_instance_scalar_parameter_value(
                mi, s_key, float(s_val), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
        except Exception:
            pass

    mel.update_material_instance(mi)
    unreal.EditorAssetLibrary.save_loaded_asset(mi)
    _sync_spinboxes_from_mi(mi)
    slot_id = _get_selected_poly_target_id(default_for_assign=-1)
    apply_material_to_selected_actors(mi, slot_idx=slot_id)
    _set_panel_status(
        f"[Library Applied] Loaded preset '{preset_name}' onto '{mi.get_name()}'!",
        color=(0.45, 0.96, 0.65, 1.0),
    )
    return True


def export_material_library_pack(ue_folder: str = DEFAULT_UE_FOLDER) -> str:
    """
    Batch-exports all Material Instances in /Game/Textures/ComfyUI and the Studio Library into a portable
    JSON Material Pack (D:/AI/PlagimUE_AI/Exported_Material_Pack.json) for cross-project sharing.
    """
    save_material_preset_to_library(ue_folder)
    lib = _load_preset_library_dict()
    base_dir = _normalize_ue_folder(ue_folder)
    all_mis = _discover_material_instances(base_dir)
    mel = unreal.MaterialEditingLibrary

    catalog = []
    for mi_p in all_mis:
        try:
            mi_obj = unreal.EditorAssetLibrary.load_asset(mi_p)
            if not isinstance(mi_obj, unreal.MaterialInstanceConstant):
                continue
            parent_m = mi_obj.get_editor_property("parent")
            t_dict = {}
            for t_name in mel.get_texture_parameter_names(mi_obj):
                tex = mel.get_material_instance_texture_parameter_value(
                    mi_obj, str(t_name), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
                if tex:
                    t_dict[str(t_name)] = tex.get_path_name().split(".")[0]
            catalog.append({
                "name": mi_obj.get_name(),
                "path": mi_p,
                "master_material": parent_m.get_path_name().split(".")[0] if parent_m else "",
                "textures": t_dict,
            })
        except Exception:
            pass

    export_path = os.path.join(_SCRIPT_DIR, "Exported_Material_Pack.json")
    pack_data = {
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_folder": base_dir,
        "total_materials": len(catalog),
        "studio_presets": lib,
        "materials_catalog": catalog,
    }
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(pack_data, f, indent=2, ensure_ascii=False)

    _set_panel_status(
        f"[Batch Export OK] Exported {len(catalog)} materials & {len(lib)} presets -> {export_path}",
        color=(0.45, 0.96, 0.65, 1.0),
    )
    return export_path


def _refresh_prompt_master_combo(combo, ue_folder: str = DEFAULT_UE_FOLDER, select_path: str = "") -> None:
    """
    Refreshes the dedicated Master Material dropdown (PromptMasterMatCombo) in Section 1 (Prompt)
    with all Master Materials (MM_ComfyPBR_Master, MM_ArchViz_Decal, MM_ArchViz_Glass, MM_ArchViz_Fabric,
    MM_ArchViz_Foliage, MM_ArchViz_Emissive, etc.).
    """
    if not combo:
        return
    try:
        mm_map = getattr(builtins, "_COMFY_MM_MAP", {})
        if not isinstance(mm_map, dict):
            mm_map = {}
        current_raw = (
            select_path
            or str(combo.get_selected_option() or "").strip()
            or getattr(builtins, "_COMFY_PROMPT_MASTER_MAT_PATH", "")
            or getattr(builtins, "_COMFY_MASTER_MAT_PATH", DEFAULT_MASTER_MAT_PATH)
        )
        current_full = mm_map.get(current_raw, current_raw)
        mm_options = _discover_master_materials(ue_folder)
        builtins._COMFY_SYNCING_UI = True
        try:
            combo.clear_options()
            short_options = []
            for full_path in mm_options:
                short_name = full_path.split("/")[-1]
                mm_map[short_name] = full_path
                if short_name not in short_options:
                    short_options.append(short_name)
                    combo.add_option(short_name)
            builtins._COMFY_MM_MAP = mm_map
            current_short = current_full.split("/")[-1] if current_full else DEFAULT_MASTER_MAT_NAME
            if current_short and current_short in short_options:
                combo.set_selected_option(current_short)
            elif short_options:
                combo.set_selected_option(short_options[0])
        finally:
            builtins._COMFY_SYNCING_UI = False
    except Exception:
        pass


def _get_selected_actor_active_mi():
    """Returns the MaterialInstanceConstant assigned to the currently selected viewport actor (active slot or Decal)."""
    try:
        actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        sel_actors = actor_sub.get_selected_level_actors() if actor_sub else []
        aim_poly_on = bool(getattr(builtins, "_COMFY_POLY_AIM_ACTIVE", False))
        if aim_poly_on and getattr(builtins, "_COMFY_AIMED_SLOT_ID", None) is not None:
            active_slot = int(getattr(builtins, "_COMFY_AIMED_SLOT_ID", 0))
        else:
            active_slot = max(0, _get_selected_poly_target_id(default_for_assign=0))
        for act in sel_actors:
            for comp in act.get_components_by_class(unreal.StaticMeshComponent):
                n_mats = comp.get_num_materials()
                if n_mats > 0:
                    check_slot = active_slot if active_slot < n_mats else 0
                    mat_s = comp.get_material(check_slot)
                    if isinstance(mat_s, unreal.MaterialInstanceConstant):
                        return mat_s
                for idx in range(n_mats):
                    mat_i = comp.get_material(idx)
                    if isinstance(mat_i, unreal.MaterialInstanceConstant):
                        return mat_i
            for d_comp in act.get_components_by_class(unreal.DecalComponent):
                d_mat = d_comp.get_decal_material()
                if isinstance(d_mat, unreal.MaterialInstanceConstant):
                    return d_mat
    except Exception:
        pass
    return None


def _refresh_master_combo(combo, ue_folder: str = DEFAULT_UE_FOLDER, select_path: str = "") -> None:
    """
    Refreshes the list of available Material Instances (MI_*) AND Master Materials (MM_*)
    in MasterMatComboBox using short asset names, so the user can directly pick and assign
    any Material Instance or Master Material from Section 3!
    """
    if not combo:
        return
    try:
        mm_map = getattr(builtins, "_COMFY_MM_MAP", {})
        if not isinstance(mm_map, dict):
            mm_map = {}
        actor_mi = _get_selected_actor_active_mi()
        last_mi = getattr(builtins, "_COMFY_LAST_MATERIAL", None)
        pref_path = (
            select_path
            or (actor_mi.get_path_name().split(".")[0] if actor_mi else "")
            or (last_mi.get_path_name().split(".")[0] if isinstance(last_mi, unreal.MaterialInstanceConstant) else "")
            or str(combo.get_selected_option() or "").strip()
            or getattr(builtins, "_COMFY_MASTER_MAT_PATH", DEFAULT_MASTER_MAT_PATH)
        )
        current_full = mm_map.get(pref_path, pref_path)
        mi_options = _discover_material_instances(ue_folder)
        mm_options = _discover_master_materials(ue_folder)
        options = list(mi_options) + [p for p in mm_options if p not in mi_options]
        if current_full and current_full.startswith("/Game") and current_full not in options:
            options.insert(0, current_full)
        builtins._COMFY_SYNCING_UI = True
        try:
            combo.clear_options()
            short_options = []
            for full_path in options:
                short_name = full_path.split("/")[-1]
                mm_map[short_name] = full_path
                if short_name not in short_options:
                    short_options.append(short_name)
                    combo.add_option(short_name)
            builtins._COMFY_MM_MAP = mm_map
            current_short = current_full.split("/")[-1] if current_full else ""
            if current_short and current_short in short_options:
                combo.set_selected_option(current_short)
            elif short_options:
                combo.set_selected_option(short_options[0])
        finally:
            builtins._COMFY_SYNCING_UI = False
    except Exception:
        pass


def _discover_material_instances(ue_folder: str = DEFAULT_UE_FOLDER) -> list:
    """Finds all MaterialInstanceConstant (MI_*) assets inside the target folder and subfolders."""
    ue_folder = _normalize_ue_folder(ue_folder)
    found = []
    for search_dir in (ue_folder, DEFAULT_UE_FOLDER):
        try:
            for a_path in unreal.EditorAssetLibrary.list_assets(search_dir, recursive=True):
                clean = a_path.split(".")[0]
                name = clean.split("/")[-1]
                if name.startswith("MI_") and clean not in found:
                    found.append(clean)
        except Exception:
            pass
    return found


def _discover_mask_textures(ue_folder: str = DEFAULT_UE_FOLDER) -> list:
    """Finds available B&W masks (in Masks/ first) and grayscale/height/roughness textures suitable for mask blending."""
    ue_folder = _normalize_ue_folder(ue_folder)
    dedicated_masks = []
    other_masks = []
    for search_dir in (ue_folder, DEFAULT_UE_FOLDER):
        try:
            for a_path in unreal.EditorAssetLibrary.list_assets(search_dir, recursive=True):
                clean = a_path.split(".")[0]
                name = clean.split("/")[-1]
                if name.startswith(("T_Mask_", "T_LivePaintMask_")) or f"/{MASKS_SUBFOLDER}/" in clean:
                    if clean not in dedicated_masks:
                        dedicated_masks.append(clean)
                elif name.startswith("T_") and (
                    "Height" in name or "Roughness" in name or "Mask" in name or "Albedo" in name
                ):
                    if clean not in other_masks and clean not in dedicated_masks:
                        other_masks.append(clean)
        except Exception:
            pass
    return dedicated_masks + other_masks


def _resolve_mi_path(name_or_path: str) -> str:
    """Resolves a short MI_* name displayed in a ComboBox back to its full Content Browser path."""
    s = (name_or_path or "").strip()
    if not s:
        return ""
    mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
    if s in mi_map:
        return mi_map[s]
    return s


def _resolve_mask_path(name_or_path: str) -> str:
    """Resolves a short T_* texture name displayed in MaskCombo back to its full Content Browser path."""
    s = (name_or_path or "").strip()
    if not s:
        return ""
    mask_map = getattr(builtins, "_COMFY_MASK_MAP", {})
    if s in mask_map:
        return mask_map[s]
    return s


def _matches_search_query(full_path: str, query_text: str) -> bool:
    """Returns True if all space-separated keywords in query_text match the asset name or category path."""
    q = (query_text or "").strip().lower()
    if not q:
        return True
    haystack = full_path.lower().replace("_", " ")
    # Also support Russian search keywords via translation map
    q_en = _translate_or_clean_prompt(q).lower()
    combined_tokens = [tok for tok in q.split() if tok]
    en_tokens = [tok for tok in q_en.split() if tok]
    for idx, tok in enumerate(combined_tokens):
        if tok in haystack:
            continue
        if idx < len(en_tokens) and en_tokens[idx] in haystack:
            continue
        if any(et in haystack for et in en_tokens):
            continue
        return False
    return True


def _discover_albedo_textures(ue_folder: str = DEFAULT_UE_FOLDER) -> list:
    """Finds all PBR Albedo textures (T_*_Albedo) inside /Game/Textures/ComfyUI/Textures/<category>/ and ue_folder."""
    ue_folder = _normalize_ue_folder(ue_folder)
    found = []
    tex_map = getattr(builtins, "_COMFY_TEX_MAP", {})
    if not isinstance(tex_map, dict):
        tex_map = {}
    for search_dir in (f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}", ue_folder, DEFAULT_UE_FOLDER):
        try:
            for a_path in unreal.EditorAssetLibrary.list_assets(search_dir, recursive=True):
                clean = a_path.split(".")[0]
                name = clean.split("/")[-1]
                if name.startswith("T_") and not name.startswith("T_Default_"):
                    tex_map[name] = clean
                    if name.endswith("_Albedo") and clean not in found:
                        found.append(clean)
        except Exception:
            pass
    builtins._COMFY_TEX_MAP = tex_map
    return found


def _assign_pbr_textures_by_stem_to_layer_slot(target_mi, name_or_tex, slot_idx: int = 1) -> str:
    """
    Directly assigns a PBR texture set (T_<stem>_Albedo, _Normal, _Roughness, _Height) into
    target_mi's LayerB_* (slot 1), Layer2_* (slot 2), Layer3_* (slot 3), or Layer4_* (slot 4) parameters
    (or Seam_* if slot_idx == 0). Also copies scalar PBR settings from MI_<stem> if one exists.
    Returns the short Albedo texture name (e.g. 'T_<stem>_Albedo').
    """
    if not target_mi:
        return "None"
    mel = unreal.MaterialEditingLibrary
    pfx = "Seam" if slot_idx == 0 else ("LayerB" if slot_idx == 1 else f"Layer{slot_idx}")

    tex_obj = name_or_tex if isinstance(name_or_tex, unreal.Texture) else None
    raw_name = ""
    t_dir = ""
    if tex_obj:
        t_path = tex_obj.get_path_name().split(".")[0]
        t_dir = "/".join(t_path.split("/")[:-1])
        raw_name = t_path.split("/")[-1]
    else:
        raw_name = str(name_or_tex or "").strip().split("/")[-1].split(".")[0]

    if not raw_name or raw_name == "None":
        return "None"

    if raw_name.startswith("MI_"):
        t_stem = raw_name[3:]
    else:
        t_stem = _extract_texture_base_stem(raw_name)

    # 1. If a corresponding MaterialInstance MI_<stem> exists, copy its scalar/vector PBR properties first
    cand_mi_short = f"MI_{t_stem}"
    resolved_mi = _resolve_mi_path(cand_mi_short)
    if resolved_mi and unreal.EditorAssetLibrary.does_asset_exist(resolved_mi):
        src_mi = unreal.EditorAssetLibrary.load_asset(resolved_mi)
        if src_mi and isinstance(src_mi, unreal.MaterialInstanceConstant):
            combine_material_into_layer_slot(
                target_mi, src_mi, slot_idx=slot_idx, enable_seams=False, update_and_save=False
            )

    # 2. Ensure _COMFY_TEX_MAP is populated and directly bind all 4 PBR textures (Albedo, Normal, Roughness, Height)
    tex_map = getattr(builtins, "_COMFY_TEX_MAP", {})
    if not tex_map or f"T_{t_stem}_Albedo" not in tex_map:
        _discover_albedo_textures(DEFAULT_UE_FOLDER)
        tex_map = getattr(builtins, "_COMFY_TEX_MAP", {})

    assigned_albedo_name = ""
    for sfx, dst_p in (
        ("_Albedo", f"{pfx}_AlbedoTexture"),
        ("_Normal", f"{pfx}_NormalTexture"),
        ("_Roughness", f"{pfx}_RoughnessTexture"),
        ("_Height", f"{pfx}_HeightTexture"),
    ):
        short_t = f"T_{t_stem}{sfx}"
        cand_paths = []
        if short_t in tex_map:
            cand_paths.append(tex_map[short_t])
        if t_dir:
            cand_paths.append(f"{t_dir}/{short_t}")
        for cat in MATERIAL_CATEGORIES:
            cand_paths.append(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/{cat}/{short_t}")
        for cp in cand_paths:
            if cp and unreal.EditorAssetLibrary.does_asset_exist(cp):
                sib_tex = unreal.EditorAssetLibrary.load_asset(cp)
                if sib_tex and isinstance(sib_tex, unreal.Texture):
                    mel.set_material_instance_texture_parameter_value(
                        target_mi, dst_p, sib_tex, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                    tex_map[short_t] = cp
                    if sfx == "_Albedo":
                        assigned_albedo_name = short_t
                    break

    if not assigned_albedo_name and tex_obj:
        mel.set_material_instance_texture_parameter_value(
            target_mi, f"{pfx}_AlbedoTexture", tex_obj, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
        )
        assigned_albedo_name = raw_name

    builtins._COMFY_TEX_MAP = tex_map
    return assigned_albedo_name or f"T_{t_stem}_Albedo"


def _get_active_layer_a_mi(ue_folder: str = DEFAULT_UE_FOLDER):
    """
    Returns the currently active Base Material Instance (Layer A).
    Prioritizes the Material Instance on the currently selected actor in the Level Viewport
    so that selecting a mesh in the viewport (e.g. Cube2) and assigning a texture/layer in BP_ComfyPanel
    always updates the selected mesh's material!
    """
    actor_mi = _get_selected_actor_active_mi()
    combo = getattr(builtins, "_COMFY_LAYER_A_COMBO", None)
    if actor_mi and isinstance(actor_mi, unreal.MaterialInstanceConstant):
        builtins._COMFY_LAST_MATERIAL = actor_mi
        if combo:
            try:
                m_path = actor_mi.get_path_name().split(".")[0]
                m_short = m_path.split("/")[-1]
                mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
                mi_map[m_short] = m_path
                builtins._COMFY_MI_MAP = mi_map
                cur_sel = str(combo.get_selected_option() or "").strip()
                if cur_sel != m_short:
                    prev_sync = getattr(builtins, "_COMFY_SYNCING_UI", False)
                    builtins._COMFY_SYNCING_UI = True
                    try:
                        if combo.find_option_index(m_short) < 0:
                            combo.add_option(m_short)
                        combo.set_selected_option(m_short)
                    finally:
                        builtins._COMFY_SYNCING_UI = prev_sync
            except Exception:
                pass
        return actor_mi
    if combo:
        try:
            sel = str(combo.get_selected_option() or "").strip()
            resolved = _resolve_mi_path(sel)
            if resolved and unreal.EditorAssetLibrary.does_asset_exist(resolved):
                obj = unreal.EditorAssetLibrary.load_asset(resolved)
                if obj and isinstance(obj, unreal.MaterialInstanceConstant):
                    builtins._COMFY_LAST_MATERIAL = obj
                    return obj
        except Exception:
            pass
    last = getattr(builtins, "_COMFY_LAST_MATERIAL", None)
    if last:
        return last
    mis = _discover_material_instances(ue_folder)
    if mis:
        obj = unreal.EditorAssetLibrary.load_asset(mis[0])
        if obj and isinstance(obj, unreal.MaterialInstanceConstant):
            builtins._COMFY_LAST_MATERIAL = obj
            return obj
    return None


def _get_or_create_widget(owner, is_wt: bool, cls, name: str):
    """Finds an existing named widget inside WidgetTree (or UserWidget) or creates a new named one."""
    if is_wt:
        found = unreal.find_object(owner, name)
        if found and isinstance(found, cls):
            return found
        return cls(owner, name)
    else:
        found = owner.find_child_widget_by_name(name)
        if found and isinstance(found, cls):
            return found
        try:
            return cls(owner, name)
        except Exception:
            return cls(owner)


def _place_on_canvas(
    canvas,
    widget_obj,
    pos_x: float,
    pos_y: float,
    width: float,
    height: float,
    apply_layout: bool = True,
):
    """Parents widget_obj onto canvas and sets its position/size only when apply_layout is True (or if unparented)."""
    need_parent = widget_obj.get_parent() != canvas
    if need_parent:
        if apply_layout or widget_obj.get_parent() is None:
            widget_obj.remove_from_parent()
            slot = canvas.add_child_to_canvas(widget_obj)
        else:
            slot = widget_obj.slot
    else:
        slot = widget_obj.slot
    if (apply_layout or need_parent) and slot and hasattr(slot, "set_position"):
        slot.set_position(unreal.Vector2D(pos_x, pos_y))
        slot.set_size(unreal.Vector2D(width, height))
    return slot


def _setup_named_label(
    owner,
    is_wt: bool,
    canvas,
    name: str,
    text_str: str,
    pos_x: float,
    pos_y: float,
    width: float,
    height: float,
    size: int = 8,
    bold: bool = True,
    color: tuple = (0.76, 0.82, 0.92, 1.0),
    apply_layout: bool = True,
):
    """Finds or creates a named TextBlock inside WidgetTree or UserWidget."""
    created_new = (unreal.find_object(owner, name) is None) if is_wt else (owner.find_child_widget_by_name(name) is None)
    lbl = _get_or_create_widget(owner, is_wt, unreal.TextBlock, name)
    if apply_layout or created_new:
        lbl.set_text(text_str)
        _style_text(lbl, size=size, bold=bold, color=color)
    _place_on_canvas(canvas, lbl, pos_x, pos_y, width, height, apply_layout=apply_layout)
    return lbl


def _setup_named_button(
    owner,
    is_wt: bool,
    canvas,
    btn_name: str,
    lbl_name: str,
    text_str: str,
    pos_x: float,
    pos_y: float,
    width: float,
    height: float,
    color: tuple = (0.92, 0.95, 1.0, 1.0),
    apply_layout: bool = True,
    tooltip: str = "",
):
    """Finds or creates a named EditorUtilityButton with a centered, non-wrapping TextBlock child."""
    created_new = (unreal.find_object(owner, btn_name) is None) if is_wt else (owner.find_child_widget_by_name(btn_name) is None)
    btn = _get_or_create_widget(owner, is_wt, unreal.EditorUtilityButton, btn_name)
    lbl = _get_or_create_widget(owner, is_wt, unreal.TextBlock, lbl_name)
    font_sz = 7 if (len(text_str) >= 16 and width <= 145.0) else 8
    if apply_layout or created_new or lbl.get_parent() != btn:
        lbl.set_text(text_str)
        _style_text(lbl, size=font_sz, bold=True, color=color)
        if lbl.get_parent() != btn:
            for c in list(btn.get_all_children()):
                c.remove_from_parent()
            btn.add_child(lbl)
        try:
            b_slot = lbl.slot
            if b_slot:
                if hasattr(b_slot, "set_padding"):
                    b_slot.set_padding(unreal.Margin(2.0, 1.0, 2.0, 1.0))
                if hasattr(b_slot, "set_horizontal_alignment"):
                    b_slot.set_horizontal_alignment(unreal.HorizontalAlignment.H_ALIGN_CENTER)
                if hasattr(b_slot, "set_vertical_alignment"):
                    b_slot.set_vertical_alignment(unreal.VerticalAlignment.V_ALIGN_CENTER)
        except Exception:
            pass
    if tooltip:
        try:
            btn.set_tool_tip_text(tooltip)
        except Exception:
            pass
    _place_on_canvas(canvas, btn, pos_x, pos_y, width, height, apply_layout=apply_layout)
    return btn


def _create_styled_spinbox(
    owner,
    canvas,
    label_text: str,
    pos_x: float,
    pos_y: float,
    width: float,
    default_val: float,
    min_val: float,
    max_val: float,
    step: float = 0.01,
    digits: int = 2,
    param_name: str = "",
    is_wt: bool = False,
    apply_layout: bool = True,
):
    """Finds or creates a named EditorUtilitySpinBox + Label for real-time parameter tweaking."""
    safe_key = param_name or re.sub(r"[^A-Za-z0-9_]", "_", label_text)
    lbl_name = f"SpinLbl_{safe_key}"
    sb_name = f"Spin_{safe_key}"

    _setup_named_label(
        owner,
        is_wt,
        canvas,
        lbl_name,
        label_text,
        pos_x,
        pos_y,
        width,
        14.0,
        size=8,
        bold=True,
        color=(0.74, 0.82, 0.94, 1.0),
        apply_layout=apply_layout,
    )

    created_new = (unreal.find_object(owner, sb_name) is None) if is_wt else (owner.find_child_widget_by_name(sb_name) is None)
    sb = _get_or_create_widget(owner, is_wt, unreal.EditorUtilitySpinBox, sb_name)
    if apply_layout or created_new:
        try:
            white_sc = unreal.SlateColor(unreal.LinearColor(0.96, 0.97, 1.0, 1.0))
            f = sb.get_editor_property("font")
            f.size = 9.0
            sb.set_editor_property("font", f)
            sb.set_editor_property("foreground_color", white_sc)
            sb.set_editor_property("min_fractional_digits", 1 if digits > 0 else 0)
            sb.set_editor_property("max_fractional_digits", digits)
            sb.set_editor_property("delta", step)
        except Exception:
            pass
        sb.set_min_value(min_val)
        sb.set_max_value(max_val)
        sb.set_min_slider_value(min_val)
        sb.set_max_slider_value(max_val)
        sb.set_value(default_val)
    else:
        try:
            sb.set_editor_property("min_fractional_digits", 1 if digits > 0 else 0)
            sb.set_editor_property("max_fractional_digits", digits)
            sb.set_editor_property("delta", step)
            sb.set_min_value(min_val)
            sb.set_max_value(max_val)
            sb.set_min_slider_value(min_val)
            sb.set_max_slider_value(max_val)
        except Exception:
            pass

    _place_on_canvas(canvas, sb, pos_x, pos_y + 15.0, width, 26.0, apply_layout=apply_layout)
    return sb


def _sync_spinboxes_from_mi(mi) -> None:
    """Updates all SpinBoxes in the panel to reflect the current scalar parameters of mi."""
    if not mi:
        return
    spin_map = getattr(builtins, "_COMFY_SPINBOX_MAP", {})
    mel = unreal.MaterialEditingLibrary
    mask_spin_keys = {
        "Blend_Mask_Tiling_X",
        "Blend_Mask_Tiling_Y",
        "Blend_Mask_Brightness",
        "Blend_Mask_Contrast",
        "Blend_Mask_Invert",
    }
    builtins._COMFY_SYNCING_UI = True
    try:
        for param_name, (sb, default_val) in spin_map.items():
            if param_name in mask_spin_keys:
                continue
            try:
                val = mel.get_material_instance_scalar_parameter_value(
                    mi,
                    param_name,
                    unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
                )
                sb.set_value(float(val))
            except Exception:
                sb.set_value(float(default_val))
        seams_trip_cb = getattr(builtins, "_COMFY_SEAMS_TRIP_CHECK", None)
        if seams_trip_cb:
            try:
                st_val = float(
                    mel.get_material_instance_scalar_parameter_value(
                        mi, "Seams_Triplanar", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                )
                seams_trip_cb.set_is_checked(bool(st_val >= 0.5))
            except Exception:
                seams_trip_cb.set_is_checked(False)
        at_trip_cb = getattr(builtins, "_COMFY_ANTITILE_TRIP_CHECK", None)
        if at_trip_cb:
            try:
                at_val = float(
                    mel.get_material_instance_scalar_parameter_value(
                        mi, "AntiTile_Triplanar", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                )
                at_trip_cb.set_is_checked(bool(at_val >= 0.5))
            except Exception:
                at_trip_cb.set_is_checked(False)
    finally:
        builtins._COMFY_SYNCING_UI = False


def _find_widget_any(owner, is_wt: bool, name: str):
    """Finds a child widget by name in either a WidgetTree or a live UserWidget."""
    if is_wt:
        return unreal.find_object(owner, name)
    return owner.find_child_widget_by_name(name)


def _clear_delegate_safe(delegate_obj) -> None:
    """Safely clears existing Python callables from a UMG multicast delegate before re-binding."""
    try:
        if hasattr(delegate_obj, "clear"):
            delegate_obj.clear()
    except Exception:
        pass


def bake_studio_ui_to_blueprint(force_reset_layout: bool = False) -> bool:
    """
    Запекает весь интерфейс ComfyUI PBR & Substance Studio напрямую внутрь WidgetTree блюпринта BP_ComfyPanel,
    компилирует и сохраняет BP_ComfyPanel.uasset, чтобы все элементы отображались и редактировались в UMG Designer.
    Если элементы уже запечены и force_reset_layout=False, пользовательская вёрстка не перезаписывается.
    """
    try:
        _ensure_panel_uasset_in_project()
        if not unreal.EditorAssetLibrary.does_asset_exist(PANEL_ASSET_PATH):
            return False
        bp = unreal.EditorAssetLibrary.load_asset(PANEL_ASSET_PATH)
        if not bp:
            return False
        wt = unreal.find_object(bp, "WidgetTree")
        if not wt:
            return False

        already_in_wt = (
            unreal.find_object(wt, "StudioInnerCanvas") is not None
            and unreal.find_object(wt, "StudioStatusBarLabel") is not None
            and unreal.find_object(wt, "FindBlendMaskBtn") is not None
            and unreal.find_object(wt, "Layer10MaskComboBox") is not None
            and unreal.find_object(wt, "Layer1MaskTriplanarCheck") is not None
            and unreal.find_object(wt, "SeamsTriplanarCheck") is not None
            and unreal.find_object(wt, "SeamMtlComboBox") is not None
            and unreal.find_object(wt, "TileLayerDMtlComboBox") is not None
            and unreal.find_object(wt, "Spin_Seam_Width_V") is not None
            and unreal.find_object(wt, "Spin_Seam_Edge_Irregularity") is not None
            and unreal.find_object(wt, "SeamsOnlyBtn") is not None
            and unreal.find_object(wt, "BakeMixedMtlBtn") is not None
            and unreal.find_object(wt, "BlendPresetBtn_7") is not None
            and unreal.find_object(wt, "AntiTileSectionHeaderLabel") is not None
        )
        if already_in_wt and not force_reset_layout:
            return True

        # Remove legacy placeholder labels from WidgetTree before baking
        for old_name in ("TextBlock_1", "TestCheckLabel"):
            old_w = unreal.find_object(wt, old_name)
            if old_w:
                try:
                    old_w.remove_from_parent()
                except Exception:
                    pass

        enhance_comfy_panel_ui(wt, is_wt=True, apply_layout=True)
        unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        unreal.EditorAssetLibrary.save_loaded_asset(bp)
        return True
    except Exception as exc:
        unreal.log_warning(f"ComfyUI PBR: bake_studio_ui_to_blueprint warning: {exc}")
        return False


def enhance_comfy_panel_ui(widget=None, is_wt: bool = False, apply_layout: bool = None):
    """
    Builds or binds the full ComfyUI Seamless PBR & Substance Material Studio interface inside BP_ComfyPanel:
    - When called with is_wt=True on BP_ComfyPanel:WidgetTree, bakes all named widgets into the Blueprint.
    - When called on a live EditorUtilityWidget instance, preserves any layout edits made in UMG Designer
      (apply_layout=False when already baked) and binds all interactive Python callbacks.
    """
    if not is_wt:
        bake_studio_ui_to_blueprint(force_reset_layout=False)
        w = _get_open_panel_widget() or widget
    else:
        w = widget or _get_open_panel_widget()
    if not w:
        return None

    btn = _find_widget_any(w, is_wt, "GenerateBtn")
    prompt_box = _find_widget_any(w, is_wt, "PromptInput")
    path_box = _find_widget_any(w, is_wt, "PathInput")
    if not btn:
        return w

    existing_inner = _find_widget_any(w, is_wt, "StudioInnerCanvas")
    existing_status = _find_widget_any(w, is_wt, "StudioStatusBarLabel")
    existing_find_mask = _find_widget_any(w, is_wt, "FindBlendMaskBtn")
    existing_l10_mask = _find_widget_any(w, is_wt, "Layer10MaskComboBox")
    existing_edit_mask_layer = _find_widget_any(w, is_wt, "EditMaskLayerComboBox")
    existing_tiling_x = _find_widget_any(w, is_wt, "Spin_Blend_Mask_Tiling_X")
    existing_gen_ref_btn = _find_widget_any(w, is_wt, "GenerateRefBtn")
    existing_poly_id_btn = _find_widget_any(w, is_wt, "AssignPolyIDBtn")
    existing_spawn_decal_btn = _find_widget_any(w, is_wt, "SpawnDecalBtn")
    existing_decal_cat_btn = _find_widget_any(w, is_wt, "CatBtn_decal")
    existing_prompt_mm_combo = _find_widget_any(w, is_wt, "PromptMasterMatCombo")
    existing_seam_mtl_combo = _find_widget_any(w, is_wt, "SeamMtlComboBox")
    existing_tile_ld_combo = _find_widget_any(w, is_wt, "TileLayerDMtlComboBox")
    existing_seam_w_v = _find_widget_any(w, is_wt, "Spin_Seam_Width_V")
    existing_seam_edge_irreg = _find_widget_any(w, is_wt, "Spin_Seam_Edge_Irregularity")
    existing_seams_only_btn = _find_widget_any(w, is_wt, "SeamsOnlyBtn")
    existing_bake_mixed_btn = _find_widget_any(w, is_wt, "BakeMixedMtlBtn")
    existing_blend_btn_7 = _find_widget_any(w, is_wt, "BlendPresetBtn_7")
    existing_antitile_hdr = _find_widget_any(w, is_wt, "AntiTileSectionHeaderLabel")
    already_baked = (
        existing_inner is not None
        and existing_status is not None
        and existing_find_mask is not None
        and existing_l10_mask is not None
        and existing_edit_mask_layer is not None
        and existing_tiling_x is not None
        and existing_gen_ref_btn is not None
        and existing_poly_id_btn is not None
        and existing_spawn_decal_btn is not None
        and existing_decal_cat_btn is not None
        and existing_prompt_mm_combo is not None
        and existing_seam_mtl_combo is not None
        and existing_tile_ld_combo is not None
        and existing_seam_w_v is not None
        and existing_seam_edge_irreg is not None
        and existing_seams_only_btn is not None
        and existing_bake_mixed_btn is not None
        and existing_blend_btn_7 is not None
        and existing_antitile_hdr is not None
    )

    if apply_layout is None:
        apply_layout = not already_baked

    # Find the outermost Root CanvasPanel
    root_canvas = _find_widget_any(w, is_wt, "CanvasPanel_0")
    if not root_canvas:
        curr_p = btn.get_parent()
        while curr_p:
            if isinstance(curr_p, unreal.CanvasPanel):
                root_canvas = curr_p
            curr_p = curr_p.get_parent()
    if not root_canvas and not is_wt:
        root_canvas = getattr(builtins, "_COMFY_ROOT_CANVAS", None)
    if not root_canvas:
        return w
    if not is_wt:
        builtins._COMFY_ROOT_CANVAS = root_canvas

    if apply_layout:
        keep_widgets = {prompt_box, btn, path_box}
        for kw in keep_widgets:
            if kw and kw.get_parent() != root_canvas:
                kw.remove_from_parent()
                root_canvas.add_child_to_canvas(kw)

        scroll_box = _get_or_create_widget(w, is_wt, unreal.EditorUtilityScrollBox, "StudioScrollBox")
        size_box = _get_or_create_widget(w, is_wt, unreal.SizeBox, "StudioSizeBox")
        canvas = _get_or_create_widget(w, is_wt, unreal.CanvasPanel, "StudioInnerCanvas")

        for ch in list(root_canvas.get_all_children()):
            if ch not in keep_widgets and ch != scroll_box:
                ch.remove_from_parent()

        try:
            scroll_box.set_always_show_scrollbar(True)
            scroll_box.set_animate_wheel_scrolling(True)
            scroll_box.set_wheel_scroll_multiplier(1.2)
            scroll_box.set_editor_property("wheel_scroll_multiplier", 1.2)
        except Exception:
            pass

        if scroll_box.get_parent() != root_canvas:
            scroll_box.remove_from_parent()
            scroll_slot = root_canvas.add_child_to_canvas(scroll_box)
        else:
            scroll_slot = scroll_box.slot
        try:
            scroll_slot.set_anchors(unreal.Anchors(unreal.Vector2D(0.0, 0.0), unreal.Vector2D(1.0, 1.0)))
            scroll_slot.set_offsets(unreal.Margin(0.0, 0.0, 0.0, 0.0))
        except Exception:
            scroll_slot.set_position(unreal.Vector2D(0.0, 0.0))
            scroll_slot.set_size(unreal.Vector2D(430.0, 620.0))

        size_box.set_width_override(424.0)
        size_box.set_height_override(2850.0)
        if size_box.get_parent() != scroll_box:
            size_box.remove_from_parent()
            scroll_box.add_child(size_box)

        if canvas.get_parent() != size_box:
            canvas.remove_from_parent()
            size_box.add_child(canvas)

        for kw in (prompt_box, btn, path_box):
            if kw and kw.get_parent() != canvas:
                kw.remove_from_parent()
                canvas.add_child_to_canvas(kw)
    else:
        scroll_box = _get_or_create_widget(w, is_wt, unreal.EditorUtilityScrollBox, "StudioScrollBox")
        try:
            scroll_box.set_always_show_scrollbar(True)
            scroll_box.set_animate_wheel_scrolling(True)
            scroll_box.set_wheel_scroll_multiplier(1.2)
            scroll_box.set_editor_property("wheel_scroll_multiplier", 1.2)
        except Exception:
            pass
        size_box = _get_or_create_widget(w, is_wt, unreal.SizeBox, "StudioSizeBox")
        try:
            size_box.set_width_override(424.0)
            size_box.set_height_override(2850.0)
        except Exception:
            pass
        canvas = existing_inner

    if not is_wt:
        is_fresh_widget = getattr(builtins, "_COMFY_ENHANCED_WIDGET_ID", None) != id(w)
        if is_fresh_widget:
            builtins._COMFY_POLY_AIM_ACTIVE = False
            builtins._COMFY_AIMED_SLOT_ID = None
        builtins._COMFY_UI_INIT_UNTIL = time.time() + 1.2
        builtins._COMFY_PREVIEW_IMAGES = {}
        builtins._COMFY_ENHANCED_WIDGET_ID = id(w)
        builtins._COMFY_PANEL_WIDGET = w
        builtins._COMFY_BTN_REFS = []
        builtins._COMFY_SPINBOX_MAP = {}

    # Narrow Vertical Scrollable Layout: Left X = 14.0, Width = 390.0 (Right edge = 404.0), Height = 1035.0
    _setup_named_label(
        w, is_wt, canvas, "HeaderTitleLabel",
        "ComfyUI PBR & Substance Studio",
        14.0, 5.0, 296.0, 16.0,
        size=10, bold=True, color=(0.95, 0.96, 1.0, 1.0),
        apply_layout=True,
    )
    inst_id_hdr = get_instance_fingerprint()
    _setup_named_label(
        w, is_wt, canvas, "HeaderSubtitleLabel",
        f"Copy ID: {inst_id_hdr}",
        14.0, 23.0, 158.0, 14.0,
        size=8, bold=True, color=(0.58, 0.84, 1.0, 1.0),
        apply_layout=True,
    )

    if not is_wt:
        old_hdr_badge = _find_widget_any(w, is_wt, "HeaderGenerationsBadge")
        if old_hdr_badge:
            try:
                old_hdr_badge.set_text("")
                old_hdr_badge.set_visibility(unreal.SlateVisibility.COLLAPSED)
            except Exception:
                pass
        copy_id_btn = _setup_named_button(
            w, is_wt, canvas, "CopyInstanceIdBtn", "CopyInstanceIdBtnLabel",
            "Copy ID",
            174.0, 20.0, 58.0, 18.0,
            color=(0.68, 0.88, 1.0, 1.0),
            apply_layout=True,
            tooltip=f"Click to copy your Support Copy ID ({inst_id_hdr}) to clipboard",
        )
        hdr_donate_btn = _setup_named_button(
            w, is_wt, canvas, "HeaderBuyGenBtn", "HeaderBuyGenBtnLabel",
            "Donate",
            318.0, 10.0, 86.0, 22.0,
            color=(1.0, 0.58, 0.76, 1.0),
            apply_layout=True,
            tooltip="Support the project with a donation (opens donation page in your browser)",
        )
        builtins._COMFY_HDR_GEN_BADGE = None
        builtins._COMFY_COPY_ID_BTN = copy_id_btn
        builtins._COMFY_HDR_DONATE_BTN = hdr_donate_btn

    # === Section 1: Prompt + Target Master Material Selector + GENERATE PBR / B&W MASK / STOP Buttons ===
    _setup_named_label(
        w, is_wt, canvas, "PromptSectionLabel",
        "1. Prompt & Target Master Mtl:",
        14.0, 45.0, 196.0, 14.0,
        size=8, bold=True, color=(0.76, 0.82, 0.92, 1.0),
        apply_layout=True,
    )

    created_pmm = (_find_widget_any(w, is_wt, "PromptMasterMatCombo") is None)
    prompt_mm_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "PromptMasterMatCombo")
    if apply_layout or created_pmm:
        _style_combo_box(prompt_mm_combo)
    _refresh_prompt_master_combo(
        prompt_mm_combo,
        str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER,
        select_path=getattr(builtins, "_COMFY_PROMPT_MASTER_MAT_PATH", DEFAULT_MASTER_MAT_PATH),
    )
    _place_on_canvas(canvas, prompt_mm_combo, 214.0, 42.0, 190.0, 22.0, apply_layout=True)

    if prompt_box:
        if not str(prompt_box.get_text()).strip():
            prompt_box.set_text("natural oak wood veneer, clean continuous wood grain")
        _place_on_canvas(canvas, prompt_box, 14.0, 67.0, 390.0, 28.0, apply_layout=True)

    if btn:
        _place_on_canvas(canvas, btn, 14.0, 98.0, 142.0, 26.0, apply_layout=True)
        gen_lbl = _get_or_create_widget(w, is_wt, unreal.TextBlock, "GenerateBtnLabel")
        if apply_layout or gen_lbl.get_parent() != btn:
            gen_lbl.set_text("GENERATE PBR")
            _style_text(gen_lbl, size=8, bold=True, color=(0.98, 0.98, 1.0, 1.0))
            if gen_lbl.get_parent() != btn:
                for c in list(btn.get_all_children()):
                    c.remove_from_parent()
                btn.add_child(gen_lbl)
            try:
                g_slot = gen_lbl.slot
                if g_slot and hasattr(g_slot, "set_padding"):
                    g_slot.set_padding(unreal.Margin(2.0, 1.0, 2.0, 1.0))
            except Exception:
                pass

    gen_mask_btn = _setup_named_button(
        w, is_wt, canvas, "GenerateMaskBtn", "GenerateMaskBtnLabel",
        "GENERATE B&W MASK",
        162.0, 98.0, 142.0, 26.0,
        color=(0.88, 0.96, 1.0, 1.0),
        apply_layout=True,
    )
    cancel_gen_btn = _setup_named_button(
        w, is_wt, canvas, "CancelGenBtn", "CancelGenBtnLabel",
        "STOP / CANCEL",
        310.0, 98.0, 94.0, 26.0,
        color=(1.0, 0.50, 0.44, 1.0),
        apply_layout=True,
    )
    if not is_wt:
        builtins._COMFY_PROMPT_MM_COMBO = prompt_mm_combo
        builtins._COMFY_MASK_GEN_BTN = gen_mask_btn
        builtins._COMFY_CANCEL_BTN = cancel_gen_btn

        def _on_prompt_mm_changed(selected_item, _selection_type):
            if not selected_item or getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            sel_s = str(selected_item).strip()
            mm_map = getattr(builtins, "_COMFY_MM_MAP", {})
            full_mm = mm_map.get(sel_s, f"{DEFAULT_UE_FOLDER}/{sel_s}" if sel_s.startswith("MM_") else sel_s)
            builtins._COMFY_PROMPT_MASTER_MAT_PATH = full_mm
            builtins._COMFY_MASTER_MAT_PATH = full_mm
            mm_c = getattr(builtins, "_COMFY_MASTER_COMBO", None)
            if mm_c:
                builtins._COMFY_SYNCING_UI = True
                try:
                    mm_c.add_option(sel_s)
                    mm_c.set_selected_option(sel_s)
                except Exception:
                    pass
                finally:
                    builtins._COMFY_SYNCING_UI = False
            _set_panel_status(
                f"[Target Master Material: {sel_s}] Prompt will generate a material based on '{sel_s}'.",
                color=(0.55, 0.96, 0.82, 1.0),
            )

        def _on_gen_mask_clicked():
            p_txt = str(prompt_box.get_text()) if prompt_box else "grunge dirt splatters and scratches"
            f_txt = str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER
            run_mask_workflow(p_txt, f_txt, DEFAULT_JSON_PATH)

        def _on_cancel_gen_clicked():
            cancel_comfy_generation()

        _clear_delegate_safe(prompt_mm_combo.on_selection_changed)
        _clear_delegate_safe(gen_mask_btn.on_clicked)
        _clear_delegate_safe(cancel_gen_btn.on_clicked)
        prompt_mm_combo.on_selection_changed.add_callable(_on_prompt_mm_changed)
        gen_mask_btn.on_clicked.add_callable(_on_gen_mask_clicked)
        cancel_gen_btn.on_clicked.add_callable(_on_cancel_gen_clicked)
        builtins._COMFY_BTN_REFS.append((prompt_mm_combo, _on_prompt_mm_changed))
        builtins._COMFY_BTN_REFS.append((gen_mask_btn, _on_gen_mask_clicked))
        builtins._COMFY_BTN_REFS.append((cancel_gen_btn, _on_cancel_gen_clicked))

    # Helper to create or find styled keyword search boxes
    def _create_search_box(box_name: str, pos_x: float, pos_y: float, width: float, hint_str: str, height: float = 22.0):
        created_new = (_find_widget_any(w, is_wt, box_name) is None)
        s_box = _get_or_create_widget(w, is_wt, unreal.EditorUtilityEditableTextBox, box_name)
        if apply_layout or created_new:
            try:
                if prompt_box:
                    wst = prompt_box.get_editor_property("widget_style")
                    fnt = wst.get_editor_property("font")
                    fnt.size = 8.0
                    wst.set_editor_property("font", fnt)
                    wst.set_editor_property(
                        "foreground_color",
                        unreal.SlateColor(unreal.LinearColor(0.92, 0.96, 1.0, 1.0)),
                    )
                    s_box.set_editor_property("widget_style", wst)
                s_box.set_hint_text(hint_str)
            except Exception:
                pass
        _place_on_canvas(canvas, s_box, pos_x, pos_y, width, height, apply_layout=apply_layout)
        return s_box

    # === License / Promo Key Input, AI Generations Counter & "+ Buy Generations" Redirect Row (Y = 127.0) ===
    if not is_wt:
        lic_key_box = _create_search_box(
            "LicenseKeyBox", 14.0, 127.0, 132.0, "12-Word Seed / Key...", height=22.0
        )
        _place_on_canvas(canvas, lic_key_box, 14.0, 127.0, 132.0, 22.0, apply_layout=True)
        try:
            lic_key_box.set_hint_text("12-Word Seed / Key...")
            lic_key_box.set_tool_tip_text(
                "Paste your 12-Word Seed Key (or Promo Code) and press Enter to add AI Generations"
            )
        except Exception:
            pass

        cur_gens = get_remaining_generations()
        gen_col = _get_generations_badge_color(cur_gens)
        init_gen_txt = (
            "Credits: 0 left (TOP UP)"
            if cur_gens <= 0
            else (f"Credits: {cur_gens} left (LOW)" if cur_gens <= LOW_GENERATIONS_WARNING_THRESHOLD else f"Credits: {cur_gens} left")
        )
        gen_count_lbl = _setup_named_label(
            w, is_wt, canvas, "GenerationsCountLabel",
            init_gen_txt,
            150.0, 130.5, 124.0, 15.0,
            size=8, bold=True, color=gen_col,
            apply_layout=True,
        )

        buy_gens_btn = _setup_named_button(
            w, is_wt, canvas, "BuyGenerationsBtn", "BuyGenerationsBtnLabel",
            "+ Buy Generations",
            278.0, 127.0, 126.0, 22.0,
            color=(1.0, 0.85, 0.32, 1.0),
            apply_layout=True,
            tooltip="Open the payment page in your browser to purchase AI Generation packs (or activate a pasted 12-Word Seed Key)",
        )
        builtins._COMFY_GEN_COUNT_LBL = gen_count_lbl
        builtins._COMFY_LICENSE_KEY_BOX = lic_key_box
        builtins._COMFY_BUY_GENS_BTN = buy_gens_btn

        def _clear_license_box_safely():
            if not lic_key_box:
                return
            try:
                builtins._COMFY_SYNCING_UI = True
                lic_key_box.set_text("")
            except Exception:
                pass
            finally:
                builtins._COMFY_SYNCING_UI = False

        def _on_license_key_changed(new_text):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            k_str = str(new_text or "").strip()
            if not k_str:
                return
            # Auto-activate immediately when a valid 12-word seed phrase is pasted
            tokens = [t.strip().lower() for t in k_str.replace(",", " ").replace("-", " ").split() if t.strip()]
            if len(tokens) == 12:
                ok_v, _, _, _, _ = verify_12word_seed_phrase(k_str)
                if ok_v:
                    ok, msg = activate_license_or_promo_key(k_str)
                    if ok:
                        builtins._COMFY_LAST_KEY_ACTIVATED_TS = time.time()
                        _clear_license_box_safely()
                    _set_panel_status(
                        f"[Seed / License] {msg}",
                        color=(0.45, 0.96, 0.65, 1.0) if ok else (1.0, 0.72, 0.32, 1.0),
                    )

        def _on_license_key_committed(new_text, _commit_method):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            k_str = str(new_text or "").strip()
            if not k_str:
                return
            ok, msg = activate_license_or_promo_key(k_str)
            if ok:
                builtins._COMFY_LAST_KEY_ACTIVATED_TS = time.time()
                _clear_license_box_safely()
            _set_panel_status(
                f"[Seed / License] {msg}",
                color=(0.45, 0.96, 0.65, 1.0) if ok else (1.0, 0.72, 0.32, 1.0),
            )

        def _on_buy_generations_clicked():
            # If focus-loss just redeemed a key milliseconds ago, don't open the browser
            if time.time() - getattr(builtins, "_COMFY_LAST_KEY_ACTIVATED_TS", 0.0) < 2.0:
                return
            typed_k = str(lic_key_box.get_text() or "").strip() if lic_key_box else ""
            st_now = _load_studio_license_state()
            redeemed_now = set(st_now.get("redeemed_keys") or [])
            word_cnt = len([t for t in typed_k.replace(",", " ").replace("-", " ").split() if t.strip()])
            p_hash = _hash_promo_token(typed_k) if typed_k else ""
            if word_cnt >= 4 or (p_hash in _PROMO_HASH_PACKS and f"PROMO-{p_hash.upper()}" not in redeemed_now):
                ok, msg = activate_license_or_promo_key(typed_k)
                if ok:
                    builtins._COMFY_LAST_KEY_ACTIVATED_TS = time.time()
                    _clear_license_box_safely()
                _set_panel_status(
                    f"[Seed / Promo] {msg}",
                    color=(0.45, 0.96, 0.65, 1.0) if ok else (1.0, 0.72, 0.32, 1.0),
                )
                return
            open_buy_generations_url()

        def _on_donate_clicked():
            open_donate_url()

        def _on_copy_id_clicked():
            copy_instance_id_to_clipboard()

        _clear_delegate_safe(lic_key_box.on_text_changed)
        _clear_delegate_safe(lic_key_box.on_text_committed)
        _clear_delegate_safe(buy_gens_btn.on_clicked)
        _clear_delegate_safe(hdr_donate_btn.on_clicked)
        _clear_delegate_safe(copy_id_btn.on_clicked)
        lic_key_box.on_text_changed.add_callable(_on_license_key_changed)
        lic_key_box.on_text_committed.add_callable(_on_license_key_committed)
        buy_gens_btn.on_clicked.add_callable(_on_buy_generations_clicked)
        hdr_donate_btn.on_clicked.add_callable(_on_donate_clicked)
        copy_id_btn.on_clicked.add_callable(_on_copy_id_clicked)
        builtins._COMFY_BTN_REFS.extend(
            [
                (lic_key_box, _on_license_key_changed),
                (lic_key_box, _on_license_key_committed),
                (buy_gens_btn, _on_buy_generations_clicked),
                (hdr_donate_btn, _on_donate_clicked),
                (copy_id_btn, _on_copy_id_clicked),
            ]
        )
        send_ledger_audit_heartbeat("panel_init")

    # === Section 1B: Generate Seamless PBR Material from Reference Image (Y = 152..250) ===
    _setup_named_label(
        w, is_wt, canvas, "RefSectionLabel",
        "1B. Generate Material from Reference Image (Photo / Texture):",
        14.0, 152.0, 390.0, 14.0,
        size=8, bold=True, color=(0.58, 0.94, 0.82, 1.0),
        apply_layout=True,
    )

    ref_path_box = _create_search_box(
        "RefImagePathBox", 14.0, 168.0, 278.0, "Select reference photo (.png/.jpg) or Texture...", height=24.0
    )
    browse_ref_btn = _setup_named_button(
        w, is_wt, canvas, "BrowseRefBtn", "BrowseRefBtnLabel",
        "Browse...",
        296.0, 168.0, 70.0, 24.0,
        color=(0.88, 0.96, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Open file browser to choose a Reference Photo (.png, .jpg, .jpeg, .webp)",
    )
    pick_ref_btn = _setup_named_button(
        w, is_wt, canvas, "PickRefAssetBtn", "PickRefAssetBtnLabel",
        "<-",
        370.0, 168.0, 34.0, 24.0,
        color=(0.65, 0.95, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Use selected Texture2D from Unreal Content Browser as Reference Image",
    )

    created_rm_c = (_find_widget_any(w, is_wt, "RefModeComboBox") is None)
    ref_mode_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "RefModeComboBox")
    if apply_layout or created_rm_c:
        _style_combo_box(ref_mode_combo)
    cur_rm_sel = str(ref_mode_combo.get_selected_option() or "").strip()
    ref_mode_combo.clear_options()
    ref_mode_options = [
        "Seamless Img2Img + CHORD (5 Maps)",
        "Direct CHORD from Photo (De-lit)",
        "AI Vision Prompt + CHORD",
    ]
    for rm_opt in ref_mode_options:
        ref_mode_combo.add_option(rm_opt)
    if cur_rm_sel in ref_mode_options:
        ref_mode_combo.set_selected_option(cur_rm_sel)
    else:
        ref_mode_combo.set_selected_option(ref_mode_options[0])
    _place_on_canvas(canvas, ref_mode_combo, 14.0, 196.0, 266.0, 24.0, apply_layout=apply_layout)

    _setup_named_label(
        w, is_wt, canvas, "RefDenoiseLabel",
        "Denoise:",
        284.0, 200.0, 52.0, 14.0,
        size=8, bold=True, color=(0.82, 0.86, 0.94, 1.0),
        apply_layout=apply_layout,
    )
    created_rd_sb = (_find_widget_any(w, is_wt, "Spin_RefDenoise") is None)
    ref_denoise_sb = _get_or_create_widget(w, is_wt, unreal.EditorUtilitySpinBox, "Spin_RefDenoise")
    if apply_layout or created_rd_sb:
        try:
            white_sc = unreal.SlateColor(unreal.LinearColor(0.96, 0.97, 1.0, 1.0))
            f = ref_denoise_sb.get_editor_property("font")
            f.size = 8.0
            ref_denoise_sb.set_editor_property("font", f)
            ref_denoise_sb.set_editor_property("foreground_color", white_sc)
            ref_denoise_sb.set_editor_property("min_fractional_digits", 2)
            ref_denoise_sb.set_editor_property("max_fractional_digits", 2)
            ref_denoise_sb.set_editor_property("delta", 0.05)
        except Exception:
            pass
        ref_denoise_sb.set_min_value(0.15)
        ref_denoise_sb.set_max_value(0.90)
        ref_denoise_sb.set_min_slider_value(0.15)
        ref_denoise_sb.set_max_slider_value(0.90)
        ref_denoise_sb.set_value(0.52)
    _place_on_canvas(canvas, ref_denoise_sb, 338.0, 196.0, 66.0, 24.0, apply_layout=apply_layout)

    gen_ref_btn = _setup_named_button(
        w, is_wt, canvas, "GenerateRefBtn", "GenerateRefBtnLabel",
        "GENERATE PBR FROM REFERENCE",
        14.0, 224.0, 390.0, 26.0,
        color=(0.55, 0.96, 0.78, 1.0),
        apply_layout=apply_layout,
        tooltip="Generate seamless tileable PBR maps (Albedo, Normal, Roughness, Metallic, Height) from the selected Reference Image",
    )

    if not is_wt:
        builtins._COMFY_REF_PATH_BOX = ref_path_box
        builtins._COMFY_REF_MODE_COMBO = ref_mode_combo
        builtins._COMFY_REF_DENOISE_SB = ref_denoise_sb
        builtins._COMFY_GEN_REF_BTN = gen_ref_btn

        def _on_browse_ref_clicked():
            chosen = _browse_reference_image_dialog()
            if chosen:
                ref_path_box.set_text(chosen)
                _set_panel_status(
                    f"[Reference] Selected image: '{os.path.basename(chosen)}'",
                    color=(0.55, 0.88, 1.0, 1.0),
                )

        def _on_pick_ref_asset_clicked():
            selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
            picked_tex = None
            for a in selected_assets:
                if isinstance(a, unreal.Texture):
                    picked_tex = a
                    break
            if not picked_tex:
                _set_panel_status(
                    "[!] Select a Texture in Content Browser and click '<-' (or use 'Browse...' for file on disk)!",
                    color=(1.0, 0.72, 0.3, 1.0),
                )
                return
            src_file = ""
            try:
                import_data = picked_tex.get_editor_property("asset_import_data")
                if import_data:
                    src_file = str(import_data.get_first_filename() or "").strip()
            except Exception:
                pass
            if not src_file or not os.path.exists(src_file):
                try:
                    temp_export_dir = os.path.join(os.path.dirname(DEFAULT_JSON_PATH), "_temp_ref_ue")
                    os.makedirs(temp_export_dir, exist_ok=True)
                    out_png = os.path.join(temp_export_dir, f"{picked_tex.get_name()}.png")
                    exp_task = unreal.AssetExportTask()
                    exp_task.object = picked_tex
                    exp_task.filename = out_png
                    exp_task.automated = True
                    exp_task.prompt = False
                    exp_task.replace_identical = True
                    unreal.Exporter.run_asset_export_task(exp_task)
                    if os.path.exists(out_png):
                        src_file = out_png
                except Exception:
                    pass
            if src_file and os.path.exists(src_file):
                ref_path_box.set_text(src_file)
                _set_panel_status(
                    f"[Reference] Picked Texture '{picked_tex.get_name()}' -> {os.path.basename(src_file)}",
                    color=(0.45, 0.92, 0.60, 1.0),
                )
            else:
                _set_panel_status(
                    f"[!] Could not resolve source file for '{picked_tex.get_name()}', please use 'Browse...'!",
                    color=(1.0, 0.72, 0.3, 1.0),
                )

        def _on_gen_ref_clicked():
            r_path = str(ref_path_box.get_text() or "").strip()
            r_mode_lbl = str(ref_mode_combo.get_selected_option() or "Seamless Img2Img + CHORD (5 Maps)").strip()
            r_denoise = float(ref_denoise_sb.get_value()) if ref_denoise_sb else 0.52
            p_hint = str(prompt_box.get_text() or "").strip() if prompt_box else ""
            f_txt = str(path_box.get_text() or DEFAULT_UE_FOLDER).strip() if path_box else DEFAULT_UE_FOLDER
            run_reference_workflow(
                ref_image_path=r_path,
                ref_mode_label=r_mode_lbl,
                prompt_hint=p_hint,
                denoise=r_denoise,
                folder_path=f_txt,
                json_path=DEFAULT_JSON_PATH,
            )

        _clear_delegate_safe(browse_ref_btn.on_clicked)
        _clear_delegate_safe(pick_ref_btn.on_clicked)
        _clear_delegate_safe(gen_ref_btn.on_clicked)
        browse_ref_btn.on_clicked.add_callable(_on_browse_ref_clicked)
        pick_ref_btn.on_clicked.add_callable(_on_pick_ref_asset_clicked)
        gen_ref_btn.on_clicked.add_callable(_on_gen_ref_clicked)
        builtins._COMFY_BTN_REFS.extend(
            [
                (browse_ref_btn, _on_browse_ref_clicked),
                (pick_ref_btn, _on_pick_ref_asset_clicked),
                (gen_ref_btn, _on_gen_ref_clicked),
            ]
        )

    # === Section 1B: Quick Category Preset Buttons & 368 Curated Prompts (3 rows of 4 buttons) ===
    _setup_named_label(
        w, is_wt, canvas, "PresetsSectionLabel",
        "Quick Category Presets (368 Prompts - click category to cycle):",
        14.0, 272.0, 390.0, 14.0,
        size=8, bold=True, color=(0.68, 0.78, 0.92, 1.0),
        apply_layout=apply_layout,
    )

    _setup_named_label(
        w, is_wt, canvas, "SeedLabel",
        "Seed (Variant):",
        14.0, 379.0, 84.0, 16.0,
        size=8, bold=True, color=(0.76, 0.88, 1.0, 1.0),
        apply_layout=apply_layout,
    )
    seed_box = _create_search_box("PresetSearchBox", 100.0, 375.0, 122.0, "Seed (e.g. 100001)", height=24.0)
    try:
        cur_seed_txt = str(seed_box.get_text() or "").strip()
        if not cur_seed_txt or not cur_seed_txt.lstrip("-").isdigit():
            seed_box.set_text(str(_get_selected_seed()))
    except Exception:
        pass

    prev_seed_btn = _setup_named_button(
        w, is_wt, canvas, "PrevSeedBtn", "PrevSeedBtnLabel",
        "-1",
        226.0, 375.0, 36.0, 24.0,
        color=(0.88, 0.94, 1.0, 1.0),
        apply_layout=apply_layout,
    )
    next_seed_btn = _setup_named_button(
        w, is_wt, canvas, "NextSeedBtn", "NextSeedBtnLabel",
        "+1",
        266.0, 375.0, 36.0, 24.0,
        color=(0.88, 0.94, 1.0, 1.0),
        apply_layout=apply_layout,
    )
    rand_seed_btn = _setup_named_button(
        w, is_wt, canvas, "RandomPresetBtn", "RandomPresetBtnLabel",
        "New Seed",
        306.0, 375.0, 98.0, 24.0,
        color=(0.65, 0.95, 0.82, 1.0),
        apply_layout=apply_layout,
    )

    created_pr_c = (_find_widget_any(w, is_wt, "PresetComboBox") is None)
    preset_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "PresetComboBox")
    if apply_layout or created_pr_c:
        _style_combo_box(preset_combo)
    _place_on_canvas(canvas, preset_combo, 14.0, 403.0, 390.0, 26.0, apply_layout=apply_layout)

    if not hasattr(builtins, "_COMFY_ACTIVE_PRESET_CAT"):
        builtins._COMFY_ACTIVE_PRESET_CAT = "wood"
    if not hasattr(builtins, "_COMFY_PRESET_CYCLE_IDX") or not isinstance(getattr(builtins, "_COMFY_PRESET_CYCLE_IDX", None), dict):
        builtins._COMFY_PRESET_CYCLE_IDX = {}

    def _populate_preset_combo(cat_key: str = "", search_query: str = "", select_idx: int = 0):
        c_key = cat_key or getattr(builtins, "_COMFY_ACTIVE_PRESET_CAT", "wood")
        builtins._COMFY_ACTIVE_PRESET_CAT = c_key
        q = (search_query or "").strip()
        p_map = {}
        options_list = []

        if q:
            for ck, c_title in PRESET_CATEGORIES_ORDER:
                for p_title, p_text in CATEGORY_PRESET_PROMPTS.get(ck, []):
                    hay = f"{ck} {c_title} {p_title} {p_text}"
                    if _matches_search_query(hay, q):
                        disp = f"[{c_title}] {p_title}"
                        p_map[disp] = (ck, p_title, p_text)
                        options_list.append(disp)
        else:
            c_title = dict(PRESET_CATEGORIES_ORDER).get(c_key, c_key.title())
            for idx_p, (p_title, p_text) in enumerate(CATEGORY_PRESET_PROMPTS.get(c_key, []), start=1):
                disp = f"{idx_p:02d}. [{c_title}] {p_title}"
                p_map[disp] = (c_key, p_title, p_text)
                options_list.append(disp)

        builtins._COMFY_PRESET_MAP = p_map
        builtins._COMFY_SYNCING_UI = True
        try:
            preset_combo.clear_options()
            for opt in options_list:
                preset_combo.add_option(opt)
            if options_list:
                chosen = options_list[select_idx % len(options_list)]
                preset_combo.set_selected_option(chosen)
        finally:
            builtins._COMFY_SYNCING_UI = False
        return options_list

    _populate_preset_combo(getattr(builtins, "_COMFY_ACTIVE_PRESET_CAT", "wood"))

    def _apply_preset_option(opt_label: str):
        p_map = getattr(builtins, "_COMFY_PRESET_MAP", {})
        if opt_label not in p_map:
            return
        ck, p_title, p_text = p_map[opt_label]
        if prompt_box:
            prompt_box.set_text(p_text)
        mm_target = CATEGORY_TO_MASTER_MATERIAL.get(ck, DEFAULT_MASTER_MAT_PATH)
        if ck != "bw_mask" and mm_target:
            builtins._COMFY_PROMPT_MASTER_MAT_PATH = mm_target
            builtins._COMFY_MASTER_MAT_PATH = mm_target
            mm_short_t = mm_target.split("/")[-1]
            builtins._COMFY_SYNCING_UI = True
            try:
                p_mm_c = getattr(builtins, "_COMFY_PROMPT_MM_COMBO", None)
                if p_mm_c:
                    p_mm_c.add_option(mm_short_t)
                    p_mm_c.set_selected_option(mm_short_t)
                mm_c = getattr(builtins, "_COMFY_MASTER_COMBO", None)
                if mm_c:
                    mm_c.add_option(mm_short_t)
                    mm_c.set_selected_option(mm_short_t)
            except Exception:
                pass
            finally:
                builtins._COMFY_SYNCING_UI = False
        action_hint = "GENERATE B&W MASK" if ck == "bw_mask" else f"GENERATE PBR ({mm_target.split('/')[-1]})"
        c_title = dict(PRESET_CATEGORIES_ORDER).get(ck, ck.title())
        _set_panel_status(
            f"[Preset: {c_title}] '{p_title}' (Seed: {_get_selected_seed()}) -> {action_hint}",
            color=(0.55, 0.88, 1.0, 1.0),
        )

    if not is_wt:
        builtins._COMFY_SEED_BOX = seed_box
        builtins._COMFY_PRESET_SEARCH = None
        builtins._COMFY_PRESET_COMBO = preset_combo

        def _on_preset_combo_changed(selected_item, _selection_type):
            if not selected_item or getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            _apply_preset_option(str(selected_item))

        def _on_seed_text_changed(_new_text):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            s_val = _get_selected_seed()
            _set_panel_status(
                f"[Seed Variant: {s_val}] Same prompt with different Seed produces a new material variation.",
                color=(0.65, 0.94, 0.82, 1.0),
            )

        def _on_prev_seed_clicked():
            s_val = _set_selected_seed(max(1, _get_selected_seed() - 1))
            _set_panel_status(
                f"[Seed Variant -1 -> {s_val}] Click GENERATE PBR / B&W MASK for variant #{s_val}",
                color=(0.65, 0.94, 0.82, 1.0),
            )

        def _on_next_seed_clicked():
            s_val = _set_selected_seed(_get_selected_seed() + 1)
            _set_panel_status(
                f"[Seed Variant +1 -> {s_val}] Click GENERATE PBR / B&W MASK for variant #{s_val}",
                color=(0.65, 0.94, 0.82, 1.0),
            )

        def _on_random_seed_clicked():
            s_val = _set_selected_seed(random.randint(100000, 999999))
            _set_panel_status(
                f"[New Random Seed: {s_val}] Click GENERATE PBR / B&W MASK for a new variation of the current prompt!",
                color=(0.55, 0.96, 0.78, 1.0),
            )

        _clear_delegate_safe(preset_combo.on_selection_changed)
        _clear_delegate_safe(seed_box.on_text_changed)
        _clear_delegate_safe(prev_seed_btn.on_clicked)
        _clear_delegate_safe(next_seed_btn.on_clicked)
        _clear_delegate_safe(rand_seed_btn.on_clicked)
        preset_combo.on_selection_changed.add_callable(_on_preset_combo_changed)
        seed_box.on_text_changed.add_callable(_on_seed_text_changed)
        prev_seed_btn.on_clicked.add_callable(_on_prev_seed_clicked)
        next_seed_btn.on_clicked.add_callable(_on_next_seed_clicked)
        rand_seed_btn.on_clicked.add_callable(_on_random_seed_clicked)
        builtins._COMFY_BTN_REFS.extend(
            [
                (preset_combo, _on_preset_combo_changed),
                (seed_box, _on_seed_text_changed),
                (prev_seed_btn, _on_prev_seed_clicked),
                (next_seed_btn, _on_next_seed_clicked),
                (rand_seed_btn, _on_random_seed_clicked),
            ]
        )

    # Remove any legacy category buttons (such as CatBtn_mirror) so nothing peeks out behind Row 2
    valid_cat_btn_names = {f"CatBtn_{k}" for k, _ in PRESET_CATEGORIES_ORDER}
    try:
        for ch in list(canvas.get_all_children()):
            ch_nm = str(ch.get_name())
            if ch_nm.startswith("CatBtn_") and ch_nm not in valid_cat_btn_names:
                ch.set_visibility(unreal.SlateVisibility.COLLAPSED)
                ch.remove_from_parent()
    except Exception:
        pass

    # 13 Category Buttons in 3 rows: Row 0 & 1 have 4 buttons (93px each), Row 2 has 5 buttons (Foliage, Plastic, Light, Decals, B&W Mask, 73.2px each)
    for c_idx, (cat_key, cat_label) in enumerate(PRESET_CATEGORIES_ORDER):
        if c_idx < 8:
            row_i = c_idx // 4
            col_i = c_idx % 4
            cur_btn_w = 93.0
            cur_gap = 6.0
        else:
            row_i = 2
            col_i = c_idx - 8
            cur_btn_w = 73.2
            cur_gap = 6.0
        cat_x = 14.0 + col_i * (cur_btn_w + cur_gap)
        cat_y = 290.0 + row_i * 27.0
        is_mask_cat = cat_key == "bw_mask"
        is_decal_cat = cat_key == "decal"
        btn_col = (
            (0.65, 0.94, 1.0, 1.0)
            if is_mask_cat
            else ((0.58, 0.98, 0.82, 1.0) if is_decal_cat else (0.92, 0.94, 0.98, 1.0))
        )

        c_btn = _setup_named_button(
            w, is_wt, canvas,
            f"CatBtn_{cat_key}", f"CatBtnLbl_{cat_key}",
            cat_label,
            cat_x, cat_y, cur_btn_w, 24.0,
            color=btn_col,
            apply_layout=True,
        )

        if not is_wt:
            def _make_cat_btn_cb(ck=cat_key):
                def _on_cat_click():
                    cycle_map = getattr(builtins, "_COMFY_PRESET_CYCLE_IDX", {})
                    if not isinstance(cycle_map, dict):
                        cycle_map = {}
                    cur_idx = cycle_map.get(ck, 0)
                    items = CATEGORY_PRESET_PROMPTS.get(ck, [])
                    if items:
                        next_idx = cur_idx % len(items)
                        cycle_map[ck] = (next_idx + 1) % len(items)
                    else:
                        next_idx = 0
                    builtins._COMFY_PRESET_CYCLE_IDX = cycle_map
                    opts = _populate_preset_combo(ck, search_query="", select_idx=next_idx)
                    if opts:
                        _apply_preset_option(opts[next_idx % len(opts)])

                return _on_cat_click

            cat_cb = _make_cat_btn_cb()
            _clear_delegate_safe(c_btn.on_clicked)
            c_btn.on_clicked.add_callable(cat_cb)
            builtins._COMFY_BTN_REFS.append((c_btn, cat_cb))

    # === Section 2: Target Folder + Resolution + AI PBR Model (CHORD / DA2) ===
    _setup_named_label(
        w, is_wt, canvas, "TargetFolderLabel",
        "2. Target Folder:",
        14.0, 453.0, 230.0, 14.0,
        size=8, bold=True, color=(0.76, 0.82, 0.92, 1.0),
        apply_layout=apply_layout,
    )

    if path_box:
        if not str(path_box.get_text()).strip():
            path_box.set_text(DEFAULT_UE_FOLDER)
        _place_on_canvas(canvas, path_box, 14.0, 470.0, 230.0, 26.0, apply_layout=apply_layout)

    _setup_named_label(
        w, is_wt, canvas, "ResolutionLabel",
        "Texture Resolution:",
        250.0, 453.0, 154.0, 14.0,
        size=8, bold=True, color=(0.76, 0.82, 0.92, 1.0),
        apply_layout=apply_layout,
    )

    created_res_c = (_find_widget_any(w, is_wt, "ResolutionComboBox") is None)
    res_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "ResolutionComboBox")
    if apply_layout or created_res_c:
        _style_combo_box(res_combo)
    saved_res_label = getattr(builtins, "_COMFY_RESOLUTION_LABEL", DEFAULT_RESOLUTION_LABEL)
    res_combo.clear_options()
    for label, _px, _tag in RESOLUTION_OPTIONS:
        res_combo.add_option(label)
    res_combo.set_selected_option(saved_res_label)
    _place_on_canvas(canvas, res_combo, 250.0, 470.0, 154.0, 26.0, apply_layout=apply_layout)

    if not is_wt:
        builtins._COMFY_RES_COMBO = res_combo

        def _on_res_changed(selected_item, _selection_type):
            if selected_item:
                builtins._COMFY_RESOLUTION_LABEL = str(selected_item)
                px, tag = _get_selected_resolution()
                _set_panel_status(
                    f"[Resolution] Set to {px}x{px} ({tag})",
                    color=(0.55, 0.85, 1.0, 1.0),
                )

        _clear_delegate_safe(res_combo.on_selection_changed)
        res_combo.on_selection_changed.add_callable(_on_res_changed)
        builtins._COMFY_BTN_REFS.append((res_combo, _on_res_changed))

    _setup_named_label(
        w, is_wt, canvas, "AIModelLabel",
        "AI PBR Model / Pipeline (Ubisoft CHORD / DepthAnything V2):",
        14.0, 504.0, 390.0, 14.0,
        size=8, bold=True, color=(0.58, 0.90, 1.0, 1.0),
        apply_layout=apply_layout,
    )

    created_mod_c = (_find_widget_any(w, is_wt, "AIModelComboBox") is None)
    model_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "AIModelComboBox")
    if apply_layout or created_mod_c:
        _style_combo_box(model_combo)
    saved_model_label = getattr(builtins, "_COMFY_MODEL_LABEL", DEFAULT_PBR_MODEL_LABEL)
    model_combo.clear_options()
    for m_label, _pmode, _ckpt in PBR_MODEL_OPTIONS:
        model_combo.add_option(m_label)
    model_combo.set_selected_option(saved_model_label)
    _place_on_canvas(canvas, model_combo, 14.0, 520.0, 390.0, 26.0, apply_layout=apply_layout)

    if not is_wt:
        builtins._COMFY_MODEL_COMBO = model_combo

        def _on_model_changed(selected_item, _selection_type):
            if selected_item:
                builtins._COMFY_MODEL_LABEL = str(selected_item)
                m_lbl, p_mode, ckpt = _get_selected_pbr_model()
                pipe_desc = "Ubisoft CHORD De-lit 5-Map PBR" if p_mode == "chord" else "DepthAnything V2 Fast 4-Map PBR"
                _set_panel_status(
                    f"[AI Model] {m_lbl} ({pipe_desc})",
                    color=(0.55, 0.88, 1.0, 1.0),
                )

        _clear_delegate_safe(model_combo.on_selection_changed)
        model_combo.on_selection_changed.add_callable(_on_model_changed)
        builtins._COMFY_BTN_REFS.append((model_combo, _on_model_changed))

    # === Section 3: Master Material Selection, Creation & Apply to Actor ===
    _setup_named_label(
        w, is_wt, canvas, "MasterMatLabel",
        "3. Master Material & Viewport Assignment:",
        14.0, 570.0, 390.0, 14.0,
        size=8, bold=True, color=(0.76, 0.82, 0.92, 1.0),
        apply_layout=apply_layout,
    )

    created_mm_c = (_find_widget_any(w, is_wt, "MasterMatComboBox") is None)
    mm_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "MasterMatComboBox")
    if apply_layout or created_mm_c:
        _style_combo_box(mm_combo)
    cur_folder = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
    _refresh_master_combo(mm_combo, cur_folder)
    _place_on_canvas(canvas, mm_combo, 14.0, 587.0, 312.0, 26.0, apply_layout=apply_layout)

    pick_mm_btn = _setup_named_button(
        w, is_wt, canvas, "PickMasterMatBtn", "PickMasterMatBtnLabel",
        "<-",
        330.0, 587.0, 34.0, 26.0,
        color=(0.65, 0.95, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Use Selected Asset from Content Browser (взять выделенный Мастер-Материал из Content Browser)",
    )
    find_mm_btn = _setup_named_button(
        w, is_wt, canvas, "FindMasterMatBtn", "FindMasterMatBtnLabel",
        "Find",
        368.0, 587.0, 36.0, 26.0,
        color=(0.98, 0.88, 0.60, 1.0),
        apply_layout=apply_layout,
        tooltip="Browse to Asset in Content Browser (показать текущий Мастер-Материал в Content Browser)",
    )

    create_mm_btn = _setup_named_button(
        w, is_wt, canvas, "CreateMasterMatBtn", "CreateMasterMatBtnLabel",
        "Create Master Material",
        14.0, 618.0, 191.0, 26.0,
        color=(0.95, 0.98, 1.0, 1.0),
        apply_layout=apply_layout,
    )
    apply_btn = _setup_named_button(
        w, is_wt, canvas, "ApplyToActorBtn", "ApplyToActorBtnLabel",
        "Apply to Selected Actor",
        213.0, 618.0, 191.0, 26.0,
        color=(0.92, 0.95, 1.0, 1.0),
        apply_layout=apply_layout,
    )

    if not is_wt:
        builtins._COMFY_MASTER_COMBO = mm_combo

        def _on_mm_opening():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            _refresh_master_combo(mm_combo, folder_now)

        def _on_mm_changed(selected_item, _selection_type):
            if (
                not selected_item
                or getattr(builtins, "_COMFY_SYNCING_UI", False)
                or time.time() < getattr(builtins, "_COMFY_UI_INIT_UNTIL", 0.0)
                or _selection_type == unreal.SelectInfo.DIRECT
            ):
                return
            sel_s = str(selected_item).strip()
            mm_map = getattr(builtins, "_COMFY_MM_MAP", {})
            full_p = mm_map.get(sel_s, _resolve_mi_path(sel_s))
            asset_obj = unreal.EditorAssetLibrary.load_asset(full_p) if full_p and unreal.EditorAssetLibrary.does_asset_exist(full_p) else None
            if isinstance(asset_obj, unreal.MaterialInstanceConstant):
                builtins._COMFY_LAST_MATERIAL = asset_obj
                la_c = getattr(builtins, "_COMFY_LAYER_A_COMBO", None)
                if la_c:
                    builtins._COMFY_SYNCING_UI = True
                    try:
                        la_c.add_option(sel_s)
                        la_c.set_selected_option(sel_s)
                    finally:
                        builtins._COMFY_SYNCING_UI = False
                _sync_spinboxes_from_mi(asset_obj)
                sync_layers_fn = getattr(builtins, "_COMFY_SYNC_PANEL_FROM_ACTOR_FN", None)
                slot_id = _get_selected_poly_target_id(default_for_assign=-1)
                applied_cnt = apply_material_to_selected_actors(asset_obj, slot_idx=slot_id)
                slot_msg = f"Slot ID {slot_id}" if slot_id >= 0 else "All Slots"
                if applied_cnt > 0:
                    _set_panel_status(
                        f"[Material Assigned -> {slot_msg}] Applied '{sel_s}' to selected actor!",
                        color=(0.45, 0.96, 0.65, 1.0),
                    )
                else:
                    _set_panel_status(
                        f"[Active Material] '{sel_s}' ready for {slot_msg}.",
                        color=(0.55, 0.88, 1.0, 1.0),
                    )
            else:
                builtins._COMFY_MASTER_MAT_PATH = full_p or sel_s
                if isinstance(asset_obj, unreal.MaterialInterface):
                    slot_id = _get_selected_poly_target_id(default_for_assign=-1)
                    apply_material_to_selected_actors(asset_obj, slot_idx=slot_id)
                _set_panel_status(
                    f"[Master Material] Active: {sel_s}",
                    color=(0.55, 0.85, 1.0, 1.0),
                )

        def _on_pick_mm_clicked():
            selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
            picked_mat = None
            for a in selected_assets:
                if isinstance(a, (unreal.MaterialInstanceConstant, unreal.Material)):
                    picked_mat = a
                    break
            if not picked_mat:
                _set_panel_status(
                    "[!] Select a Material Instance (MI_*) or Master Material in Content Browser and click '<-'",
                    color=(1.0, 0.72, 0.3, 1.0),
                )
                return
            picked_path = picked_mat.get_path_name().split(".")[0]
            if isinstance(picked_mat, unreal.MaterialInstanceConstant):
                builtins._COMFY_LAST_MATERIAL = picked_mat
            else:
                builtins._COMFY_MASTER_MAT_PATH = picked_path
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            _refresh_master_combo(mm_combo, folder_now, select_path=picked_path)
            slot_id = _get_selected_poly_target_id(default_for_assign=-1)
            apply_material_to_selected_actors(picked_mat, slot_idx=slot_id)
            _set_panel_status(
                f"[OK] Picked & Applied '{picked_mat.get_name()}' (Target ID: {slot_id if slot_id >= 0 else 'All'})!",
                color=(0.45, 0.92, 0.60, 1.0),
            )

        def _on_find_mm_clicked():
            sel_s = str(mm_combo.get_selected_option() or "").strip()
            mm_map = getattr(builtins, "_COMFY_MM_MAP", {})
            mm_path = mm_map.get(sel_s, getattr(builtins, "_COMFY_MASTER_MAT_PATH", DEFAULT_MASTER_MAT_PATH))
            if mm_path and unreal.EditorAssetLibrary.does_asset_exist(mm_path):
                unreal.EditorAssetLibrary.sync_browser_to_objects([mm_path])
                _set_panel_status(
                    f"[Browse] Synced Content Browser to '{mm_path.split('/')[-1]}'.",
                    color=(0.55, 0.88, 1.0, 1.0),
                )
            else:
                _set_panel_status(
                    "[!] Master Material asset not found yet — click 'Create Master Material' first!",
                    color=(1.0, 0.72, 0.3, 1.0),
                )

        def _on_create_mm_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            _set_panel_status("[...] Building all Master Materials (MM_ComfyPBR_Master + MM_ArchViz_*)...", color=(0.55, 0.85, 1.0, 1.0))
            mm = create_or_update_master_material(folder_now, DEFAULT_MASTER_MAT_NAME)
            for arch_mm_name in ("MM_ArchViz_Foliage", "MM_ArchViz_Fabric", "MM_ArchViz_Glass", "MM_ArchViz_Emissive", "MM_ArchViz_Decal"):
                try:
                    create_or_update_master_material(folder_now, arch_mm_name)
                except Exception:
                    pass
            mm_path = mm.get_path_name().split(".")[0]
            _refresh_master_combo(mm_combo, folder_now, select_path=mm_path)
            _set_panel_status(
                f"[OK] Built {mm.get_name()} + all MM_ArchViz_* Master Materials (with Mesh Paint [R,G,B,A] + PBR + Seams)!",
                color=(0.45, 0.92, 0.60, 1.0),
            )

        def _on_apply_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            mat = _get_active_viewport_material(folder_now)
            if not mat:
                _set_panel_status("[!] Please generate or select a material first!", color=(1.0, 0.65, 0.3, 1.0))
                return
            slot_id = _get_selected_poly_target_id(default_for_assign=-1)
            applied = apply_material_to_selected_actors(mat, slot_idx=slot_id)
            if applied > 0:
                slot_lbl = f"Slot ID {slot_id}" if slot_id >= 0 else "All Slots"
                _set_panel_status(
                    f"[OK] Material '{mat.get_name()}' applied to {slot_lbl} on selected actor(s) ({applied}).",
                    color=(0.45, 0.92, 0.60, 1.0),
                )
            else:
                _set_panel_status(
                    "[!] Select a mesh actor in the level viewport first!",
                    color=(1.0, 0.72, 0.3, 1.0),
                )

        _clear_delegate_safe(mm_combo.on_opening)
        _clear_delegate_safe(mm_combo.on_selection_changed)
        _clear_delegate_safe(pick_mm_btn.on_clicked)
        _clear_delegate_safe(find_mm_btn.on_clicked)
        _clear_delegate_safe(create_mm_btn.on_clicked)
        _clear_delegate_safe(apply_btn.on_clicked)

        mm_combo.on_opening.add_callable(_on_mm_opening)
        mm_combo.on_selection_changed.add_callable(_on_mm_changed)
        pick_mm_btn.on_clicked.add_callable(_on_pick_mm_clicked)
        find_mm_btn.on_clicked.add_callable(_on_find_mm_clicked)
        create_mm_btn.on_clicked.add_callable(_on_create_mm_clicked)
        apply_btn.on_clicked.add_callable(_on_apply_clicked)
        builtins._COMFY_BTN_REFS.extend(
            [
                (mm_combo, _on_mm_opening),
                (mm_combo, _on_mm_changed),
                (pick_mm_btn, _on_pick_mm_clicked),
                (find_mm_btn, _on_find_mm_clicked),
                (create_mm_btn, _on_create_mm_clicked),
                (apply_btn, _on_apply_clicked),
            ]
        )

    # =========================================================================
    # === Section 5B: POLYGON & MATERIAL ID STUDIO (Before Section 6) ===
    # =========================================================================
    _setup_named_label(
        w, is_wt, canvas, "PolyIDStudioHeaderLabel",
        "5B. Polygon & Material ID Studio (Change Polygon IDs on Mesh):",
        14.0, 2376.0, 390.0, 15.0,
        size=8, bold=True, color=(0.58, 0.96, 0.82, 1.0),
        apply_layout=apply_layout,
    )

    created_pid_c = (_find_widget_any(w, is_wt, "PolyTargetIDCombo") is None)
    poly_id_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "PolyTargetIDCombo")
    if apply_layout or created_pid_c:
        _style_combo_box(poly_id_combo)
    saved_pid_lbl = getattr(builtins, "_COMFY_POLY_ID_LABEL", POLY_ID_SLOT_OPTIONS[0][0])
    poly_id_combo.clear_options()
    for p_lbl, _p_slot in POLY_ID_SLOT_OPTIONS:
        poly_id_combo.add_option(p_lbl)
    poly_id_combo.set_selected_option(saved_pid_lbl)
    _place_on_canvas(canvas, poly_id_combo, 14.0, 2394.0, 148.0, 24.0, apply_layout=apply_layout)

    created_pm_c = (_find_widget_any(w, is_wt, "PolySelectModeCombo") is None)
    poly_mode_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "PolySelectModeCombo")
    if apply_layout or created_pm_c:
        _style_combo_box(poly_mode_combo)
    saved_pm_lbl = getattr(builtins, "_COMFY_POLY_MODE_LABEL", POLY_SELECT_MODE_OPTIONS[0][0])
    poly_mode_combo.clear_options()
    for m_lbl, _m_k in POLY_SELECT_MODE_OPTIONS:
        poly_mode_combo.add_option(m_lbl)
    poly_mode_combo.set_selected_option(saved_pm_lbl)
    _place_on_canvas(canvas, poly_mode_combo, 166.0, 2394.0, 238.0, 24.0, apply_layout=apply_layout)

    if not hasattr(builtins, "_COMFY_POLY_AIM_ACTIVE") or is_wt:
        builtins._COMFY_POLY_AIM_ACTIVE = False
    created_aim_cb = (_find_widget_any(w, is_wt, "PolyAimPickCheck") is None)
    aim_pick_check = _get_or_create_widget(w, is_wt, unreal.EditorUtilityCheckBox, "PolyAimPickCheck")
    try:
        _clear_delegate_safe(aim_pick_check.on_check_state_changed)
        aim_pick_check.set_is_checked(False if is_wt else bool(getattr(builtins, "_COMFY_POLY_AIM_ACTIVE", False)))
    except Exception:
        pass
    if not is_wt:
        builtins._COMFY_POLY_AIM_CHECK = aim_pick_check
    try:
        aim_pick_check.set_tool_tip_text(
            "Enable Live 3D Crosshair Polygon Highlight in Viewport (Press Middle Mouse Button in Viewport to assign ID!)"
        )
    except Exception:
        pass
    _place_on_canvas(canvas, aim_pick_check, 14.0, 2423.0, 22.0, 22.0, apply_layout=apply_layout)

    _setup_named_label(
        w, is_wt, canvas, "PolyAimPickLabel",
        "Aim Pick (MMB)",
        38.0, 2427.0, 96.0, 14.0,
        size=8, bold=True, color=(0.68, 0.94, 1.0, 1.0),
        apply_layout=apply_layout,
    )

    assign_poly_btn = _setup_named_button(
        w, is_wt, canvas, "AssignPolyIDBtn", "AssignPolyIDBtnLabel",
        "Assign ID to Aimed Face (+ Apply Mtl)",
        136.0, 2422.0, 268.0, 25.0,
        color=(0.55, 0.98, 0.80, 1.0),
        apply_layout=apply_layout,
        tooltip="Assigns the selected Target Material ID to the polygon / face under the Viewport Camera Crosshair and applies Base mtl",
    )

    poly_top_btn = _setup_named_button(
        w, is_wt, canvas, "PolyTopZBtn", "PolyTopZBtnLabel",
        "Top (+Z) -> ID",
        14.0, 2451.0, 93.0, 24.0,
        color=(0.88, 0.95, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Assigns all Top (+Z) upward-facing polygons of the selected actor to Target ID",
    )
    poly_sides_btn = _setup_named_button(
        w, is_wt, canvas, "PolySidesXYBtn", "PolySidesXYBtnLabel",
        "Sides (XY) -> ID",
        113.0, 2451.0, 93.0, 24.0,
        color=(0.88, 0.95, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Assigns all vertical Side (XY) polygons of the selected actor to Target ID",
    )
    poly_bot_btn = _setup_named_button(
        w, is_wt, canvas, "PolyBotZBtn", "PolyBotZBtnLabel",
        "Bottom (-Z) -> ID",
        212.0, 2451.0, 93.0, 24.0,
        color=(0.88, 0.95, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Assigns all Bottom (-Z) downward-facing polygons of the selected actor to Target ID",
    )
    poly_reset_btn = _setup_named_button(
        w, is_wt, canvas, "PolyResetIDBtn", "PolyResetIDBtnLabel",
        "Reset to ID 0",
        311.0, 2451.0, 93.0, 24.0,
        color=(1.0, 0.80, 0.58, 1.0),
        apply_layout=apply_layout,
        tooltip="Merges all polygons of the selected actor back into Material ID 0",
    )

    if not is_wt:
        builtins._COMFY_POLY_ID_COMBO = poly_id_combo
        builtins._COMFY_POLY_MODE_COMBO = poly_mode_combo
        builtins._COMFY_POLY_AIM_CHECK = aim_pick_check

        def _on_poly_id_combo_changed(selected_item, _selection_type):
            if (
                not selected_item
                or getattr(builtins, "_COMFY_SYNCING_UI", False)
                or time.time() < getattr(builtins, "_COMFY_UI_INIT_UNTIL", 0.0)
                or _selection_type == unreal.SelectInfo.DIRECT
            ):
                return
            builtins._COMFY_POLY_ID_LABEL = str(selected_item)
            slot_id = _get_selected_poly_target_id(default_for_assign=-1)
            if slot_id >= 0:
                try:
                    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                    for act in (a_sub.get_selected_level_actors() if a_sub else []):
                        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
                            if slot_id < comp.get_num_materials():
                                slot_mi = comp.get_material(slot_id)
                                if isinstance(slot_mi, unreal.MaterialInstanceConstant):
                                    sync_fn = getattr(builtins, "_COMFY_SYNC_PANEL_FROM_ACTOR_FN", None)
                                    if sync_fn:
                                        sync_fn(slot_mi, actor_label=f"{act.get_actor_label()} [ID {slot_id}]")
                                        return
                except Exception:
                    pass
                _set_panel_status(
                    f"[Polygon Target ID: {slot_id}] Active slot set to ID {slot_id}. Click 'Assign ID' or 'Apply to Selected Actor'.",
                    color=(0.55, 0.94, 0.82, 1.0),
                )
            else:
                _set_panel_status(
                    "[Polygon Target ID: All IDs] 'Apply to Selected Actor' will now assign material to all slots.",
                    color=(0.55, 0.88, 1.0, 1.0),
                )

        def _on_poly_mode_combo_changed(selected_item, _selection_type):
            if not selected_item or getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            builtins._COMFY_POLY_MODE_LABEL = str(selected_item)
            _set_panel_status(
                f"[Poly Selection Mode] '{selected_item}'",
                color=(0.55, 0.88, 1.0, 1.0),
            )

        def _on_aim_pick_check_changed(is_checked: bool):
            if getattr(builtins, "_COMFY_SYNCING_UI", False) or time.time() < getattr(builtins, "_COMFY_UI_INIT_UNTIL", 0.0):
                return
            builtins._COMFY_POLY_AIM_ACTIVE = bool(is_checked)
            if not is_checked:
                builtins._COMFY_AIMED_SLOT_ID = None
            if is_checked:
                _set_panel_status(
                    "[Aim Pick: ON] Look at any mesh face in Viewport (Cyan outline) & press Middle Mouse Button (or click 'Assign ID')!",
                    color=(0.35, 0.98, 0.88, 1.0),
                )
            else:
                _set_panel_status(
                    "[Aim Pick: OFF] Live viewport polygon highlight disabled.",
                    color=(0.75, 0.82, 0.92, 1.0),
                )

        def _on_assign_poly_id_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            assign_poly_id_to_aimed_face(folder_now)

        def _on_poly_top_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            assign_poly_id_by_direction("top", folder_now)

        def _on_poly_sides_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            assign_poly_id_by_direction("sides", folder_now)

        def _on_poly_bot_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            assign_poly_id_by_direction("bottom", folder_now)

        def _on_poly_reset_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            reset_selected_actor_poly_ids(folder_now)

        for d_poly in (
            poly_id_combo.on_selection_changed,
            poly_mode_combo.on_selection_changed,
            aim_pick_check.on_check_state_changed,
            assign_poly_btn.on_clicked,
            poly_top_btn.on_clicked,
            poly_sides_btn.on_clicked,
            poly_bot_btn.on_clicked,
            poly_reset_btn.on_clicked,
        ):
            _clear_delegate_safe(d_poly)

        poly_id_combo.on_selection_changed.add_callable(_on_poly_id_combo_changed)
        poly_mode_combo.on_selection_changed.add_callable(_on_poly_mode_combo_changed)
        aim_pick_check.on_check_state_changed.add_callable(_on_aim_pick_check_changed)
        assign_poly_btn.on_clicked.add_callable(_on_assign_poly_id_clicked)
        poly_top_btn.on_clicked.add_callable(_on_poly_top_clicked)
        poly_sides_btn.on_clicked.add_callable(_on_poly_sides_clicked)
        poly_bot_btn.on_clicked.add_callable(_on_poly_bot_clicked)
        poly_reset_btn.on_clicked.add_callable(_on_poly_reset_clicked)
        builtins._COMFY_BTN_REFS.extend(
            [
                (poly_id_combo, _on_poly_id_combo_changed),
                (poly_mode_combo, _on_poly_mode_combo_changed),
                (aim_pick_check, _on_aim_pick_check_changed),
                (assign_poly_btn, _on_assign_poly_id_clicked),
                (poly_top_btn, _on_poly_top_clicked),
                (poly_sides_btn, _on_poly_sides_clicked),
                (poly_bot_btn, _on_poly_bot_clicked),
                (poly_reset_btn, _on_poly_reset_clicked),
            ]
        )

    # =========================================================================
    # === Section 4: CORONA LAYERED MATERIAL (Layers 1..10) & SUBSTANCE SEAMS ===
    # =========================================================================
    _setup_named_label(
        w, is_wt, canvas, "BlendStudioHeaderLabel",
        "4. Corona Layered Material & Substance Seams Studio:",
        14.0, 670.0, 390.0, 16.0,
        size=9, bold=True, color=(0.55, 0.88, 1.0, 1.0),
        apply_layout=apply_layout,
    )

    def _create_inline_spinbox(
        sb_name: str,
        pos_x: float,
        pos_y: float,
        width: float,
        height: float,
        default_val: float = 100.0,
        min_val: float = 0.0,
        max_val: float = 100.0,
        step: float = 1.0,
        digits: int = 1,
    ):
        created_new = (_find_widget_any(w, is_wt, sb_name) is None)
        sb_obj = _get_or_create_widget(w, is_wt, unreal.EditorUtilitySpinBox, sb_name)
        if apply_layout or created_new:
            try:
                white_sc = unreal.SlateColor(unreal.LinearColor(0.96, 0.97, 1.0, 1.0))
                f = sb_obj.get_editor_property("font")
                f.size = 8.0
                sb_obj.set_editor_property("font", f)
                sb_obj.set_editor_property("foreground_color", white_sc)
                sb_obj.set_editor_property("min_fractional_digits", 1 if digits > 0 else 0)
                sb_obj.set_editor_property("max_fractional_digits", digits)
                sb_obj.set_editor_property("delta", step)
            except Exception:
                pass
            sb_obj.set_min_value(min_val)
            sb_obj.set_max_value(max_val)
            sb_obj.set_min_slider_value(min_val)
            sb_obj.set_max_slider_value(max_val)
            sb_obj.set_value(default_val)
        _place_on_canvas(canvas, sb_obj, pos_x, pos_y, width, height, apply_layout=apply_layout)
        return sb_obj

    def _create_inline_checkbox(
        cb_name: str,
        pos_x: float,
        pos_y: float,
        size_px: float = 22.0,
        default_checked: bool = True,
        tooltip: str = "",
    ):
        created_new = (_find_widget_any(w, is_wt, cb_name) is None)
        cb_obj = _get_or_create_widget(w, is_wt, unreal.EditorUtilityCheckBox, cb_name)
        if apply_layout or created_new:
            try:
                cb_obj.set_is_checked(default_checked)
            except Exception:
                pass
        if tooltip:
            try:
                cb_obj.set_tool_tip_text(tooltip)
            except Exception:
                pass
        _place_on_canvas(canvas, cb_obj, pos_x, pos_y, size_px, size_px, apply_layout=apply_layout)
        return cb_obj

    # Keep legacy search boxes & labels hidden/collapsed offscreen so Section 4 starts cleanly with Base mtl
    la_search = _create_search_box("LayerASearchBox", -500.0, 492.0, 10.0, "", height=10.0)
    mask_search = _create_search_box("BlendMaskSearchBox", -500.0, 492.0, 10.0, "", height=10.0)
    lb_search = _create_search_box("LayerBSearchBox", -500.0, 492.0, 10.0, "", height=10.0)
    for hidden_sb in (la_search, mask_search, lb_search):
        try:
            hidden_sb.set_text("")
            hidden_sb.set_visibility(unreal.SlateVisibility.COLLAPSED)
        except Exception:
            pass
    for old_lbl_name in ("LayerBLabel", "BlendMaskLabel", "SearchMtlFilterLabel", "SearchMaskFilterLabel"):
        old_lbl = _find_widget_any(w, is_wt, old_lbl_name)
        if old_lbl:
            try:
                old_lbl.set_visibility(unreal.SlateVisibility.COLLAPSED)
            except Exception:
                pass

    # Base mtl row — matches Corona 'Base mtl: [ None ]'
    _setup_named_label(
        w, is_wt, canvas, "LayerALabel",
        "Base mtl:",
        14.0, 696.0, 64.0, 14.0,
        size=8, bold=True, color=(0.82, 0.86, 0.94, 1.0),
        apply_layout=apply_layout,
    )
    created_la_c = (_find_widget_any(w, is_wt, "LayerAComboBox") is None)
    la_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "LayerAComboBox")
    if apply_layout or created_la_c:
        _style_combo_box(la_combo)
    _place_on_canvas(canvas, la_combo, 80.0, 692.0, 246.0, 24.0, apply_layout=apply_layout)

    pick_la_btn = _setup_named_button(
        w, is_wt, canvas, "PickLayerABtn", "PickLayerABtnLabel",
        "<-",
        330.0, 692.0, 34.0, 24.0,
        color=(0.65, 0.95, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Use Selected Asset from Content Browser or Viewport Actor in Base mtl",
    )
    find_la_btn = _setup_named_button(
        w, is_wt, canvas, "FindLayerABtn", "FindLayerABtnLabel",
        "Find",
        368.0, 692.0, 36.0, 24.0,
        color=(0.98, 0.88, 0.60, 1.0),
        apply_layout=apply_layout,
        tooltip="Browse to Base mtl in Content Browser",
    )

    # Displacement row — matches Corona 'Displacement: [ Blend all layers ]'
    _setup_named_label(
        w, is_wt, canvas, "DisplacementModeLabel",
        "Displacement:",
        14.0, 724.0, 82.0, 14.0,
        size=8, bold=True, color=(0.82, 0.86, 0.94, 1.0),
        apply_layout=apply_layout,
    )
    created_disp_c = (_find_widget_any(w, is_wt, "DisplacementModeComboBox") is None)
    disp_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "DisplacementModeComboBox")
    if apply_layout or created_disp_c:
        _style_combo_box(disp_combo)
    disp_combo.clear_options()
    disp_combo.add_option("Blend all layers")
    disp_combo.add_option("Base layer only")
    disp_combo.set_selected_option("Blend all layers")
    _place_on_canvas(canvas, disp_combo, 98.0, 720.0, 306.0, 24.0, apply_layout=apply_layout)

    # =========================================================================
    # === CORONA LAYERS 1 .. 10 (Y = 754 .. 1466, 72px per layer) ===
    # =========================================================================
    layer_ui_rows = []
    for layer_idx in range(1, 11):
        ly = 754.0 + (layer_idx - 1) * 72.0
        m_y = ly + 15.0
        k_y = ly + 41.0

        _setup_named_label(
            w, is_wt, canvas, f"LayerHdrLabel_{layer_idx}",
            f"Layer {layer_idx}",
            14.0, ly, 140.0, 14.0,
            size=8, bold=True, color=(0.68, 0.86, 1.0, 1.0),
            apply_layout=apply_layout,
        )

        # Row 1: Mtl: [100,0] [None / MI_*] [<-] [F] [x]
        _setup_named_label(
            w, is_wt, canvas, f"LayerMtlLbl_{layer_idx}",
            "Mtl:",
            18.0, m_y + 4.0, 30.0, 14.0,
            size=8, bold=False, color=(0.78, 0.82, 0.88, 1.0),
            apply_layout=apply_layout,
        )
        mtl_amt_sb = _create_inline_spinbox(
            f"Spin_Layer{layer_idx}_Mtl_Amount",
            50.0, m_y, 60.0, 23.0,
            default_val=100.0, min_val=0.0, max_val=100.0, step=1.0, digits=1,
        )

        mtl_combo_name = "LayerBComboBox" if layer_idx == 1 else f"Layer{layer_idx}MtlComboBox"
        created_mc = (_find_widget_any(w, is_wt, mtl_combo_name) is None)
        m_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, mtl_combo_name)
        if apply_layout or created_mc:
            _style_combo_box(m_combo)
        _place_on_canvas(canvas, m_combo, 114.0, m_y, 204.0, 23.0, apply_layout=apply_layout)

        pick_m_name = "PickLayerBBtn" if layer_idx == 1 else f"PickLayer{layer_idx}MtlBtn"
        pick_m_lbl = "PickLayerBBtnLabel" if layer_idx == 1 else f"PickLayer{layer_idx}MtlBtnLabel"
        pick_m_btn = _setup_named_button(
            w, is_wt, canvas, pick_m_name, pick_m_lbl,
            "<-",
            321.0, m_y, 27.0, 23.0,
            color=(0.65, 0.95, 1.0, 1.0),
            apply_layout=apply_layout,
            tooltip=f"Assign selected Material Instance from Content Browser to Layer {layer_idx}",
        )

        find_m_name = "FindLayerBBtn" if layer_idx == 1 else f"FindLayer{layer_idx}MtlBtn"
        find_m_lbl = "FindLayerBBtnLabel" if layer_idx == 1 else f"FindLayer{layer_idx}MtlBtnLabel"
        find_m_btn = _setup_named_button(
            w, is_wt, canvas, find_m_name, find_m_lbl,
            "F",
            350.0, m_y, 27.0, 23.0,
            color=(0.98, 0.88, 0.60, 1.0),
            apply_layout=apply_layout,
            tooltip=f"Find Layer {layer_idx} Material in Content Browser",
        )

        m_check = _create_inline_checkbox(
            f"Layer{layer_idx}MtlCheck",
            381.0, m_y + 1.0, 22.0, True,
            tooltip=f"Enable / Disable Layer {layer_idx} Material",
        )

        # Row 2: Mask: [100,0] [No Map / T_*] [<-] [F] [x] 3P[ ]
        _setup_named_label(
            w, is_wt, canvas, f"LayerMaskLbl_{layer_idx}",
            "Mask:",
            18.0, k_y + 4.0, 32.0, 14.0,
            size=8, bold=False, color=(0.78, 0.82, 0.88, 1.0),
            apply_layout=apply_layout,
        )
        mask_amt_sb = _create_inline_spinbox(
            f"Spin_Layer{layer_idx}_Mask_Amount",
            50.0, k_y, 56.0, 23.0,
            default_val=100.0, min_val=0.0, max_val=100.0, step=1.0, digits=1,
        )

        mask_combo_name = "BlendMaskComboBox" if layer_idx == 1 else f"Layer{layer_idx}MaskComboBox"
        created_kc = (_find_widget_any(w, is_wt, mask_combo_name) is None)
        k_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, mask_combo_name)
        if apply_layout or created_kc:
            _style_combo_box(k_combo)
        _place_on_canvas(canvas, k_combo, 108.0, k_y, 168.0, 23.0, apply_layout=apply_layout)

        pick_k_name = "PickBlendMaskBtn" if layer_idx == 1 else f"PickLayer{layer_idx}MaskBtn"
        pick_k_lbl = "PickBlendMaskBtnLabel" if layer_idx == 1 else f"PickLayer{layer_idx}MaskBtnLabel"
        pick_k_btn = _setup_named_button(
            w, is_wt, canvas, pick_k_name, pick_k_lbl,
            "<-",
            278.0, k_y, 25.0, 23.0,
            color=(0.65, 0.95, 1.0, 1.0),
            apply_layout=apply_layout,
            tooltip=f"Assign selected Texture from Content Browser to Layer {layer_idx} Mask",
        )

        find_k_name = "FindBlendMaskBtn" if layer_idx == 1 else f"FindLayer{layer_idx}MaskBtn"
        find_k_lbl = "FindBlendMaskBtnLabel" if layer_idx == 1 else f"FindLayer{layer_idx}MaskBtnLabel"
        find_k_btn = _setup_named_button(
            w, is_wt, canvas, find_k_name, find_k_lbl,
            "F",
            305.0, k_y, 25.0, 23.0,
            color=(0.98, 0.88, 0.60, 1.0),
            apply_layout=apply_layout,
            tooltip=f"Find Layer {layer_idx} Mask Texture in Content Browser",
        )

        k_check = _create_inline_checkbox(
            f"Layer{layer_idx}MaskCheck",
            333.0, k_y + 1.0, 22.0, True,
            tooltip=f"Enable / Disable Layer {layer_idx} Mask Map",
        )

        _setup_named_label(
            w, is_wt, canvas, f"LayerMaskTripLbl_{layer_idx}",
            "3P",
            356.0, k_y + 4.0, 18.0, 14.0,
            size=7, bold=True, color=(0.55, 0.94, 1.0, 1.0),
            apply_layout=apply_layout,
        )

        k_trip_check = _create_inline_checkbox(
            f"Layer{layer_idx}MaskTriplanarCheck",
            375.0, k_y + 1.0, 22.0, False,
            tooltip=f"Triplanar (World-Aligned Coordinates) for Layer {layer_idx} Mask & Seams — Checked: World Coordinates, Unchecked: Mesh UV Unwrap",
        )

        layer_ui_rows.append(
            {
                "idx": layer_idx,
                "mtl_amt": mtl_amt_sb,
                "mtl_combo": m_combo,
                "pick_mtl": pick_m_btn,
                "find_mtl": find_m_btn,
                "mtl_check": m_check,
                "mask_amt": mask_amt_sb,
                "mask_combo": k_combo,
                "pick_mask": pick_k_btn,
                "find_mask": find_k_btn,
                "mask_check": k_check,
                "mask_trip_check": k_trip_check,
            }
        )

    lb_combo = layer_ui_rows[0]["mtl_combo"]
    mask_combo = layer_ui_rows[0]["mask_combo"]

    # Dedicated Seam Material + Layer B, Layer C, Layer D Material Rows for Section 5 (Y = 1674.0 .. 1752.0, 26px per row)
    _setup_named_label(
        w, is_wt, canvas, "SeamMtlLabel",
        "Seam Mtl:",
        14.0, 1678.0, 62.0, 14.0,
        size=8, bold=True, color=(0.78, 0.90, 1.0, 1.0),
        apply_layout=apply_layout,
    )
    seam_mtl_amt_sb = _create_inline_spinbox(
        "Spin_Seam_Mtl_Amount",
        78.0, 1674.0, 50.0, 23.0,
        default_val=100.0, min_val=0.0, max_val=100.0, step=1.0, digits=1,
    )
    created_smc = (_find_widget_any(w, is_wt, "SeamMtlComboBox") is None)
    seam_mtl_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "SeamMtlComboBox")
    if apply_layout or created_smc:
        _style_combo_box(seam_mtl_combo)
    _place_on_canvas(canvas, seam_mtl_combo, 131.0, 1674.0, 187.0, 23.0, apply_layout=apply_layout)

    pick_seam_btn = _setup_named_button(
        w, is_wt, canvas, "PickSeamMtlBtn", "PickSeamMtlBtnLabel",
        "<-",
        321.0, 1674.0, 27.0, 23.0,
        color=(0.65, 0.95, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Assign selected Material Instance from Content Browser into Substance Seams (Mortar / Grout)",
    )
    find_seam_btn = _setup_named_button(
        w, is_wt, canvas, "FindSeamMtlBtn", "FindSeamMtlBtnLabel",
        "F",
        350.0, 1674.0, 27.0, 23.0,
        color=(0.98, 0.88, 0.60, 1.0),
        apply_layout=apply_layout,
        tooltip="Find Seam Material in Content Browser",
    )
    seam_mtl_check = _create_inline_checkbox(
        "SeamMtlCheck",
        381.0, 1675.0, 22.0, True,
        tooltip="Enable / Disable Seam Material (Recessed Mortar / Grout Joints)",
    )

    # Collapse any legacy Layer F widgets if present
    for old_f_name in (
        "TileLayerFMtlLabel", "Spin_TileLayerF_Mtl_Amount", "TileLayerFMtlComboBox",
        "PickTileLayerFMtlBtn", "PickTileLayerFMtlBtnLabel", "FindTileLayerFMtlBtn",
        "FindTileLayerFMtlBtnLabel", "TileLayerFMtlCheck",
    ):
        old_fw = _find_widget_any(w, is_wt, old_f_name)
        if old_fw:
            try:
                old_fw.set_visibility(unreal.SlateVisibility.COLLAPSED)
                _place_on_canvas(canvas, old_fw, -500.0, 1674.0, 10.0, 10.0, apply_layout=True)
            except Exception:
                pass

    tile_layer_rows = []
    for t_letter, t_slot_k, t_y, t_col in (
        ("B", 1, 1700.0, (0.68, 0.96, 0.86, 1.0)),
        ("C", 2, 1726.0, (0.76, 0.92, 1.0, 1.0)),
        ("D", 3, 1752.0, (0.94, 0.86, 1.0, 1.0)),
    ):
        _setup_named_label(
            w, is_wt, canvas, f"TileLayer{t_letter}MtlLabel",
            f"Layer {t_letter} Mtl:",
            14.0, t_y + 4.0, 62.0, 14.0,
            size=8, bold=True, color=t_col,
            apply_layout=apply_layout,
        )
        t_amt_sb = _create_inline_spinbox(
            f"Spin_TileLayer{t_letter}_Mtl_Amount",
            78.0, t_y, 50.0, 23.0,
            default_val=100.0, min_val=0.0, max_val=100.0, step=1.0, digits=1,
        )
        t_combo_name = f"TileLayer{t_letter}MtlComboBox"
        created_tc = (_find_widget_any(w, is_wt, t_combo_name) is None)
        t_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, t_combo_name)
        if apply_layout or created_tc:
            _style_combo_box(t_combo)
        _place_on_canvas(canvas, t_combo, 131.0, t_y, 187.0, 23.0, apply_layout=apply_layout)

        t_pick_btn = _setup_named_button(
            w, is_wt, canvas, f"PickTileLayer{t_letter}MtlBtn", f"PickTileLayer{t_letter}MtlBtnLabel",
            "<-",
            321.0, t_y, 27.0, 23.0,
            color=(0.65, 0.95, 1.0, 1.0),
            apply_layout=apply_layout,
            tooltip=f"Assign selected Material Instance from Content Browser into Tile Variation Layer {t_letter} (Random Tiles {t_letter})",
        )
        t_find_btn = _setup_named_button(
            w, is_wt, canvas, f"FindTileLayer{t_letter}MtlBtn", f"FindTileLayer{t_letter}MtlBtnLabel",
            "F",
            350.0, t_y, 27.0, 23.0,
            color=(0.98, 0.88, 0.60, 1.0),
            apply_layout=apply_layout,
            tooltip=f"Find Layer {t_letter} Material in Content Browser",
        )
        t_check = _create_inline_checkbox(
            f"TileLayer{t_letter}MtlCheck",
            381.0, t_y + 1.0, 22.0, True,
            tooltip=f"Enable / Disable Tile Variation Layer {t_letter}",
        )
        tile_layer_rows.append(
            {
                "letter": t_letter,
                "slot_k": t_slot_k,
                "amt_sb": t_amt_sb,
                "combo": t_combo,
                "pick_btn": t_pick_btn,
                "find_btn": t_find_btn,
                "check": t_check,
            }
        )

    def _refresh_blend_combos(auto_select_first_on_filter: bool = False):
        folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
        mis = _discover_material_instances(folder_now)
        mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
        if not isinstance(mi_map, dict):
            mi_map = {}
        for m_path in mis:
            mi_map[m_path.split("/")[-1]] = m_path
        builtins._COMFY_MI_MAP = mi_map

        masks = _discover_mask_textures(folder_now)
        mask_map = getattr(builtins, "_COMFY_MASK_MAP", {})
        if not isinstance(mask_map, dict):
            mask_map = {}
        for t_path in masks:
            mask_map[t_path.split("/")[-1]] = t_path
        builtins._COMFY_MASK_MAP = mask_map

        q_a = str(la_search.get_text() or "").strip() if la_search else ""
        q_m = str(mask_search.get_text() or "").strip() if mask_search else ""

        cur_a = str(la_combo.get_selected_option() or "").strip()
        if not cur_a:
            act_mi = _get_selected_actor_active_mi()
            last_mi = getattr(builtins, "_COMFY_LAST_MATERIAL", None)
            if act_mi:
                cur_a = act_mi.get_path_name().split(".")[0].split("/")[-1]
            elif isinstance(last_mi, unreal.MaterialInstanceConstant):
                cur_a = last_mi.get_path_name().split(".")[0].split("/")[-1]

        builtins._COMFY_SYNCING_UI = True
        try:
            # Base mtl combo
            la_combo.clear_options()
            la_shorts = []
            for m_path in mis:
                if _matches_search_query(m_path, q_a):
                    s_name = m_path.split("/")[-1]
                    if s_name not in la_shorts:
                        la_shorts.append(s_name)
                        la_combo.add_option(s_name)
            la_combo.add_option("None")
            if not auto_select_first_on_filter and cur_a and (cur_a in la_shorts or cur_a == "None"):
                la_combo.set_selected_option(cur_a)
            elif la_shorts:
                la_combo.set_selected_option(la_shorts[0])
            else:
                la_combo.set_selected_option("None")

            # Layer 1..10 Mtl & Mask combos + Section 5 Seam Mtl combo
            alb_texs = _discover_albedo_textures(folder_now)
            filtered_mis = []
            for t_path in alb_texs:
                if _matches_search_query(t_path, q_a):
                    s_name = t_path.split("/")[-1]
                    if s_name not in filtered_mis:
                        filtered_mis.append(s_name)
            for m_path in mis:
                if _matches_search_query(m_path, q_a):
                    s_name = m_path.split("/")[-1]
                    if s_name not in filtered_mis:
                        filtered_mis.append(s_name)

            filtered_masks = []
            for t_path in masks:
                if _matches_search_query(t_path, q_m):
                    s_name = t_path.split("/")[-1]
                    if s_name not in filtered_masks:
                        filtered_masks.append(s_name)

            for row_d in layer_ui_rows:
                mc = row_d["mtl_combo"]
                kc = row_d["mask_combo"]
                cur_mc = str(mc.get_selected_option() or "").strip()
                cur_kc = str(kc.get_selected_option() or "").strip()

                mc.clear_options()
                mc.add_option("None")
                for s_name in filtered_mis:
                    mc.add_option(s_name)
                if cur_mc and (cur_mc in filtered_mis or cur_mc.startswith("None")):
                    mc.set_selected_option("None" if cur_mc.startswith("None") else cur_mc)
                else:
                    mc.set_selected_option("None")

                kc.clear_options()
                kc.add_option("No Map")
                for s_name in filtered_masks:
                    kc.add_option(s_name)
                if cur_kc and (cur_kc in filtered_masks or cur_kc == "No Map"):
                    kc.set_selected_option(cur_kc)
                else:
                    kc.set_selected_option("No Map")

            cur_seam_mc = str(seam_mtl_combo.get_selected_option() or "").strip()
            seam_mtl_combo.clear_options()
            seam_mtl_combo.add_option("None")
            for s_name in filtered_mis:
                seam_mtl_combo.add_option(s_name)
            if cur_seam_mc and (cur_seam_mc in filtered_mis or cur_seam_mc.startswith("None")):
                seam_mtl_combo.set_selected_option("None" if cur_seam_mc.startswith("None") else cur_seam_mc)
            else:
                seam_mtl_combo.set_selected_option("None")

            for tr in tile_layer_rows:
                tc = tr["combo"]
                cur_tc = str(tc.get_selected_option() or "").strip()
                tc.clear_options()
                tc.add_option("None")
                for s_name in filtered_mis:
                    tc.add_option(s_name)
                if cur_tc and (cur_tc in filtered_mis or cur_tc.startswith("None")):
                    tc.set_selected_option("None" if cur_tc.startswith("None") else cur_tc)
                else:
                    tc.set_selected_option("None")
        finally:
            builtins._COMFY_SYNCING_UI = False

    _refresh_blend_combos()

    # Hide legacy unified Blend_Mask_Tiling spinbox and label if present in WidgetTree
    for old_w_name in ("SpinLbl_Blend_Mask_Tiling", "Spin_Blend_Mask_Tiling"):
        old_w = _find_widget_any(w, is_wt, old_w_name)
        if old_w:
            try:
                old_w.set_visibility(unreal.SlateVisibility.COLLAPSED)
                _place_on_canvas(canvas, old_w, -500.0, 1250.0, 10.0, 10.0, apply_layout=True)
            except Exception:
                pass

    # Row: Select which Layer's Mask (Layer 1 .. Layer 10) is being edited + Bake Mixed Mtl button
    _setup_named_label(
        w, is_wt, canvas, "EditMaskLayerLabel",
        "Edit Mask of Layer:",
        14.0, 1478.0, 114.0, 14.0,
        size=8, bold=True, color=(0.68, 0.88, 1.0, 1.0),
        apply_layout=apply_layout,
    )
    created_eml = (_find_widget_any(w, is_wt, "EditMaskLayerComboBox") is None)
    edit_mask_layer_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "EditMaskLayerComboBox")
    if apply_layout or created_eml:
        _style_combo_box(edit_mask_layer_combo)
    cur_eml_sel = str(edit_mask_layer_combo.get_selected_option() or "").strip()
    edit_mask_layer_combo.clear_options()
    for l_i in range(1, 11):
        edit_mask_layer_combo.add_option(f"Layer {l_i}")
    if cur_eml_sel.startswith("Layer "):
        edit_mask_layer_combo.set_selected_option(cur_eml_sel)
    else:
        edit_mask_layer_combo.set_selected_option("Layer 1")
    _place_on_canvas(canvas, edit_mask_layer_combo, 130.0, 1474.0, 146.0, 24.0, apply_layout=apply_layout)

    bake_mixed_btn = _setup_named_button(
        w, is_wt, canvas, "BakeMixedMtlBtn", "BakeMixedMtlBtnLabel",
        "Bake Mixed Mtl",
        282.0, 1474.0, 122.0, 24.0,
        color=(0.45, 0.98, 0.72, 1.0),
        apply_layout=apply_layout,
        tooltip="Bakes Base mtl + all active Corona Layers (1..10) & Masks into a single standalone Material Instance (MI_Baked_*) ready for Seams & Tile Generator!",
    )

    # Quick Action Buttons under Edit Mask of Layer (4 buttons: Mask Only, Seams Only, Invert Mask, Reset All)
    mask_only_btn = _setup_named_button(
        w, is_wt, canvas, "MaskOnlyBtn", "MaskOnlyBtnLabel",
        "Mask Only",
        14.0, 1504.0, 93.0, 25.0,
        color=(0.65, 0.96, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Apply B&W Masks only and disable Substance Seams",
    )
    seams_only_btn = _setup_named_button(
        w, is_wt, canvas, "SeamsOnlyBtn", "SeamsOnlyBtnLabel",
        "Seams Only",
        113.0, 1504.0, 93.0, 25.0,
        color=(0.58, 0.98, 0.82, 1.0),
        apply_layout=apply_layout,
        tooltip="Enable Substance Seams only and disable B&W Masks and Random/Checkerboard Tile Blends",
    )
    inv_mask_btn = _setup_named_button(
        w, is_wt, canvas, "InvertMaskBtn", "InvertMaskBtnLabel",
        "Invert Mask (0/1)",
        212.0, 1504.0, 93.0, 25.0,
        color=(0.94, 0.96, 1.0, 1.0),
        apply_layout=apply_layout,
    )
    reset_all_btn = _setup_named_button(
        w, is_wt, canvas, "ResetAllBtn", "ResetAllBtnLabel",
        "Reset All",
        311.0, 1504.0, 93.0, 25.0,
        color=(1.0, 0.78, 0.55, 1.0),
        apply_layout=apply_layout,
    )

    if not is_wt:
        builtins._COMFY_LA_SEARCH = la_search
        builtins._COMFY_LAYER_A_COMBO = la_combo
        builtins._COMFY_LB_SEARCH = lb_search
        builtins._COMFY_LAYER_B_COMBO = lb_combo
        builtins._COMFY_SEAM_MTL_COMBO = seam_mtl_combo
        builtins._COMFY_SEAM_MTL_AMT = seam_mtl_amt_sb
        builtins._COMFY_SEAM_MTL_CHECK = seam_mtl_check
        builtins._COMFY_MASK_SEARCH = mask_search
        builtins._COMFY_MASK_COMBO = mask_combo
        builtins._COMFY_EDIT_MASK_LAYER_COMBO = edit_mask_layer_combo
        builtins._COMFY_CORONA_LAYER_ROWS = layer_ui_rows
        if not hasattr(builtins, "_COMFY_CORONA_LAYER_STATE") or not isinstance(getattr(builtins, "_COMFY_CORONA_LAYER_STATE", None), dict):
            builtins._COMFY_CORONA_LAYER_STATE = {}

        def _get_selected_mask_layer_idx() -> int:
            try:
                sel_txt = str(edit_mask_layer_combo.get_selected_option() or "Layer 1").strip()
                if sel_txt.startswith("Layer "):
                    return max(1, min(10, int(sel_txt.split(" ")[1])))
            except Exception:
                pass
            return 1

        def _get_layer_mask_params(mi_key: str, l_idx: int) -> dict:
            st_all = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
            st_mi = st_all.setdefault(mi_key, {})
            st_l = st_mi.setdefault(l_idx, {})
            raw_tx = float(st_l.get("Blend_Mask_Tiling_X", 1.0))
            raw_ty = float(st_l.get("Blend_Mask_Tiling_Y", 1.0))
            raw_cn = float(st_l.get("Blend_Mask_Contrast", 1.0))
            tx_clean = max(0.01, raw_tx) if raw_tx > 0.001 else 1.0
            ty_clean = max(0.01, raw_ty) if raw_ty > 0.001 else 1.0
            cn_clean = max(0.05, raw_cn) if raw_cn > 0.001 else 1.0
            st_l["Blend_Mask_Tiling_X"] = tx_clean
            st_l["Blend_Mask_Tiling_Y"] = ty_clean
            st_l["Blend_Mask_Contrast"] = cn_clean
            return {
                "Blend_Mask_Tiling_X": tx_clean,
                "Blend_Mask_Tiling_Y": ty_clean,
                "Blend_Mask_Brightness": float(st_l.get("Blend_Mask_Brightness", 0.0)),
                "Blend_Mask_Contrast": cn_clean,
                "Blend_Mask_Invert": float(st_l.get("Blend_Mask_Invert", 0.0)),
                "Blend_Mask_Triplanar": float(st_l.get("Blend_Mask_Triplanar", 1.0 if st_l.get("mask_trip", False) else 0.0)),
            }

        def _sync_mask_spinboxes_for_selected_layer(mi):
            if not mi:
                return
            mi_key = mi.get_path_name().split(".")[0]
            l_idx = _get_selected_mask_layer_idx()
            m_params = _get_layer_mask_params(mi_key, l_idx)
            spin_map = getattr(builtins, "_COMFY_SPINBOX_MAP", {})
            builtins._COMFY_SYNCING_UI = True
            try:
                for p_k, p_val in m_params.items():
                    if p_k in spin_map:
                        spin_map[p_k][0].set_value(float(p_val))
            finally:
                builtins._COMFY_SYNCING_UI = False

        def _apply_corona_layer_row_to_mi(row_d: dict, save_asset: bool = True):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            target_mi = _get_active_layer_a_mi(folder_now)
            if not target_mi:
                return
            l_idx = row_d["idx"]
            sel_mtl = str(row_d["mtl_combo"].get_selected_option() or "None").strip()
            sel_msk = str(row_d["mask_combo"].get_selected_option() or "No Map").strip()
            mtl_amt = float(row_d["mtl_amt"].get_value())
            msk_amt = float(row_d["mask_amt"].get_value())
            mtl_on = bool(row_d["mtl_check"].is_checked())
            msk_on = bool(row_d["mask_check"].is_checked())
            msk_trip = bool(row_d["mask_trip_check"].is_checked()) if row_d.get("mask_trip_check") else False

            mi_key = target_mi.get_path_name().split(".")[0]
            st_all = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
            st_mi = st_all.setdefault(mi_key, {})
            prev_l = st_mi.get(l_idx, {})
            prev_l.update({
                "mtl": sel_mtl,
                "mtl_amt": mtl_amt,
                "mtl_on": mtl_on,
                "mask": sel_msk,
                "mask_amt": msk_amt,
                "mask_on": msk_on,
                "mask_trip": msk_trip,
                "Blend_Mask_Triplanar": 1.0 if msk_trip else 0.0,
            })
            st_mi[l_idx] = prev_l

            # If Layer 1, 2, or 3 was edited in Section 4, mirror to Section 5 Layer B/C/D row
            if l_idx in (1, 2, 3) and (l_idx - 1) < len(tile_layer_rows):
                tr_sync = tile_layer_rows[l_idx - 1]
                builtins._COMFY_SYNCING_UI = True
                try:
                    if sel_mtl and not sel_mtl.startswith("None") and tr_sync["combo"].find_option_index(sel_mtl) < 0:
                        tr_sync["combo"].add_option(sel_mtl)
                    tr_sync["combo"].set_selected_option(sel_mtl if (sel_mtl and not sel_mtl.startswith("None")) else "None")
                    tr_sync["amt_sb"].set_value(mtl_amt)
                    tr_sync["check"].set_is_checked(mtl_on)
                finally:
                    builtins._COMFY_SYNCING_UI = False

            # Check if Section 5 Seam Mtl is active (uses dedicated Seam_* parameters, slot_idx = 0)
            seam_sel = str(seam_mtl_combo.get_selected_option() or "None").strip()
            seam_amt = float(seam_mtl_amt_sb.get_value())
            seam_on = bool(seam_mtl_check.is_checked())
            has_active_seam_mtl = bool(seam_sel and not seam_sel.startswith("None") and seam_on and seam_amt > 0.0)
            st_mi["seam"] = {"mtl": seam_sel, "amt": seam_amt, "on": seam_on}

            # Collect all active rows in bottom-to-top Corona order (Layer 1, Layer 2, Layer 3, ...)
            active_rows = []
            for r_chk in layer_ui_rows:
                r_m = str(r_chk["mtl_combo"].get_selected_option() or "None").strip()
                if r_m and not r_m.startswith("None") and bool(r_chk["mtl_check"].is_checked()) and float(r_chk["mtl_amt"].get_value()) > 0.0:
                    active_rows.append(r_chk)

            mel = unreal.MaterialEditingLibrary
            applied_summaries = []

            if has_active_seam_mtl:
                _assign_pbr_textures_by_stem_to_layer_slot(target_mi, seam_sel, slot_idx=0)
                seam_w = max(0.0, min(1.0, seam_amt / 100.0))
                mel.set_material_instance_scalar_parameter_value(
                    target_mi, "Seam_Mtl_Enable", seam_w, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
                applied_summaries.append(f"Seam:{seam_sel}({seam_w*100:.0f}%)")
            else:
                mel.set_material_instance_scalar_parameter_value(
                    target_mi, "Seam_Mtl_Enable", 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )

            if not active_rows and not has_active_seam_mtl:
                for slot_k in (1, 2, 3, 4):
                    en_name = "LayerB_Enable" if slot_k == 1 else f"Layer{slot_k}_Enable"
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, en_name, 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                l1_m_params = _get_layer_mask_params(mi_key, 1)
                if l_idx == 1:
                    l1_m_params["Blend_Mask_Triplanar"] = 1.0 if msk_trip else 0.0
                for mk_p, mk_v in l1_m_params.items():
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, mk_p, float(mk_v), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                mel.update_material_instance(target_mi)
                if save_asset:
                    unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
                _sync_spinboxes_from_mi(target_mi)
                _sync_mask_spinboxes_for_selected_layer(target_mi)
                _set_panel_status(f"[Layer {l_idx}] All overlay layers disabled on '{target_mi.get_name()}' (3P={msk_trip}).", color=(0.75, 0.82, 0.92, 1.0))
                return

            avail_slots = (1, 2, 3, 4)
            for idx_pos, slot_k in enumerate(avail_slots):
                en_name = "LayerB_Enable" if slot_k == 1 else f"Layer{slot_k}_Enable"
                if idx_pos >= len(active_rows):
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, en_name, 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                    continue

                act_row = active_rows[idx_pos]
                act_idx = act_row["idx"]
                act_mtl = str(act_row["mtl_combo"].get_selected_option() or "None").strip()
                act_msk = str(act_row["mask_combo"].get_selected_option() or "No Map").strip()
                act_mtl_w = max(0.0, min(1.0, float(act_row["mtl_amt"].get_value()) / 100.0))
                act_msk_w = max(0.0, min(1.0, float(act_row["mask_amt"].get_value()) / 100.0))
                act_msk_on = bool(act_row["mask_check"].is_checked())
                act_msk_trip = bool(act_row["mask_trip_check"].is_checked()) if act_row.get("mask_trip_check") else False

                _assign_pbr_textures_by_stem_to_layer_slot(target_mi, act_mtl, slot_idx=slot_k)

                mel.set_material_instance_scalar_parameter_value(
                    target_mi, en_name, act_mtl_w, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
                mel.set_material_instance_scalar_parameter_value(
                    target_mi, "Vertex_Paint_Strength", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )

                act_mask_params = _get_layer_mask_params(mi_key, act_idx)
                act_mask_params["Blend_Mask_Triplanar"] = 1.0 if act_msk_trip else 0.0
                has_valid_mask = bool(act_msk and act_msk != "No Map")
                # When act_msk_on is True (default), keep Use_Mask = 1.0 even when Mask is "No Map" (with Mask_Strength = 0.0)
                # so the layer does not flood the whole mesh and can be painted via Mesh Paint (R/G/B/A) or Seams/Random Tiles!
                use_mask_val = 1.0 if act_msk_on else 0.0
                eff_msk_w = (act_msk_w if act_msk_on else 0.0) if has_valid_mask else 0.0

                if slot_k == 1:
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, "LayerB_Use_Mask", use_mask_val, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                    if has_valid_mask:
                        resolved_m = _resolve_mask_path(act_msk)
                        tex = unreal.EditorAssetLibrary.load_asset(resolved_m) if resolved_m else None
                        if tex and isinstance(tex, unreal.Texture):
                            mel.set_material_instance_texture_parameter_value(
                                target_mi, "BlendMaskTexture", tex, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            )
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, "Blend_Mask_Strength", eff_msk_w if has_valid_mask else 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                    for mk_p, mk_v in act_mask_params.items():
                        mel.set_material_instance_scalar_parameter_value(
                            target_mi, mk_p, float(mk_v), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                else:
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, f"Layer{slot_k}_Use_Mask", use_mask_val, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                    if has_valid_mask:
                        resolved_m = _resolve_mask_path(act_msk)
                        tex = unreal.EditorAssetLibrary.load_asset(resolved_m) if resolved_m else None
                        if tex and isinstance(tex, unreal.Texture):
                            mel.set_material_instance_texture_parameter_value(
                                target_mi, f"Layer{slot_k}_MaskTexture", tex, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            )
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, f"Layer{slot_k}_Mask_Strength", eff_msk_w if has_valid_mask else 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                    slot_param_map = {
                        "Blend_Mask_Tiling_X": f"Layer{slot_k}_Mask_Tiling_X",
                        "Blend_Mask_Tiling_Y": f"Layer{slot_k}_Mask_Tiling_Y",
                        "Blend_Mask_Brightness": f"Layer{slot_k}_Mask_Brightness",
                        "Blend_Mask_Contrast": f"Layer{slot_k}_Mask_Contrast",
                        "Blend_Mask_Invert": f"Layer{slot_k}_Mask_Invert",
                        "Blend_Mask_Triplanar": f"Layer{slot_k}_Mask_Triplanar",
                    }
                    for mk_p, mk_v in act_mask_params.items():
                        dst_mp = slot_param_map.get(mk_p)
                        if dst_mp:
                            mel.set_material_instance_scalar_parameter_value(
                                target_mi, dst_mp, float(mk_v), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            )

                applied_summaries.append(f"L{act_idx}:{act_mtl}({act_mtl_w*100:.0f}%{' 3P' if act_msk_trip else ''})")

            mel.update_material_instance(target_mi)
            if save_asset:
                unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
                apply_material_to_selected_actors(target_mi)
            _sync_spinboxes_from_mi(target_mi)
            _sync_mask_spinboxes_for_selected_layer(target_mi)
            _set_panel_status(
                f"[Layered Material] Active ({len(applied_summaries)}): {', '.join(applied_summaries)} -> '{target_mi.get_name()}'",
                color=(0.45, 0.92, 0.60, 1.0),
            )

        def _apply_seam_material_to_mi(save_asset: bool = True, auto_enable_seams: bool = False):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            target_mi = _get_active_layer_a_mi(folder_now)
            if not target_mi:
                if save_asset:
                    _set_panel_status("[!] Select or generate a Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
                return
            seam_sel = str(seam_mtl_combo.get_selected_option() or "None").strip()
            seam_amt = float(seam_mtl_amt_sb.get_value())
            seam_on = bool(seam_mtl_check.is_checked())
            mel = unreal.MaterialEditingLibrary

            if auto_enable_seams and seam_sel and not seam_sel.startswith("None") and seam_on:
                cur_seams_en = float(mel.get_material_instance_scalar_parameter_value(
                    target_mi, "Seams_Enable", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                ))
                if cur_seams_en <= 0.001:
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, "Seams_Enable", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                cur_in_seams = float(mel.get_material_instance_scalar_parameter_value(
                    target_mi, "Blend_In_Seams", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                ))
                if cur_in_seams <= 0.001:
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, "Blend_In_Seams", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )

            _apply_corona_layer_row_to_mi(layer_ui_rows[0], save_asset=save_asset)
            if save_asset:
                if seam_sel and not seam_sel.startswith("None") and seam_on and seam_amt > 0.0:
                    _set_panel_status(
                        f"[Substance Seams Mtl] Assigned '{seam_sel}' ({seam_amt:.0f}%) into Mortar Seams of '{target_mi.get_name()}'!",
                        color=(0.45, 0.96, 0.72, 1.0),
                    )
                else:
                    _set_panel_status(
                        f"[Substance Seams Mtl] Cleared / disabled Seam Material on '{target_mi.get_name()}'.",
                        color=(0.75, 0.82, 0.92, 1.0),
                    )

        def _apply_tile_layer_material_to_mi(tr_row: dict, save_asset: bool = True, auto_enable_tiles: bool = False):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            target_mi = _get_active_layer_a_mi(folder_now)
            if not target_mi:
                if save_asset:
                    _set_panel_status("[!] Select or generate a Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
                return
            t_letter = tr_row["letter"]
            slot_k = tr_row["slot_k"]
            t_sel = str(tr_row["combo"].get_selected_option() or "None").strip()
            t_amt = float(tr_row["amt_sb"].get_value())
            t_on = bool(tr_row["check"].is_checked())
            mel = unreal.MaterialEditingLibrary

            # Mirror into Corona Layer 1/2/3 row so Section 4 and Section 5 stay synchronized
            c_row = layer_ui_rows[slot_k - 1]
            builtins._COMFY_SYNCING_UI = True
            try:
                if t_sel and not t_sel.startswith("None") and c_row["mtl_combo"].find_option_index(t_sel) < 0:
                    c_row["mtl_combo"].add_option(t_sel)
                c_row["mtl_combo"].set_selected_option(t_sel if (t_sel and not t_sel.startswith("None")) else "None")
                c_row["mtl_amt"].set_value(t_amt)
                c_row["mtl_check"].set_is_checked(t_on)
            finally:
                builtins._COMFY_SYNCING_UI = False

            rnd_param = "Blend_Random_Tiles" if slot_k == 1 else f"Layer{slot_k}_Random_Tiles"
            if auto_enable_tiles and t_sel and not t_sel.startswith("None") and t_on:
                cur_seams_en = float(mel.get_material_instance_scalar_parameter_value(
                    target_mi, "Seams_Enable", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                ))
                if cur_seams_en <= 0.001:
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, "Seams_Enable", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                cur_rnd = float(mel.get_material_instance_scalar_parameter_value(
                    target_mi, rnd_param, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                ))
                cur_chk = float(mel.get_material_instance_scalar_parameter_value(
                    target_mi, "Blend_Checkerboard_Tiles", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )) if slot_k == 1 else 0.0
                if cur_rnd <= 0.001 and cur_chk <= 0.001:
                    mel.set_material_instance_scalar_parameter_value(
                        target_mi, rnd_param, 0.25, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )

            _apply_corona_layer_row_to_mi(c_row, save_asset=save_asset)
            if save_asset:
                if t_sel and not t_sel.startswith("None") and t_on and t_amt > 0.0:
                    _set_panel_status(
                        f"[Tile Layer {t_letter}] Assigned '{t_sel}' ({t_amt:.0f}%) into Layer {t_letter} ({rnd_param}) of '{target_mi.get_name()}'!",
                        color=(0.45, 0.96, 0.72, 1.0),
                    )
                else:
                    _set_panel_status(
                        f"[Tile Layer {t_letter}] Cleared / disabled Layer {t_letter} Material on '{target_mi.get_name()}'.",
                        color=(0.75, 0.82, 0.92, 1.0),
                    )

        def _resolve_mi_short_from_albedo_tex(alb_tex, target_tint_rgb=None) -> str:
            if not alb_tex:
                return "None"
            t_name = str(alb_tex.get_name() or "").strip()
            if not t_name or t_name.startswith("T_Default_") or t_name.startswith("Default"):
                return "None"
            mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
            alb_path = alb_tex.get_path_name().split(".")[0]
            mel = unreal.MaterialEditingLibrary
            candidates = []
            for s_short, s_path in list(mi_map.items()):
                try:
                    c_mi = unreal.EditorAssetLibrary.load_asset(s_path)
                    if c_mi and isinstance(c_mi, unreal.MaterialInstanceConstant):
                        c_alb = mel.get_material_instance_texture_parameter_value(
                            c_mi, "AlbedoTexture", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                        if c_alb and c_alb.get_path_name().split(".")[0] == alb_path:
                            candidates.append((s_short, c_mi))
                except Exception:
                    pass
            if candidates and target_tint_rgb is not None:
                best_short = None
                best_err = 999.0
                for s_short, c_mi in candidates:
                    try:
                        c_bri = float(mel.get_material_instance_scalar_parameter_value(c_mi, "Albedo_Brightness", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                        if c_bri <= 0.0:
                            c_bri = 1.0
                        c_col = mel.get_material_instance_vector_parameter_value(c_mi, "Albedo_ColorTint", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
                        cr = (float(c_col.r) if c_col else 1.0) * c_bri
                        cg = (float(c_col.g) if c_col else 1.0) * c_bri
                        cb = (float(c_col.b) if c_col else 1.0) * c_bri
                        err = abs(cr - target_tint_rgb[0]) + abs(cg - target_tint_rgb[1]) + abs(cb - target_tint_rgb[2])
                        if err < best_err:
                            best_err = err
                            best_short = s_short
                    except Exception:
                        pass
                if best_short:
                    return best_short
            if t_name.startswith("T_") and t_name.endswith("_Albedo"):
                stem = t_name[2:-7]
                cand_short = f"MI_{stem}"
                if cand_short in mi_map or _resolve_mi_path(cand_short):
                    return cand_short
            if candidates:
                return candidates[0][0]
            if t_name.startswith("T_") and t_name.endswith("_Albedo"):
                return f"MI_{t_name[2:-7]}"
            return "None"

        def _extract_hardware_layers_from_mi(mi) -> dict:
            extracted = {}
            if not mi:
                return extracted
            mel = unreal.MaterialEditingLibrary
            mask_map = getattr(builtins, "_COMFY_MASK_MAP", {})
            try:
                sm_en = float(mel.get_material_instance_scalar_parameter_value(mi, "Seam_Mtl_Enable", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                sm_alb = mel.get_material_instance_texture_parameter_value(mi, "Seam_AlbedoTexture", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
                sm_col = mel.get_material_instance_vector_parameter_value(mi, "Seam_ColorTint", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
                sm_tint = (float(sm_col.r), float(sm_col.g), float(sm_col.b)) if sm_col else None
                sm_short = _resolve_mi_short_from_albedo_tex(sm_alb, target_tint_rgb=sm_tint)
                if sm_en > 0.001 and sm_short != "None":
                    extracted["seam"] = {
                        "mtl": sm_short,
                        "amt": max(0.0, min(100.0, sm_en * 100.0)),
                        "on": True,
                    }
            except Exception:
                pass
            for slot_k in (1, 2, 3, 4):
                try:
                    en_name = "LayerB_Enable" if slot_k == 1 else f"Layer{slot_k}_Enable"
                    alb_name = "LayerB_AlbedoTexture" if slot_k == 1 else f"Layer{slot_k}_AlbedoTexture"
                    col_name = "LayerB_ColorTint" if slot_k == 1 else f"Layer{slot_k}_ColorTint"
                    msk_name = "BlendMaskTexture" if slot_k == 1 else f"Layer{slot_k}_MaskTexture"
                    use_m_name = "LayerB_Use_Mask" if slot_k == 1 else f"Layer{slot_k}_Use_Mask"
                    str_m_name = "Blend_Mask_Strength" if slot_k == 1 else f"Layer{slot_k}_Mask_Strength"
                    tx_name = "Blend_Mask_Tiling_X" if slot_k == 1 else f"Layer{slot_k}_Mask_Tiling_X"
                    ty_name = "Blend_Mask_Tiling_Y" if slot_k == 1 else f"Layer{slot_k}_Mask_Tiling_Y"
                    br_name = "Blend_Mask_Brightness" if slot_k == 1 else f"Layer{slot_k}_Mask_Brightness"
                    cn_name = "Blend_Mask_Contrast" if slot_k == 1 else f"Layer{slot_k}_Mask_Contrast"
                    iv_name = "Blend_Mask_Invert" if slot_k == 1 else f"Layer{slot_k}_Mask_Invert"
                    tp_name = "Blend_Mask_Triplanar" if slot_k == 1 else f"Layer{slot_k}_Mask_Triplanar"

                    en_v = float(mel.get_material_instance_scalar_parameter_value(mi, en_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    alb_t = mel.get_material_instance_texture_parameter_value(mi, alb_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
                    col_v = mel.get_material_instance_vector_parameter_value(mi, col_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
                    l_tint = (float(col_v.r), float(col_v.g), float(col_v.b)) if col_v else None
                    mtl_short = "None"
                    if alb_t:
                        a_n = str(alb_t.get_name() or "").strip()
                        if a_n and not a_n.startswith(("WhiteSquare", "Default", "BaseFlatten", "T_Default_")):
                            mtl_short = a_n
                    if mtl_short == "None":
                        mtl_short = _resolve_mi_short_from_albedo_tex(alb_t, target_tint_rgb=l_tint)
                    if en_v <= 0.001 or mtl_short == "None":
                        continue

                    use_m_v = float(mel.get_material_instance_scalar_parameter_value(mi, use_m_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    str_m_v = float(mel.get_material_instance_scalar_parameter_value(mi, str_m_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    msk_t = mel.get_material_instance_texture_parameter_value(mi, msk_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
                    msk_short = "No Map"
                    if msk_t:
                        m_n = str(msk_t.get_name() or "").strip()
                        if m_n and not m_n.startswith(("WhiteSquare", "Default", "BaseFlatten", "T_Default_")) and use_m_v >= 0.5:
                            msk_short = m_n
                            mask_map[m_n] = msk_t.get_path_name().split(".")[0]
                    builtins._COMFY_MASK_MAP = mask_map

                    tx_v = float(mel.get_material_instance_scalar_parameter_value(mi, tx_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    ty_v = float(mel.get_material_instance_scalar_parameter_value(mi, ty_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    br_v = float(mel.get_material_instance_scalar_parameter_value(mi, br_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    cn_v = float(mel.get_material_instance_scalar_parameter_value(mi, cn_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    iv_v = float(mel.get_material_instance_scalar_parameter_value(mi, iv_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    tp_v = float(mel.get_material_instance_scalar_parameter_value(mi, tp_name, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))

                    extracted[slot_k] = {
                        "mtl": mtl_short,
                        "mtl_amt": max(0.0, min(100.0, en_v * 100.0)),
                        "mtl_on": True,
                        "mask": msk_short,
                        "mask_amt": max(0.0, min(100.0, str_m_v * 100.0)) if str_m_v > 0.001 else 100.0,
                        "mask_on": bool(str_m_v > 0.001 or msk_short == "No Map"),
                        "mask_trip": bool(tp_v >= 0.5),
                        "Blend_Mask_Tiling_X": tx_v if tx_v > 0.0 else 1.0,
                        "Blend_Mask_Tiling_Y": ty_v if ty_v > 0.0 else 1.0,
                        "Blend_Mask_Brightness": br_v,
                        "Blend_Mask_Contrast": cn_v if cn_v > 0.0 else 1.0,
                        "Blend_Mask_Invert": iv_v,
                        "Blend_Mask_Triplanar": 1.0 if tp_v >= 0.5 else 0.0,
                    }
                except Exception:
                    pass
            return extracted

        def _sync_corona_layers_from_mi(mi):
            if not mi:
                return
            mi_key = mi.get_path_name().split(".")[0]
            st_all = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
            st_mi = st_all.setdefault(mi_key, {})
            hw_layers = _extract_hardware_layers_from_mi(mi)
            for k_hw in (1, 2, 3, 4):
                if k_hw not in hw_layers:
                    st_mi.pop(k_hw, None)
            if hw_layers:
                for k_idx, k_data in hw_layers.items():
                    st_mi[k_idx] = dict(k_data)

            mel = unreal.MaterialEditingLibrary
            l1_trip_hw = False
            try:
                l1_trip_hw = float(mel.get_material_instance_scalar_parameter_value(mi, "Blend_Mask_Triplanar", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)) >= 0.5
            except Exception:
                pass

            builtins._COMFY_SYNCING_UI = True
            try:
                saved_seam = st_mi.get("seam")
                if not saved_seam and "seam" in hw_layers:
                    saved_seam = hw_layers["seam"]
                    st_mi["seam"] = dict(saved_seam)
                if saved_seam and str(saved_seam.get("mtl", "None")) != "None":
                    sm_opt = str(saved_seam.get("mtl", "None"))
                    if seam_mtl_combo.find_option_index(sm_opt) < 0:
                        seam_mtl_combo.add_option(sm_opt)
                    seam_mtl_amt_sb.set_value(float(saved_seam.get("amt", 100.0)))
                    seam_mtl_check.set_is_checked(bool(saved_seam.get("on", True)))
                    seam_mtl_combo.set_selected_option(sm_opt)
                else:
                    seam_mtl_amt_sb.set_value(float(saved_seam.get("amt", 100.0)) if saved_seam else 100.0)
                    seam_mtl_check.set_is_checked(bool(saved_seam.get("on", True)) if saved_seam else True)
                    seam_mtl_combo.set_selected_option("None")

                for row_d in layer_ui_rows:
                    idx_l = row_d["idx"]
                    saved_r = st_mi.get(idx_l)
                    if saved_r and str(saved_r.get("mtl", "None")) != "None":
                        m_opt = str(saved_r.get("mtl", "None"))
                        k_opt = str(saved_r.get("mask", "No Map"))
                        if row_d["mtl_combo"].find_option_index(m_opt) < 0:
                            row_d["mtl_combo"].add_option(m_opt)
                        if k_opt and k_opt != "No Map" and row_d["mask_combo"].find_option_index(k_opt) < 0:
                            row_d["mask_combo"].add_option(k_opt)
                        row_d["mtl_amt"].set_value(float(saved_r.get("mtl_amt", 100.0)))
                        row_d["mask_amt"].set_value(float(saved_r.get("mask_amt", 100.0)))
                        row_d["mtl_check"].set_is_checked(bool(saved_r.get("mtl_on", True)))
                        row_d["mask_check"].set_is_checked(bool(saved_r.get("mask_on", True)))
                        if row_d.get("mask_trip_check"):
                            row_d["mask_trip_check"].set_is_checked(
                                bool(saved_r.get("mask_trip", float(saved_r.get("Blend_Mask_Triplanar", 0.0)) >= 0.5))
                            )
                        row_d["mtl_combo"].set_selected_option(m_opt)
                        row_d["mask_combo"].set_selected_option(k_opt)
                    else:
                        row_d["mtl_amt"].set_value(float(saved_r.get("mtl_amt", 100.0)) if saved_r else 100.0)
                        row_d["mask_amt"].set_value(float(saved_r.get("mask_amt", 100.0)) if saved_r else 100.0)
                        row_d["mtl_check"].set_is_checked(bool(saved_r.get("mtl_on", True)) if saved_r else True)
                        row_d["mask_check"].set_is_checked(bool(saved_r.get("mask_on", True)) if saved_r else True)
                        if row_d.get("mask_trip_check"):
                            row_d["mask_trip_check"].set_is_checked(
                                bool(saved_r.get("mask_trip", l1_trip_hw if idx_l == 1 else False)) if saved_r else (l1_trip_hw if idx_l == 1 else False)
                            )
                        row_d["mtl_combo"].set_selected_option("None")
                        row_d["mask_combo"].set_selected_option(str(saved_r.get("mask", "No Map")) if saved_r else "No Map")

                for tr in tile_layer_rows:
                    sk = tr["slot_k"]
                    saved_tr = st_mi.get(sk)
                    if saved_tr and str(saved_tr.get("mtl", "None")) != "None":
                        tm_opt = str(saved_tr.get("mtl", "None"))
                        if tr["combo"].find_option_index(tm_opt) < 0:
                            tr["combo"].add_option(tm_opt)
                        tr["amt_sb"].set_value(float(saved_tr.get("mtl_amt", 100.0)))
                        tr["check"].set_is_checked(bool(saved_tr.get("mtl_on", True)))
                        tr["combo"].set_selected_option(tm_opt)
                    else:
                        tr["amt_sb"].set_value(float(saved_tr.get("mtl_amt", 100.0)) if saved_tr else 100.0)
                        tr["check"].set_is_checked(bool(saved_tr.get("mtl_on", True)) if saved_tr else True)
                        tr["combo"].set_selected_option("None")
            finally:
                builtins._COMFY_SYNCING_UI = False
            _sync_mask_spinboxes_for_selected_layer(mi)
            ref_mp_fn = getattr(builtins, "_COMFY_REFRESH_MP_FN", None)
            if callable(ref_mp_fn):
                try:
                    ref_mp_fn()
                except Exception:
                    pass

        def _sync_panel_from_selected_actor_or_mi(picked_mi, actor_label: str = ""):
            if not picked_mi or not isinstance(picked_mi, unreal.MaterialInstanceConstant):
                return
            m_path = picked_mi.get_path_name().split(".")[0]
            m_short = m_path.split("/")[-1]
            mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
            mi_map[m_short] = m_path
            builtins._COMFY_MI_MAP = mi_map
            builtins._COMFY_LAST_MATERIAL = picked_mi
            builtins._COMFY_SYNCING_UI = True
            try:
                if la_combo.find_option_index(m_short) < 0:
                    la_combo.add_option(m_short)
                la_combo.set_selected_option(m_short)
                if mm_combo.find_option_index(m_short) < 0:
                    mm_combo.add_option(m_short)
                mm_combo.set_selected_option(m_short)
            finally:
                builtins._COMFY_SYNCING_UI = False
            _sync_spinboxes_from_mi(picked_mi)
            _sync_corona_layers_from_mi(picked_mi)

            act_layers = []
            for r_d in layer_ui_rows:
                rm = str(r_d["mtl_combo"].get_selected_option() or "None").strip()
                rk = str(r_d["mask_combo"].get_selected_option() or "No Map").strip()
                if rm and not rm.startswith("None") and bool(r_d["mtl_check"].is_checked()):
                    act_layers.append(f"L{r_d['idx']}: {rm} [{rk}]")
            src_tag = f"Actor '{actor_label}'" if actor_label else "Selected MI"
            if act_layers:
                _set_panel_status(
                    f"[Auto-Blend {src_tag}] Base: {m_short} + {' | '.join(act_layers)}",
                    color=(0.45, 0.96, 0.65, 1.0),
                )
            else:
                _set_panel_status(
                    f"[{src_tag}] Base mtl: {m_short} (Single Material — no active blend layers)",
                    color=(0.65, 0.88, 1.0, 1.0),
                )

        builtins._COMFY_SYNC_PANEL_FROM_ACTOR_FN = _sync_panel_from_selected_actor_or_mi

        def _on_edit_mask_layer_changed(selected_item, _selection_type):
            if not selected_item or getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            mi = _get_active_layer_a_mi(folder_now)
            l_idx = _get_selected_mask_layer_idx()
            if mi:
                _sync_mask_spinboxes_for_selected_layer(mi)
            _set_panel_status(
                f"[Mask Editor] Now editing mask parameters (Tiling X/Y, Brightness, Contrast, Invert) for Layer {l_idx}.",
                color=(0.55, 0.88, 1.0, 1.0),
            )

        def _on_disp_mode_changed(selected_item, _selection_type):
            if (
                not selected_item
                or getattr(builtins, "_COMFY_SYNCING_UI", False)
                or time.time() < getattr(builtins, "_COMFY_UI_INIT_UNTIL", 0.0)
                or _selection_type == unreal.SelectInfo.DIRECT
            ):
                return
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            mi = _get_active_layer_a_mi(folder_now)
            if not mi:
                return
            mode_str = str(selected_item)
            mel = unreal.MaterialEditingLibrary
            if mode_str == "Base layer only":
                mel.set_material_instance_scalar_parameter_value(
                    mi, "Blend_Height_Sharpness", 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            else:
                mel.set_material_instance_scalar_parameter_value(
                    mi, "Blend_Height_Sharpness", 0.5, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            mel.update_material_instance(mi)
            unreal.EditorAssetLibrary.save_loaded_asset(mi)
            _set_panel_status(f"[Displacement] Mode: '{mode_str}' on '{mi.get_name()}'.", color=(0.55, 0.88, 1.0, 1.0))

        def _on_la_search_changed(new_text):
            _refresh_blend_combos(auto_select_first_on_filter=True)

        def _on_mask_search_changed(new_text):
            _refresh_blend_combos(auto_select_first_on_filter=True)

        def _on_la_opening():
            _refresh_blend_combos()

        def _on_la_changed(selected_item, _selection_type):
            if (
                not selected_item
                or getattr(builtins, "_COMFY_SYNCING_UI", False)
                or time.time() < getattr(builtins, "_COMFY_UI_INIT_UNTIL", 0.0)
                or _selection_type == unreal.SelectInfo.DIRECT
            ):
                return
            sel_s = str(selected_item).strip()
            if sel_s == "None":
                return
            resolved = _resolve_mi_path(sel_s)
            mi = unreal.EditorAssetLibrary.load_asset(resolved) if resolved else None
            if mi and isinstance(mi, unreal.MaterialInstanceConstant):
                builtins._COMFY_LAST_MATERIAL = mi
                mm_c = getattr(builtins, "_COMFY_MASTER_COMBO", None)
                if mm_c:
                    builtins._COMFY_SYNCING_UI = True
                    try:
                        mm_c.add_option(sel_s)
                        mm_c.set_selected_option(sel_s)
                    finally:
                        builtins._COMFY_SYNCING_UI = False
                _sync_spinboxes_from_mi(mi)
                _sync_corona_layers_from_mi(mi)
                slot_id = _get_selected_poly_target_id(default_for_assign=-1)
                apply_material_to_selected_actors(mi, slot_idx=slot_id)
                _set_panel_status(
                    f"[Base mtl -> ID {slot_id if slot_id >= 0 else 'All'}] Applied & editing '{mi.get_name()}' in real time.",
                    color=(0.45, 0.96, 0.65, 1.0),
                )

        def _on_pick_la_cb_clicked():
            selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
            picked_mi = None
            for a in selected_assets:
                if isinstance(a, unreal.MaterialInstanceConstant):
                    picked_mi = a
                    break
            if not picked_mi:
                try:
                    actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                    for actor in actor_sub.get_selected_level_actors():
                        for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
                            for idx in range(comp.get_num_materials()):
                                mat_i = comp.get_material(idx)
                                if isinstance(mat_i, unreal.MaterialInstanceConstant):
                                    picked_mi = mat_i
                                    break
                            if picked_mi:
                                break
                        if picked_mi:
                            break
                except Exception:
                    pass
            if not picked_mi:
                _set_panel_status(
                    "[!] Select a Material Instance in Content Browser (or mesh actor in viewport) and click '<-'!",
                    color=(1.0, 0.72, 0.3, 1.0),
                )
                return
            m_path = picked_mi.get_path_name().split(".")[0]
            m_short = m_path.split("/")[-1]
            mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
            mi_map[m_short] = m_path
            builtins._COMFY_MI_MAP = mi_map
            builtins._COMFY_LAST_MATERIAL = picked_mi
            la_combo.add_option(m_short)
            la_combo.set_selected_option(m_short)
            _sync_spinboxes_from_mi(picked_mi)
            _sync_corona_layers_from_mi(picked_mi)
            _set_panel_status(
                f"[Base mtl] Picked '{m_short}' from selection.",
                color=(0.45, 0.92, 0.60, 1.0),
            )

        def _on_find_la_cb_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            mi = _get_active_layer_a_mi(folder_now)
            if mi:
                m_path = mi.get_path_name().split(".")[0]
                unreal.EditorAssetLibrary.sync_browser_to_objects([m_path])
                _set_panel_status(
                    f"[Browse] Synced Content Browser to Base mtl '{mi.get_name()}'.",
                    color=(0.55, 0.88, 1.0, 1.0),
                )
            else:
                _set_panel_status("[!] No Base mtl Material Instance selected!", color=(1.0, 0.72, 0.3, 1.0))

        # Bind callbacks for each of the 10 Corona Layers
        for row_d in layer_ui_rows:
            def _make_layer_callbacks(rd=row_d):
                l_num = rd["idx"]
                mc = rd["mtl_combo"]
                kc = rd["mask_combo"]
                m_sb = rd["mtl_amt"]
                k_sb = rd["mask_amt"]
                m_ck = rd["mtl_check"]
                k_ck = rd["mask_check"]

                def _on_mc_open():
                    _refresh_blend_combos()

                def _on_kc_open():
                    _refresh_blend_combos()

                def _on_mc_sel(sel_item, _stype):
                    if not sel_item or getattr(builtins, "_COMFY_SYNCING_UI", False):
                        return
                    _apply_corona_layer_row_to_mi(rd, save_asset=True)

                def _on_kc_sel(sel_item, _stype):
                    if not sel_item or getattr(builtins, "_COMFY_SYNCING_UI", False):
                        return
                    edit_mask_layer_combo.set_selected_option(f"Layer {l_num}")
                    _apply_corona_layer_row_to_mi(rd, save_asset=True)

                def _on_msb_chg(_v: float):
                    _apply_corona_layer_row_to_mi(rd, save_asset=False)

                def _on_msb_com(_v: float, _cm):
                    _apply_corona_layer_row_to_mi(rd, save_asset=True)

                def _on_ksb_chg(_v: float):
                    _apply_corona_layer_row_to_mi(rd, save_asset=False)

                def _on_ksb_com(_v: float, _cm):
                    _apply_corona_layer_row_to_mi(rd, save_asset=True)

                def _on_mck_chg(_is_checked: bool):
                    _apply_corona_layer_row_to_mi(rd, save_asset=True)

                def _on_kck_chg(_is_checked: bool):
                    _apply_corona_layer_row_to_mi(rd, save_asset=True)

                def _on_ktrip_chg(is_checked: bool):
                    _apply_corona_layer_row_to_mi(rd, save_asset=True)
                    mode_lbl = "Triplanar (World Coordinates)" if is_checked else "UV Unwrap (TexCoord[0])"
                    _set_panel_status(
                        f"[Layer {l_num} Mask Projection] Switched to {mode_lbl}.",
                        color=(0.45, 0.96, 0.78, 1.0) if is_checked else (0.65, 0.88, 1.0, 1.0),
                    )

                def _on_pick_m():
                    selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
                    for a in selected_assets:
                        if isinstance(a, unreal.Texture):
                            t_path = a.get_path_name().split(".")[0]
                            t_name = t_path.split("/")[-1]
                            t_stem = _extract_texture_base_stem(t_name)
                            alb_short = f"T_{t_stem}_Albedo"
                            tex_map = getattr(builtins, "_COMFY_TEX_MAP", {})
                            tex_map[t_name] = t_path
                            builtins._COMFY_TEX_MAP = tex_map
                            if mc.find_option_index(alb_short) < 0:
                                mc.add_option(alb_short)
                            mc.set_selected_option(alb_short)
                            _apply_corona_layer_row_to_mi(rd, save_asset=True)
                            if l_num in (1, 2, 3, 4):
                                _refresh_mp_mtl_combo()
                            return
                        if isinstance(a, unreal.MaterialInstanceConstant):
                            m_path = a.get_path_name().split(".")[0]
                            m_short = m_path.split("/")[-1]
                            mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
                            mi_map[m_short] = m_path
                            builtins._COMFY_MI_MAP = mi_map
                            if mc.find_option_index(m_short) < 0:
                                mc.add_option(m_short)
                            mc.set_selected_option(m_short)
                            _apply_corona_layer_row_to_mi(rd, save_asset=True)
                            if l_num in (1, 2, 3, 4):
                                _refresh_mp_mtl_combo()
                            return
                    _set_panel_status(f"[!] Select a Texture (T_*) or Material Instance (MI_*) in Content Browser for Layer {l_num}!", color=(1.0, 0.72, 0.3, 1.0))

                def _on_find_m():
                    sel_b = str(mc.get_selected_option() or "").strip()
                    if not sel_b or sel_b.startswith("None"):
                        _set_panel_status(f"[!] Layer {l_num} Mtl/Tex is currently None!", color=(1.0, 0.72, 0.3, 1.0))
                        return
                    tex_map = getattr(builtins, "_COMFY_TEX_MAP", {})
                    resolved_b = tex_map.get(sel_b) or _resolve_mi_path(sel_b)
                    if resolved_b and unreal.EditorAssetLibrary.does_asset_exist(resolved_b):
                        unreal.EditorAssetLibrary.sync_browser_to_objects([resolved_b])
                        _set_panel_status(f"[Browse] Synced Content Browser to Layer {l_num} '{sel_b}'.", color=(0.55, 0.88, 1.0, 1.0))

                def _on_pick_k():
                    selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
                    for a in selected_assets:
                        if isinstance(a, unreal.Texture):
                            t_path = a.get_path_name().split(".")[0]
                            t_short = t_path.split("/")[-1]
                            mask_map = getattr(builtins, "_COMFY_MASK_MAP", {})
                            mask_map[t_short] = t_path
                            builtins._COMFY_MASK_MAP = mask_map
                            kc.add_option(t_short)
                            kc.set_selected_option(t_short)
                            edit_mask_layer_combo.set_selected_option(f"Layer {l_num}")
                            _apply_corona_layer_row_to_mi(rd, save_asset=True)
                            return
                    _set_panel_status(f"[!] Select a Texture in Content Browser for Layer {l_num} Mask!", color=(1.0, 0.72, 0.3, 1.0))

                def _on_find_k():
                    sel_m = str(kc.get_selected_option() or "").strip()
                    if not sel_m or sel_m == "No Map":
                        _set_panel_status(f"[!] Layer {l_num} Mask is currently No Map!", color=(1.0, 0.72, 0.3, 1.0))
                        return
                    resolved_m = _resolve_mask_path(sel_m)
                    if resolved_m and unreal.EditorAssetLibrary.does_asset_exist(resolved_m):
                        unreal.EditorAssetLibrary.sync_browser_to_objects([resolved_m])
                        _set_panel_status(f"[Browse] Synced Content Browser to Layer {l_num} Mask '{sel_m}'.", color=(0.55, 0.88, 1.0, 1.0))

                return (
                    _on_mc_open, _on_kc_open, _on_mc_sel, _on_kc_sel,
                    _on_msb_chg, _on_msb_com, _on_ksb_chg, _on_ksb_com,
                    _on_mck_chg, _on_kck_chg, _on_ktrip_chg, _on_pick_m, _on_find_m, _on_pick_k, _on_find_k
                )

            (
                cb_m_open, cb_k_open, cb_m_sel, cb_k_sel,
                cb_msb_chg, cb_msb_com, cb_ksb_chg, cb_ksb_com,
                cb_mck, cb_kck, cb_ktrip, cb_pm, cb_fm, cb_pk, cb_fk
            ) = _make_layer_callbacks()

            for d_o in (
                row_d["mtl_combo"].on_opening, row_d["mtl_combo"].on_selection_changed,
                row_d["mask_combo"].on_opening, row_d["mask_combo"].on_selection_changed,
                row_d["mtl_amt"].on_value_changed, row_d["mtl_amt"].on_value_committed,
                row_d["mask_amt"].on_value_changed, row_d["mask_amt"].on_value_committed,
                row_d["mtl_check"].on_check_state_changed, row_d["mask_check"].on_check_state_changed,
                row_d["mask_trip_check"].on_check_state_changed,
                row_d["pick_mtl"].on_clicked, row_d["find_mtl"].on_clicked,
                row_d["pick_mask"].on_clicked, row_d["find_mask"].on_clicked,
            ):
                _clear_delegate_safe(d_o)

            row_d["mtl_combo"].on_opening.add_callable(cb_m_open)
            row_d["mtl_combo"].on_selection_changed.add_callable(cb_m_sel)
            row_d["mask_combo"].on_opening.add_callable(cb_k_open)
            row_d["mask_combo"].on_selection_changed.add_callable(cb_k_sel)
            row_d["mtl_amt"].on_value_changed.add_callable(cb_msb_chg)
            row_d["mtl_amt"].on_value_committed.add_callable(cb_msb_com)
            row_d["mask_amt"].on_value_changed.add_callable(cb_ksb_chg)
            row_d["mask_amt"].on_value_committed.add_callable(cb_ksb_com)
            row_d["mtl_check"].on_check_state_changed.add_callable(cb_mck)
            row_d["mask_check"].on_check_state_changed.add_callable(cb_kck)
            row_d["mask_trip_check"].on_check_state_changed.add_callable(cb_ktrip)
            row_d["pick_mtl"].on_clicked.add_callable(cb_pm)
            row_d["find_mtl"].on_clicked.add_callable(cb_fm)
            row_d["pick_mask"].on_clicked.add_callable(cb_pk)
            row_d["find_mask"].on_clicked.add_callable(cb_fk)

            builtins._COMFY_BTN_REFS.extend([
                (row_d["mtl_combo"], cb_m_open), (row_d["mtl_combo"], cb_m_sel),
                (row_d["mask_combo"], cb_k_open), (row_d["mask_combo"], cb_k_sel),
                (row_d["mtl_amt"], cb_msb_chg), (row_d["mtl_amt"], cb_msb_com),
                (row_d["mask_amt"], cb_ksb_chg), (row_d["mask_amt"], cb_ksb_com),
                (row_d["mtl_check"], cb_mck), (row_d["mask_check"], cb_kck),
                (row_d["mask_trip_check"], cb_ktrip),
                (row_d["pick_mtl"], cb_pm), (row_d["find_mtl"], cb_fm),
                (row_d["pick_mask"], cb_pk), (row_d["find_mask"], cb_fk),
            ])

        # Bind callbacks for Section 5 Seam Material row (Seam Mtl: [100.0] [ComboBox] [<-] [F] [x])
        def _on_seam_mc_open():
            _refresh_blend_combos()

        def _on_seam_mc_sel(sel_item, _stype):
            if not sel_item or getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            _apply_seam_material_to_mi(save_asset=True, auto_enable_seams=True)

        def _on_seam_amt_chg(_v: float):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            _apply_seam_material_to_mi(save_asset=False, auto_enable_seams=False)

        def _on_seam_amt_com(_v: float, _cm):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            _apply_seam_material_to_mi(save_asset=True, auto_enable_seams=False)

        def _on_seam_chk_chg(_is_checked: bool):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            _apply_seam_material_to_mi(save_asset=True, auto_enable_seams=bool(_is_checked))

        def _on_pick_seam_m():
            selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
            picked_sm = None
            for a in selected_assets:
                if isinstance(a, unreal.MaterialInstanceConstant):
                    picked_sm = a
                    break
            if not picked_sm:
                try:
                    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                    for act in (a_sub.get_selected_level_actors() if a_sub else []):
                        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
                            for s_i in range(comp.get_num_materials()):
                                m_i = comp.get_material(s_i)
                                if isinstance(m_i, unreal.MaterialInstanceConstant):
                                    picked_sm = m_i
                                    break
                            if picked_sm:
                                break
                        if picked_sm:
                            break
                except Exception:
                    pass
            if picked_sm:
                m_path = picked_sm.get_path_name().split(".")[0]
                m_short = m_path.split("/")[-1]
                mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
                mi_map[m_short] = m_path
                builtins._COMFY_MI_MAP = mi_map
                builtins._COMFY_SYNCING_UI = True
                try:
                    if seam_mtl_combo.find_option_index(m_short) < 0:
                        seam_mtl_combo.add_option(m_short)
                    seam_mtl_combo.set_selected_option(m_short)
                    seam_mtl_check.set_is_checked(True)
                finally:
                    builtins._COMFY_SYNCING_UI = False
                _apply_seam_material_to_mi(save_asset=True, auto_enable_seams=True)
                return
            _set_panel_status("[!] Select a Material Instance in Content Browser (or Actor in Viewport) for Seam Mtl!", color=(1.0, 0.72, 0.3, 1.0))

        def _on_find_seam_m():
            sel_sm = str(seam_mtl_combo.get_selected_option() or "").strip()
            if not sel_sm or sel_sm.startswith("None"):
                _set_panel_status("[!] Seam Mtl is currently None!", color=(1.0, 0.72, 0.3, 1.0))
                return
            resolved_sm = _resolve_mi_path(sel_sm)
            if resolved_sm and unreal.EditorAssetLibrary.does_asset_exist(resolved_sm):
                unreal.EditorAssetLibrary.sync_browser_to_objects([resolved_sm])
                _set_panel_status(f"[Browse] Synced Content Browser to Seam Mtl '{sel_sm}'.", color=(0.55, 0.88, 1.0, 1.0))

        for d_sm in (
            seam_mtl_combo.on_opening, seam_mtl_combo.on_selection_changed,
            seam_mtl_amt_sb.on_value_changed, seam_mtl_amt_sb.on_value_committed,
            seam_mtl_check.on_check_state_changed,
            pick_seam_btn.on_clicked, find_seam_btn.on_clicked,
        ):
            _clear_delegate_safe(d_sm)

        seam_mtl_combo.on_opening.add_callable(_on_seam_mc_open)
        seam_mtl_combo.on_selection_changed.add_callable(_on_seam_mc_sel)
        seam_mtl_amt_sb.on_value_changed.add_callable(_on_seam_amt_chg)
        seam_mtl_amt_sb.on_value_committed.add_callable(_on_seam_amt_com)
        seam_mtl_check.on_check_state_changed.add_callable(_on_seam_chk_chg)
        pick_seam_btn.on_clicked.add_callable(_on_pick_seam_m)
        find_seam_btn.on_clicked.add_callable(_on_find_seam_m)

        builtins._COMFY_BTN_REFS.extend([
            (seam_mtl_combo, _on_seam_mc_open), (seam_mtl_combo, _on_seam_mc_sel),
            (seam_mtl_amt_sb, _on_seam_amt_chg), (seam_mtl_amt_sb, _on_seam_amt_com),
            (seam_mtl_check, _on_seam_chk_chg),
            (pick_seam_btn, _on_pick_seam_m), (find_seam_btn, _on_find_seam_m),
        ])

        # Bind callbacks for Section 5 Tile Variation Material rows (Layer B Mtl, Layer C Mtl, Layer D Mtl)
        for tr_d in tile_layer_rows:
            def _make_tile_layer_callbacks(tr=tr_d):
                t_letter = tr["letter"]
                tc = tr["combo"]
                t_sb = tr["amt_sb"]
                t_ck = tr["check"]

                def _on_tc_open():
                    _refresh_blend_combos()

                def _on_tc_sel(sel_item, _stype):
                    if not sel_item or getattr(builtins, "_COMFY_SYNCING_UI", False):
                        return
                    _apply_tile_layer_material_to_mi(tr, save_asset=True, auto_enable_tiles=True)

                def _on_tsb_chg(_v: float):
                    if getattr(builtins, "_COMFY_SYNCING_UI", False):
                        return
                    _apply_tile_layer_material_to_mi(tr, save_asset=False, auto_enable_tiles=False)

                def _on_tsb_com(_v: float, _cm):
                    if getattr(builtins, "_COMFY_SYNCING_UI", False):
                        return
                    _apply_tile_layer_material_to_mi(tr, save_asset=True, auto_enable_tiles=False)

                def _on_tck_chg(_is_checked: bool):
                    if getattr(builtins, "_COMFY_SYNCING_UI", False):
                        return
                    _apply_tile_layer_material_to_mi(tr, save_asset=True, auto_enable_tiles=bool(_is_checked))

                def _on_pick_t():
                    selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
                    picked_tm = None
                    for a in selected_assets:
                        if isinstance(a, unreal.MaterialInstanceConstant):
                            picked_tm = a
                            break
                    if not picked_tm:
                        try:
                            a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                            for act in (a_sub.get_selected_level_actors() if a_sub else []):
                                for comp in act.get_components_by_class(unreal.StaticMeshComponent):
                                    for s_i in range(comp.get_num_materials()):
                                        m_i = comp.get_material(s_i)
                                        if isinstance(m_i, unreal.MaterialInstanceConstant):
                                            picked_tm = m_i
                                            break
                                    if picked_tm:
                                        break
                                if picked_tm:
                                    break
                        except Exception:
                            pass
                    if picked_tm:
                        m_path = picked_tm.get_path_name().split(".")[0]
                        m_short = m_path.split("/")[-1]
                        mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
                        mi_map[m_short] = m_path
                        builtins._COMFY_MI_MAP = mi_map
                        builtins._COMFY_SYNCING_UI = True
                        try:
                            if tc.find_option_index(m_short) < 0:
                                tc.add_option(m_short)
                            tc.set_selected_option(m_short)
                            t_ck.set_is_checked(True)
                        finally:
                            builtins._COMFY_SYNCING_UI = False
                        _apply_tile_layer_material_to_mi(tr, save_asset=True, auto_enable_tiles=True)
                        return
                    _set_panel_status(
                        f"[!] Select a Material Instance in Content Browser (or Actor in Viewport) for Layer {t_letter} Mtl!",
                        color=(1.0, 0.72, 0.3, 1.0),
                    )

                def _on_find_t():
                    sel_tm = str(tc.get_selected_option() or "").strip()
                    if not sel_tm or sel_tm.startswith("None"):
                        _set_panel_status(f"[!] Layer {t_letter} Mtl is currently None!", color=(1.0, 0.72, 0.3, 1.0))
                        return
                    resolved_tm = _resolve_mi_path(sel_tm)
                    if resolved_tm and unreal.EditorAssetLibrary.does_asset_exist(resolved_tm):
                        unreal.EditorAssetLibrary.sync_browser_to_objects([resolved_tm])
                        _set_panel_status(
                            f"[Browse] Synced Content Browser to Layer {t_letter} Mtl '{sel_tm}'.",
                            color=(0.55, 0.88, 1.0, 1.0),
                        )

                return _on_tc_open, _on_tc_sel, _on_tsb_chg, _on_tsb_com, _on_tck_chg, _on_pick_t, _on_find_t

            t_open, t_sel_cb, t_chg, t_com, t_chk_cb, t_pick_cb, t_find_cb = _make_tile_layer_callbacks()
            for d_tr in (
                tr_d["combo"].on_opening, tr_d["combo"].on_selection_changed,
                tr_d["amt_sb"].on_value_changed, tr_d["amt_sb"].on_value_committed,
                tr_d["check"].on_check_state_changed,
                tr_d["pick_btn"].on_clicked, tr_d["find_btn"].on_clicked,
            ):
                _clear_delegate_safe(d_tr)
            tr_d["combo"].on_opening.add_callable(t_open)
            tr_d["combo"].on_selection_changed.add_callable(t_sel_cb)
            tr_d["amt_sb"].on_value_changed.add_callable(t_chg)
            tr_d["amt_sb"].on_value_committed.add_callable(t_com)
            tr_d["check"].on_check_state_changed.add_callable(t_chk_cb)
            tr_d["pick_btn"].on_clicked.add_callable(t_pick_cb)
            tr_d["find_btn"].on_clicked.add_callable(t_find_cb)
            builtins._COMFY_BTN_REFS.extend([
                (tr_d["combo"], t_open), (tr_d["combo"], t_sel_cb),
                (tr_d["amt_sb"], t_chg), (tr_d["amt_sb"], t_com),
                (tr_d["check"], t_chk_cb),
                (tr_d["pick_btn"], t_pick_cb), (tr_d["find_btn"], t_find_cb),
            ])

        def _apply_mask_only_no_seams():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            mi = _get_selected_actor_active_mi() or _get_active_layer_a_mi(folder_now)
            if not mi:
                _set_panel_status("[!] Select or generate a Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
                return
            l_idx = _get_selected_mask_layer_idx()
            target_row = layer_ui_rows[l_idx - 1]
            mel = unreal.MaterialEditingLibrary
            mask_only_params = {
                "Seams_Enable": 0.0,
                "Seam_Mtl_Enable": 0.0,
                "Blend_In_Seams": 0.0,
                "Blend_Checkerboard_Tiles": 0.0,
                "Blend_Random_Tiles": 0.0,
                "Layer2_Random_Tiles": 0.0,
                "Layer3_Random_Tiles": 0.0,
                "Layer4_Random_Tiles": 0.0,
                "Blend_Height_Sharpness": 0.0,
            }
            for k, v in mask_only_params.items():
                mel.set_material_instance_scalar_parameter_value(
                    mi, k, float(v), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            _apply_corona_layer_row_to_mi(target_row, save_asset=True)
            _sync_spinboxes_from_mi(mi)
            _set_panel_status(
                f"[Layer {l_idx} Mask Only] Applied B&W Masks without Substance Seams to '{mi.get_name()}'!",
                color=(0.45, 0.92, 0.60, 1.0),
            )

        def _apply_seams_only_no_masks():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            mi = _get_selected_actor_active_mi() or _get_active_layer_a_mi(folder_now)
            if not mi:
                _set_panel_status("[!] Select or generate a Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
                return
            mel = unreal.MaterialEditingLibrary
            sel_sm = str(seam_mtl_combo.get_selected_option() or "").strip()
            has_seam_mtl = False
            if sel_sm and not sel_sm.startswith("None") and bool(seam_mtl_check.is_checked()):
                resolved_sm = _resolve_mi_path(sel_sm)
                sm_mi = unreal.EditorAssetLibrary.load_asset(resolved_sm) if resolved_sm else None
                if sm_mi and isinstance(sm_mi, unreal.MaterialInstanceConstant):
                    combine_material_into_layer_slot(mi, sm_mi, slot_idx=0, enable_seams=True, update_and_save=False)
                    has_seam_mtl = True
            seams_only_params = {
                "Seams_Enable": 1.0,
                "Seam_Mtl_Enable": 1.0 if has_seam_mtl else 0.0,
                "Blend_Mask_Strength": 0.0,
                "Layer2_Mask_Strength": 0.0,
                "Layer3_Mask_Strength": 0.0,
                "Layer4_Mask_Strength": 0.0,
                "Blend_Checkerboard_Tiles": 0.0,
                "Blend_Random_Tiles": 0.0,
                "Layer2_Random_Tiles": 0.0,
                "Layer3_Random_Tiles": 0.0,
                "Layer4_Random_Tiles": 0.0,
                "LayerB_Enable": 0.0,
                "Layer2_Enable": 0.0,
                "Layer3_Enable": 0.0,
                "Layer4_Enable": 0.0,
            }
            for k, v in seams_only_params.items():
                mel.set_material_instance_scalar_parameter_value(
                    mi, k, float(v), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                )
            mel.update_material_instance(mi)
            unreal.EditorAssetLibrary.save_loaded_asset(mi)
            _sync_spinboxes_from_mi(mi)
            _set_panel_status(
                f"[Seams Only] Enabled Substance Seams without Masks or Tile Blends on '{mi.get_name()}'!",
                color=(0.45, 0.96, 0.75, 1.0),
            )

        def _on_invert_mask_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            mi = _get_active_layer_a_mi(folder_now)
            if not mi:
                return
            l_idx = _get_selected_mask_layer_idx()
            mi_key = mi.get_path_name().split(".")[0]
            m_params = _get_layer_mask_params(mi_key, l_idx)
            cur_inv = float(m_params.get("Blend_Mask_Invert", 0.0))
            new_inv = 0.0 if cur_inv >= 0.5 else 1.0
            st_all = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
            st_all.setdefault(mi_key, {}).setdefault(l_idx, {})["Blend_Mask_Invert"] = new_inv
            _apply_corona_layer_row_to_mi(layer_ui_rows[l_idx - 1], save_asset=True)
            _set_panel_status(
                f"[Layer {l_idx} Mask Invert] '{mi.get_name()}' Invert = {new_inv:.1f}",
                color=(0.55, 0.88, 1.0, 1.0),
            )

        def _on_reset_all_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            actor_mi = _get_selected_actor_active_mi()
            combo_mi = _get_active_layer_a_mi(folder_now)
            mi = actor_mi or combo_mi
            if not mi:
                _set_panel_status("[!] Select a Base mtl or Viewport Actor first!", color=(1.0, 0.72, 0.3, 1.0))
                return
            reset_substance_and_blend_parameters(mi)
            if combo_mi and combo_mi.get_path_name() != mi.get_path_name():
                reset_substance_and_blend_parameters(combo_mi)
            mi_key = mi.get_path_name().split(".")[0]
            mi_short = mi_key.split("/")[-1]
            st_all = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
            st_all[mi_key] = {}
            if combo_mi:
                st_all[combo_mi.get_path_name().split(".")[0]] = {}
            builtins._COMFY_LAST_MATERIAL = mi
            builtins._COMFY_SYNCING_UI = True
            try:
                if la_combo.find_option_index(mi_short) < 0:
                    la_combo.add_option(mi_short)
                la_combo.set_selected_option(mi_short)
                if mm_combo.find_option_index(mi_short) < 0:
                    mm_combo.add_option(mi_short)
                mm_combo.set_selected_option(mi_short)
                seam_mtl_amt_sb.set_value(100.0)
                seam_mtl_check.set_is_checked(True)
                seam_mtl_combo.set_selected_option("None")
                for tr in tile_layer_rows:
                    tr["amt_sb"].set_value(100.0)
                    tr["check"].set_is_checked(True)
                    tr["combo"].set_selected_option("None")
                for rd in layer_ui_rows:
                    rd["mtl_amt"].set_value(100.0)
                    rd["mask_amt"].set_value(100.0)
                    rd["mtl_check"].set_is_checked(True)
                    rd["mask_check"].set_is_checked(True)
                    if rd.get("mask_trip_check"):
                        rd["mask_trip_check"].set_is_checked(False)
                    rd["mtl_combo"].set_selected_option("None")
                    rd["mask_combo"].set_selected_option("No Map")
            finally:
                builtins._COMFY_SYNCING_UI = False
            _sync_spinboxes_from_mi(mi)
            _sync_mask_spinboxes_for_selected_layer(mi)
            _set_panel_status(
                f"[Reset] Restored default Corona Layered & Substance parameters on '{mi.get_name()}'.",
                color=(0.45, 0.92, 0.60, 1.0),
            )

        def _on_bake_mixed_mtl_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            baked_mi = bake_layered_material_to_new_mi(folder_now, assign_to_actor=True)
            if not baked_mi:
                return
            b_short = baked_mi.get_name()
            _refresh_blend_combos()
            _refresh_master_combo(mm_combo, folder_now, select_path=baked_mi.get_path_name().split(".")[0])
            builtins._COMFY_SYNCING_UI = True
            try:
                if la_combo.find_option_index(b_short) < 0:
                    la_combo.add_option(b_short)
                la_combo.set_selected_option(b_short)
                seam_mtl_amt_sb.set_value(100.0)
                seam_mtl_check.set_is_checked(True)
                seam_mtl_combo.set_selected_option("None")
                for tr in tile_layer_rows:
                    tr["amt_sb"].set_value(100.0)
                    tr["check"].set_is_checked(True)
                    tr["combo"].set_selected_option("None")
                for rd in layer_ui_rows:
                    rd["mtl_amt"].set_value(100.0)
                    rd["mask_amt"].set_value(100.0)
                    rd["mtl_check"].set_is_checked(True)
                    rd["mask_check"].set_is_checked(True)
                    if rd.get("mask_trip_check"):
                        rd["mask_trip_check"].set_is_checked(False)
                    rd["mtl_combo"].set_selected_option("None")
                    rd["mask_combo"].set_selected_option("No Map")
            finally:
                builtins._COMFY_SYNCING_UI = False
            _sync_spinboxes_from_mi(baked_mi)

        for d_obj in (
            la_search.on_text_changed, mask_search.on_text_changed,
            la_combo.on_opening, la_combo.on_selection_changed,
            disp_combo.on_selection_changed,
            edit_mask_layer_combo.on_selection_changed,
            pick_la_btn.on_clicked, find_la_btn.on_clicked,
            bake_mixed_btn.on_clicked,
            mask_only_btn.on_clicked, seams_only_btn.on_clicked, inv_mask_btn.on_clicked, reset_all_btn.on_clicked,
        ):
            _clear_delegate_safe(d_obj)

        la_search.on_text_changed.add_callable(_on_la_search_changed)
        mask_search.on_text_changed.add_callable(_on_mask_search_changed)
        la_combo.on_opening.add_callable(_on_la_opening)
        la_combo.on_selection_changed.add_callable(_on_la_changed)
        disp_combo.on_selection_changed.add_callable(_on_disp_mode_changed)
        edit_mask_layer_combo.on_selection_changed.add_callable(_on_edit_mask_layer_changed)
        pick_la_btn.on_clicked.add_callable(_on_pick_la_cb_clicked)
        find_la_btn.on_clicked.add_callable(_on_find_la_cb_clicked)
        bake_mixed_btn.on_clicked.add_callable(_on_bake_mixed_mtl_clicked)
        mask_only_btn.on_clicked.add_callable(_apply_mask_only_no_seams)
        seams_only_btn.on_clicked.add_callable(_apply_seams_only_no_masks)
        inv_mask_btn.on_clicked.add_callable(_on_invert_mask_clicked)
        reset_all_btn.on_clicked.add_callable(_on_reset_all_clicked)

        builtins._COMFY_BTN_REFS.extend(
            [
                (la_search, _on_la_search_changed),
                (mask_search, _on_mask_search_changed),
                (la_combo, _on_la_opening),
                (la_combo, _on_la_changed),
                (disp_combo, _on_disp_mode_changed),
                (edit_mask_layer_combo, _on_edit_mask_layer_changed),
                (pick_la_btn, _on_pick_la_cb_clicked),
                (find_la_btn, _on_find_la_cb_clicked),
                (bake_mixed_btn, _on_bake_mixed_mtl_clicked),
                (mask_only_btn, _apply_mask_only_no_seams),
                (seams_only_btn, _apply_seams_only_no_masks),
                (inv_mask_btn, _on_invert_mask_clicked),
                (reset_all_btn, _on_reset_all_clicked),
            ]
        )

    # Row 4A-Mask-1: Split Mask Tiling X & Mask Tiling Y (2 wide SpinBoxes)
    # Row 4A-Mask-2: Mask Brightness, Mask Contrast, Mask Invert (3 SpinBoxes)
    mask_spin_rows = [
        (
            1536.0,
            190.5,
            9.0,
            [
                ("Mask Tiling X", "Blend_Mask_Tiling_X", 1.0, 0.01, 32.0, 0.05, 2),
                ("Mask Tiling Y", "Blend_Mask_Tiling_Y", 1.0, 0.01, 32.0, 0.05, 2),
            ],
        ),
        (
            1584.0,
            124.0,
            9.0,
            [
                ("Mask Brightness", "Blend_Mask_Brightness", 0.0, -1.0, 1.0, 0.05, 2),
                ("Mask Contrast", "Blend_Mask_Contrast", 1.0, 0.1, 8.0, 0.1, 2),
                ("Mask Invert", "Blend_Mask_Invert", 0.0, 0.0, 1.0, 1.0, 1),
            ],
        ),
    ]
    for m_row_y, ms_w, ms_gap, m_items in mask_spin_rows:
        ms_x = 14.0
        for label_txt, param_name, def_val, min_v, max_v, step_v, digits_v in m_items:
            sb = _create_styled_spinbox(
                w, canvas, label_txt, ms_x, m_row_y, ms_w, def_val, min_v, max_v, step_v, digits_v,
                param_name=param_name, is_wt=is_wt, apply_layout=apply_layout,
            )
            if not is_wt:
                builtins._COMFY_SPINBOX_MAP[param_name] = (sb, def_val)

                def _make_mask_sb_callbacks(p_name=param_name, l_txt=label_txt):
                    def _on_val_changed(new_val: float):
                        if getattr(builtins, "_COMFY_SYNCING_UI", False):
                            return
                        folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                        mi = _get_active_layer_a_mi(folder_now)
                        if not mi:
                            return
                        l_idx = _get_selected_mask_layer_idx()
                        mi_key = mi.get_path_name().split(".")[0]
                        st_all = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
                        st_all.setdefault(mi_key, {}).setdefault(l_idx, {})[p_name] = float(new_val)
                        mel = unreal.MaterialEditingLibrary
                        # Determine which hardware slot (1..4) this layer maps to, or default to slot 1
                        active_indices = []
                        for r_chk in layer_ui_rows:
                            r_m = str(r_chk["mtl_combo"].get_selected_option() or "None").strip()
                            if r_m and not r_m.startswith("None") and bool(r_chk["mtl_check"].is_checked()) and float(r_chk["mtl_amt"].get_value()) > 0.0:
                                active_indices.append(r_chk["idx"])
                        avail_slots = (1, 2, 3, 4)
                        target_slot = 1
                        if l_idx in active_indices:
                            pos_i = active_indices.index(l_idx)
                            if pos_i < len(avail_slots):
                                target_slot = avail_slots[pos_i]
                        if target_slot == 1:
                            mel.set_material_instance_scalar_parameter_value(
                                mi, p_name, float(new_val), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            )
                        else:
                            slot_param_map = {
                                "Blend_Mask_Tiling_X": f"Layer{target_slot}_Mask_Tiling_X",
                                "Blend_Mask_Tiling_Y": f"Layer{target_slot}_Mask_Tiling_Y",
                                "Blend_Mask_Brightness": f"Layer{target_slot}_Mask_Brightness",
                                "Blend_Mask_Contrast": f"Layer{target_slot}_Mask_Contrast",
                                "Blend_Mask_Invert": f"Layer{target_slot}_Mask_Invert",
                            }
                            dst_mp = slot_param_map.get(p_name)
                            if dst_mp:
                                mel.set_material_instance_scalar_parameter_value(
                                    mi, dst_mp, float(new_val), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                                )
                        mel.update_material_instance(mi)

                    def _on_val_committed(new_val: float, _commit_method):
                        if getattr(builtins, "_COMFY_SYNCING_UI", False):
                            return
                        _on_val_changed(new_val)
                        folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                        mi = _get_active_layer_a_mi(folder_now)
                        if not mi:
                            return
                        l_idx = _get_selected_mask_layer_idx()
                        unreal.EditorAssetLibrary.save_loaded_asset(mi)
                        _set_panel_status(
                            f"[Layer {l_idx} Mask] '{mi.get_name()}' {l_txt} ({p_name}) = {float(new_val):.3f}",
                            color=(0.55, 0.88, 1.0, 1.0),
                        )

                    return _on_val_changed, _on_val_committed

                cb_chg, cb_com = _make_mask_sb_callbacks()
                _clear_delegate_safe(sb.on_value_changed)
                _clear_delegate_safe(sb.on_value_committed)
                sb.on_value_changed.add_callable(cb_chg)
                sb.on_value_committed.add_callable(cb_com)
                builtins._COMFY_BTN_REFS.append((sb, cb_chg))
                builtins._COMFY_BTN_REFS.append((sb, cb_com))
            ms_x += ms_w + ms_gap

    # Section 5 Header: Substance Seams & Tile Generator + Triplanar Seams Checkbox
    _setup_named_label(
        w, is_wt, canvas, "SubstanceSeamsSectionLabel",
        "5. Substance Seams & Tile Generator:",
        14.0, 1652.0, 266.0, 15.0,
        size=8, bold=True, color=(0.55, 0.88, 1.0, 1.0),
        apply_layout=True,
    )
    _setup_named_label(
        w, is_wt, canvas, "SeamsTriplanarLabel",
        "Triplanar (3P):",
        290.0, 1653.0, 88.0, 14.0,
        size=8, bold=True, color=(0.55, 0.94, 1.0, 1.0),
        apply_layout=True,
    )
    seams_trip_check = _create_inline_checkbox(
        "SeamsTriplanarCheck",
        381.0, 1649.0, 22.0, False,
        tooltip="Triplanar (World-Aligned Coordinates) for Substance Seams & Tile Grid — Checked: World Coordinates, Unchecked: Mesh UV Unwrap",
    )
    if not is_wt:
        builtins._COMFY_SEAMS_TRIP_CHECK = seams_trip_check

        def _on_seams_trip_changed(is_checked: bool):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            mi = _get_active_layer_a_mi(folder_now)
            if not mi:
                _set_panel_status("[!] Select or generate a Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
                return
            mel = unreal.MaterialEditingLibrary
            mel.set_material_instance_scalar_parameter_value(
                mi, "Seams_Triplanar", 1.0 if is_checked else 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            mel.update_material_instance(mi)
            unreal.EditorAssetLibrary.save_loaded_asset(mi)
            mode_lbl = "Triplanar (World Coordinates)" if is_checked else "UV Unwrap (TexCoord[0])"
            _set_panel_status(
                f"[Substance Seams Projection] '{mi.get_name()}' Seams_Triplanar -> {mode_lbl}",
                color=(0.45, 0.96, 0.78, 1.0) if is_checked else (0.65, 0.88, 1.0, 1.0),
            )

        _clear_delegate_safe(seams_trip_check.on_check_state_changed)
        seams_trip_check.on_check_state_changed.add_callable(_on_seams_trip_changed)
        builtins._COMFY_BTN_REFS.append((seams_trip_check, _on_seams_trip_changed))

    # Row 5A..5G: 21 Interactive Substance SpinBoxes in 7 rows of 3 (below Seam / Layer B / C / D rows at Y=1674..1752)
    spin_rows = [
        (
            1784.0,
            [
                ("Seams Enable", "Seams_Enable", 0.0, 0.0, 1.0, 0.05, 2),
                ("Tiles Count X", "Tiles_Count_X", 4.0, 1.0, 32.0, 1.0, 1),
                ("Tiles Count Y", "Tiles_Count_Y", 4.0, 1.0, 32.0, 1.0, 1),
            ],
        ),
        (
            1832.0,
            [
                ("Seam Width H", "Seam_Width", 0.04, 0.0, 0.35, 0.005, 3),
                ("Seam Width V", "Seam_Width_V", 0.04, 0.0, 0.35, 0.005, 3),
                ("Seam 3D Depth", "Seam_Depth", 1.0, 0.0, 3.0, 0.05, 2),
            ],
        ),
        (
            1880.0,
            [
                ("Seam Line Waviness", "Seam_Line_Waviness", 0.0, 0.0, 1.0, 0.05, 2),
                ("Seam Edge Irregular", "Seam_Edge_Irregularity", 0.0, 0.0, 1.0, 0.05, 2),
                ("Seam Noise Scale", "Seam_Noise_Scale", 1.0, 0.1, 8.0, 0.1, 2),
            ],
        ),
        (
            1928.0,
            [
                ("Row Shift Order", "Row_Shift_Order", 0.5, 0.0, 1.0, 0.05, 2),
                ("Blend In Seams", "Blend_In_Seams", 1.0, 0.0, 1.0, 0.05, 2),
                ("Checkerboard A/B", "Blend_Checkerboard_Tiles", 0.0, 0.0, 1.0, 0.05, 2),
            ],
        ),
        (
            1976.0,
            [
                ("Layer B Enable", "LayerB_Enable", 0.0, 0.0, 1.0, 0.05, 2),
                ("Layer C Enable", "Layer2_Enable", 0.0, 0.0, 1.0, 0.05, 2),
                ("Layer D Enable", "Layer3_Enable", 0.0, 0.0, 1.0, 0.05, 2),
            ],
        ),
        (
            2024.0,
            [
                ("Random Tiles B", "Blend_Random_Tiles", 0.0, 0.0, 1.0, 0.05, 2),
                ("Random Tiles C", "Layer2_Random_Tiles", 0.0, 0.0, 1.0, 0.05, 2),
                ("Random Tiles D", "Layer3_Random_Tiles", 0.0, 0.0, 1.0, 0.05, 2),
            ],
        ),
        (
            2072.0,
            [
                ("Tile UV Random", "Tile_Random_UV_Offset", 1.0, 0.0, 1.0, 0.05, 2),
                ("Tile Flip/Rot", "Tile_Random_Flip_Rotate", 0.5, 0.0, 1.0, 0.05, 2),
                ("Mask Strength", "Blend_Mask_Strength", 0.0, 0.0, 1.0, 0.05, 2),
            ],
        ),
    ]

    sb_w = 124.0
    sb_gap = 9.0
    for row_y, items in spin_rows:
        sx = 14.0
        for label_txt, param_name, def_val, min_v, max_v, step_v, digits_v in items:
            sb = _create_styled_spinbox(
                w, canvas, label_txt, sx, row_y, sb_w, def_val, min_v, max_v, step_v, digits_v,
                param_name=param_name, is_wt=is_wt, apply_layout=apply_layout,
            )
            if not is_wt:
                builtins._COMFY_SPINBOX_MAP[param_name] = (sb, def_val)

                def _make_sb_callbacks(p_name=param_name, l_txt=label_txt):
                    def _auto_enable_deps(mi_obj, val_f: float):
                        mel = unreal.MaterialEditingLibrary
                        spin_map = getattr(builtins, "_COMFY_SPINBOX_MAP", {})
                        need_seams = p_name in (
                            "Blend_Random_Tiles",
                            "Layer2_Random_Tiles",
                            "Layer3_Random_Tiles",
                            "Blend_Checkerboard_Tiles",
                            "Blend_In_Seams",
                            "Seam_Width",
                            "Seam_Width_V",
                            "Seam_Depth",
                            "Seam_Line_Waviness",
                            "Seam_Edge_Irregularity",
                            "Row_Shift_Order",
                            "Tiles_Count_X",
                            "Tiles_Count_Y",
                            "Tile_Random_UV_Offset",
                            "Tile_Random_Flip_Rotate",
                        ) and val_f > 0.001
                        need_layer_b = p_name in (
                            "Blend_Random_Tiles",
                            "Blend_Checkerboard_Tiles",
                            "Blend_Mask_Strength",
                        ) and val_f > 0.001
                        need_layer_c = (p_name == "Layer2_Random_Tiles" and val_f > 0.001)
                        need_layer_d = (p_name == "Layer3_Random_Tiles" and val_f > 0.001)
                        if need_seams:
                            cur_s = float(mel.get_material_instance_scalar_parameter_value(
                                mi_obj, "Seams_Enable", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            ))
                            if cur_s <= 0.001:
                                mel.set_material_instance_scalar_parameter_value(
                                    mi_obj, "Seams_Enable", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                                )
                                if "Seams_Enable" in spin_map:
                                    builtins._COMFY_SYNCING_UI = True
                                    try:
                                        spin_map["Seams_Enable"][0].set_value(1.0)
                                    finally:
                                        builtins._COMFY_SYNCING_UI = False
                        if need_layer_b:
                            cur_lb = float(mel.get_material_instance_scalar_parameter_value(
                                mi_obj, "LayerB_Enable", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            ))
                            if cur_lb <= 0.001:
                                mel.set_material_instance_scalar_parameter_value(
                                    mi_obj, "LayerB_Enable", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                                )
                                if "LayerB_Enable" in spin_map:
                                    builtins._COMFY_SYNCING_UI = True
                                    try:
                                        spin_map["LayerB_Enable"][0].set_value(1.0)
                                    finally:
                                        builtins._COMFY_SYNCING_UI = False
                            if p_name == "Blend_Mask_Strength":
                                mel.set_material_instance_scalar_parameter_value(
                                    mi_obj, "LayerB_Use_Mask", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                                )
                        if need_layer_c:
                            cur_lc = float(mel.get_material_instance_scalar_parameter_value(
                                mi_obj, "Layer2_Enable", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            ))
                            if cur_lc <= 0.001:
                                mel.set_material_instance_scalar_parameter_value(
                                    mi_obj, "Layer2_Enable", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                                )
                                if "Layer2_Enable" in spin_map:
                                    builtins._COMFY_SYNCING_UI = True
                                    try:
                                        spin_map["Layer2_Enable"][0].set_value(1.0)
                                    finally:
                                        builtins._COMFY_SYNCING_UI = False
                        if need_layer_d:
                            cur_ld = float(mel.get_material_instance_scalar_parameter_value(
                                mi_obj, "Layer3_Enable", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            ))
                            if cur_ld <= 0.001:
                                mel.set_material_instance_scalar_parameter_value(
                                    mi_obj, "Layer3_Enable", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                                )
                                if "Layer3_Enable" in spin_map:
                                    builtins._COMFY_SYNCING_UI = True
                                    try:
                                        spin_map["Layer3_Enable"][0].set_value(1.0)
                                    finally:
                                        builtins._COMFY_SYNCING_UI = False

                    def _on_val_changed(new_val: float):
                        if getattr(builtins, "_COMFY_SYNCING_UI", False):
                            return
                        folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                        mi = _get_active_layer_a_mi(folder_now)
                        if not mi:
                            return
                        mel = unreal.MaterialEditingLibrary
                        mel.set_material_instance_scalar_parameter_value(
                            mi, p_name, float(new_val), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                        _auto_enable_deps(mi, float(new_val))
                        mel.update_material_instance(mi)

                    def _on_val_committed(new_val: float, _commit_method):
                        if getattr(builtins, "_COMFY_SYNCING_UI", False):
                            return
                        folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                        mi = _get_active_layer_a_mi(folder_now)
                        if not mi:
                            return
                        mel = unreal.MaterialEditingLibrary
                        mel.set_material_instance_scalar_parameter_value(
                            mi, p_name, float(new_val), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                        _auto_enable_deps(mi, float(new_val))
                        mel.update_material_instance(mi)
                        unreal.EditorAssetLibrary.save_loaded_asset(mi)
                        _set_panel_status(
                            f"[{mi.get_name()}] {l_txt} ({p_name}) = {float(new_val):.3f}",
                            color=(0.55, 0.88, 1.0, 1.0),
                        )

                    return _on_val_changed, _on_val_committed

                cb_chg, cb_com = _make_sb_callbacks()
                _clear_delegate_safe(sb.on_value_changed)
                _clear_delegate_safe(sb.on_value_committed)
                sb.on_value_changed.add_callable(cb_chg)
                sb.on_value_committed.add_callable(cb_com)
                builtins._COMFY_BTN_REFS.append((sb, cb_chg))
                builtins._COMFY_BTN_REFS.append((sb, cb_com))
            sx += sb_w + sb_gap

    # 6 Quick Substance & Blend Mode Presets in 2 rows of 3 (Y = 1898 and Y = 1927)
    blend_presets = [
        (
            "1. In Seams",
            {
                "Seams_Enable": 1.0,
                "LayerB_Enable": 1.0,
                "Blend_In_Seams": 1.0,
                "Blend_Checkerboard_Tiles": 0.0,
                "Blend_Random_Tiles": 0.0,
                "Blend_Mask_Strength": 0.0,
            },
        ),
        (
            "2. Checker A/B",
            {
                "Seams_Enable": 1.0,
                "LayerB_Enable": 1.0,
                "Blend_In_Seams": 0.0,
                "Blend_Checkerboard_Tiles": 1.0,
                "Blend_Random_Tiles": 0.0,
                "Row_Shift_Order": 0.0,
            },
        ),
        (
            "3. Random 35%",
            {
                "Seams_Enable": 1.0,
                "LayerB_Enable": 1.0,
                "Blend_In_Seams": 0.4,
                "Blend_Checkerboard_Tiles": 0.0,
                "Blend_Random_Tiles": 0.35,
            },
        ),
        (
            "4. Mask Only",
            "__MASK_ONLY__",
        ),
        (
            "5. Seams Only",
            "__SEAMS_ONLY__",
        ),
        (
            "6. Parquet 2x10",
            {
                "Seams_Enable": 1.0,
                "Tiles_Count_X": 2.0,
                "Tiles_Count_Y": 10.0,
                "Row_Shift_Order": 0.33,
                "Row_Shift_Random": 0.25,
                "Seam_Width": 0.025,
                "Seam_Width_V": 0.025,
                "Tile_Random_UV_Offset": 1.0,
            },
        ),
        (
            "7. Reset Changes",
            "__RESET_ALL__",
        ),
    ]

    for b_idx, (b_title, param_dict) in enumerate(blend_presets):
        btn_col = (1.0, 0.78, 0.55, 1.0) if param_dict == "__RESET_ALL__" else (
            (0.65, 0.96, 1.0, 1.0) if param_dict == "__MASK_ONLY__" else (
                (0.58, 0.98, 0.82, 1.0) if param_dict == "__SEAMS_ONLY__" else (0.88, 0.95, 1.0, 1.0)
            )
        )
        if b_idx < 3:
            b_x = 14.0 + b_idx * (124.0 + 9.0)
            b_y = 2122.0
            b_w = 124.0
        else:
            b_x = 14.0 + (b_idx - 3) * (93.0 + 6.0)
            b_y = 2151.0
            b_w = 93.0
        b_btn = _setup_named_button(
            w, is_wt, canvas,
            f"BlendPresetBtn_{b_idx + 1}", f"BlendPresetBtnLbl_{b_idx + 1}",
            b_title,
            b_x, b_y, b_w, 25.0,
            color=btn_col,
            apply_layout=apply_layout,
        )

        if not is_wt:
            def _make_blend_preset_cb(p_dict=param_dict, title_str=b_title):
                def _on_b_click():
                    if p_dict == "__MASK_ONLY__":
                        _apply_mask_only_no_seams()
                        return
                    if p_dict == "__SEAMS_ONLY__":
                        _apply_seams_only_no_masks()
                        return
                    if p_dict == "__RESET_ALL__":
                        _on_reset_all_clicked()
                        return
                    folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                    mi = _get_active_layer_a_mi(folder_now)
                    if not mi:
                        _set_panel_status("[!] Select or generate a Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
                        return
                    sel_sm = str(seam_mtl_combo.get_selected_option() or "").strip()
                    if sel_sm and not sel_sm.startswith("None") and bool(seam_mtl_check.is_checked()):
                        resolved_sm = _resolve_mi_path(sel_sm)
                        sm_mi = unreal.EditorAssetLibrary.load_asset(resolved_sm) if resolved_sm else None
                        if sm_mi and isinstance(sm_mi, unreal.MaterialInstanceConstant):
                            combine_material_into_layer_slot(mi, sm_mi, slot_idx=0, enable_seams=True, update_and_save=False)
                    for tr in tile_layer_rows:
                        sel_t = str(tr["combo"].get_selected_option() or "").strip()
                        if sel_t and not sel_t.startswith("None") and bool(tr["check"].is_checked()):
                            resolved_t = _resolve_mi_path(sel_t)
                            t_mi = unreal.EditorAssetLibrary.load_asset(resolved_t) if resolved_t else None
                            if t_mi and isinstance(t_mi, unreal.MaterialInstanceConstant):
                                combine_material_into_layer_slot(mi, t_mi, slot_idx=tr["slot_k"], enable_seams=True, update_and_save=False)
                    mel = unreal.MaterialEditingLibrary
                    for k, v in p_dict.items():
                        mel.set_material_instance_scalar_parameter_value(
                            mi, k, float(v), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                    mel.update_material_instance(mi)
                    unreal.EditorAssetLibrary.save_loaded_asset(mi)
                    _sync_spinboxes_from_mi(mi)
                    apply_material_to_selected_actors(mi)
                    _set_panel_status(
                        f"[Blend Mode] Applied '{title_str}' to '{mi.get_name()}'!",
                        color=(0.45, 0.92, 0.60, 1.0),
                    )

                return _on_b_click

            b_cb = _make_blend_preset_cb()
            _clear_delegate_safe(b_btn.on_clicked)
            b_btn.on_clicked.add_callable(b_cb)
            builtins._COMFY_BTN_REFS.append((b_btn, b_cb))

    # =========================================================================
    # === Section 5A: ANTI-TILING STUDIO (Dual-Scale Blend, Macro Noise & Vertex Paint) ===
    # =========================================================================
    _setup_named_label(
        w, is_wt, canvas, "AntiTileSectionHeaderLabel",
        "5A. Anti-Tiling & Macro Variation:",
        14.0, 2188.0, 266.0, 15.0,
        size=8, bold=True, color=(0.55, 0.94, 1.0, 1.0),
        apply_layout=True,
    )
    _setup_named_label(
        w, is_wt, canvas, "AntiTileTriplanarLabel",
        "Triplanar (3P):",
        290.0, 2189.0, 88.0, 14.0,
        size=8, bold=True, color=(0.55, 0.94, 1.0, 1.0),
        apply_layout=True,
    )
    at_trip_check = _create_inline_checkbox(
        "AntiTileTriplanarCheck",
        381.0, 2185.0, 22.0, False,
        tooltip="Triplanar (World-Aligned) Macro Noise for Anti-Tiling — Checked: World Space, Unchecked: Mesh UV",
    )
    if not is_wt:
        builtins._COMFY_ANTITILE_TRIP_CHECK = at_trip_check

        def _on_at_trip_changed(is_checked: bool):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            mi = _get_active_layer_a_mi(folder_now)
            if not mi:
                return
            mel = unreal.MaterialEditingLibrary
            mel.set_material_instance_scalar_parameter_value(
                mi, "AntiTile_Triplanar", 1.0 if is_checked else 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            mel.update_material_instance(mi)
            unreal.EditorAssetLibrary.save_loaded_asset(mi)
            _set_panel_status(
                f"[Anti-Tiling 3P] '{mi.get_name()}' Macro Noise -> {'World Space (3P)' if is_checked else 'Mesh UV'}",
                color=(0.45, 0.96, 0.78, 1.0),
            )

        _clear_delegate_safe(at_trip_check.on_check_state_changed)
        at_trip_check.on_check_state_changed.add_callable(_on_at_trip_changed)
        builtins._COMFY_BTN_REFS.append((at_trip_check, _on_at_trip_changed))

    at_spin_rows = [
        (
            2208.0,
            [
                ("Anti-Tile Blend", "AntiTile_Enable", 0.0, 0.0, 1.0, 0.05, 2),
                ("Second Scale", "AntiTile_Scale", 0.85, 0.05, 4.0, 0.02, 2),
                ("Rotation Angle", "AntiTile_Rotation", 0.38, 0.0, 1.0, 0.02, 2),
            ],
        ),
        (
            2256.0,
            [
                ("Macro Variation", "AntiTile_Macro_Var", 0.0, 0.0, 1.0, 0.05, 2),
                ("Macro Noise Scale", "AntiTile_Noise_Scale", 1.0, 0.05, 10.0, 0.05, 2),
                ("Blend Contrast", "AntiTile_Contrast", 1.5, 0.1, 4.0, 0.1, 2),
            ],
        ),
    ]
    for at_row_y, at_items in at_spin_rows:
        at_x = 14.0
        for label_txt, param_name, def_val, min_v, max_v, step_v, digits_v in at_items:
            sb = _create_styled_spinbox(
                w, canvas, label_txt, at_x, at_row_y, sb_w, def_val, min_v, max_v, step_v, digits_v,
                param_name=param_name, is_wt=is_wt, apply_layout=apply_layout,
            )
            if not is_wt:
                builtins._COMFY_SPINBOX_MAP[param_name] = (sb, def_val)

                def _make_at_sb_callbacks(p_name=param_name, l_txt=label_txt):
                    def _auto_enable_at(mi_obj, val_f: float):
                        if p_name in ("AntiTile_Scale", "AntiTile_Rotation", "AntiTile_Contrast") and val_f > 0.001:
                            mel = unreal.MaterialEditingLibrary
                            cur_en = float(mel.get_material_instance_scalar_parameter_value(
                                mi_obj, "AntiTile_Enable", unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            ))
                            if cur_en <= 0.001:
                                mel.set_material_instance_scalar_parameter_value(
                                    mi_obj, "AntiTile_Enable", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                                )
                                spin_map = getattr(builtins, "_COMFY_SPINBOX_MAP", {})
                                if "AntiTile_Enable" in spin_map:
                                    builtins._COMFY_SYNCING_UI = True
                                    try:
                                        spin_map["AntiTile_Enable"][0].set_value(1.0)
                                    finally:
                                        builtins._COMFY_SYNCING_UI = False

                    def _on_at_chg(new_val: float):
                        if getattr(builtins, "_COMFY_SYNCING_UI", False):
                            return
                        folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                        mi = _get_active_layer_a_mi(folder_now)
                        if not mi:
                            return
                        mel = unreal.MaterialEditingLibrary
                        mel.set_material_instance_scalar_parameter_value(
                            mi, p_name, float(new_val), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                        _auto_enable_at(mi, float(new_val))
                        mel.update_material_instance(mi)

                    def _on_at_com(new_val: float, _commit_method):
                        if getattr(builtins, "_COMFY_SYNCING_UI", False):
                            return
                        folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                        mi = _get_active_layer_a_mi(folder_now)
                        if not mi:
                            return
                        mel = unreal.MaterialEditingLibrary
                        mel.set_material_instance_scalar_parameter_value(
                            mi, p_name, float(new_val), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                        _auto_enable_at(mi, float(new_val))
                        mel.update_material_instance(mi)
                        unreal.EditorAssetLibrary.save_loaded_asset(mi)
                        _set_panel_status(
                            f"[Anti-Tiling] '{mi.get_name()}' {l_txt} ({p_name}) = {float(new_val):.3f}",
                            color=(0.55, 0.94, 1.0, 1.0),
                        )

                    return _on_at_chg, _on_at_com

                at_chg, at_com = _make_at_sb_callbacks()
                _clear_delegate_safe(sb.on_value_changed)
                _clear_delegate_safe(sb.on_value_committed)
                sb.on_value_changed.add_callable(at_chg)
                sb.on_value_committed.add_callable(at_com)
                builtins._COMFY_BTN_REFS.append((sb, at_chg))
                builtins._COMFY_BTN_REFS.append((sb, at_com))
            at_x += sb_w + sb_gap

    at_presets = [
        (
            "1. All 3 Methods",
            {
                "AntiTile_Enable": 1.0,
                "AntiTile_Scale": 0.85,
                "AntiTile_Rotation": 0.38,
                "AntiTile_Macro_Var": 0.35,
                "AntiTile_Noise_Scale": 1.0,
                "AntiTile_Contrast": 1.5,
                "Vertex_Paint_Strength": 0.5,
            },
        ),
        (
            "2. Dual-Scale + Macro",
            {
                "AntiTile_Enable": 1.0,
                "AntiTile_Scale": 0.85,
                "AntiTile_Rotation": 0.38,
                "AntiTile_Macro_Var": 0.35,
                "AntiTile_Noise_Scale": 1.0,
                "AntiTile_Contrast": 1.5,
            },
        ),
        (
            "3. Macro Noise Only",
            {
                "AntiTile_Enable": 0.0,
                "AntiTile_Macro_Var": 0.45,
                "AntiTile_Noise_Scale": 1.0,
            },
        ),
        (
            "4. Fix Tile Borders",
            "__FIX_SEAMLESS_BORDERS__",
        ),
        (
            "5. Vertex Paint Blend",
            "__VERTEX_PAINT_ANTITILE__",
        ),
        (
            "6. Reset Anti-Tile",
            {
                "AntiTile_Enable": 0.0,
                "AntiTile_Macro_Var": 0.0,
                "Vertex_Paint_Strength": 0.0,
            },
        ),
    ]
    for at_idx, (at_title, at_dict) in enumerate(at_presets):
        at_col = (1.0, 0.78, 0.55, 1.0) if at_idx == 5 else (
            (0.55, 0.98, 0.80, 1.0) if at_idx in (0, 3, 4) else (0.88, 0.95, 1.0, 1.0)
        )
        at_bx = 14.0 + (at_idx % 3) * (124.0 + 9.0)
        at_by = 2306.0 if at_idx < 3 else 2335.0
        at_btn = _setup_named_button(
            w, is_wt, canvas,
            f"AntiTilePresetBtn_{at_idx + 1}", f"AntiTilePresetLbl_{at_idx + 1}",
            at_title,
            at_bx, at_by, 124.0, 25.0,
            color=at_col,
            apply_layout=apply_layout,
        )
        if not is_wt:
            def _make_at_preset_cb(p_d=at_dict, t_str=at_title):
                def _on_at_p_click():
                    folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                    if p_d == "__FIX_SEAMLESS_BORDERS__":
                        repair_seamless_borders_on_active_material(folder_now)
                        return
                    if p_d == "__VERTEX_PAINT_ANTITILE__":
                        enable_vertex_paint_on_selected(folder_now)
                        return
                    mi = _get_active_layer_a_mi(folder_now)
                    if not mi:
                        _set_panel_status("[!] Select or generate a Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
                        return
                    mel = unreal.MaterialEditingLibrary
                    for k, v in p_d.items():
                        mel.set_material_instance_scalar_parameter_value(
                            mi, k, float(v), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                        )
                    mel.update_material_instance(mi)
                    unreal.EditorAssetLibrary.save_loaded_asset(mi)
                    _sync_spinboxes_from_mi(mi)
                    _set_panel_status(
                        f"[Anti-Tiling] Applied '{t_str}' to '{mi.get_name()}'!",
                        color=(0.45, 0.96, 0.75, 1.0),
                    )
                return _on_at_p_click

            at_p_cb = _make_at_preset_cb()
            _clear_delegate_safe(at_btn.on_clicked)
            at_btn.on_clicked.add_callable(at_p_cb)
            builtins._COMFY_BTN_REFS.append((at_btn, at_p_cb))

    # =========================================================================
    # === Section 6: NANITE DISPLACEMENT, DECALS & SMART PRESET LIBRARY ===
    # =========================================================================
    _setup_named_label(
        w, is_wt, canvas, "NaniteDecalPaintSectionLabel",
        "6. Nanite Displacement, Decals & Smart Preset Library:",
        14.0, 2502.0, 390.0, 16.0,
        size=8, bold=True, color=(0.58, 0.96, 0.82, 1.0),
        apply_layout=apply_layout,
    )

    spawn_decal_btn = _setup_named_button(
        w, is_wt, canvas, "SpawnDecalBtn", "SpawnDecalBtnLabel",
        "Spawn Decal at Aim",
        14.0, 2521.0, 128.0, 25.0,
        color=(0.55, 0.98, 0.80, 1.0),
        apply_layout=apply_layout,
        tooltip="Creates a Deferred Decal (MI_Decal_*) on MM_ArchViz_Decal and spawns a DecalActor on the aimed surface in Viewport",
    )
    make_decal_btn = _setup_named_button(
        w, is_wt, canvas, "MakeDecalMtlBtn", "MakeDecalMtlBtnLabel",
        "Make Decal Mtl",
        146.0, 2521.0, 122.0, 25.0,
        color=(0.72, 0.94, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Converts the active material into a Deferred Decal Material Instance (MI_Decal_*) parented to MM_ArchViz_Decal",
    )
    nanite_disp_btn = _setup_named_button(
        w, is_wt, canvas, "NaniteDispBtn", "NaniteDispBtnLabel",
        "Enable Nanite Disp",
        272.0, 2521.0, 132.0, 25.0,
        color=(1.0, 0.88, 0.55, 1.0),
        apply_layout=apply_layout,
        tooltip="Applies the selected Displacement Mode (Geometric 3D Subdiv+WPO or Parallax Only) to the active face material",
    )

    created_dt_c = (_find_widget_any(w, is_wt, "DispTechCombo") is None)
    disp_tech_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "DispTechCombo")
    if apply_layout or created_dt_c:
        _style_combo_box(disp_tech_combo)
    saved_dt_lbl = getattr(builtins, "_COMFY_DISP_TECH_LABEL", DISP_TECH_OPTIONS[0][0])
    disp_tech_combo.clear_options()
    for dt_lbl, _dt_k in DISP_TECH_OPTIONS:
        disp_tech_combo.add_option(dt_lbl)
    disp_tech_combo.set_selected_option(saved_dt_lbl)
    _place_on_canvas(canvas, disp_tech_combo, 14.0, 2550.0, 152.0, 24.0, apply_layout=apply_layout)

    gen_comfy_disp_btn = _setup_named_button(
        w, is_wt, canvas, "GenComfyDispBtn", "GenComfyDispBtnLabel",
        "Gen Disp (AI)",
        170.0, 2550.0, 86.0, 24.0,
        color=(0.55, 0.98, 0.80, 1.0),
        apply_layout=apply_layout,
        tooltip="Generates a deep 3D Displacement Map (DepthAnything V2) in ComfyUI from the active material's AlbedoTexture",
    )
    apply_disp_mode_btn = _setup_named_button(
        w, is_wt, canvas, "ApplyDispModeBtn", "ApplyDispModeBtnLabel",
        "Apply",
        260.0, 2550.0, 58.0, 24.0,
        color=(0.72, 0.94, 1.0, 1.0),
        apply_layout=apply_layout,
        tooltip="Applies the selected Displacement Mode (Geometric 3D Subdivide+WPO or Parallax Only) to the aimed face",
    )
    remove_disp_btn = _setup_named_button(
        w, is_wt, canvas, "RemoveDispBtn", "RemoveDispBtnLabel",
        "Remove Disp",
        322.0, 2550.0, 82.0, 24.0,
        color=(1.0, 0.68, 0.52, 1.0),
        apply_layout=apply_layout,
        tooltip="Removes 3D Displacement (WPO=0) and Parallax (0) from the active face material and restores original mesh polygons",
    )

    extra_spin_items = [
        ("Disp Strength (cm)", "Height_Displacement_Strength", 0.0, 0.0, 25.0, 0.25, 2),
        ("Parallax Depth", "Height_Strength", 0.015, 0.0, 0.15, 0.005, 3),
        ("Mesh Paint Str", "Vertex_Paint_Strength", 1.0, 0.0, 1.0, 0.05, 2),
    ]
    es_x = 14.0
    for label_txt, param_name, def_val, min_v, max_v, step_v, digits_v in extra_spin_items:
        sb = _create_styled_spinbox(
            w, canvas, label_txt, es_x, 2580.0, sb_w, def_val, min_v, max_v, step_v, digits_v,
            param_name=param_name, is_wt=is_wt, apply_layout=apply_layout,
        )
        if not is_wt:
            builtins._COMFY_SPINBOX_MAP[param_name] = (sb, def_val)

            def _make_es_callbacks(p_name=param_name, l_txt=label_txt):
                def _on_es_chg(new_val: float):
                    if getattr(builtins, "_COMFY_SYNCING_UI", False):
                        return
                    folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                    mi = _get_active_layer_a_mi(folder_now)
                    if not mi:
                        return
                    mel = unreal.MaterialEditingLibrary
                    mel.set_material_instance_scalar_parameter_value(
                        mi, p_name, float(new_val), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                    mel.update_material_instance(mi)

                def _on_es_com(new_val: float, _commit_method):
                    if getattr(builtins, "_COMFY_SYNCING_UI", False):
                        return
                    folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
                    mi = _get_active_layer_a_mi(folder_now)
                    if not mi:
                        return
                    if p_name == "Height_Displacement_Strength" and float(new_val) > 0.01:
                        lbl_m = getattr(builtins, "_COMFY_DISP_TECH_LABEL", DISP_TECH_OPTIONS[0][0])
                        if "parallax" not in str(lbl_m).lower():
                            try:
                                a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                                s_id = _get_selected_poly_target_id(default_for_assign=-1)
                                for s_act in (a_sub.get_selected_level_actors() if a_sub else []):
                                    for s_comp in s_act.get_components_by_class(unreal.StaticMeshComponent):
                                        subdivide_polygon_group_for_displacement(s_comp, slot_id=s_id, min_tris=2048, ue_folder=folder_now)
                            except Exception:
                                pass
                    mel = unreal.MaterialEditingLibrary
                    mel.set_material_instance_scalar_parameter_value(
                        mi, p_name, float(new_val), unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                    )
                    mel.update_material_instance(mi)
                    unreal.EditorAssetLibrary.save_loaded_asset(mi)
                    _set_panel_status(
                        f"[{mi.get_name()}] {l_txt} ({p_name}) = {float(new_val):.3f}",
                        color=(0.55, 0.88, 1.0, 1.0),
                    )

                return _on_es_chg, _on_es_com

            es_chg, es_com = _make_es_callbacks()
            _clear_delegate_safe(sb.on_value_changed)
            _clear_delegate_safe(sb.on_value_committed)
            sb.on_value_changed.add_callable(es_chg)
            sb.on_value_committed.add_callable(es_com)
            builtins._COMFY_BTN_REFS.append((sb, es_chg))
            builtins._COMFY_BTN_REFS.append((sb, es_com))
        es_x += sb_w + sb_gap

    # Clean up deprecated custom brush buttons ("bicycle") if still present in WidgetTree or live widget
    builtins._COMFY_VIEWPORT_PAINT_ACTIVE = False
    for old_w_name in (
        "ViewportPaintCheck",
        "ViewportPaintCheckLabel",
        "PaintStampAddBtn",
        "PaintStampAddBtnLabel",
        "PaintStampSubBtn",
        "PaintStampSubBtnLabel",
        "UEVertexPaintBtn",
        "UEVertexPaintBtnLabel",
    ):
        old_w = _find_widget_any(w, is_wt, old_w_name)
        if old_w:
            try:
                old_w.set_visibility(unreal.SlateVisibility.COLLAPSED)
            except Exception:
                pass
            try:
                old_w.remove_from_parent()
            except Exception:
                pass
            if is_wt:
                try:
                    unreal.EditorUtilityLibrary.remove_widget(w, old_w)
                except Exception:
                    pass

    # Dedicated Mesh Paint Brush Layers (R = Layer 1, G = Layer 2, B = Layer 3, A = Layer 4) Studio Row (Runtime-only so BP_ComfyPanel Compiler GUID check never fires)
    if not is_wt:
        _setup_named_label(
            w, is_wt, canvas, "MeshPaintLayersHeaderLabel",
            "Mesh Paint Brush Layers (R=L1, G=L2, B=L3, A=L4):",
            14.0, 2626.0, 390.0, 14.0,
            size=8, bold=True, color=(0.55, 0.98, 0.84, 1.0),
            apply_layout=True,
        )

        mp_enable_check = _create_inline_checkbox(
            "MeshPaintEnableCheck",
            14.0, 2645.0,
            size_px=22.0,
            default_checked=True,
            tooltip="Enable/Disable AlbedoTexture & PBR maps on the active Mesh Paint Channel (R/G/B/A)",
        )
        _setup_named_label(
            w, is_wt, canvas, "MeshPaintAlbedoLabel",
            "AlbedoTexture",
            38.0, 2649.0, 86.0, 14.0,
            size=8, bold=False, color=(0.86, 0.89, 0.94, 1.0),
            apply_layout=True,
        )

        MESH_PAINT_CHAN_OPTIONS = [
            ("R (Layer 1)", 1),
            ("G (Layer 2)", 2),
            ("B (Layer 3)", 3),
            ("A (Layer 4)", 4),
        ]
        created_mpc = (_find_widget_any(w, is_wt, "MeshPaintChanCombo") is None)
        mp_chan_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "MeshPaintChanCombo")
        if apply_layout or created_mpc:
            _style_combo_box(mp_chan_combo)
        cur_mpc_sel = str(mp_chan_combo.get_selected_option() or "").strip()
        mp_chan_combo.clear_options()
        for c_lbl, _c_k in MESH_PAINT_CHAN_OPTIONS:
            mp_chan_combo.add_option(c_lbl)
        if cur_mpc_sel in [x[0] for x in MESH_PAINT_CHAN_OPTIONS]:
            mp_chan_combo.set_selected_option(cur_mpc_sel)
        else:
            mp_chan_combo.set_selected_option(MESH_PAINT_CHAN_OPTIONS[0][0])
        _place_on_canvas(canvas, mp_chan_combo, 14.0, 2672.0, 110.0, 24.0, apply_layout=True)

        # Square Texture Thumbnail Preview (54x54 frame + 50x48 image + 50x3 bottom accent stripe) matching UE Details Texture slot UI
        mp_thumb_border = _get_or_create_widget(w, is_wt, unreal.Image, "MeshPaintThumbBorder")
        try:
            mp_thumb_border.set_color_and_opacity(unreal.LinearColor(0.04, 0.045, 0.055, 1.0))
        except Exception:
            pass
        _place_on_canvas(canvas, mp_thumb_border, 130.0, 2643.0, 54.0, 54.0, apply_layout=True)

        mp_thumb_img = _get_or_create_widget(w, is_wt, unreal.Image, "MeshPaintThumbImg")
        try:
            mp_thumb_img.set_color_and_opacity(unreal.LinearColor(0.12, 0.13, 0.15, 1.0))
            mp_thumb_img.set_tool_tip_text("Active Mesh Paint Channel AlbedoTexture Preview")
        except Exception:
            pass
        _place_on_canvas(canvas, mp_thumb_img, 132.0, 2645.0, 50.0, 48.0, apply_layout=True)

        mp_thumb_bar = _get_or_create_widget(w, is_wt, unreal.Image, "MeshPaintThumbBar")
        try:
            mp_thumb_bar.set_color_and_opacity(unreal.LinearColor(0.86, 0.24, 0.24, 1.0))
        except Exception:
            pass
        _place_on_canvas(canvas, mp_thumb_bar, 132.0, 2693.0, 50.0, 3.0, apply_layout=True)

        # Right side of Thumbnail: Top row = Texture Dropdown, Bottom row = [<-] [Browse] [Paint Ready]
        created_mpm = (_find_widget_any(w, is_wt, "MeshPaintMtlCombo") is None)
        mp_mtl_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "MeshPaintMtlCombo")
        if apply_layout or created_mpm:
            _style_combo_box(mp_mtl_combo)
        _place_on_canvas(canvas, mp_mtl_combo, 190.0, 2644.0, 214.0, 24.0, apply_layout=True)

        pick_mp_btn = _setup_named_button(
            w, is_wt, canvas, "PickMeshPaintMtlBtn", "PickMeshPaintMtlBtnLabel",
            "<-",
            190.0, 2672.0, 38.0, 24.0,
            color=(0.65, 0.95, 1.0, 1.0),
            apply_layout=True,
            tooltip="Use Selected Asset from Content Browser (Assign selected Texture T_* or Material Instance MI_* into the active R/G/B/A Mesh Paint Channel)",
        )
        find_mp_btn = _setup_named_button(
            w, is_wt, canvas, "FindMeshPaintMtlBtn", "FindMeshPaintMtlBtnLabel",
            "Browse",
            232.0, 2672.0, 64.0, 24.0,
            color=(0.98, 0.88, 0.60, 1.0),
            apply_layout=True,
            tooltip="Browse to Asset in Content Browser (Find the active channel's Texture in Content Browser)",
        )
        prep_mp_btn = _setup_named_button(
            w, is_wt, canvas, "PrepMeshPaintBtn", "PrepMeshPaintBtnLabel",
            "Paint Ready",
            300.0, 2672.0, 104.0, 24.0,
            color=(0.55, 0.98, 0.80, 1.0),
            apply_layout=True,
            tooltip="Enables UE 5.7 Texture Color (256px) & Vertex Paint on the selected mesh and sets R/G/B/A layers to Brush-Only mask mode",
        )

        # Row 2 of Mesh Paint Brush Layers: Independent Texture Tiling along X and Y axes + [1:1] & [Reset All]
        _setup_named_label(
            w, is_wt, canvas, "MeshPaintTileXLabel",
            "Tile X:",
            14.0, 2705.0, 38.0, 14.0,
            size=8, bold=True, color=(0.98, 0.62, 0.62, 1.0),
            apply_layout=True,
        )
        mp_tile_x_spin = _create_inline_spinbox(
            "Spin_MP_TileX", 52.0, 2701.0, 72.0, 24.0,
            default_val=1.0, min_val=0.01, max_val=64.0, step=0.1, digits=2,
        )
        try:
            mp_tile_x_spin.set_min_value(0.01)
            mp_tile_x_spin.set_max_value(64.0)
            mp_tile_x_spin.set_min_slider_value(0.05)
            mp_tile_x_spin.set_max_slider_value(16.0)
            mp_tile_x_spin.set_editor_property("delta", 0.1)
            mp_tile_x_spin.set_editor_property("min_fractional_digits", 1)
            mp_tile_x_spin.set_editor_property("max_fractional_digits", 2)
            mp_tile_x_spin.set_tool_tip_text("Horizontal UV Tiling (X) for the active Mesh Paint Channel (R/G/B/A)")
        except Exception:
            pass
        _place_on_canvas(canvas, mp_tile_x_spin, 52.0, 2701.0, 72.0, 24.0, apply_layout=True)

        _setup_named_label(
            w, is_wt, canvas, "MeshPaintTileYLabel",
            "Tile Y:",
            130.0, 2705.0, 38.0, 14.0,
            size=8, bold=True, color=(0.58, 0.96, 0.68, 1.0),
            apply_layout=True,
        )
        mp_tile_y_spin = _create_inline_spinbox(
            "Spin_MP_TileY", 168.0, 2701.0, 72.0, 24.0,
            default_val=1.0, min_val=0.01, max_val=64.0, step=0.1, digits=2,
        )
        try:
            mp_tile_y_spin.set_min_value(0.01)
            mp_tile_y_spin.set_max_value(64.0)
            mp_tile_y_spin.set_min_slider_value(0.05)
            mp_tile_y_spin.set_max_slider_value(16.0)
            mp_tile_y_spin.set_editor_property("delta", 0.1)
            mp_tile_y_spin.set_editor_property("min_fractional_digits", 1)
            mp_tile_y_spin.set_editor_property("max_fractional_digits", 2)
            mp_tile_y_spin.set_tool_tip_text("Vertical UV Tiling (Y) for the active Mesh Paint Channel (R/G/B/A)")
        except Exception:
            pass
        _place_on_canvas(canvas, mp_tile_y_spin, 168.0, 2701.0, 72.0, 24.0, apply_layout=True)

        reset_mp_tile_btn = _setup_named_button(
            w, is_wt, canvas, "ResetMPTileBtn", "ResetMPTileBtnLabel",
            "1:1",
            244.0, 2701.0, 46.0, 24.0,
            color=(0.82, 0.90, 1.0, 1.0),
            apply_layout=True,
            tooltip="Reset active Mesh Paint Channel's Tile X and Tile Y back to 1.0 x 1.0",
        )

        reset_all_mp_btn = _setup_named_button(
            w, is_wt, canvas, "ResetAllMeshPaintBtn", "ResetAllMeshPaintBtnLabel",
            "Reset All",
            294.0, 2701.0, 110.0, 24.0,
            color=(1.0, 0.56, 0.48, 1.0),
            apply_layout=True,
            tooltip="Reset all 4 Mesh Paint Brush Layers (R/G/B/A textures, enable states, X/Y tiling & painted masks) back to clean defaults",
        )

    _setup_named_label(
        w, is_wt, canvas, "PresetLibHeaderLabel",
        "Smart Material Preset Library & Batch Export:",
        14.0, 2734.0, 390.0, 14.0,
        size=8, bold=True, color=(0.76, 0.86, 0.98, 1.0),
        apply_layout=True,
    )

    created_plib_c = (_find_widget_any(w, is_wt, "PresetLibraryCombo") is None)
    preset_lib_combo = _get_or_create_widget(w, is_wt, unreal.EditorUtilityComboBoxString, "PresetLibraryCombo")
    if apply_layout or created_plib_c:
        _style_combo_box(preset_lib_combo)
    lib_dict_now = _load_preset_library_dict()
    preset_lib_combo.clear_options()
    for p_k in lib_dict_now.keys():
        preset_lib_combo.add_option(p_k)
    first_lib_k = next(iter(lib_dict_now.keys()), "")
    if first_lib_k:
        preset_lib_combo.set_selected_option(first_lib_k)
    _place_on_canvas(canvas, preset_lib_combo, 14.0, 2750.0, 390.0, 24.0, apply_layout=True)

    save_plib_btn = _setup_named_button(
        w, is_wt, canvas, "SavePresetLibBtn", "SavePresetLibBtnLabel",
        "Save Preset",
        14.0, 2778.0, 124.0, 25.0,
        color=(0.55, 0.98, 0.80, 1.0),
        apply_layout=True,
        tooltip="Saves the active Material Instance (all layers, masks, seams & scalar parameters) into studio_material_library.json",
    )
    load_plib_btn = _setup_named_button(
        w, is_wt, canvas, "LoadPresetLibBtn", "LoadPresetLibBtnLabel",
        "Load Preset",
        147.0, 2778.0, 124.0, 25.0,
        color=(0.72, 0.94, 1.0, 1.0),
        apply_layout=True,
        tooltip="Applies the selected Studio Library preset to the active Material Instance and selected actor",
    )
    export_pack_btn = _setup_named_button(
        w, is_wt, canvas, "ExportPresetPackBtn", "ExportPresetPackBtnLabel",
        "Export Pack",
        280.0, 2778.0, 124.0, 25.0,
        color=(1.0, 0.88, 0.55, 1.0),
        apply_layout=True,
        tooltip="Batch-exports all project Material Instances and Studio Presets into Exported_Material_Pack.json",
    )

    if not is_wt:
        builtins._COMFY_PRESET_LIB_COMBO = preset_lib_combo
        builtins._COMFY_DISP_TECH_COMBO = disp_tech_combo
        builtins._COMFY_MP_CHAN_COMBO = mp_chan_combo
        builtins._COMFY_MP_MTL_COMBO = mp_mtl_combo
        builtins._COMFY_MP_ENABLE_CHECK = mp_enable_check
        builtins._COMFY_MP_THUMB_IMG = mp_thumb_img
        builtins._COMFY_MP_TILE_X_SPIN = mp_tile_x_spin
        builtins._COMFY_MP_TILE_Y_SPIN = mp_tile_y_spin

        def _get_selected_mp_slot_k() -> int:
            sel_c = str(mp_chan_combo.get_selected_option() or "").strip()
            for c_lbl, c_k in MESH_PAINT_CHAN_OPTIONS:
                if sel_c == c_lbl:
                    return c_k
            return 1

        def _get_mp_tile_param_names(slot_k: int):
            if slot_k == 1:
                return "LayerB_Tiling_X", "LayerB_Tiling_Y"
            return f"Layer{slot_k}_Tiling_X", f"Layer{slot_k}_Tiling_Y"

        def _update_mp_thumbnail(tex_or_name) -> None:
            if not mp_thumb_img:
                return
            tex_obj = None
            if isinstance(tex_or_name, unreal.Texture2D):
                tex_obj = tex_or_name
            elif isinstance(tex_or_name, str) and tex_or_name and tex_or_name != "None":
                tex_map = getattr(builtins, "_COMFY_TEX_MAP", {})
                t_path = tex_map.get(tex_or_name, "")
                if not t_path and tex_or_name.startswith("MI_"):
                    cand_t = f"T_{tex_or_name[3:]}_Albedo"
                    t_path = tex_map.get(cand_t, "")
                if t_path and unreal.EditorAssetLibrary.does_asset_exist(t_path):
                    loaded = unreal.EditorAssetLibrary.load_asset(t_path)
                    if isinstance(loaded, unreal.Texture2D):
                        tex_obj = loaded
            try:
                if tex_obj:
                    mp_thumb_img.set_brush_from_texture(tex_obj, False)
                    mp_thumb_img.set_color_and_opacity(unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
                else:
                    mp_thumb_img.set_brush_from_texture(None, False)
                    mp_thumb_img.set_color_and_opacity(unreal.LinearColor(0.12, 0.13, 0.15, 1.0))
            except Exception:
                pass

        def _refresh_mp_mtl_combo():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            alb_texs = _discover_albedo_textures(folder_now)
            mis = _discover_material_instances(folder_now)
            mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
            if not isinstance(mi_map, dict):
                mi_map = {}
            for m_p in mis:
                mi_map[m_p.split("/")[-1]] = m_p
            builtins._COMFY_MI_MAP = mi_map
            slot_k = _get_selected_mp_slot_k()
            c_row = layer_ui_rows[slot_k - 1]
            cur_sel = "None"
            cur_tex_obj = None
            is_enabled_slot = False
            tile_x_val = 1.0
            tile_y_val = 1.0
            target_mi = _get_active_layer_a_mi(folder_now)
            if target_mi:
                try:
                    mel = unreal.MaterialEditingLibrary
                    en_p = "LayerB_Enable" if slot_k == 1 else f"Layer{slot_k}_Enable"
                    alb_p = "LayerB_AlbedoTexture" if slot_k == 1 else f"Layer{slot_k}_AlbedoTexture"
                    tx_p, ty_p = _get_mp_tile_param_names(slot_k)
                    en_v = float(mel.get_material_instance_scalar_parameter_value(target_mi, en_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    alb_t = mel.get_material_instance_texture_parameter_value(target_mi, alb_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
                    tx_v = float(mel.get_material_instance_scalar_parameter_value(target_mi, tx_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    ty_v = float(mel.get_material_instance_scalar_parameter_value(target_mi, ty_p, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER))
                    if tx_v > 0.001:
                        tile_x_val = tx_v
                    if ty_v > 0.001:
                        tile_y_val = ty_v
                    is_enabled_slot = (en_v > 0.001)
                    if alb_t:
                        t_n = str(alb_t.get_name() or "").strip()
                        if t_n and not t_n.startswith(("WhiteSquare", "Default", "BaseFlatten", "T_Default_")):
                            cur_sel = t_n
                            if isinstance(alb_t, unreal.Texture2D):
                                cur_tex_obj = alb_t
                except Exception:
                    pass
            if cur_sel == "None" and not target_mi:
                row_sel = str(c_row["mtl_combo"].get_selected_option() or "None").strip()
                if row_sel and row_sel != "None":
                    cur_sel = f"T_{row_sel[3:]}_Albedo" if row_sel.startswith("MI_") else row_sel
                    is_enabled_slot = bool(c_row["mtl_check"].is_checked())
            builtins._COMFY_SYNCING_UI = True
            try:
                mp_mtl_combo.clear_options()
                mp_mtl_combo.add_option("None")
                for t_p in alb_texs:
                    s_t = t_p.split("/")[-1]
                    mp_mtl_combo.add_option(s_t)
                for m_p in mis:
                    s_n = m_p.split("/")[-1]
                    mp_mtl_combo.add_option(s_n)
                if cur_sel and cur_sel != "None" and mp_mtl_combo.find_option_index(cur_sel) < 0:
                    mp_mtl_combo.add_option(cur_sel)
                mp_mtl_combo.set_selected_option(cur_sel if cur_sel else "None")
                if mp_enable_check:
                    mp_enable_check.set_is_checked(bool(is_enabled_slot and cur_sel != "None"))
                if mp_tile_x_spin:
                    mp_tile_x_spin.set_value(float(tile_x_val))
                if mp_tile_y_spin:
                    mp_tile_y_spin.set_value(float(tile_y_val))
            finally:
                builtins._COMFY_SYNCING_UI = False
            _update_mp_thumbnail(cur_tex_obj or cur_sel)

        def _assign_mi_or_tex_to_mp_slot(slot_k: int, mi_short_or_none: str, tex_asset=None):
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            target_mi = _get_active_layer_a_mi(folder_now)
            if not target_mi:
                _set_panel_status("[!] Select an Actor or Base mtl first!", color=(1.0, 0.72, 0.3, 1.0))
                return
            mel = unreal.MaterialEditingLibrary
            c_row = layer_ui_rows[slot_k - 1]
            chan_letter = ("R", "G", "B", "A")[slot_k - 1]
            en_param = "LayerB_Enable" if slot_k == 1 else f"Layer{slot_k}_Enable"
            use_m_param = "LayerB_Use_Mask" if slot_k == 1 else f"Layer{slot_k}_Use_Mask"
            str_m_param = "Blend_Mask_Strength" if slot_k == 1 else f"Layer{slot_k}_Mask_Strength"

            source_arg = tex_asset if (tex_asset and isinstance(tex_asset, unreal.Texture)) else mi_short_or_none
            if not source_arg or str(source_arg).strip() == "None":
                builtins._COMFY_SYNCING_UI = True
                try:
                    c_row["mtl_combo"].set_selected_option("None")
                    c_row["mtl_check"].set_is_checked(False)
                    mp_mtl_combo.set_selected_option("None")
                    if mp_enable_check:
                        mp_enable_check.set_is_checked(False)
                finally:
                    builtins._COMFY_SYNCING_UI = False
                _update_mp_thumbnail(None)
                pfx_clr = "LayerB" if slot_k == 1 else f"Layer{slot_k}"
                t_w_clr = (
                    unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_White")
                    or unreal.EditorAssetLibrary.load_asset("/Engine/EngineResources/WhiteSquareTexture")
                    or unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/DefaultDiffuse")
                )
                t_n_clr = (
                    unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_Normal")
                    or unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/DefaultNormal")
                )
                t_g_clr = (
                    unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_Roughness")
                    or unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/BaseFlattenLinearColor")
                    or t_w_clr
                )
                for tx_sfx, def_tx in (
                    ("AlbedoTexture", t_w_clr),
                    ("NormalTexture", t_n_clr),
                    ("RoughnessTexture", t_g_clr),
                    ("HeightTexture", t_g_clr),
                ):
                    if def_tx:
                        try:
                            mel.set_material_instance_texture_parameter_value(
                                target_mi, f"{pfx_clr}_{tx_sfx}", def_tx, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            )
                        except Exception:
                            pass
                mel.set_material_instance_scalar_parameter_value(target_mi, en_param, 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
                mel.update_material_instance(target_mi)
                unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
                try:
                    mi_key_clr = target_mi.get_path_name().split(".")[0]
                    st_all_clr = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
                    if isinstance(st_all_clr, dict) and mi_key_clr in st_all_clr:
                        st_all_clr[mi_key_clr].pop(slot_k, None)
                except Exception:
                    pass
                _set_panel_status(f"[Mesh Paint {chan_letter} -> Layer {slot_k}] Cleared Layer {slot_k} on '{target_mi.get_name()}'.", color=(0.75, 0.82, 0.92, 1.0))
                return

            assigned_tex_short = _assign_pbr_textures_by_stem_to_layer_slot(target_mi, source_arg, slot_idx=slot_k)

            builtins._COMFY_SYNCING_UI = True
            try:
                if c_row["mtl_combo"].find_option_index(assigned_tex_short) < 0:
                    c_row["mtl_combo"].add_option(assigned_tex_short)
                c_row["mtl_combo"].set_selected_option(assigned_tex_short)
                c_row["mtl_amt"].set_value(100.0)
                c_row["mtl_check"].set_is_checked(True)
                c_row["mask_combo"].set_selected_option("No Map")
                c_row["mask_check"].set_is_checked(True)
                if mp_mtl_combo.find_option_index(assigned_tex_short) < 0:
                    mp_mtl_combo.add_option(assigned_tex_short)
                mp_mtl_combo.set_selected_option(assigned_tex_short)
                if mp_enable_check:
                    mp_enable_check.set_is_checked(True)
            finally:
                builtins._COMFY_SYNCING_UI = False
            _update_mp_thumbnail(tex_asset if isinstance(tex_asset, unreal.Texture2D) else assigned_tex_short)

            mel.set_material_instance_scalar_parameter_value(target_mi, en_param, 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
            mel.set_material_instance_scalar_parameter_value(target_mi, use_m_param, 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
            mel.set_material_instance_scalar_parameter_value(target_mi, str_m_param, 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
            if slot_k == 1:
                mel.set_material_instance_scalar_parameter_value(target_mi, "Blend_In_Seams", 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
            mel.set_material_instance_scalar_parameter_value(target_mi, "Vertex_Paint_Strength", 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER)
            mel.update_material_instance(target_mi)
            unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
            enable_vertex_paint_on_selected(folder_now)
            _set_panel_status(
                f"[Mesh Paint {chan_letter} -> Layer {slot_k}] Assigned texture '{assigned_tex_short}' (+Normal/Roughness/Height) to '{target_mi.get_name()}'!",
                color=(0.45, 0.96, 0.65, 1.0),
            )

        def _on_mp_enable_check_changed(is_checked: bool):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            slot_k = _get_selected_mp_slot_k()
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            target_mi = _get_active_layer_a_mi(folder_now)
            if not target_mi:
                return
            en_param = "LayerB_Enable" if slot_k == 1 else f"Layer{slot_k}_Enable"
            c_row = layer_ui_rows[slot_k - 1]
            builtins._COMFY_SYNCING_UI = True
            try:
                c_row["mtl_check"].set_is_checked(bool(is_checked))
            finally:
                builtins._COMFY_SYNCING_UI = False
            mel = unreal.MaterialEditingLibrary
            mel.set_material_instance_scalar_parameter_value(
                target_mi, en_param, 1.0 if is_checked else 0.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            mel.update_material_instance(target_mi)
            unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
            chan_letter = ("R", "G", "B", "A")[slot_k - 1]
            _set_panel_status(
                f"[Mesh Paint {chan_letter} -> Layer {slot_k}] AlbedoTexture {'ENABLED' if is_checked else 'DISABLED'} on '{target_mi.get_name()}'.",
                color=(0.45, 0.96, 0.65, 1.0) if is_checked else (0.75, 0.82, 0.92, 1.0),
            )

        def _on_mp_chan_changed(_sel_item, _stype):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            _refresh_mp_mtl_combo()

        def _on_mp_mtl_opening():
            _refresh_mp_mtl_combo()

        def _on_mp_mtl_changed(sel_item, _stype):
            if not sel_item or getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            _assign_mi_or_tex_to_mp_slot(_get_selected_mp_slot_k(), str(sel_item).strip())

        def _on_pick_mp_clicked():
            slot_k = _get_selected_mp_slot_k()
            selected_assets = unreal.EditorUtilityLibrary.get_selected_assets()
            for a in selected_assets:
                if isinstance(a, unreal.MaterialInstanceConstant):
                    m_path = a.get_path_name().split(".")[0]
                    m_short = m_path.split("/")[-1]
                    mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
                    mi_map[m_short] = m_path
                    builtins._COMFY_MI_MAP = mi_map
                    _assign_mi_or_tex_to_mp_slot(slot_k, m_short)
                    return
                if isinstance(a, unreal.Texture):
                    _assign_mi_or_tex_to_mp_slot(slot_k, "", tex_asset=a)
                    return
            _set_panel_status(
                "[!] Select a Material Instance (MI_*) or Texture (T_*) in Content Browser and click '<-'!",
                color=(1.0, 0.72, 0.3, 1.0),
            )

        def _on_find_mp_clicked():
            sel_m = str(mp_mtl_combo.get_selected_option() or "").strip()
            if not sel_m or sel_m == "None":
                _set_panel_status("[!] Active Mesh Paint channel has no Texture/Material assigned!", color=(1.0, 0.72, 0.3, 1.0))
                return
            tex_map = getattr(builtins, "_COMFY_TEX_MAP", {})
            resolved_b = tex_map.get(sel_m) or _resolve_mi_path(sel_m)
            if resolved_b and unreal.EditorAssetLibrary.does_asset_exist(resolved_b):
                unreal.EditorAssetLibrary.sync_browser_to_objects([resolved_b])
                _set_panel_status(f"[Browse] Synced Content Browser to '{sel_m}'.", color=(0.55, 0.88, 1.0, 1.0))

        def _on_prep_mp_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            enable_vertex_paint_on_selected(folder_now)

        def _apply_mp_tile_axis(axis: str, new_val: float, save_asset: bool = False):
            if getattr(builtins, "_COMFY_SYNCING_UI", False):
                return
            slot_k = _get_selected_mp_slot_k()
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            target_mi = _get_active_layer_a_mi(folder_now)
            if not target_mi:
                return
            tx_p, ty_p = _get_mp_tile_param_names(slot_k)
            p_name = tx_p if axis == "X" else ty_p
            v_clamped = max(0.01, float(new_val))
            mel = unreal.MaterialEditingLibrary
            mel.set_material_instance_scalar_parameter_value(
                target_mi, p_name, v_clamped, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            mel.update_material_instance(target_mi)
            if save_asset:
                unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
                chan_letter = ("R", "G", "B", "A")[slot_k - 1]
                cur_x = float(mp_tile_x_spin.get_value()) if mp_tile_x_spin else v_clamped
                cur_y = float(mp_tile_y_spin.get_value()) if mp_tile_y_spin else v_clamped
                _set_panel_status(
                    f"[Mesh Paint {chan_letter} -> Layer {slot_k}] Tiling (X, Y) = ({cur_x:.2f}, {cur_y:.2f}) on '{target_mi.get_name()}'",
                    color=(0.55, 0.88, 1.0, 1.0),
                )

        def _on_mp_tile_x_changed(new_val: float):
            _apply_mp_tile_axis("X", new_val, save_asset=False)

        def _on_mp_tile_x_committed(new_val: float, _commit_method):
            _apply_mp_tile_axis("X", new_val, save_asset=True)

        def _on_mp_tile_y_changed(new_val: float):
            _apply_mp_tile_axis("Y", new_val, save_asset=False)

        def _on_mp_tile_y_committed(new_val: float, _commit_method):
            _apply_mp_tile_axis("Y", new_val, save_asset=True)

        def _on_reset_mp_tile_clicked():
            slot_k = _get_selected_mp_slot_k()
            builtins._COMFY_SYNCING_UI = True
            try:
                if mp_tile_x_spin:
                    mp_tile_x_spin.set_value(1.0)
                if mp_tile_y_spin:
                    mp_tile_y_spin.set_value(1.0)
            finally:
                builtins._COMFY_SYNCING_UI = False
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            target_mi = _get_active_layer_a_mi(folder_now)
            if not target_mi:
                return
            tx_p, ty_p = _get_mp_tile_param_names(slot_k)
            mel = unreal.MaterialEditingLibrary
            mel.set_material_instance_scalar_parameter_value(
                target_mi, tx_p, 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            mel.set_material_instance_scalar_parameter_value(
                target_mi, ty_p, 1.0, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
            )
            mel.update_material_instance(target_mi)
            unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
            chan_letter = ("R", "G", "B", "A")[slot_k - 1]
            _set_panel_status(
                f"[Mesh Paint {chan_letter} -> Layer {slot_k}] Reset Tiling (X=1.0, Y=1.0) on '{target_mi.get_name()}'.",
                color=(0.45, 0.96, 0.65, 1.0),
            )

        def _on_reset_all_mp_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            target_mi = _get_active_layer_a_mi(folder_now)
            builtins._COMFY_SYNCING_UI = True
            try:
                for k_idx in range(min(4, len(layer_ui_rows))):
                    r_ui = layer_ui_rows[k_idx]
                    r_ui["mtl_combo"].set_selected_option("None")
                    r_ui["mtl_check"].set_is_checked(False)
                    r_ui["mtl_amt"].set_value(100.0)
                    r_ui["mask_combo"].set_selected_option("No Map")
                    r_ui["mask_check"].set_is_checked(False)
                if mp_mtl_combo:
                    mp_mtl_combo.set_selected_option("None")
                if mp_enable_check:
                    mp_enable_check.set_is_checked(False)
                if mp_tile_x_spin:
                    mp_tile_x_spin.set_value(1.0)
                if mp_tile_y_spin:
                    mp_tile_y_spin.set_value(1.0)
            finally:
                builtins._COMFY_SYNCING_UI = False
            _update_mp_thumbnail(None)

            if target_mi:
                mel = unreal.MaterialEditingLibrary
                t_white = (
                    unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_White")
                    or unreal.EditorAssetLibrary.load_asset("/Engine/EngineResources/WhiteSquareTexture")
                    or unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/DefaultDiffuse")
                )
                t_flat = (
                    unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_Normal")
                    or unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/DefaultNormal")
                )
                t_gray = (
                    unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{TEXTURES_SUBFOLDER}/T_Default_Roughness")
                    or unreal.EditorAssetLibrary.load_asset("/Engine/EngineMaterials/BaseFlattenLinearColor")
                    or t_white
                )

                for sk in (1, 2, 3, 4):
                    pfx = "LayerB" if sk == 1 else f"Layer{sk}"
                    for sc_name, sc_val in (
                        (f"{pfx}_Enable", 0.0),
                        (f"{pfx}_Use_Mask", 0.0),
                        (f"{pfx}_UV_Tiling", 1.0),
                        (f"{pfx}_Tiling_X", 1.0),
                        (f"{pfx}_Tiling_Y", 1.0),
                        ("Blend_Mask_Strength" if sk == 1 else f"{pfx}_Mask_Strength", 0.0),
                    ):
                        try:
                            mel.set_material_instance_scalar_parameter_value(
                                target_mi, sc_name, sc_val, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                            )
                        except Exception:
                            pass
                    for tx_suffix, def_t in (
                        ("AlbedoTexture", t_white),
                        ("NormalTexture", t_flat),
                        ("RoughnessTexture", t_gray),
                        ("HeightTexture", t_gray),
                    ):
                        if def_t:
                            try:
                                mel.set_material_instance_texture_parameter_value(
                                    target_mi, f"{pfx}_{tx_suffix}", def_t, unreal.MaterialParameterAssociation.GLOBAL_PARAMETER
                                )
                            except Exception:
                                pass
                mel.update_material_instance(target_mi)
                unreal.EditorAssetLibrary.save_loaded_asset(target_mi)
                try:
                    mi_key_rst = target_mi.get_path_name().split(".")[0]
                    st_all_rst = getattr(builtins, "_COMFY_CORONA_LAYER_STATE", {})
                    if isinstance(st_all_rst, dict) and mi_key_rst in st_all_rst:
                        for sk_pop in (1, 2, 3, 4):
                            st_all_rst[mi_key_rst].pop(sk_pop, None)
                except Exception:
                    pass

            mi_lbl = target_mi.get_name() if target_mi else "Panel"
            _set_panel_status(
                f"[Mesh Paint Reset All] Cleared R/G/B/A layers, textures & X/Y tiling (1:1) on '{mi_lbl}'.",
                color=(0.45, 0.96, 0.65, 1.0),
            )

        builtins._COMFY_REFRESH_MP_FN = _refresh_mp_mtl_combo

        def _on_disp_tech_changed(selected_item, _selection_type):
            if (
                not selected_item
                or getattr(builtins, "_COMFY_SYNCING_UI", False)
                or time.time() < getattr(builtins, "_COMFY_UI_INIT_UNTIL", 0.0)
                or _selection_type == unreal.SelectInfo.DIRECT
            ):
                return
            builtins._COMFY_DISP_TECH_LABEL = str(selected_item)
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            setup_nanite_displacement_on_selected(folder_now, displacement_cm=4.0, parallax_depth=0.035)

        def _on_gen_comfy_disp_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            generate_displacement_in_comfy_for_active_mi(folder_now)

        def _on_apply_disp_mode_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            setup_nanite_displacement_on_selected(folder_now, displacement_cm=4.0, parallax_depth=0.035)

        def _on_remove_disp_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            remove_displacement_on_selected(folder_now)

        def _on_spawn_decal_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            spawn_decal_actor_in_viewport(folder_now)
            _refresh_master_combo(mm_combo, folder_now)

        def _on_make_decal_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            dec_mi = create_decal_material_from_mi(None, folder_now)
            if dec_mi:
                dec_path = dec_mi.get_path_name().split(".")[0]
                _refresh_master_combo(mm_combo, folder_now, select_path=dec_path)
                _set_panel_status(
                    f"[Decal Material Ready] Created '{dec_mi.get_name()}' (Parent: MM_ArchViz_Decal)!",
                    color=(0.45, 0.96, 0.65, 1.0),
                )

        def _on_nanite_disp_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            setup_nanite_displacement_on_selected(folder_now, displacement_cm=4.0, parallax_depth=0.035)

        def _on_save_plib_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            save_material_preset_to_library(folder_now)

        def _on_load_plib_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            sel_p = str(preset_lib_combo.get_selected_option() or "").strip()
            if sel_p:
                load_material_preset_from_library(sel_p, folder_now)

        def _on_export_pack_clicked():
            folder_now = _normalize_ue_folder(str(path_box.get_text()) if path_box else DEFAULT_UE_FOLDER)
            export_material_library_pack(folder_now)

        for d_s6 in (
            spawn_decal_btn.on_clicked,
            make_decal_btn.on_clicked,
            nanite_disp_btn.on_clicked,
            disp_tech_combo.on_selection_changed,
            gen_comfy_disp_btn.on_clicked,
            apply_disp_mode_btn.on_clicked,
            remove_disp_btn.on_clicked,
            mp_enable_check.on_check_state_changed,
            mp_chan_combo.on_selection_changed,
            mp_mtl_combo.on_opening,
            mp_mtl_combo.on_selection_changed,
            pick_mp_btn.on_clicked,
            find_mp_btn.on_clicked,
            prep_mp_btn.on_clicked,
            mp_tile_x_spin.on_value_changed,
            mp_tile_x_spin.on_value_committed,
            mp_tile_y_spin.on_value_changed,
            mp_tile_y_spin.on_value_committed,
            reset_mp_tile_btn.on_clicked,
            reset_all_mp_btn.on_clicked,
            save_plib_btn.on_clicked,
            load_plib_btn.on_clicked,
            export_pack_btn.on_clicked,
        ):
            _clear_delegate_safe(d_s6)

        _refresh_mp_mtl_combo()

        spawn_decal_btn.on_clicked.add_callable(_on_spawn_decal_clicked)
        make_decal_btn.on_clicked.add_callable(_on_make_decal_clicked)
        nanite_disp_btn.on_clicked.add_callable(_on_nanite_disp_clicked)
        disp_tech_combo.on_selection_changed.add_callable(_on_disp_tech_changed)
        gen_comfy_disp_btn.on_clicked.add_callable(_on_gen_comfy_disp_clicked)
        apply_disp_mode_btn.on_clicked.add_callable(_on_apply_disp_mode_clicked)
        remove_disp_btn.on_clicked.add_callable(_on_remove_disp_clicked)
        mp_enable_check.on_check_state_changed.add_callable(_on_mp_enable_check_changed)
        mp_chan_combo.on_selection_changed.add_callable(_on_mp_chan_changed)
        mp_mtl_combo.on_opening.add_callable(_on_mp_mtl_opening)
        mp_mtl_combo.on_selection_changed.add_callable(_on_mp_mtl_changed)
        pick_mp_btn.on_clicked.add_callable(_on_pick_mp_clicked)
        find_mp_btn.on_clicked.add_callable(_on_find_mp_clicked)
        prep_mp_btn.on_clicked.add_callable(_on_prep_mp_clicked)
        mp_tile_x_spin.on_value_changed.add_callable(_on_mp_tile_x_changed)
        mp_tile_x_spin.on_value_committed.add_callable(_on_mp_tile_x_committed)
        mp_tile_y_spin.on_value_changed.add_callable(_on_mp_tile_y_changed)
        mp_tile_y_spin.on_value_committed.add_callable(_on_mp_tile_y_committed)
        reset_mp_tile_btn.on_clicked.add_callable(_on_reset_mp_tile_clicked)
        reset_all_mp_btn.on_clicked.add_callable(_on_reset_all_mp_clicked)
        save_plib_btn.on_clicked.add_callable(_on_save_plib_clicked)
        load_plib_btn.on_clicked.add_callable(_on_load_plib_clicked)
        export_pack_btn.on_clicked.add_callable(_on_export_pack_clicked)

        builtins._COMFY_BTN_REFS.extend([
            (spawn_decal_btn, _on_spawn_decal_clicked),
            (make_decal_btn, _on_make_decal_clicked),
            (nanite_disp_btn, _on_nanite_disp_clicked),
            (disp_tech_combo, _on_disp_tech_changed),
            (gen_comfy_disp_btn, _on_gen_comfy_disp_clicked),
            (apply_disp_mode_btn, _on_apply_disp_mode_clicked),
            (remove_disp_btn, _on_remove_disp_clicked),
            (mp_enable_check, _on_mp_enable_check_changed),
            (mp_chan_combo, _on_mp_chan_changed),
            (mp_mtl_combo, _on_mp_mtl_opening),
            (mp_mtl_combo, _on_mp_mtl_changed),
            (pick_mp_btn, _on_pick_mp_clicked),
            (find_mp_btn, _on_find_mp_clicked),
            (prep_mp_btn, _on_prep_mp_clicked),
            (mp_tile_x_spin, _on_mp_tile_x_changed),
            (mp_tile_x_spin, _on_mp_tile_x_committed),
            (mp_tile_y_spin, _on_mp_tile_y_changed),
            (mp_tile_y_spin, _on_mp_tile_y_committed),
            (reset_mp_tile_btn, _on_reset_mp_tile_clicked),
            (reset_all_mp_btn, _on_reset_all_mp_clicked),
            (save_plib_btn, _on_save_plib_clicked),
            (load_plib_btn, _on_load_plib_clicked),
            (export_pack_btn, _on_export_pack_clicked),
        ])

    # Status Bar (Y = 2812)
    status_tb = _setup_named_label(
        w, is_wt, canvas, "StudioStatusBarLabel",
        "[OK] Studio Ready: Corona Layers, UE5.7 Texture Color Mesh Paint, Decals & Library",
        14.0, 2812.0, 390.0, 20.0,
        size=8, bold=True, color=(0.48, 0.90, 0.62, 1.0),
        apply_layout=True,
    )

    if not is_wt:
        builtins._COMFY_STATUS_TB = status_tb
        actor_init_mi = _get_selected_actor_active_mi()
        init_mi = actor_init_mi or _get_active_layer_a_mi(cur_folder)
        if init_mi:
            if actor_init_mi:
                _sync_panel_from_selected_actor_or_mi(actor_init_mi)
            else:
                _sync_spinboxes_from_mi(init_mi)
                _sync_corona_layers_from_mi(init_mi)

    return w


def _browse_reference_image_dialog() -> str:
    """Opens a native Windows Open File Dialog to choose a reference image (.png/.jpg/.jpeg/.webp)."""
    try:
        import ctypes
        from ctypes import wintypes

        class OPENFILENAMEW(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wintypes.DWORD),
                ("hwndOwner", wintypes.HWND),
                ("hInstance", wintypes.HINSTANCE),
                ("lpstrFilter", wintypes.LPCWSTR),
                ("lpstrCustomFilter", wintypes.LPWSTR),
                ("nMaxCustFilter", wintypes.DWORD),
                ("nFilterIndex", wintypes.DWORD),
                ("lpstrFile", wintypes.LPWSTR),
                ("nMaxFile", wintypes.DWORD),
                ("lpstrFileTitle", wintypes.LPWSTR),
                ("nMaxFileTitle", wintypes.DWORD),
                ("lpstrInitialDir", wintypes.LPCWSTR),
                ("lpstrTitle", wintypes.LPCWSTR),
                ("Flags", wintypes.DWORD),
                ("nFileOffset", wintypes.WORD),
                ("nFileExtension", wintypes.WORD),
                ("lpstrDefExt", wintypes.LPCWSTR),
                ("lCustData", wintypes.LPARAM),
                ("lpfnHook", wintypes.LPVOID),
                ("lpTemplateName", wintypes.LPCWSTR),
                ("pvReserved", wintypes.LPVOID),
                ("dwReserved", wintypes.DWORD),
                ("FlagsEx", wintypes.DWORD),
            ]

        buf = ctypes.create_unicode_buffer(1024)
        ofn = OPENFILENAMEW()
        ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
        ofn.lpstrFilter = "Image Files (*.png;*.jpg;*.jpeg;*.webp;*.bmp)\0*.png;*.jpg;*.jpeg;*.webp;*.bmp\0All Files (*.*)\0*.*\0\0"
        ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
        ofn.nMaxFile = 1024
        ofn.lpstrTitle = "Select Reference Image (Texture or Interior Photo)"
        ofn.Flags = 0x00080000 | 0x00001000 | 0x00000800 | 0x00000008  # OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR
        if ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
            return buf.value
    except Exception as exc:
        unreal.log_warning(f"ComfyUI PBR: File dialog warning: {exc}")
    return ""


def run_reference_workflow(
    ref_image_path: str = "",
    ref_mode_label: str = "Seamless Img2Img + CHORD (5 Maps)",
    prompt_hint: str = "",
    denoise: float = 0.52,
    folder_path: str = DEFAULT_UE_FOLDER,
    json_path: str = DEFAULT_JSON_PATH,
) -> None:
    """
    Non-blocking generation of a seamless 5-map PBR Material in ComfyUI from a Reference Image:
    - 'Seamless Img2Img + CHORD (5 Maps)': Pre-processes reference into a periodic de-lit tile ->
      SDXL Circular VAE + SeamlessTile Img2Img -> Ubisoft CHORD 5-map decomposition.
    - 'Direct CHORD from Photo (De-lit)': Pre-processes reference into a periodic de-lit tile ->
      Ubisoft CHORD 5-map decomposition directly from photo.
    - 'AI Vision Prompt + CHORD': Uses Gemini Vision to extract detailed surface prompt from photo ->
      SDXL Seamless Text-to-PBR + Ubisoft CHORD.
    """
    panel = _get_open_panel_widget()
    if getattr(builtins, "_COMFY_ENHANCED_WIDGET_ID", None) != id(panel):
        panel = enhance_comfy_panel_ui(panel)

    ref_clean = (ref_image_path or "").strip().strip('"')
    if not ref_clean or not os.path.exists(ref_clean):
        _set_panel_status(
            "[!] Please select a valid Reference Image file via 'Browse...' or '<-' first!",
            color=(1.0, 0.72, 0.3, 1.0),
        )
        return

    if getattr(builtins, "_COMFY_JOB_RUNNING", False):
        _set_panel_status(
            "[...] A ComfyUI generation job is already running, please wait...",
            color=(1.0, 0.80, 0.35, 1.0),
        )
        return

    if not _check_can_generate_or_prompt_buy(1):
        return

    if "Direct CHORD" in ref_mode_label:
        ref_mode = "chord_direct"
    elif "AI Vision" in ref_mode_label:
        ref_mode = "ai_vision_pbr"
    else:
        ref_mode = "img2img_seamless"

    ue_import_path = _normalize_ue_folder(folder_path)
    if ue_import_path.split("/")[-1].lower() in [c.lower() for c in MATERIAL_CATEGORIES] or ue_import_path.split("/")[-1] in (TEXTURES_SUBFOLDER, MASKS_SUBFOLDER):
        ue_import_path = "/".join(ue_import_path.split("/")[:-1]) or DEFAULT_UE_FOLDER
    _ensure_folder_structure(ue_import_path)
    selected_mm_path = _get_selected_prompt_master_material_path(ue_import_path)
    res_px, res_tag = _get_selected_resolution()
    _model_label, pipeline_mode, ckpt_name = _get_selected_pbr_model()

    ref_stem = os.path.splitext(os.path.basename(ref_clean))[0]
    slug = _make_slug(ref_stem) or "ref_mat"
    seed_val = _get_selected_seed()
    asset_base_name = f"Ref_{slug}_{res_tag}_S{seed_val % 100000}"
    mm_low_r = selected_mm_path.lower()
    if "decal" in mm_low_r:
        mat_category = "Decal"
    elif "glass" in mm_low_r:
        mat_category = "Glass"
    elif "foliage" in mm_low_r:
        mat_category = "Foliage"
    elif "fabric" in mm_low_r:
        mat_category = "Fabric"
    elif "emissive" in mm_low_r:
        mat_category = "Light"
    else:
        mat_category = _detect_material_category(prompt_hint or ref_stem, prompt_hint or ref_stem)
    builtins._COMFY_MASTER_MAT_PATH = selected_mm_path
    pipe_short = "Ubisoft CHORD" if pipeline_mode == "chord" else "DepthAnything V2"

    state = {
        "done": False,
        "error": None,
        "downloaded": {},
        "start_time": time.time(),
        "ref_name": os.path.basename(ref_clean),
        "ue_import_path": ue_import_path,
        "selected_mm_path": selected_mm_path,
        "asset_base_name": asset_base_name,
        "mat_category": mat_category,
        "res_px": res_px,
        "res_tag": res_tag,
        "pipe_short": pipe_short,
        "is_single_leaf": False,
        "seed_val": seed_val,
    }
    builtins._COMFY_CANCEL_REQUESTED = False
    builtins._COMFY_JOB_RUNNING = True
    _set_panel_status(
        f"[...] Preparing Reference '{state['ref_name']}' ({ref_mode_label}, {res_px}x{res_px}, Seed: {seed_val})...",
        color=(0.55, 0.88, 1.0, 1.0),
    )

    def _worker():
        try:
            plugin_dir = r"D:\AI\MyAiAssistant\Corona_ComfyUI_PBR_Plugin"
            if plugin_dir not in sys.path and os.path.exists(plugin_dir):
                sys.path.insert(0, plugin_dir)
            import comfy_to_corona as c2c

            if ref_mode == "ai_vision_pbr":
                extracted = c2c.extract_materials_from_reference_image(ref_clean, target_hint=prompt_hint)
                if not extracted:
                    raise RuntimeError("AI Vision could not extract material description from reference image.")
                first_mat = extracted[0]
                prompt_en = str(first_mat.get("prompt_en") or prompt_hint or "seamless architectural texture")
                cat_raw = str(first_mat.get("category") or "").strip().capitalize()
                if cat_raw in MATERIAL_CATEGORIES:
                    state["mat_category"] = cat_raw
                workflow = c2c._build_txt2pbr_workflow(
                    prompt_en=prompt_en,
                    res_px=res_px,
                    pipeline_mode=pipeline_mode,
                    ckpt_name=ckpt_name,
                )
            else:
                pre_path = c2c.preprocess_reference_for_seamless(ref_clean, target_size=1024)
                uploaded_name = c2c.upload_image_to_comfy(pre_path)
                prompt_en = (
                    _translate_or_clean_prompt(prompt_hint)
                    if (prompt_hint or "").strip()
                    else "homogeneous architectural surface texture, uniform flat lighting, consistent natural micro-relief"
                )
                workflow = c2c._build_reference_pbr_workflow(
                    uploaded_comfy_filename=uploaded_name,
                    ref_mode=ref_mode,
                    prompt_en=prompt_en,
                    denoise=float(denoise),
                    res_px=res_px,
                    pipeline_mode=pipeline_mode,
                    ckpt_name=ckpt_name,
                )

            for _nid, _ndata in workflow.items():
                _inp = _ndata.get("inputs", {})
                if "seed" in _inp:
                    _inp["seed"] = seed_val

            req = urllib.request.Request(
                f"{COMFY_URL}/prompt",
                data=json.dumps({"prompt": workflow}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
            prompt_id = res_data["prompt_id"]

            while True:
                if getattr(builtins, "_COMFY_CANCEL_REQUESTED", False):
                    state["error"] = "__CANCELLED__"
                    break
                if time.time() - state["start_time"] > 600:
                    state["error"] = "ComfyUI reference generation timed out (600 sec)"
                    break

                try:
                    with urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}", timeout=5.0) as h_resp:
                        history = json.loads(h_resp.read().decode("utf-8"))
                    if prompt_id in history:
                        entry = history[prompt_id]
                        st_info = entry.get("status", {})
                        if st_info.get("status_str") == "error":
                            state["error"] = f"ComfyUI internal error: {st_info}"
                            break

                        outputs = entry.get("outputs", {})
                        temp_dir = os.path.dirname(json_path)
                        node_to_kind = {
                            "76": "albedo",
                            "80": "height",
                            "82": "normal",
                            "85": "roughness",
                            "86": "metallic",
                            "87": "depth_macro",
                            "91": "albedo",
                            "92": "height",
                            "93": "normal",
                            "94": "roughness",
                            "95": "metallic",
                            "98": "leaf_source",
                        }
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
                                    elif "leaf_source" in low_f:
                                        kind = "leaf_source"
                                    elif "depth_macro" in low_f:
                                        kind = "depth_macro"
                                    else:
                                        kind = "albedo"

                                params = urllib.parse.urlencode(
                                    {
                                        "filename": fname,
                                        "subfolder": image.get("subfolder", ""),
                                        "type": image.get("type", "output"),
                                    }
                                )
                                img_bytes = urllib.request.urlopen(f"{COMFY_URL}/view?{params}", timeout=15.0).read()
                                clean_filename = f"T_{asset_base_name}_{kind.capitalize()}.png"
                                local_path = os.path.join(temp_dir, clean_filename)
                                with open(local_path, "wb") as out_f:
                                    out_f.write(img_bytes)
                                state["downloaded"][kind] = local_path

                        macro_p = state["downloaded"].pop("depth_macro", "")
                        hgt_main_p = state["downloaded"].get("height", "")
                        alb_main_p = state["downloaded"].get("albedo", "")
                        if hgt_main_p and os.path.exists(hgt_main_p):
                            _enhance_height_map_contrast_and_blend(
                                hgt_main_p,
                                macro_depth_png_path=macro_p,
                                albedo_png_path=alb_main_p,
                            )
                        if macro_p and os.path.exists(macro_p):
                            try:
                                os.remove(macro_p)
                            except Exception:
                                pass

                        if state.get("is_single_leaf"):
                            leaf_src_p = state["downloaded"].pop("leaf_source", "")
                            alb_p = state["downloaded"].get("albedo", "")
                            nrm_p = state["downloaded"].get("normal", "")
                            hgt_p = state["downloaded"].get("height", "")
                            opac_p = os.path.join(temp_dir, f"T_{asset_base_name}_Opacity.png")
                            if _extract_leaf_opacity_and_bleed_edges(leaf_src_p, alb_p, opac_p, nrm_p, hgt_p):
                                state["downloaded"]["opacity"] = opac_p
                            if leaf_src_p and os.path.exists(leaf_src_p):
                                try:
                                    os.remove(leaf_src_p)
                                except Exception:
                                    pass
                        elif str(state.get("mat_category", "")).lower() == "decal":
                            alb_p = state["downloaded"].get("albedo", "")
                            hgt_p = state["downloaded"].get("height", "")
                            opac_p = os.path.join(temp_dir, f"T_{asset_base_name}_Opacity.png")
                            if _extract_decal_opacity_and_bleed_edges(alb_p, opac_p, hgt_p, state.get("prompt_en", "")):
                                state["downloaded"]["opacity"] = opac_p

                        try:
                            _enforce_seamless_pbr_maps(
                                state["downloaded"],
                                is_cutout_or_decal=bool(
                                    state.get("is_single_leaf")
                                    or str(state.get("mat_category", "")).lower() == "decal"
                                ),
                            )
                        except Exception:
                            pass
                        break
                except Exception:
                    pass
                time.sleep(1.0)
        except Exception as e:
            state["error"] = str(e)
        finally:
            state["done"] = True

    threading.Thread(target=_worker, daemon=True).start()

    tick_box = {"handle": None, "last_sec": -1}

    def _on_ref_slate_tick(_delta_time: float):
        if getattr(builtins, "_COMFY_CANCEL_REQUESTED", False):
            if tick_box["handle"] is not None:
                try:
                    unreal.unregister_slate_post_tick_callback(tick_box["handle"])
                except Exception:
                    pass
                tick_box["handle"] = None
            builtins._COMFY_JOB_RUNNING = False
            return

        elapsed = int(time.time() - state["start_time"])
        if not state["done"]:
            if elapsed != tick_box["last_sec"]:
                tick_box["last_sec"] = elapsed
                _set_panel_status(
                    f"[...] Generating PBR from Reference '{state['ref_name']}' ({state['res_px']}x{state['res_px']}, {elapsed}s)...",
                    color=(1.0, 0.82, 0.35, 1.0),
                )
            return

        if tick_box["handle"] is not None:
            try:
                unreal.unregister_slate_post_tick_callback(tick_box["handle"])
            except Exception:
                pass
            tick_box["handle"] = None
        builtins._COMFY_ACTIVE_TICK_HANDLE = None
        builtins._COMFY_JOB_RUNNING = False

        if state["error"] == "__CANCELLED__":
            _set_panel_status("[Cancelled] Reference generation stopped by user.", color=(1.0, 0.55, 0.40, 1.0))
            return
        if state["error"]:
            unreal.log_error(f"ComfyUI Reference PBR Error: {state['error']}")
            _set_panel_status(f"[Error] {state['error']}", color=(1.0, 0.40, 0.40, 1.0))
            return

        try:
            tex_dest_folder = f"{ue_import_path}/{TEXTURES_SUBFOLDER}/{state['mat_category']}"
            mat_dest_folder = f"{ue_import_path}/{state['mat_category']}"
            unreal.EditorAssetLibrary.make_directory(tex_dest_folder)
            unreal.EditorAssetLibrary.make_directory(mat_dest_folder)

            tasks = []
            kind_to_asset_name = {}
            for kind, file_path in state["downloaded"].items():
                t = unreal.AssetImportTask()
                t.filename = file_path
                t.destination_path = tex_dest_folder
                t.replace_existing = True
                t.save = True
                t.automated = True
                tasks.append(t)
                kind_to_asset_name[kind] = os.path.splitext(os.path.basename(file_path))[0]

            if tasks:
                unreal.AssetToolsHelpers.get_asset_tools().import_asset_tools_tasks(tasks) if hasattr(
                    unreal.AssetToolsHelpers.get_asset_tools(), "import_asset_tools_tasks"
                ) else unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)

            tex_map = {}
            for kind, a_name in kind_to_asset_name.items():
                tex_obj = unreal.EditorAssetLibrary.load_asset(f"{tex_dest_folder}/{a_name}")
                if tex_obj:
                    tex_map[kind] = tex_obj
                f_path = state["downloaded"].get(kind)
                if f_path and os.path.exists(f_path):
                    try:
                        os.remove(f_path)
                    except Exception:
                        pass

            mi_name = f"MI_{asset_base_name}"
            mi_asset = _build_pbr_material_instance(
                mat_dest_folder,
                mi_name,
                tex_map,
                master_mat_path=state["selected_mm_path"],
            )

            try:
                mi_clean_path = mi_asset.get_path_name().split(".")[0]
                mi_short_name = mi_clean_path.split("/")[-1]
                mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
                if not isinstance(mi_map, dict):
                    mi_map = {}
                mi_map[mi_short_name] = mi_clean_path
                builtins._COMFY_MI_MAP = mi_map
                la_c = getattr(builtins, "_COMFY_LAYER_A_COMBO", None)
                if la_c:
                    la_c.add_option(mi_short_name)
                    la_c.set_selected_option(mi_short_name)
                for rd in getattr(builtins, "_COMFY_CORONA_LAYER_ROWS", []):
                    rd["mtl_combo"].add_option(mi_short_name)
                _sync_spinboxes_from_mi(mi_asset)
            except Exception:
                pass

            applied_count = apply_material_to_selected_actors(mi_asset)
            try:
                unreal.EditorAssetLibrary.sync_browser_to_objects([mi_asset.get_path_name()])
            except Exception:
                pass

            applied_msg = " and applied to actor!" if applied_count > 0 else ""
            consume_generation_credit(1)
            _set_panel_status(
                f"[OK] Reference PBR Done in {elapsed}s! -> {state['mat_category']}/{mi_name}{applied_msg} (Gens left: {get_remaining_generations()})",
                color=(0.45, 0.92, 0.60, 1.0),
            )
        except Exception as exc:
            unreal.log_error(f"ComfyUI Reference Import Error: {traceback.format_exc()}")
            _set_panel_status(f"[UE Error] {exc}", color=(1.0, 0.40, 0.40, 1.0))

    tick_box["handle"] = unreal.register_slate_post_tick_callback(_on_ref_slate_tick)
    builtins._COMFY_ACTIVE_TICK_HANDLE = tick_box["handle"]


COMFY_EMBEDDED_PYTHON = r"D:\AI\ComfyUI_windows_portable\python_embeded\python.exe"


def _is_single_leaf_cutout_prompt(prompt_raw: str, prompt_en: str = "") -> bool:
    """Returns True if the prompt requests a single isolated leaf / twig with an alpha/opacity cutout mask."""
    combined = f"{prompt_raw or ''} {prompt_en or ''}".lower()
    return any(
        k in combined
        for k in (
            "single isolated",
            "single leaf",
            "(cutout)",
            "alpha cutout",
            "leaf cutout",
            "isolated leaf",
            "один лист",
            "одиночный лист",
        )
    )


def _extract_leaf_opacity_and_bleed_edges(
    source_img_path: str,
    albedo_path: str,
    opacity_out_path: str,
    normal_path: str = "",
    height_path: str = "",
) -> bool:
    """
    Extracts a crisp botanical leaf contour Opacity Mask (T_<Name>_Opacity.png) from the isolated leaf image
    (using exterior border flood-fill + chroma/luma segmentation + fenestration hole detection so interior dark veins
    are 100% preserved while the outer contour and Monstera/fern splits are cleanly cut out), and performs 24px
    iterative morphological color dilation (UV edge padding) on T_<Name>_Albedo.png to prevent black mipmap fringes.
    """
    import subprocess

    py_exe = COMFY_EMBEDDED_PYTHON if os.path.exists(COMFY_EMBEDDED_PYTHON) else "python"
    ref_path = source_img_path if (source_img_path and os.path.exists(source_img_path)) else albedo_path
    if not ref_path or not os.path.exists(ref_path):
        return False

    script = r"""
import sys, os, cv2, numpy as np

ref_p, alb_p, opac_p, nrm_p, hgt_p = sys.argv[1:6]
ref_img = cv2.imread(ref_p, cv2.IMREAD_COLOR)
if ref_img is None:
    sys.exit(1)

h, w = ref_img.shape[:2]
b, g, r = cv2.split(ref_img)
max_c = np.maximum(np.maximum(r, g), b)
min_c = np.minimum(np.minimum(r, g), b)
sat = max_c.astype(np.int16) - min_c.astype(np.int16)

border_pixels = np.concatenate([ref_img[0, :], ref_img[-1, :], ref_img[:, 0], ref_img[:, -1]], axis=0)
bg_med = np.median(border_pixels, axis=0)
diff_bg = np.linalg.norm(ref_img.astype(np.float32) - bg_med.astype(np.float32), axis=2)

# 1. Exterior background flood-fill from all 4 image borders
bg_cand = ((diff_bg < 42.0) & (max_c < 58) & (sat < 35)).astype(np.uint8) * 255
num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bg_cand, connectivity=8)
border_labels = set(np.unique(np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])))
border_labels.discard(0)
ext_bg = np.isin(labels, list(border_labels))

# 2. True deep interior fenestrations / splits (Monstera holes, gaps between fern leaflets or pine needles)
deep_dark = ((diff_bg < 18.0) & (max_c < 24) & (sat < 18)).astype(np.uint8) * 255
n_d, lbl_d, st_d, _ = cv2.connectedComponentsWithStats(deep_dark, connectivity=8)
hole_labels = [i for i in range(1, n_d) if st_d[i, cv2.CC_STAT_AREA] >= 64]
holes_bg = np.isin(lbl_d, hole_labels)

fg_mask = (~(ext_bg | holes_bg)).astype(np.uint8) * 255

# 3. Keep main botanical specimen component(s) and close any tiny interior vein pinholes (< 48px)
n_fg, lbl_fg, st_fg, _ = cv2.connectedComponentsWithStats(fg_mask, connectivity=8)
if n_fg > 1:
    max_area = max(st_fg[i, cv2.CC_STAT_AREA] for i in range(1, n_fg))
    keep_fg = [i for i in range(1, n_fg) if st_fg[i, cv2.CC_STAT_AREA] >= max(64, int(max_area * 0.02))]
    fg_mask = (np.isin(lbl_fg, keep_fg)).astype(np.uint8) * 255

# Close tiny pinholes inside leaf blade while preserving true fenestrations
inv_fg = cv2.bitwise_not(fg_mask)
n_inv, lbl_inv, st_inv, _ = cv2.connectedComponentsWithStats(inv_fg, connectivity=8)
tiny_holes = [i for i in range(1, n_inv) if st_inv[i, cv2.CC_STAT_AREA] < 64]
if tiny_holes:
    fg_mask[np.isin(lbl_inv, tiny_holes)] = 255

# 4. Erode 1px & anti-alias contour to eliminate any dark background fringe along leaf teeth/margins
k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
fg_mask = cv2.erode(fg_mask, k3, iterations=1)
fg_mask = cv2.GaussianBlur(fg_mask, (5, 5), 0)
_, fg_mask_bin = cv2.threshold(fg_mask, 127, 255, cv2.THRESH_BINARY)
cv2.imwrite(opac_p, fg_mask_bin)

# 5. UV Edge Padding (Color Dilation) on Albedo so mipmaps and bilinear filtering have zero dark halo
if alb_p and os.path.exists(alb_p):
    alb_img = cv2.imread(alb_p, cv2.IMREAD_COLOR)
    if alb_img is not None:
        if alb_img.shape[:2] != (h, w):
            fg_for_alb = cv2.resize(fg_mask_bin, (alb_img.shape[1], alb_img.shape[0]), interpolation=cv2.INTER_NEAREST)
        else:
            fg_for_alb = fg_mask_bin
        valid = (fg_for_alb > 127).astype(np.uint8)
        # Erode valid seed by 2px so only pure interior leaf color bleeds outward
        valid_seed = cv2.erode(valid, k3, iterations=2)
        if np.any(valid_seed):
            valid = valid_seed
        dilated = alb_img.copy()
        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        for _ in range(16):
            next_valid = cv2.dilate(valid, k5, iterations=1)
            ring = (next_valid > 0) & (valid == 0)
            if not np.any(ring):
                break
            dil_step = cv2.dilate(dilated, k5, iterations=1)
            dilated[ring] = dil_step[ring]
            valid = next_valid
        # Fill remaining exterior background with median leaf border color
        rem_bg = (valid == 0)
        if np.any(rem_bg) and np.any(fg_for_alb > 127):
            med_leaf = np.median(alb_img[fg_for_alb > 127], axis=0).astype(np.uint8)
            dilated[rem_bg] = med_leaf
        cv2.imwrite(alb_p, dilated)
"""
    try:
        cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        res = subprocess.run(
            [py_exe, "-c", script, ref_path, albedo_path or "", opacity_out_path, normal_path or "", height_path or ""],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=cflags,
        )
        return res.returncode == 0 and os.path.exists(opacity_out_path)
    except Exception as exc:
        unreal.log_warning(f"ComfyUI Leaf Opacity Cutout extraction error: {exc}")
        return False


def _extract_decal_opacity_and_bleed_edges(
    albedo_path: str,
    opacity_out_path: str,
    height_path: str = "",
    prompt_en: str = "",
) -> bool:
    """
    Extracts a clean alpha/opacity mask (`opacity_out_path`, 0=transparent background, 255=opaque decal)
    for ArchViz Decals (cracks, potholes, leaks, stains, puddles, markings) by comparing each pixel's
    color and luminance against the 4-border background median, and bleeds interior decal colors outward
    in `albedo_path` so translucent decal edges never show a white/gray background halo.
    """
    import subprocess

    if not albedo_path or not os.path.exists(albedo_path):
        return False
    py_exe = COMFY_EMBEDDED_PYTHON if os.path.exists(COMFY_EMBEDDED_PYTHON) else "python"
    script = r"""
import sys, os, cv2, numpy as np

alb_p, opac_p, hgt_p = sys.argv[1:4]
alb = cv2.imread(alb_p, cv2.IMREAD_COLOR)
if alb is None:
    sys.exit(1)

H, W = alb.shape[:2]
alb_f = alb.astype(np.float32)

# Sample 4 borders (margin=12px) to estimate background color & luminance
m = max(4, min(16, H // 32))
top = alb_f[:m, :, :].reshape(-1, 3)
bot = alb_f[-m:, :, :].reshape(-1, 3)
lft = alb_f[:, :m, :].reshape(-1, 3)
rgt = alb_f[:, -m:, :].reshape(-1, 3)
border_px = np.concatenate([top, bot, lft, rgt], axis=0)
bg_med = np.median(border_px, axis=0)

diff_rgb = np.linalg.norm(alb_f - bg_med, axis=2)
lum = 0.114 * alb_f[:, :, 0] + 0.587 * alb_f[:, :, 1] + 0.299 * alb_f[:, :, 2]
bg_lum = float(0.114 * bg_med[0] + 0.587 * bg_med[1] + 0.299 * bg_med[2])

# Determine whether decal feature is darker than background (cracks, stains, oil) or brighter (paint markings)
p5, p95 = np.percentile(lum, (5.0, 95.0))
if (bg_lum - p5) >= (p95 - bg_lum):
    lum_diff = np.clip(bg_lum - lum, 0.0, 255.0)
else:
    lum_diff = np.clip(lum - bg_lum, 0.0, 255.0)

score = np.maximum(lum_diff * 1.35, diff_rgb * 0.85)
s_p50, s_p98 = np.percentile(score, (55.0, 98.5))
low_t = max(14.0, s_p50 + (s_p98 - s_p50) * 0.22)
high_t = max(low_t + 12.0, s_p50 + (s_p98 - s_p50) * 0.68)

alpha = np.clip((score - low_t) / max(high_t - low_t, 1.0), 0.0, 1.0)
alpha = alpha * alpha * (3.0 - 2.0 * alpha)

# Smoothly fade outer 6% frame border so decal never clips at box edges
yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
ux = np.minimum(xx / float(W), 1.0 - xx / float(W))
uy = np.minimum(yy / float(H), 1.0 - yy / float(H))
ed = np.minimum(ux, uy)
border_fade = np.clip(ed / 0.06, 0.0, 1.0)
alpha *= border_fade

opac_u8 = np.clip(alpha * 255.0, 0.0, 255.0).astype(np.uint8)
cv2.imwrite(opac_p, opac_u8)

# Bleed interior decal colors outward into transparent background to eliminate white/gray edge halos
fg_mask = (opac_u8 > 64).astype(np.uint8)
if np.any(fg_mask):
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    valid = fg_mask.copy()
    dilated = alb.copy()
    for _ in range(18):
        next_v = cv2.dilate(valid, k5, iterations=1)
        ring = (next_v > 0) & (valid == 0)
        if not np.any(ring):
            break
        step = cv2.erode(dilated, k5, iterations=1) if (bg_lum - p5) >= (p95 - bg_lum) else cv2.dilate(dilated, k5, iterations=1)
        dilated[ring] = step[ring]
        valid = next_v
    rem = (valid == 0)
    if np.any(rem):
        med_fg = np.median(alb[fg_mask > 0], axis=0).astype(np.uint8)
        dilated[rem] = med_fg
    cv2.imwrite(alb_p, dilated)
"""
    try:
        cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        res = subprocess.run(
            [py_exe, "-c", script, albedo_path, opacity_out_path, height_path or ""],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=cflags,
        )
        return res.returncode == 0 and os.path.exists(opacity_out_path)
    except Exception as exc:
        unreal.log_warning(f"ComfyUI Decal Opacity extraction error: {exc}")
        return False


def run_workflow(
    prompt_text: str = "natural oak wood veneer, clean continuous wood grain",
    folder_path: str = DEFAULT_UE_FOLDER,
    json_path: str = DEFAULT_JSON_PATH,
) -> None:
    """
    Неблокирующий запуск генерации бесшовного PBR-материала в ComfyUI из BP_ComfyPanel
    с назначением сгенерированных карт в выбранный Мастер-Материал (через Material Instance).
    """
    panel = _get_open_panel_widget()
    if getattr(builtins, "_COMFY_ENHANCED_WIDGET_ID", None) != id(panel):
        panel = enhance_comfy_panel_ui(panel)

    if panel:
        try:
            if not (prompt_text or "").strip():
                pb = panel.find_child_widget_by_name("PromptInput")
                if pb:
                    prompt_text = str(pb.get_text())
            if not (folder_path or "").strip():
                fb = panel.find_child_widget_by_name("PathInput")
                if fb:
                    folder_path = str(fb.get_text())
        except Exception:
            pass

    if getattr(builtins, "_COMFY_JOB_RUNNING", False):
        _set_panel_status(
            "[...] PBR generation is already running in ComfyUI, please wait...",
            "WAIT...",
            color=(1.0, 0.80, 0.35, 1.0),
        )
        return

    if not _check_can_generate_or_prompt_buy(1):
        return

    ue_import_path = _normalize_ue_folder(folder_path)
    if ue_import_path.split("/")[-1].lower() in [c.lower() for c in MATERIAL_CATEGORIES] or ue_import_path.split("/")[-1] in (TEXTURES_SUBFOLDER, MASKS_SUBFOLDER):
        ue_import_path = "/".join(ue_import_path.split("/")[:-1]) or DEFAULT_UE_FOLDER
    _ensure_folder_structure(ue_import_path)
    if getattr(builtins, "_COMFY_ACTIVE_PRESET_CAT", "") == "bw_mask":
        bw_txts = {t_txt.strip().lower() for _t_lbl, t_txt in CATEGORY_PRESET_PROMPTS.get("bw_mask", []) if not _t_lbl.lower().startswith("decal")}
        if (prompt_text or "").strip().lower() in bw_txts:
            return run_mask_workflow(prompt_text=prompt_text, folder_path=folder_path, json_path=json_path)
    selected_mm_path = _get_selected_prompt_master_material_path(ue_import_path)
    res_px, res_tag = _get_selected_resolution()
    model_label, pipeline_mode, ckpt_name = _get_selected_pbr_model()
    prompt_en = _translate_or_clean_prompt(prompt_text)
    is_single_leaf = _is_single_leaf_cutout_prompt(prompt_text, prompt_en)
    mm_low = selected_mm_path.lower()
    if is_single_leaf:
        mat_category = "Foliage"
        selected_mm_path = f"{DEFAULT_UE_FOLDER}/MM_ArchViz_Foliage"
    elif "decal" in mm_low:
        mat_category = "Decal"
    elif "glass" in mm_low:
        mat_category = "Glass"
    elif "foliage" in mm_low:
        mat_category = "Foliage"
    elif "fabric" in mm_low:
        mat_category = "Fabric"
    elif "emissive" in mm_low:
        mat_category = "Light"
    else:
        mat_category = _detect_material_category(prompt_text, prompt_en)
    builtins._COMFY_PROMPT_MASTER_MAT_PATH = selected_mm_path
    builtins._COMFY_MASTER_MAT_PATH = selected_mm_path
    mm_short_n = selected_mm_path.split("/")[-1]
    builtins._COMFY_SYNCING_UI = True
    try:
        p_mm_c = getattr(builtins, "_COMFY_PROMPT_MM_COMBO", None)
        if p_mm_c:
            p_mm_c.add_option(mm_short_n)
            p_mm_c.set_selected_option(mm_short_n)
        mm_c = getattr(builtins, "_COMFY_MASTER_COMBO", None)
        if mm_c:
            mm_c.add_option(mm_short_n)
            mm_c.set_selected_option(mm_short_n)
    except Exception:
        pass
    finally:
        builtins._COMFY_SYNCING_UI = False
    slug = _make_slug(prompt_en)
    seed_val = _get_selected_seed()
    asset_base_name = f"{slug}_{res_tag}_S{seed_val % 100000}"

    if not os.path.exists(json_path):
        msg = f"[Error] Workflow file not found: {json_path}"
        unreal.log_error(msg)
        _set_panel_status(msg, "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        # Set selected base Text-to-Image checkpoint (RealVisXL V5.0 or SDXL Base 1.0)
        if "71" in workflow and "inputs" in workflow["71"]:
            workflow["71"]["inputs"]["ckpt_name"] = ckpt_name

        if is_single_leaf:
            # Disable circular edge tiling so the single leaf stays centered inside the frame with clean borders
            if "101" in workflow and "inputs" in workflow["101"]:
                workflow["101"]["inputs"]["tiling"] = "disable"
            if "75" in workflow and "inputs" in workflow["75"]:
                workflow["75"]["inputs"]["tiling"] = "disable"
            full_positive = (
                f"Top-down orthographic flat-lay botanical macro scan of a {prompt_en}, "
                "centered single isolated botanical specimen filling 80 percent of frame, "
                "completely isolated on a uniform solid pure pitch-black background (#000000), "
                "razor-sharp leaf margin edges, crisp organic leaf venation, flat even studio lighting, "
                "no cast shadows, 8k photorealistic PBR botanical asset"
            )
            full_negative = (
                "overlapping leaves, multiple leaves, background clutter, soil, ground, branches in background, "
                "white background, grey background, textured background, vignette, drop shadow, cast shadow, "
                "perspective, angled view, 3d render, blurry edges, border touching frame, watermark, text"
            )
        elif mat_category.lower() == "decal":
            if "101" in workflow and "inputs" in workflow["101"]:
                workflow["101"]["inputs"]["tiling"] = "disable"
            if "75" in workflow and "inputs" in workflow["75"]:
                workflow["75"]["inputs"]["tiling"] = "disable"
            full_positive = (
                f"Top-down orthographic flat decal scan of {prompt_en}, "
                "centered isolated decal feature surrounded by a clean uniform flat neutral background, "
                "high contrast between decal detail and flat background, flat even studio lighting, "
                "no cast shadows, 8k photorealistic PBR decal asset"
            )
            full_negative = (
                "brick pattern, tiled grid, background clutter, vignette, drop shadow, cast shadow, "
                "perspective, angled view, 3d render, border touching frame, watermark, text"
            )
        elif mat_category.lower() in ("tile", "brick") or any(
            k in prompt_en.lower()
            for k in (
                "slab", "rings", "cross-section", "cross-cut", "end-grain", "stump",
                "plywood edge", "veneer plies", "multi-layer", "butcher block", "paving blocks",
                "osb", "chipboard", "pegboard", "glulam", "clt", "shou sugi ban", "charred",
                "barnwood", "bark", "parquet", "herringbone", "chevron",
                "soil", "mulch", "loam", "humus", "woodchip", "litter", "peat",
            )
        ):
            full_positive = (
                f"Top-down orthographic macro texture scan of {prompt_en}, "
                "uniform repeating micro-scale pattern, consistent element size and even luminosity across entire frame, "
                "flat even diffused studio lighting, no shadows, photorealistic 8k PBR material, sharp micro-details"
            )
            full_negative = (
                "large blotches, macro spots, uneven brightness, dark patches, bright patches, central motif, focal point, "
                "perspective, angled view, 3d render, harsh shadows, directional lighting, "
                "specular highlights, vignette, depth of field, blurry, low quality, visible border, watermark, text"
            )
        else:
            full_positive = (
                f"Top-down orthographic macro texture scan of a continuous flat sheet of {prompt_en}, "
                "single uninterrupted homogeneous surface, uniform fine-grained micro-scale texture, "
                "consistent brightness and color across entire frame, no tiles, no seams, flat even diffused studio lighting, "
                "no shadows, photorealistic 8k PBR material, sharp micro-details"
            )
            full_negative = (
                "large blotches, giant pattern, macro spots, uneven lighting, dark patches, bright patches, central motif, focal point, "
                "tiles, tiled wall, brick pattern, grid, panels, joints, grout lines, bevels, cracks, slits, "
                "perspective, angled view, 3d render, harsh shadows, directional lighting, "
                "specular highlights, vignette, depth of field, blurry, low quality, seam, visible border, watermark, text"
            )

        if "72" in workflow and "inputs" in workflow["72"]:
            workflow["72"]["inputs"]["text"] = full_positive
        if "73" in workflow and "inputs" in workflow["73"]:
            workflow["73"]["inputs"]["text"] = full_negative

        # SDXL and Ubisoft CHORD both work natively at 1024x1024 (CHORD internally resizes any input to 1024),
        # so we always generate at 1024 and only downscale the final maps for 512 (faster & sharper than a 512 latent).
        base_latent_res = 1024
        if "77" in workflow and "inputs" in workflow["77"]:
            workflow["77"]["inputs"]["width"] = base_latent_res
            workflow["77"]["inputs"]["height"] = base_latent_res

        if pipeline_mode == "chord":
            # Ubisoft CHORD PBR Decomposition Pipeline (ChordLoadModel -> ChordMaterialEstimation -> ChordNormalToHeight)
            for old_id in ("78", "79", "81", "83", "84", "108", "109"):
                workflow.pop(old_id, None)

            # CHORD natively resizes all 5 outputs (basecolor, normal, roughness, metalness, height)
            # to the resolution (ori_h, ori_w) of its input image while running its internal solver at 1024x1024.
            chord_img_input = ["102", 0]
            if res_px != 1024:
                workflow["90"] = {
                    "class_type": "ImageScale",
                    "inputs": {
                        "upscale_method": "nearest-exact" if res_px > 1024 else "area",
                        "width": res_px,
                        "height": res_px,
                        "crop": "disabled",
                        "image": ["102", 0],
                    },
                }
                chord_img_input = ["90", 0]

            if is_single_leaf:
                workflow["98"] = {
                    "class_type": "SaveImage",
                    "inputs": {
                        "filename_prefix": "api_leaf_source",
                        "images": chord_img_input,
                    },
                }

            workflow["110"] = {
                "class_type": "ChordLoadModel",
                "inputs": {
                    "ckpt_name": "chord_v1.safetensors",
                },
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
                "inputs": {
                    "normal": ["111", 1],
                },
            }
            if "76" in workflow and "inputs" in workflow["76"]:
                workflow["76"]["inputs"]["images"] = ["111", 0]
                workflow["76"]["inputs"]["filename_prefix"] = "api_albedo"
            if "82" in workflow and "inputs" in workflow["82"]:
                workflow["82"]["inputs"]["images"] = ["111", 1]
                workflow["82"]["inputs"]["filename_prefix"] = "api_normal"
            if "85" in workflow and "inputs" in workflow["85"]:
                workflow["85"]["inputs"]["images"] = ["111", 2]
                workflow["85"]["inputs"]["filename_prefix"] = "api_roughness"
            if "80" in workflow and "inputs" in workflow["80"]:
                workflow["80"]["inputs"]["images"] = ["112", 0]
                workflow["80"]["inputs"]["filename_prefix"] = "api_height"
            workflow["86"] = {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "api_metallic",
                    "images": ["111", 3],
                },
            }
            # Run DepthAnything_V2 in parallel to fuse macro displacement with CHORD's micro normal-to-height
            # (Skip extra ViT-L model load for Decals and Single-Leaf cutouts to avoid VRAM thrashing & 500s+ stalls)
            if not is_single_leaf and str(mat_category).lower() != "decal":
                workflow["79"] = {
                    "class_type": "DownloadAndLoadDepthAnythingV2Model",
                    "inputs": {
                        "model": "depth_anything_v2_vitl_fp16.safetensors",
                        "precision": "fp16",
                    },
                }
                workflow["78"] = {
                    "class_type": "DepthAnything_V2",
                    "inputs": {
                        "da_model": ["79", 0],
                        "images": chord_img_input,
                    },
                }
                workflow["87"] = {
                    "class_type": "SaveImage",
                    "inputs": {
                        "filename_prefix": "api_depth_macro",
                        "images": ["78", 0],
                    },
                }
        else:
            # Fast DepthAnything_V2 (fp16) + NormalMapSimple PBR Pipeline
            if "78" in workflow and workflow["78"].get("class_type") == "MarigoldDepthEstimation":
                workflow["79"] = {
                    "class_type": "DownloadAndLoadDepthAnythingV2Model",
                    "inputs": {
                        "model": "depth_anything_v2_vitl_fp16.safetensors",
                        "precision": "fp16",
                    },
                }
                workflow["78"] = {
                    "class_type": "DepthAnything_V2",
                    "inputs": {
                        "da_model": ["79", 0],
                        "images": ["102", 0],
                    },
                }
            if "81" in workflow and workflow["81"].get("class_type") == "NormalMapSimple":
                workflow["81"]["inputs"]["scale_XY"] = 1.5

            if res_px > 1024:
                detail_res = min(res_px, 2048)
                workflow["90"] = {
                    "class_type": "ImageScale",
                    "inputs": {
                        "upscale_method": "bicubic",
                        "width": detail_res,
                        "height": detail_res,
                        "crop": "disabled",
                        "image": ["75", 0],
                    },
                }
                if "102" in workflow and "inputs" in workflow["102"]:
                    workflow["102"]["inputs"]["images"] = ["90", 0]

                if res_px > 2048:
                    for scale_id, save_id in (("91", "76"), ("92", "80"), ("93", "82"), ("94", "85")):
                        if save_id in workflow and "inputs" in workflow[save_id]:
                            orig_img_input = workflow[save_id]["inputs"].get("images")
                            if orig_img_input:
                                workflow[scale_id] = {
                                    "class_type": "ImageScale",
                                    "inputs": {
                                        "upscale_method": "bicubic",
                                        "width": res_px,
                                        "height": res_px,
                                        "crop": "disabled",
                                        "image": orig_img_input,
                                    },
                                }
                                workflow[save_id]["inputs"]["images"] = [scale_id, 0]
            elif res_px < 1024:
                for scale_id, save_id in (("91", "76"), ("92", "80"), ("93", "82"), ("94", "85")):
                    if save_id in workflow and "inputs" in workflow[save_id]:
                        orig_img_input = workflow[save_id]["inputs"].get("images")
                        if orig_img_input:
                            workflow[scale_id] = {
                                "class_type": "ImageScale",
                                "inputs": {
                                    "upscale_method": "area",
                                    "width": res_px,
                                    "height": res_px,
                                    "crop": "disabled",
                                    "image": orig_img_input,
                                },
                            }
                            workflow[save_id]["inputs"]["images"] = [scale_id, 0]

        for node_id, node_data in workflow.items():
            inputs = node_data.get("inputs", {})
            if "seed" in inputs:
                inputs["seed"] = seed_val
    except Exception as exc:
        unreal.log_error(f"ComfyUI PBR: JSON preparation error: {exc}")
        _set_panel_status(f"[JSON Error] {exc}", "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))
        return

    pipe_short = "Ubisoft CHORD" if pipeline_mode == "chord" else "DepthAnything V2"
    state = {
        "done": False,
        "error": None,
        "downloaded": {},
        "start_time": time.time(),
        "prompt_en": prompt_en,
        "ue_import_path": ue_import_path,
        "selected_mm_path": selected_mm_path,
        "asset_base_name": asset_base_name,
        "res_px": res_px,
        "res_tag": res_tag,
        "pipe_short": pipe_short,
        "is_single_leaf": is_single_leaf,
        "mat_category": mat_category,
        "seed_val": seed_val,
    }
    builtins._COMFY_CANCEL_REQUESTED = False
    builtins._COMFY_JOB_RUNNING = True
    _set_panel_status(
        f"[...] Sending {res_px}x{res_px} ({res_tag}) [{pipe_short}, Seed: {seed_val}] job to ComfyUI: '{prompt_en}'...",
        "WAIT...",
        color=(0.55, 0.85, 1.0, 1.0),
    )

    def _worker():
        try:
            req = urllib.request.Request(
                f"{COMFY_URL}/prompt",
                data=json.dumps({"prompt": workflow}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
            prompt_id = res_data["prompt_id"]

            while True:
                if getattr(builtins, "_COMFY_CANCEL_REQUESTED", False):
                    state["error"] = "__CANCELLED__"
                    break
                if time.time() - state["start_time"] > 1800:
                    state["error"] = "ComfyUI generation timed out (1800 sec)"
                    break

                try:
                    with urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}", timeout=5.0) as h_resp:
                        history = json.loads(h_resp.read().decode("utf-8"))
                    if prompt_id in history:
                        entry = history[prompt_id]
                        st_info = entry.get("status", {})
                        if st_info.get("status_str") == "error":
                            state["error"] = f"ComfyUI internal error: {st_info}"
                            break

                        outputs = entry.get("outputs", {})
                        temp_dir = os.path.dirname(json_path)
                        node_to_kind = {
                            "76": "albedo",
                            "80": "height",
                            "82": "normal",
                            "85": "roughness",
                            "86": "metallic",
                            "87": "depth_macro",
                            "91": "albedo",
                            "92": "height",
                            "93": "normal",
                            "94": "roughness",
                            "95": "metallic",
                            "98": "leaf_source",
                        }
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
                                    elif "leaf_source" in low_f:
                                        kind = "leaf_source"
                                    elif "depth_macro" in low_f:
                                        kind = "depth_macro"
                                    else:
                                        kind = "albedo"

                                params = urllib.parse.urlencode(
                                    {
                                        "filename": fname,
                                        "subfolder": image.get("subfolder", ""),
                                        "type": image.get("type", "output"),
                                    }
                                )
                                img_bytes = urllib.request.urlopen(f"{COMFY_URL}/view?{params}", timeout=15.0).read()
                                clean_filename = f"T_{asset_base_name}_{kind.capitalize()}.png"
                                local_path = os.path.join(temp_dir, clean_filename)
                                with open(local_path, "wb") as out_f:
                                    out_f.write(img_bytes)
                                state["downloaded"][kind] = local_path

                        macro_p = state["downloaded"].pop("depth_macro", "")
                        hgt_main_p = state["downloaded"].get("height", "")
                        alb_main_p = state["downloaded"].get("albedo", "")
                        if hgt_main_p and os.path.exists(hgt_main_p):
                            _enhance_height_map_contrast_and_blend(
                                hgt_main_p,
                                macro_depth_png_path=macro_p,
                                albedo_png_path=alb_main_p,
                            )
                        if macro_p and os.path.exists(macro_p):
                            try:
                                os.remove(macro_p)
                            except Exception:
                                pass

                        if state.get("is_single_leaf"):
                            leaf_src_p = state["downloaded"].pop("leaf_source", "")
                            alb_p = state["downloaded"].get("albedo", "")
                            nrm_p = state["downloaded"].get("normal", "")
                            hgt_p = state["downloaded"].get("height", "")
                            opac_p = os.path.join(temp_dir, f"T_{asset_base_name}_Opacity.png")
                            if _extract_leaf_opacity_and_bleed_edges(leaf_src_p, alb_p, opac_p, nrm_p, hgt_p):
                                state["downloaded"]["opacity"] = opac_p
                            if leaf_src_p and os.path.exists(leaf_src_p):
                                try:
                                    os.remove(leaf_src_p)
                                except Exception:
                                    pass
                        elif str(state.get("mat_category", "")).lower() == "decal":
                            alb_p = state["downloaded"].get("albedo", "")
                            hgt_p = state["downloaded"].get("height", "")
                            opac_p = os.path.join(temp_dir, f"T_{asset_base_name}_Opacity.png")
                            if _extract_decal_opacity_and_bleed_edges(alb_p, opac_p, hgt_p, state.get("prompt_en", "")):
                                state["downloaded"]["opacity"] = opac_p
                        try:
                            _enforce_seamless_pbr_maps(
                                state["downloaded"],
                                is_cutout_or_decal=bool(
                                    state.get("is_single_leaf")
                                    or str(state.get("mat_category", "")).lower() == "decal"
                                ),
                            )
                        except Exception:
                            pass
                        try:
                            free_req = urllib.request.Request(
                                f"{COMFY_URL}/free",
                                data=b'{"unload_models": false, "free_memory": true}',
                                headers={"Content-Type": "application/json"},
                                method="POST",
                            )
                            urllib.request.urlopen(free_req, timeout=3.0).read()
                        except Exception:
                            pass
                        break
                except Exception:
                    pass
                time.sleep(1.0)
        except Exception as e:
            state["error"] = str(e)
        finally:
            state["done"] = True

    threading.Thread(target=_worker, daemon=True).start()

    tick_box = {"handle": None, "last_sec": -1}

    def _on_slate_tick(_delta_time: float):
        if getattr(builtins, "_COMFY_CANCEL_REQUESTED", False):
            if tick_box["handle"] is not None:
                try:
                    unreal.unregister_slate_post_tick_callback(tick_box["handle"])
                except Exception:
                    pass
                tick_box["handle"] = None
            builtins._COMFY_JOB_RUNNING = False
            return

        elapsed = int(time.time() - state["start_time"])
        if not state["done"]:
            if elapsed != tick_box["last_sec"]:
                tick_box["last_sec"] = elapsed
                _set_panel_status(
                    f"[...] Generating {state['res_px']}x{state['res_px']} ({state['res_tag']}) PBR in ComfyUI: '{prompt_en[:42]}' ({elapsed}s)...",
                    f"WAIT ({elapsed}s)",
                    color=(1.0, 0.82, 0.35, 1.0),
                )
            return

        if tick_box["handle"] is not None:
            try:
                unreal.unregister_slate_post_tick_callback(tick_box["handle"])
            except Exception:
                pass
            tick_box["handle"] = None
        builtins._COMFY_ACTIVE_TICK_HANDLE = None

        builtins._COMFY_JOB_RUNNING = False

        if state["error"] == "__CANCELLED__":
            _set_panel_status("[Cancelled] Generation stopped by user.", "GENERATE PBR", color=(1.0, 0.55, 0.40, 1.0))
            return
        if state["error"]:
            unreal.log_error(f"ComfyUI PBR Error: {state['error']}")
            _set_panel_status(f"[Error] {state['error']}", "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))
            return

        try:
            _set_panel_status(
                f"[...] Importing PBR maps into {TEXTURES_SUBFOLDER}/{mat_category}/ and building Material Instance...",
                "IMPORTING...",
                color=(0.55, 0.85, 1.0, 1.0),
            )
            tex_dest_folder = f"{ue_import_path}/{TEXTURES_SUBFOLDER}/{mat_category}"
            mat_dest_folder = f"{ue_import_path}/{mat_category}"
            unreal.EditorAssetLibrary.make_directory(tex_dest_folder)
            unreal.EditorAssetLibrary.make_directory(mat_dest_folder)

            tasks = []
            kind_to_asset_name = {}
            for kind, file_path in state["downloaded"].items():
                t = unreal.AssetImportTask()
                t.filename = file_path
                t.destination_path = tex_dest_folder
                t.replace_existing = True
                t.save = True
                t.automated = True
                tasks.append(t)
                kind_to_asset_name[kind] = os.path.splitext(os.path.basename(file_path))[0]

            if tasks:
                unreal.AssetToolsHelpers.get_asset_tools().import_asset_tools_tasks(tasks) if hasattr(
                    unreal.AssetToolsHelpers.get_asset_tools(), "import_asset_tools_tasks"
                ) else unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)

            tex_map = {}
            for kind, a_name in kind_to_asset_name.items():
                tex_obj = unreal.EditorAssetLibrary.load_asset(f"{tex_dest_folder}/{a_name}")
                if tex_obj:
                    tex_map[kind] = tex_obj
                f_path = state["downloaded"].get(kind)
                if f_path and os.path.exists(f_path):
                    try:
                        os.remove(f_path)
                    except Exception:
                        pass

            mi_name = f"MI_{asset_base_name}"
            mi_asset = _build_pbr_material_instance(
                mat_dest_folder,
                mi_name,
                tex_map,
                master_mat_path=state["selected_mm_path"],
            )

            try:
                mi_clean_path = mi_asset.get_path_name().split(".")[0]
                mi_short_name = mi_clean_path.split("/")[-1]
                mi_map = getattr(builtins, "_COMFY_MI_MAP", {})
                if not isinstance(mi_map, dict):
                    mi_map = {}
                mi_map[mi_short_name] = mi_clean_path
                builtins._COMFY_MI_MAP = mi_map
                la_c = getattr(builtins, "_COMFY_LAYER_A_COMBO", None)
                lb_c = getattr(builtins, "_COMFY_LAYER_B_COMBO", None)
                if la_c:
                    la_c.add_option(mi_short_name)
                    la_c.set_selected_option(mi_short_name)
                if lb_c:
                    lb_c.add_option(mi_short_name)
                _sync_spinboxes_from_mi(mi_asset)
            except Exception:
                pass

            applied_count = apply_material_to_selected_actors(mi_asset)

            try:
                unreal.EditorAssetLibrary.sync_browser_to_objects([mi_asset.get_path_name()])
            except Exception:
                pass

            mm_short = state["selected_mm_path"].split("/")[-1]
            applied_msg = " and applied to actor!" if applied_count > 0 else ""
            consume_generation_credit(1)
            _set_panel_status(
                f"[OK] Done in {elapsed}s! Textures -> {TEXTURES_SUBFOLDER}/{mat_category}/, Material -> {mat_category}/{mi_name}{applied_msg} (Gens left: {get_remaining_generations()})",
                "GENERATE PBR",
                color=(0.45, 0.92, 0.60, 1.0),
            )
            unreal.log(f"ComfyUI PBR: Successfully created Material Instance {mi_asset.get_path_name()} from {mm_short}.")
        except Exception as exc:
            unreal.log_error(f"ComfyUI PBR Import/Material Error: {traceback.format_exc()}")
            _set_panel_status(f"[UE Error] {exc}", "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))

    tick_box["handle"] = unreal.register_slate_post_tick_callback(_on_slate_tick)
    builtins._COMFY_ACTIVE_TICK_HANDLE = tick_box["handle"]


def run_mask_workflow(
    prompt_text: str = "grunge dirt splatters and surface scratches",
    folder_path: str = DEFAULT_UE_FOLDER,
    json_path: str = DEFAULT_JSON_PATH,
) -> None:
    """
    Non-blocking generation of a single seamless Black & White (grayscale) mask texture in ComfyUI
    without generating the other PBR maps (skips Height/Normal/Roughness nodes).
    Automatically imports the mask into Textures/ (sRGB=False) and assigns it to BlendMaskTexture.
    """
    panel = _get_open_panel_widget()
    if getattr(builtins, "_COMFY_ENHANCED_WIDGET_ID", None) != id(panel):
        panel = enhance_comfy_panel_ui(panel)

    if panel:
        try:
            if not (prompt_text or "").strip():
                pb = panel.find_child_widget_by_name("PromptInput")
                if pb:
                    prompt_text = str(pb.get_text())
            if not (folder_path or "").strip():
                fb = panel.find_child_widget_by_name("PathInput")
                if fb:
                    folder_path = str(fb.get_text())
        except Exception:
            pass

    if getattr(builtins, "_COMFY_JOB_RUNNING", False):
        _set_panel_status(
            "[...] ComfyUI generation is already running, please wait...",
            "WAIT...",
            color=(1.0, 0.80, 0.35, 1.0),
        )
        return

    if not _check_can_generate_or_prompt_buy(1):
        return

    ue_import_path = _normalize_ue_folder(folder_path)
    if ue_import_path.split("/")[-1].lower() in [c.lower() for c in MATERIAL_CATEGORIES] or ue_import_path.split("/")[-1] in (TEXTURES_SUBFOLDER, MASKS_SUBFOLDER):
        ue_import_path = "/".join(ue_import_path.split("/")[:-1]) or DEFAULT_UE_FOLDER
    _ensure_folder_structure(ue_import_path)
    res_px, res_tag = _get_selected_resolution()
    prompt_en = _translate_or_clean_prompt(prompt_text)
    slug = _make_slug(prompt_en)
    seed_val = _get_selected_seed()
    mask_asset_name = f"T_Mask_{slug}_{res_tag}_S{seed_val % 100000}"

    if not os.path.exists(json_path):
        msg = f"[Error] Workflow file not found: {json_path}"
        unreal.log_error(msg)
        _set_panel_status(msg, "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        full_positive = (
            f"Top-down orthographic seamless tileable black and white grayscale alpha mask of {prompt_en}, "
            "high contrast monochrome stencil pattern, pure black and white values, flat studio map, 8k substance designer mask"
        )
        full_negative = (
            "color, colorful, rgb, saturation, 3d render, perspective, angled view, directional lighting, "
            "shadows, vignette, depth of field, blurry, watermark, text, border"
        )

        if "72" in workflow and "inputs" in workflow["72"]:
            workflow["72"]["inputs"]["text"] = full_positive
        if "73" in workflow and "inputs" in workflow["73"]:
            workflow["73"]["inputs"]["text"] = full_negative

        base_latent_res = 1024
        if "77" in workflow and "inputs" in workflow["77"]:
            workflow["77"]["inputs"]["width"] = base_latent_res
            workflow["77"]["inputs"]["height"] = base_latent_res

        # Strip out Height, Normal, Roughness, and Preview nodes so ComfyUI only computes the single B&W Mask
        for unused_id in ("78", "79", "80", "81", "82", "84", "85", "108", "109"):
            workflow.pop(unused_id, None)

        # Keep node 83 (grayscale desaturation) from workflow or fallback to ImageToBW
        if "83" not in workflow:
            workflow["83"] = {
                "class_type": "ImageToBW",
                "inputs": {
                    "image": ["102", 0],
                    "channel": "luminance",
                },
            }
        mask_source = ["83", 0]

        if res_px != 1024:
            workflow["90"] = {
                "class_type": "ImageScale",
                "inputs": {
                    "upscale_method": "lanczos" if res_px > 1024 else "area",
                    "width": res_px,
                    "height": res_px,
                    "crop": "disabled",
                    "image": mask_source,
                },
            }
            mask_source = ["90", 0]

        if "76" in workflow and "inputs" in workflow["76"]:
            workflow["76"]["inputs"]["images"] = mask_source
            workflow["76"]["inputs"]["filename_prefix"] = "api_bw_mask"

        for node_id, node_data in workflow.items():
            inputs = node_data.get("inputs", {})
            if "seed" in inputs:
                inputs["seed"] = seed_val
    except Exception as exc:
        unreal.log_error(f"ComfyUI Mask JSON preparation error: {exc}")
        _set_panel_status(f"[JSON Error] {exc}", "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))
        return

    state = {
        "done": False,
        "error": None,
        "local_path": None,
        "start_time": time.time(),
        "prompt_en": prompt_en,
        "ue_import_path": ue_import_path,
        "mask_asset_name": mask_asset_name,
        "res_px": res_px,
        "res_tag": res_tag,
        "seed_val": seed_val,
    }
    builtins._COMFY_CANCEL_REQUESTED = False
    builtins._COMFY_JOB_RUNNING = True
    _set_panel_status(
        f"[...] Sending {res_px}x{res_px} B&W Mask [Seed: {seed_val}] job to ComfyUI: '{prompt_en}'...",
        "WAIT...",
        color=(0.55, 0.85, 1.0, 1.0),
    )

    def _mask_worker():
        try:
            req = urllib.request.Request(
                f"{COMFY_URL}/prompt",
                data=json.dumps({"prompt": workflow}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
            prompt_id = res_data["prompt_id"]

            while True:
                if getattr(builtins, "_COMFY_CANCEL_REQUESTED", False):
                    state["error"] = "__CANCELLED__"
                    break
                if time.time() - state["start_time"] > 1800:
                    state["error"] = "ComfyUI mask generation timed out (1800 sec)"
                    break
                try:
                    with urllib.request.urlopen(f"{COMFY_URL}/history/{prompt_id}", timeout=5.0) as h_resp:
                        history = json.loads(h_resp.read().decode("utf-8"))
                    if prompt_id in history:
                        entry = history[prompt_id]
                        st_info = entry.get("status", {})
                        if st_info.get("status_str") == "error":
                            state["error"] = f"ComfyUI internal error: {st_info}"
                            break
                        outputs = entry.get("outputs", {})
                        temp_dir = os.path.dirname(json_path)
                        for _nid, node_out in outputs.items():
                            for image in node_out.get("images", []):
                                fname = image["filename"]
                                params = urllib.parse.urlencode(
                                    {
                                        "filename": fname,
                                        "subfolder": image.get("subfolder", ""),
                                        "type": image.get("type", "output"),
                                    }
                                )
                                img_bytes = urllib.request.urlopen(f"{COMFY_URL}/view?{params}", timeout=15.0).read()
                                local_path = os.path.join(temp_dir, f"{mask_asset_name}.png")
                                with open(local_path, "wb") as out_f:
                                    out_f.write(img_bytes)
                                state["local_path"] = local_path
                                break
                        break
                except Exception:
                    pass
                time.sleep(1.0)
        except Exception as e:
            state["error"] = str(e)
        finally:
            state["done"] = True

    threading.Thread(target=_mask_worker, daemon=True).start()

    tick_box = {"handle": None, "last_sec": -1}

    def _on_mask_tick(_delta_time: float):
        if getattr(builtins, "_COMFY_CANCEL_REQUESTED", False):
            if tick_box["handle"] is not None:
                try:
                    unreal.unregister_slate_post_tick_callback(tick_box["handle"])
                except Exception:
                    pass
                tick_box["handle"] = None
            builtins._COMFY_JOB_RUNNING = False
            return

        elapsed = int(time.time() - state["start_time"])
        if not state["done"]:
            if elapsed != tick_box["last_sec"]:
                tick_box["last_sec"] = elapsed
                _set_panel_status(
                    f"[...] Generating {state['res_px']}x{state['res_px']} B&W Mask in ComfyUI: '{prompt_en[:40]}' ({elapsed}s)...",
                    f"WAIT ({elapsed}s)",
                    color=(1.0, 0.82, 0.35, 1.0),
                )
            return

        if tick_box["handle"] is not None:
            try:
                unreal.unregister_slate_post_tick_callback(tick_box["handle"])
            except Exception:
                pass
            tick_box["handle"] = None
        builtins._COMFY_ACTIVE_TICK_HANDLE = None

        builtins._COMFY_JOB_RUNNING = False

        if state["error"] == "__CANCELLED__":
            _set_panel_status("[Cancelled] Mask generation stopped by user.", "GENERATE PBR", color=(1.0, 0.55, 0.40, 1.0))
            return
        if state["error"] or not state["local_path"]:
            err = state["error"] or "No mask image returned from ComfyUI"
            unreal.log_error(f"ComfyUI B&W Mask Error: {err}")
            _set_panel_status(f"[Error] {err}", "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))
            return

        try:
            tex_dest_folder = f"{ue_import_path}/{MASKS_SUBFOLDER}"
            unreal.EditorAssetLibrary.make_directory(tex_dest_folder)

            t = unreal.AssetImportTask()
            t.filename = state["local_path"]
            t.destination_path = tex_dest_folder
            t.replace_existing = True
            t.save = True
            t.automated = True

            asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
            if hasattr(asset_tools, "import_asset_tools_tasks"):
                asset_tools.import_asset_tools_tasks([t])
            else:
                asset_tools.import_asset_tasks([t])

            try:
                os.remove(state["local_path"])
            except Exception:
                pass

            mask_ue_path = f"{tex_dest_folder}/{mask_asset_name}"
            mask_tex = unreal.EditorAssetLibrary.load_asset(mask_ue_path)
            if mask_tex:
                mask_tex.set_editor_property("srgb", False)
                unreal.EditorAssetLibrary.save_loaded_asset(mask_tex)

                mk_map = getattr(builtins, "_COMFY_MASK_MAP", {})
                if not isinstance(mk_map, dict):
                    mk_map = {}
                mk_map[mask_asset_name] = mask_ue_path
                builtins._COMFY_MASK_MAP = mk_map
                mk_combo = getattr(builtins, "_COMFY_MASK_COMBO", None)
                if mk_combo:
                    mk_combo.add_option(mask_asset_name)
                    mk_combo.set_selected_option(mask_asset_name)

                target_mi = _get_active_layer_a_mi(ue_import_path)
                if target_mi:
                    mel = unreal.MaterialEditingLibrary
                    mel.set_material_instance_texture_parameter_value(
                        target_mi,
                        "BlendMaskTexture",
                        mask_tex,
                        unreal.MaterialParameterAssociation.GLOBAL_PARAMETER,
                    )
                    mel.update_material_instance(target_mi)
                    unreal.EditorAssetLibrary.save_loaded_asset(target_mi)

                try:
                    unreal.EditorAssetLibrary.sync_browser_to_objects([mask_ue_path])
                except Exception:
                    pass

            consume_generation_credit(1)
            _set_panel_status(
                f"[OK] B&W Mask ready in {elapsed}s -> {MASKS_SUBFOLDER}/{mask_asset_name} (Gens left: {get_remaining_generations()})!",
                "GENERATE PBR",
                color=(0.45, 0.92, 0.60, 1.0),
            )
        except Exception as exc:
            unreal.log_error(f"ComfyUI Mask Import Error: {traceback.format_exc()}")
            _set_panel_status(f"[UE Error] {exc}", "GENERATE PBR", color=(1.0, 0.40, 0.40, 1.0))

    tick_box["handle"] = unreal.register_slate_post_tick_callback(_on_mask_tick)
    builtins._COMFY_ACTIVE_TICK_HANDLE = tick_box["handle"]


def register_comfy_toolbar_button() -> None:
    """Регистрирует кнопку 'ComfyUI PBR' на верхней панели инструментов Unreal Editor."""
    try:
        script_dir_norm = _SCRIPT_DIR.replace("\\", "/")
        menus = unreal.ToolMenus.get()
        toolbar = menus.extend_menu("LevelEditor.LevelEditorToolBar.User")
        comfy_entry = unreal.ToolMenuEntry(
            name="AIComfyPBRPanelOpen",
            type=unreal.MultiBlockType.TOOL_BAR_BUTTON,
        )
        comfy_entry.set_label("ComfyUI PBR")
        comfy_entry.set_tool_tip("Открыть студию генерации PBR-материалов и Substance-швов ComfyUI (BP_ComfyPanel)")
        comfy_entry.set_string_command(
            type=unreal.ToolMenuStringCommandType.PYTHON,
            custom_type="",
            string=(
                f"import sys, importlib; "
                f"sys.path.append('{script_dir_norm}') if '{script_dir_norm}' not in sys.path else None; "
                f"import comfy_to_ue; importlib.reload(comfy_to_ue); comfy_to_ue.enhance_comfy_panel_ui()"
            ),
        )
        toolbar.add_menu_entry("AI_Assistant", comfy_entry)
        menus.refresh_all_widgets()
    except Exception as exc:
        unreal.log_warning(f"ComfyUI PBR: не удалось добавить кнопку на панель: {exc}")


def register_auto_enhance_watcher() -> None:
    """
    Автоматически отслеживает открытие или восстановление вкладки BP_ComfyPanel при старте Unreal Editor
    и мгновенно строит полный интерфейс студии (прокрутка, CHORD, 289 пресетов, Substance Seams и маски).
    """
    old_h = getattr(builtins, "_COMFY_AUTO_ENHANCE_HANDLE", None)
    if old_h is not None:
        try:
            unreal.unregister_slate_post_tick_callback(old_h)
        except Exception:
            pass
        builtins._COMFY_AUTO_ENHANCE_HANDLE = None

    state = {
        "last_check": 0.0,
        "last_actor_check": 0.0,
        "last_actor_sig": None,
        "last_aim_check": 0.0,
        "mmb_was_down": False,
        "last_aim_sig": None,
    }

    def _on_watch_tick(_dt: float):
        now = time.time()
        # 0. Live Polygon ID Aim Picker via Middle-Mouse-Button (MMB) — OFF by default; only active when explicitly enabled by user
        aim_cb_widget = getattr(builtins, "_COMFY_POLY_AIM_CHECK", None)
        aim_poly_on = bool(getattr(builtins, "_COMFY_POLY_AIM_ACTIVE", False))
        if aim_cb_widget is not None:
            try:
                aim_poly_on = aim_poly_on and bool(aim_cb_widget.is_checked())
            except Exception:
                pass
        if (
            aim_poly_on
            and not getattr(builtins, "_COMFY_JOB_RUNNING", False)
            and now >= getattr(builtins, "_COMFY_UI_INIT_UNTIL", 0.0)
        ):
            try:
                import ctypes
                u32 = ctypes.windll.user32
                mmb_down = bool(u32.GetAsyncKeyState(0x04) & 0x8000)
                nav_mod_down = bool(
                    (u32.GetAsyncKeyState(0x01) & 0x8000)
                    or (u32.GetAsyncKeyState(0x02) & 0x8000)
                    or (u32.GetAsyncKeyState(0x12) & 0x8000)
                )
            except Exception:
                mmb_down = False
                nav_mod_down = False

            if mmb_down and not nav_mod_down and not state["mmb_was_down"]:
                state["mmb_was_down"] = True
                try:
                    assign_poly_id_to_aimed_face(DEFAULT_UE_FOLDER)
                except Exception:
                    pass
            elif not mmb_down:
                state["mmb_was_down"] = False

            if aim_poly_on and now - state["last_aim_check"] >= 0.14:
                state["last_aim_check"] = now
                try:
                    pick = _pick_polygon_under_camera_ray()
                    if pick and pick.get("selected_pids"):
                        _draw_polygon_selection_outline(
                            pick["comp"],
                            pick["topo"],
                            pick["selected_pids"],
                            color=(0.0, 0.95, 1.0, 1.0),
                            duration=0.18,
                            thickness=2.2,
                        )
                        cur_gid_aim = int(pick.get("cur_gid", 0))
                        builtins._COMFY_AIMED_SLOT_ID = cur_gid_aim
                        target_slot = _get_selected_poly_target_id(default_for_assign=1)
                        act_lbl = pick["actor"].get_actor_label() if pick.get("actor") else "Mesh"
                        aim_sig = (act_lbl, cur_gid_aim, target_slot, len(pick["selected_pids"]), pick["mode_key"])
                        if aim_sig != state["last_aim_sig"]:
                            state["last_aim_sig"] = aim_sig
                            try:
                                sync_fn_aim = getattr(builtins, "_COMFY_SYNC_PANEL_FROM_ACTOR_FN", None)
                                comp_aim = pick.get("comp")
                                if sync_fn_aim and comp_aim and cur_gid_aim < comp_aim.get_num_materials():
                                    m_aim = comp_aim.get_material(cur_gid_aim)
                                    if isinstance(m_aim, unreal.MaterialInstanceConstant):
                                        sync_fn_aim(m_aim, actor_label=f"{act_lbl} [Cyan Face ID {cur_gid_aim}]")
                            except Exception:
                                pass
                            _set_panel_status(
                                f"[Aim Pick] '{act_lbl}' | Cyan Face ID: {cur_gid_aim} -> Target ID: {target_slot} ({len(pick['selected_pids'])} polys) [Press MMB]",
                                color=(0.35, 0.98, 0.88, 1.0),
                            )
                except Exception:
                    pass

        # 1. Fast Actor Selection Watcher (every 0.25s) — auto-detects active slot's Material & populates Base + Layer 1..10
        if now - state["last_actor_check"] >= 0.25:
            state["last_actor_check"] = now
            try:
                sync_fn = getattr(builtins, "_COMFY_SYNC_PANEL_FROM_ACTOR_FN", None)
                if sync_fn and not getattr(builtins, "_COMFY_JOB_RUNNING", False):
                    actor_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                    sel_actors = actor_sub.get_selected_level_actors() if actor_sub else []
                    if aim_poly_on and getattr(builtins, "_COMFY_AIMED_SLOT_ID", None) is not None:
                        active_slot = int(getattr(builtins, "_COMFY_AIMED_SLOT_ID", 0))
                    else:
                        active_slot = max(0, _get_selected_poly_target_id(default_for_assign=0))
                    picked_actor = None
                    picked_mi = None
                    picked_is_decal = False
                    for act in sel_actors:
                        best_mi = None
                        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
                            n_mats = comp.get_num_materials()
                            if n_mats > 0:
                                check_slot = active_slot if active_slot < n_mats else 0
                                mat_s = comp.get_material(check_slot)
                                if isinstance(mat_s, unreal.MaterialInstanceConstant):
                                    best_mi = mat_s
                                    break
                            for idx in range(n_mats):
                                mat_i = comp.get_material(idx)
                                if isinstance(mat_i, unreal.MaterialInstanceConstant):
                                    best_mi = mat_i
                                    break
                            if best_mi is not None:
                                break
                        if best_mi is None:
                            for d_comp in act.get_components_by_class(unreal.DecalComponent):
                                d_mat = d_comp.get_decal_material()
                                if isinstance(d_mat, unreal.MaterialInstanceConstant):
                                    best_mi = d_mat
                                    picked_is_decal = True
                                    break
                        if best_mi is not None:
                            picked_actor = act
                            picked_mi = best_mi
                            break
                    if picked_actor is not None and picked_mi is not None:
                        sig = (picked_actor.get_path_name(), active_slot, picked_mi.get_path_name())
                        if sig != state["last_actor_sig"]:
                            state["last_actor_sig"] = sig
                            slot_tag = "[Decal]" if picked_is_decal else f"[ID {active_slot}]"
                            sync_fn(picked_mi, actor_label=f"{picked_actor.get_actor_label()} {slot_tag}")
                    elif not sel_actors:
                        state["last_actor_sig"] = None
            except Exception:
                pass

        if now - state["last_check"] < 1.2:
            return
        state["last_check"] = now
        try:
            if not unreal.EditorAssetLibrary.does_asset_exist(PANEL_ASSET_PATH):
                return
            bp = unreal.EditorAssetLibrary.load_asset(PANEL_ASSET_PATH)
            if not bp:
                return
            sub = unreal.get_editor_subsystem(unreal.EditorUtilitySubsystem)
            w = sub.find_utility_widget_from_blueprint(bp)
            if not w:
                return
            btn = w.find_child_widget_by_name("GenerateBtn")
            if not btn:
                return
            # Если новый экземпляр виджета ещё не привязан к Python-обработчикам (или ещё не содержит StudioInnerCanvas / AntiTileSectionHeaderLabel)
            p = btn.get_parent()
            if (
                getattr(builtins, "_COMFY_ENHANCED_WIDGET_ID", None) != id(w)
                or (p is not None and p.get_parent() is None)
                or w.find_child_widget_by_name("AntiTileSectionHeaderLabel") is None
                or w.find_child_widget_by_name("MeshPaintLayersHeaderLabel") is None
                or w.find_child_widget_by_name("MeshPaintThumbImg") is None
                or w.find_child_widget_by_name("Spin_MP_TileX") is None
                or w.find_child_widget_by_name("ResetAllMeshPaintBtn") is None
                or w.find_child_widget_by_name("BuyGenerationsBtn") is None
            ):
                enhance_comfy_panel_ui(w)
            if not getattr(builtins, "_COMFY_DISP_NRM_MM_UPGRADED_V4", False):
                builtins._COMFY_DISP_NRM_MM_UPGRADED_V4 = True
                try:
                    ensure_directional_light_contact_shadows(0.0)
                    mm_obj = unreal.EditorAssetLibrary.load_asset(f"{DEFAULT_UE_FOLDER}/{DEFAULT_MASTER_MAT_NAME}")
                    if mm_obj:
                        create_or_update_master_material(DEFAULT_UE_FOLDER, DEFAULT_MASTER_MAT_NAME)
                except Exception:
                    pass
                try:
                    a_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                    for act in (a_sub.get_all_level_actors() if a_sub else []):
                        for comp in act.get_components_by_class(unreal.StaticMeshComponent):
                            try:
                                ws = comp.get_world_scale()
                                if abs(ws.x) < 1e-3 or abs(ws.y) < 1e-3 or abs(ws.z) < 1e-3:
                                    comp.set_world_scale3d(
                                        unreal.Vector(
                                            ws.x if abs(ws.x) >= 1e-3 else 0.01,
                                            ws.y if abs(ws.y) >= 1e-3 else 0.01,
                                            ws.z if abs(ws.z) >= 1e-3 else 0.01,
                                        )
                                    )
                            except Exception:
                                pass
                            sm = comp.static_mesh
                            if not sm:
                                continue
                            num_sec = max(1, sm.get_num_sections(0))
                            if comp.get_num_materials() > num_sec or len(sm.static_materials) > num_sec:
                                saved_m = [comp.get_material(i) or sm.get_material(i) for i in range(num_sec)]
                                md = sm.get_static_mesh_description(0)
                                if md:
                                    for gi in range(num_sec, len(sm.static_materials) + 2):
                                        pg = unreal.PolygonGroupID(gi)
                                        if md.is_polygon_group_valid(pg) and not list(md.get_polygon_group_polygons(pg)):
                                            try:
                                                md.delete_polygon_group(pg)
                                            except Exception:
                                                pass
                                    _rebuild_static_mesh_with_exact_slots(comp, sm, md, saved_m)
                except Exception:
                    pass
        except Exception:
            pass

    builtins._COMFY_AUTO_ENHANCE_HANDLE = unreal.register_slate_post_tick_callback(_on_watch_tick)


def launch_comfy_studio():
    """Устанавливает BP_ComfyPanel при необходимости, добавляет кнопку на тулбар и открывает окно плагина."""
    _ensure_panel_uasset_in_project()
    register_comfy_toolbar_button()
    register_auto_enhance_watcher()
    return enhance_comfy_panel_ui()


register_auto_enhance_watcher()


