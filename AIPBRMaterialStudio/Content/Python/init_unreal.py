# Copyright 2026 NeuroPlugin Lab (Daniil Sukhnosenko). All Rights Reserved.
# Auto-loader for Unreal Engine 5 Editor (<Plugin>/Content/Python/init_unreal.py)

import os
import sys
import unreal

_THIS_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

try:
    import comfy_to_ue
    comfy_to_ue.register_comfy_toolbar_button()
    comfy_to_ue.register_auto_enhance_watcher()
    unreal.log("[AI PBR Material Studio] Loaded v2.1.1 (GitHub Edition - Universal).")
except Exception as exc:
    unreal.log_warning(f"[AI PBR Material Studio] Auto-init warning: {exc}")
