# Copyright (c) 2026 Daniil Sukhnosenko (hurling-shawl22@bravealias.com)
# Auto-loader for Unreal Engine 5 Editor (<Project>/Content/Python/init_unreal.py)

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
    unreal.log("[UE5 Material Studio] Loaded successfully (Author: Daniil Sukhnosenko).")
except Exception as exc:
    unreal.log_warning(f"[UE5 Material Studio] Auto-init warning: {exc}")
