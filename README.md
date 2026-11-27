## Unreal Engine 5.4 – 5.8, Blender 3.6–5.1+ & 3ds Max Suite (v2.1.1 — GitHub Edition)

> Drop the **`AIPBRMaterialStudio`** folder from your engine version's branch directly into `<YourProject>/Plugins/AIPBRMaterialStudio/` (Universal Zero-C++ Content + Python plugin — works out of the box across UE 5.4–5.8+ without Visual Studio or DLL rebuilds — Cloud AI generations activated via single-use 12-word keys + full offline studio).

| Unreal Engine | GitHub Branch | `Target` | Universal Zero-C++ |
| :--- | :--- | :--- | :--- |
| **UE 5.4** | [`5.4Version`](https://github.com/danyasuhonosenko-ops/GitHub_Release_UE5_Material_Studio/tree/5.4Version) | `UE 5.4+` | Ready (No DLL) |
| **UE 5.5** | [`5.5Version`](https://github.com/danyasuhonosenko-ops/GitHub_Release_UE5_Material_Studio/tree/5.5Version) | `UE 5.5+` | Ready (No DLL) |
| **UE 5.6** | [`5.6Version`](https://github.com/danyasuhonosenko-ops/GitHub_Release_UE5_Material_Studio/tree/5.6Version) | `UE 5.6+` | Ready (No DLL) |
| **UE 5.7 (Default)** | [`main`](https://github.com/danyasuhonosenko-ops/GitHub_Release_UE5_Material_Studio/tree/main) | `UE 5.7+` | Ready (No DLL) |
| **UE 5.8** | [`5.8Version`](https://github.com/danyasuhonosenko-ops/GitHub_Release_UE5_Material_Studio/tree/5.8Version) | `UE 5.8+` | Ready (No DLL) |

**3-Step Install:** Download ZIP for your UE branch -> copy `AIPBRMaterialStudio/` into `<YourProject>/Plugins/` -> open Unreal Engine and click **AI PBR Studio** on the toolbar.

### Blender 3.6 – 5.1+ Add-on (`Blender/`) & Autodesk 3ds Max Companion (`3dsMax/`)
- **Blender 4.2 – 5.1+ (Cycles & EEVEE Extension):** Download `Blender/AIPBRMaterialStudio_Blender_v2.1.1.zip` and drag-and-drop it into Blender (or **Edit -> Preferences -> Get Extensions -> Install from Disk...**).
- **Blender 3.6 – 4.1 (Legacy Add-on):** Install `Blender/AIPBRMaterialStudio_Blender_Legacy_v2.1.1.zip` via **Preferences -> Add-ons -> Install...**. Open **3D Viewport -> Sidebar (`N`) -> AI PBR Studio**.
- **Autodesk 3ds Max 2022–2026 + Corona Renderer:** Download `3dsMax/` and run `INSTALL_3DSMAX_PLUGIN.bat`.
- All 3 DCCs (**UE5 + Blender + 3ds Max**) share the same hardware **Copy ID & Wallet**, include **0-Gen instant Physical Metal Synthesis** (Polished & Brushed metals), automatic **Normal/Height artifact healing**, **Free Local ComfyUI** mode, and **Free Offline `From Maps` PBR Assembler**.

---

# UE5 ArchViz & GameDev PBR Material Studio (Public Beta)

**Author:** Daniil Sukhnosenko (`hurling-shawl22@bravealias.com`)  
**Engine Compatibility:** Unreal Engine 5.4 – 5.8 (Tested on UE 5.7, compatible with UE 5.8)  
**Edition:** Public Beta (In-Engine Material, Seam, Layer, Decal, Mesh Paint & Displacement Studio)

---

## Overview (EN)

**UE5 PBR Material Studio** is an all-in-one Python + Editor Utility Widget studio for **Unreal Engine 5** designed for ArchViz artists, environment artists, and level designers. It eliminates repetitive shader graphs and manual mesh preparation by combining multi-layer Corona-style material blending, procedural tile/brick seams, anti-tiling, 4-channel viewport Mesh Paint, 1-click Deferred Decals, and geometric 3D displacement into a single dockable panel.

> **Note on Cloud AI PBR Generation:**  
> In this public GitHub release, **100% of the in-engine Material & Mesh Studio tools work out of the box** with your existing textures and Material Instances. Cloud AI Texture & Displacement Generation (5-Map PBR Decomposition & Depth Estimation) is powered by our remote GPU cluster.

---

## Get AI Generation Credits (Gumroad)

Need more Cloud AI Generations (`1K PBR = 1 Gen`, `2K PBR = 2 Gens`, `4K PBR = 3 Gens`)? Purchase an activation key pack directly on Gumroad or click **`+ Buy More Generations`** inside the plugin:

- **Storefront (All Packs):** [danyasuhon.gumroad.com](https://danyasuhon.gumroad.com)
- **Trial Pack — 10 Generations (`$2`):** [ai-pbr-10-gens](https://danyasuhon.gumroad.com/l/ai-pbr-10-gens) (`$0.20 / 1K PBR`)
- **Mini Pack — 50 Generations (`$5`):** [ai-pbr-50-gens](https://danyasuhon.gumroad.com/l/ai-pbr-50-gens) (`$0.10 / 1K PBR`)
- **Starter Pack — 100 Generations (`$10`):** [ai-pbr-100-gens](https://danyasuhon.gumroad.com/l/ai-pbr-100-gens) (`$0.10 / 1K PBR`)
- **Pro Pack — 250 Generations (`$20`):** [ai-pbr-250-gens](https://danyasuhon.gumroad.com/l/ai-pbr-250-gens) (`$0.08 / 1K PBR — Save 20%`)
- **Studio Pack — 500 Generations (`$35`):** [ai-pbr-500-gens](https://danyasuhon.gumroad.com/l/ai-pbr-500-gens) (`$0.07 / 1K PBR — Save 30%`)

After purchase, your unique **12-word activation key** is generated automatically and sent directly to your checkout email in a separate message from **AI PBR Studio** within seconds (check Spam/Promotions if not in Inbox; support: [Telegram](https://t.me/+gzRT98zYKOwzZThi), [WhatsApp](https://chat.whatsapp.com/EPoUXQKaCVn0ueNqHQHDlK), or `unwatched-giver57@bravealias.com`), then paste it into **AI PBR Studio → Account**.

### Key Features Available in Public Beta

1. **Master Material Auto-Builder (`MM_ComfyPBR_Master` & `MM_ArchViz_*`)**
   - Automatically constructs and compiles the complete node graph for Opaque PBR, Glass, Fabric, Foliage (Subsurface + Alpha Cutout), Emissive, and Deferred Decals directly via Unreal Python API.
2. **Interactive Polygon ID Raycast & Slot Assignment**
   - Aim at any polygon in the Level Viewport (`MMB` or `Pick Face`) and assign materials to individual faces (`Single Triangle`, `Quad`, `Coplanar Island`, `UV Seam Island`, or `Whole Element`) without leaving Unreal Editor.
3. **4-Layer Corona-Style Material Mixer**
   - Blend up to 4 full PBR material layers (`Layer 1..4`) on top of a Base Material with height-modulated transitions, procedural masks, or viewport brush painting.
4. **Procedural Seams & Tile Generator**
   - Real-time tile/brick grid generator (`Tiles X/Y`, `Row Shift`, `Seam Width H/V`, `3D Seam Bevel Normals`, `Edge Irregularity`, `Waviness`, `Random Tile Luminance & UV Flip/Rotate`, and `Checkerboard / Random Tile Blending`).
5. **Anti-Tiling Studio (Dual-Scale, Macro Variation & Triplanar)**
   - Eliminates texture repetition on large walls, floors, and terrains using dual-scale rotated UV blending, macro luminance variation, 3P world-aligned projection, and 1-click seamless border baking.
6. **4-Channel (`R / G / B / A`) Mesh Paint Brush Studio**
   - Dedicated Texture Color & Vertex Paint workflow for Unreal Engine 5.7+ with per-layer thumbnail previews, independent `Tile X` / `Tile Y` controls, `1:1` quick reset, and `Reset All`.
7. **1-Click Deferred Decal Converter & Viewport Raycast Spawner**
   - Convert any PBR material into an `MM_ArchViz_Decal` instance with auto-luminance edge masking and spawn it directly onto the aimed surface in the viewport.
8. **3D Geometric Subdivision + WPO Displacement & Parallax Occlusion**
   - Subdivides low-poly architectural meshes (`Cube`, `Rectangle`, walls, floors) in-place with MikkTSpace tangents and drives true 3D World Position Offset (`WPO`) or Parallax Occlusion Mapping (`POM`) with micro contact shadows.
9. **Smart Material Preset Library & Batch Pack Exporter**
   - Save and load multi-layer material presets and batch-export material packs to JSON.

---

## Quick Installation, Update & Uninstall (1-Click `.bat`)

### Option A: Automated 1-Click Scripts (Recommended)
1. **Install / Update (`INSTALL_AI_PBR_STUDIO.bat` or `UPDATE_AI_PBR_STUDIO.bat`)**:
   - Double-click **`INSTALL_AI_PBR_STUDIO.bat`** (or **`UPDATE_AI_PBR_STUDIO.bat`**) and select your Unreal Engine 5 project folder (where `.uproject` is located).
   - It automatically downloads the latest release from GitHub, copies `BP_ComfyPanel.uasset` and Python modules into `Content/`, enables `PythonScriptPlugin` and `EditorScriptingUtilities`, and preserves your credit balance.
   - Inside Unreal Engine, you can also click the **`Update`** button at the top-right of the `BP_ComfyPanel` header at any time for instant Over-The-Air (OTA) updates.
2. **Uninstall (`UNINSTALL_AI_PBR_STUDIO.bat`)**:
   - Double-click **`UNINSTALL_AI_PBR_STUDIO.bat`** and select your Unreal Engine 5 project folder to cleanly remove the plugin scripts and UI widget while keeping all materials and textures you already generated in `Content/Textures/ComfyUI`.

### Option B: Manual Installation (2 Steps)
Enable the built-in **Python Editor Script Plugin** and **Editor Scripting Utilities** in Unreal Engine (`Edit -> Plugins -> Scripting`).

### Step 1: Copy the UI Widget Asset
Copy the `Content/AIPBR_Studio_Plugin` folder from this repository into your Unreal Engine project's `Content/` directory so the asset path is:
```text
<YourUEProject>/Content/AIPBR_Studio_Plugin/BP_ComfyPanel.uasset
```

### Step 2: Launch the Studio from Python
Copy `comfy_to_ue.py` (and optionally `init_unreal.py`) into `<YourUEProject>/Content/Python/`, or run the following snippet in Unreal Engine's **Output Log -> Python** console:

```python
import sys, importlib
sys.path.append(r"path/to/GitHub_Release_UE5_Material_Studio")
import comfy_to_ue
importlib.reload(comfy_to_ue)
comfy_to_ue.launch_comfy_studio()
```

---

## Описание на русском (RU)

**UE5 PBR Material Studio** — это единая панель инструментов внутри **Unreal Engine 5** для архитектурной визуализации (ArchViz), левел-дизайна и работы с окружением.

В публичной бета-версии на GitHub **полностью открыт весь функционал внутридвижковой студии** (работает с любыми вашими текстурами и материалами без подключения внешних серверов):
- **Автосборка мастер-материалов** (`MM_ComfyPBR_Master`, `MM_ArchViz_Glass`, `Fabric`, `Foliage`, `Emissive`, `Decal`).
- **Назначение материалов по полигонам (`Polygon ID`)** прямо во вьюпорте (`Single`, `Quad`, `Coplanar Face`, `Seam Loop`) без пересборки меша в 3ds Max / Blender.
- **4-слойный микшер материалов в стиле CoronaLayeredMtl** (смешивание по карте высот, процедурным маскам и кисти).
- **Процедурные швы и раскладка плитки/кирпича (Procedural Seams)**: ширина и глубина швов, фаски нормалей, неровность краёв, сдвиг рядов, рандомизация плиток.
- **Anti-Tiling Studio**: устранение тайлинга (Dual-Scale поворот, макро-шум, трипланарная проекция, бесшовное запекание границ).
- **Mesh Paint Studio (`R / G / B / A`)**: рисование четырьмя PBR-слоями по мешу с независимым тайлингом `Tile X / Tile Y` для каждого канала.
- **Генератор декалей (`Spawn Decal at Aim`)** и **3D-дисплейсмент (`Geometric 3D Subdiv + WPO` / `Parallax Only`)** с автоматическим подразделением низкополигональных стен и полов и возвратом исходной сетки (`Remove Disp`).
- **Аддон для Blender 3.6–5.1+ (`Blender/`):** нативный UI в N-панели (`3D Viewport -> N -> AI PBR Studio`) для **Cycles и EEVEE**, единый Copy ID и кошелёк с UE5/3ds Max, бесплатный мгновенный физический синтез полированных и брашированных металлов (`0 Gens`), автолечение диполей карт нормалей/высот, бесплатный сборщик локальных карт `From Maps` и режим локального ComfyUI. Для Blender 4.2–5.1+ установите `Blender/AIPBRMaterialStudio_Blender_v2.1.1.zip`, для 3.6–4.1 — `AIPBRMaterialStudio_Blender_Legacy_v2.1.1.zip`.
- **Компаньон 3ds Max + Corona (`3dsMax/`):** единый баланс и быстрый экспорт в UE5 (`INSTALL_3DSMAX_PLUGIN.bat`).

> **Облачная AI-генерация текстур (5-Map PBR Decomposition Engine):**  
> Функции облачной генерации с нуля и по фото-референсу работают через наш удалённый GPU-кластер.

---

## Author & Community Support (Feedback / Bug Reports)

Created and maintained by **Daniil Sukhnosenko**.  
- **🌍 International Community & Support (WhatsApp):** [Join WhatsApp Community](https://chat.whatsapp.com/EPoUXQKaCVn0ueNqHQHDlK)  
- **🇷🇺 Чат сообщества и техподдержка (Telegram):** [Digital Asset Life Chat](https://t.me/+gzRT98zYKOwzZThi)  
- **Email / LinkedIn:** `hurling-shawl22@bravealias.com`

© 2026 Daniil Sukhnosenko. All rights reserved.
