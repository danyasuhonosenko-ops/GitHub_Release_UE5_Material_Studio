# UE5 ArchViz & GameDev PBR Material Studio (Public Beta)

**Author:** Daniil Sukhnosenko (`hurling-shawl22@bravealias.com`)  
**Engine Compatibility:** Unreal Engine 5.3 – 5.7+ (Tested on UE 5.7)  
**Edition:** Public Beta (In-Engine Material, Seam, Layer, Decal, Mesh Paint & Displacement Studio)

---

## Overview (EN)

**UE5 PBR Material Studio** is an all-in-one Python + Editor Utility Widget studio for **Unreal Engine 5** designed for ArchViz artists, environment artists, and level designers. It eliminates repetitive shader graphs and manual mesh preparation by combining multi-layer Corona-style material blending, Substance-style procedural tile/brick seams, anti-tiling, 4-channel viewport Mesh Paint, 1-click Deferred Decals, and geometric 3D displacement into a single dockable panel.

> **Note on Cloud AI PBR Generation:**  
> In this public GitHub release, **100% of the in-engine Material & Mesh Studio tools work out of the box** with your existing textures and Material Instances. Cloud AI Texture & Displacement Generation (Ubisoft CHORD 5-Map PBR & DepthAnything V2) is currently in **Closed Beta** — reach out to **Daniil Sukhnosenko on LinkedIn** to request a Beta API Key.

### Key Features Available in Public Beta

1. **Master Material Auto-Builder (`MM_ComfyPBR_Master` & `MM_ArchViz_*`)**
   - Automatically constructs and compiles the complete node graph for Opaque PBR, Glass, Fabric, Foliage (Subsurface + Alpha Cutout), Emissive, and Deferred Decals directly via Unreal Python API.
2. **Interactive Polygon ID Raycast & Slot Assignment**
   - Aim at any polygon in the Level Viewport (`MMB` or `Pick Face`) and assign materials to individual faces (`Single Triangle`, `Quad`, `Coplanar Island`, `UV Seam Island`, or `Whole Element`) without leaving Unreal Editor.
3. **4-Layer Corona-Style Material Mixer**
   - Blend up to 4 full PBR material layers (`Layer 1..4`) on top of a Base Material with height-modulated transitions, procedural masks, or viewport brush painting.
4. **Substance-Style Procedural Seams & Tiles**
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

## Quick Installation (2 Steps)

### Prerequisite
Enable the built-in **Python Editor Script Plugin** and **Editor Scripting Utilities** in Unreal Engine (`Edit -> Plugins -> Scripting`).

### Step 1: Copy the UI Widget Asset
Copy the `Content/ConfyUI_plagin` folder from this repository into your Unreal Engine project's `Content/` directory so the asset path is:
```text
<YourUEProject>/Content/ConfyUI_plagin/BP_ComfyPanel.uasset
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
- **Процедурные швы и раскладка плитки/кирпича (Substance-блок)**: ширина и глубина швов, фаски нормалей, неровность краёв, сдвиг рядов, рандомизация плиток.
- **Anti-Tiling Studio**: устранение тайлинга (Dual-Scale поворот, макро-шум, трипланарная проекция, бесшовное запекание границ).
- **Mesh Paint Studio (`R / G / B / A`)**: рисование четырьмя PBR-слоями по мешу с независимым тайлингом `Tile X / Tile Y` для каждого канала.
- **Генератор декалей (`Spawn Decal at Aim`)** и **3D-дисплейсмент (`Geometric 3D Subdiv + WPO` / `Parallax Only`)** с автоматическим подразделением низкополигональных стен и полов и возвратом исходной сетки (`Remove Disp`).

> **Облачная AI-генерация текстур (Ubisoft CHORD / DepthAnything V2):**  
> Функции облачной генерации с нуля и по фото-референсу находятся в закрытом бета-тесте. Напишите мне в **LinkedIn**, чтобы получить тестовый ключ доступа.

---

## Author & Community Support (Feedback / Bug Reports)

Created and maintained by **Daniil Sukhnosenko**.  
- **🌍 International Community & Support (WhatsApp):** [Join WhatsApp Community](https://chat.whatsapp.com/EPoUXQKaCVn0ueNqHQHDlK)  
- **🇷🇺 Чат сообщества и техподдержка (Telegram):** [Digital Asset Life Chat](https://t.me/+gzRT98zYKOwzZThi)  
- **Email / LinkedIn:** `hurling-shawl22@bravealias.com`

© 2026 Daniil Sukhnosenko. All rights reserved.
