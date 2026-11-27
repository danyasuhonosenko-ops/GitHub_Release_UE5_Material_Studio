-- ============================================================================
-- ComfyUI Corona PBR Studio — Native 3ds Max Rollout & MacroScript (with Unified Credits)
-- Category: "AI ArchViz" (Customize -> Customize User Interface -> Category: AI ArchViz)
-- ============================================================================

global ro_CoronaComfyPBRStudio
global openCoronaComfyPBRDialog
global openCoronaComfyPBRQt
global CoronaComfyPBR_ResolvePluginDir
global CoronaComfyPBR_ResolvePythonExe

fn CoronaComfyPBR_ResolvePluginDir = (
    local sf = try (getSourceFileName()) catch ""
    local baseDir = if sf != undefined and sf != "" then (getFilenamePath sf) else ""
    if baseDir != "" do (
        if doesFileExist (baseDir + "corona_pbr_studio_qt.py") do return baseDir
        if doesFileExist (baseDir + @"AIPBRMaterialStudio\corona_pbr_studio_qt.py") do return (baseDir + @"AIPBRMaterialStudio\")
    )
    local cand1 = (getDir #userScripts) + @"\AIPBRMaterialStudio\"
    if doesFileExist (cand1 + "corona_pbr_studio_qt.py") do return cand1
    local cand2 = (getDir #userStartupScripts) + @"\AIPBRMaterialStudio\"
    if doesFileExist (cand2 + "corona_pbr_studio_qt.py") do return cand2
    cand1
)

fn CoronaComfyPBR_ResolvePythonExe pluginDir = (
    local envPy = try ((systemTools.getEnvVariable "AIPBR_COMFY_PYTHON") as string) catch ""
    if envPy != "" and envPy != "undefined" and doesFileExist envPy do return envPy
    local cleanRoot = trimRight (substituteString pluginDir "/" "\\") "\\"
    local parent1 = pathConfig.removePathLeaf cleanRoot
    local parent2 = pathConfig.removePathLeaf parent1
    local comfyPy = parent2 + @"\ComfyUI_windows_portable\python_embeded\python.exe"
    if doesFileExist comfyPy do return comfyPy
    local maxPy = (getDir #maxroot) + @"Python\python.exe"
    if doesFileExist maxPy do return maxPy
    "python"
)

rollout ro_CoronaComfyPBRStudio "ComfyUI Corona PBR Studio" width:416 height:565
(
    local pluginDir = CoronaComfyPBR_ResolvePluginDir()
    local pyExe = CoronaComfyPBR_ResolvePythonExe pluginDir
    local runJobPy = pluginDir + "run_job.py"
    local jobJsonPath = pluginDir + "current_job.json"
    local cachedBalance = 0
    local cachedCopyId = "PBR-UNKNOWN"

    group "0. AI Generation Credits (Unified Wallet: UE5 & 3ds Max)"
    (
        label lbl_copyId "Copy ID: detecting..." align:#left across:2
        label lbl_credits "Credits: syncing..." align:#right
        button btn_syncCredits "↻ Sync Balance" width:188 height:24 across:2
        button btn_buyCredits "+ Buy Generations (Gumroad)" width:188 height:24
        edittext edt_seedKey "Key:" text:"" width:272 align:#left across:2
        button btn_redeemKey "Activate Key" width:106 height:20 align:#right
    )

    group "1. Text Prompt / Quick Preset (RU / EN)"
    (
        edittext edt_prompt "" text:"oak wood parquet floor, herringbone pattern" width:386 height:22
        dropdownlist ddl_res "Resolution:" items:#("512x512 (Fast)", "1024x1024 (1K)", "2048x2048 (2K)", "4096x4096 (4K)") selection:2 width:186 across:2
        dropdownlist ddl_pipe "Pipeline:" items:#("AI 5-Map PBR Engine", "DepthAnything V2 (Fast)") selection:1 width:186
        button btn_genPrompt "GENERATE CORONA PBR FROM PROMPT (1 Gen)" width:386 height:32
    )

    group "2. Generate Material from Reference Image"
    (
        edittext edt_refPath "" text:"" width:304 across:2
        button btn_browseRef "Browse..." width:74 height:20 align:#right
        dropdownlist ddl_refMode "Reference Mode:" items:#("1. Make Seamless + Redraw (5-Map PBR)", "2. Extract PBR Maps Only (No Denoise)", "3. AI Vision: Photo -> New Texture", "4. 4x Expand Texture (AI Outpaint 2x2)") selection:1 width:386
        spinner spn_denoise "Img2Img Denoise:" range:[0.2, 0.9, 0.52] type:#float scale:0.05 fieldWidth:45 across:2 align:#left
        edittext edt_hint "Hint:" text:"" fieldWidth:132 align:#right
        button btn_genRef "GENERATE CORONA PBR FROM REFERENCE (1 Gen)" width:386 height:32
    )

    group "3. CoronaPhysicalMtl & Assignment"
    (
        checkbox chk_applySel "Assign to Selected Objects" checked:true across:2
        checkbox chk_disp "Enable Displacement" checked:false
        spinner spn_slot "Medit Slot:" range:[1, 24, 1] type:#integer fieldWidth:40 across:3
        spinner spn_uvw "UVW (mm):" range:[100, 10000, 1000] type:#float fieldWidth:55
        spinner spn_bump "Bump:" range:[0.1, 5.0, 1.0] type:#float fieldWidth:40
    )

    button btn_openFullStudio "OPEN FULL STUDIO (289 Presets + AI Room Extractor)" width:392 height:34
    label lbl_status "Ready. Connected to ComfyUI (127.0.0.1:8188)" align:#left

    fn getCreditsMod forceReload:false = (
        local mObj = undefined
        try (
            local pDirPy = substituteString (CoronaComfyPBR_ResolvePluginDir()) "\\" "/"
            if forceReload then (
                python.Execute ("import sys, importlib; d='" + pDirPy + "'; (sys.path.insert(0, d) if d not in sys.path else None); import pbr_credits_ledger; importlib.reload(pbr_credits_ledger)")
            ) else (
                python.Execute ("import sys; d='" + pDirPy + "'; (sys.path.insert(0, d) if d not in sys.path else None)")
            )
            mObj = python.Import "pbr_credits_ledger"
        ) catch ()
        mObj
    )

    fn getResPx = (
        case ddl_res.selection of (
            1: 512
            2: 1024
            3: 2048
            4: 4096
            default: 1024
        )
    )

    fn getSelectedCost = (
        local rPx = getResPx()
        local cost = if rPx >= 4096 then 3 else if rPx >= 2048 then 2 else 1
        local mObj = getCreditsMod forceReload:false
        if mObj != undefined do (
            try (cost = (mObj.ms_get_pbr_cost rPx) as integer) catch ()
        )
        cost
    )

    fn updateCostLabels = (
        local c = getSelectedCost()
        local unitTxt = if c == 1 then "1 Gen" else ((c as string) + " Gens")
        btn_genPrompt.caption = "GENERATE CORONA PBR FROM PROMPT (" + unitTxt + ")"
        btn_genRef.caption = "GENERATE CORONA PBR FROM REFERENCE (" + unitTxt + ")"
    )

    fn refreshCreditsUI syncServer:false forceReload:false = (
        local mObj = getCreditsMod forceReload:forceReload
        if mObj != undefined then (
            try (cachedCopyId = (mObj.ms_get_instance_id()) as string) catch ()
            try (cachedBalance = (mObj.ms_get_balance syncServer) as integer) catch ()
            local tag = if cachedBalance > 10 then "OK" else if cachedBalance > 0 then "LOW" else "0 - TOP UP"
            lbl_copyId.text = "Copy ID: " + cachedCopyId
            lbl_credits.text = "Credits: " + (cachedBalance as string) + " Gens (" + tag + ")"
        ) else (
            lbl_copyId.text = "Copy ID: offline"
            lbl_credits.text = "Credits: Python bridge error"
        )
        updateCostLabels()
    )

    fn getPipeMode = (
        if ddl_pipe.selection == 1 then "chord" else "da2"
    )

    fn getRefModeStr = (
        case ddl_refMode.selection of (
            1: "img2img_seamless"
            2: "chord_direct"
            3: "ai_vision_pbr"
            4: "outpaint_4x"
            default: "img2img_seamless"
        )
    )

    fn escapeJson str = (
        local s = substituteString str "\\" "\\\\"
        s = substituteString s "\"" "\\\""
        s
    )

    fn confirmAndCheckCredits cost jobLabel = (
        refreshCreditsUI syncServer:true forceReload:false
        if cachedBalance < cost do (
            messageBox ("Insufficient AI Generation Credits!\n\nRequired: " + (cost as string) + " Gen(s)\nAvailable: " + (cachedBalance as string) + " Gen(s)\n\nPlease redeem a 12-word seed key or click '+ Buy Generations'.") title:"Insufficient Credits"
            lbl_status.text = "Stopped: insufficient credits (" + (cachedBalance as string) + " < " + (cost as string) + ")."
            return false
        )
        local afterBal = cachedBalance - cost
        local creditWord = if cost == 1 then "Generation" else "Generations"
        local q = "Start generating " + jobLabel + " on ComfyUI Cloud GPU?\n\n" +
            "• Cost: " + (cost as string) + " " + creditWord + "\n" +
            "• Balance after start: " + (afterBal as string) + " Gens\n" +
            "• Automatic refund on ComfyUI generation error.\n\nProceed?"
        if not (queryBox q title:"Confirm AI PBR Generation") do (
            lbl_status.text = "Generation cancelled (no credits deducted)."
            return false
        )
        true
    )

    fn launchPythonRunner createNoWindow:true = (
        local p = dotNetObject "System.Diagnostics.Process"
        p.StartInfo.FileName = pyExe
        p.StartInfo.Arguments = "\"" + runJobPy + "\""
        p.StartInfo.UseShellExecute = false
        p.StartInfo.CreateNoWindow = createNoWindow
        p.Start()
    )

    on ro_CoronaComfyPBRStudio open do (
        refreshCreditsUI syncServer:true forceReload:true
    )

    on ddl_res selected idx do updateCostLabels()

    on btn_syncCredits pressed do (
        refreshCreditsUI syncServer:true forceReload:true
        lbl_status.text = "Balance synced: " + (cachedBalance as string) + " Gens."
    )

    on btn_buyCredits pressed do (
        local mObj = getCreditsMod forceReload:false
        if mObj != undefined do (
            try (mObj.ms_open_buy_url()) catch ()
            lbl_status.text = "Opened store (Copy ID copied: " + cachedCopyId + ")."
        )
    )

    on btn_redeemKey pressed do (
        local mObj = getCreditsMod forceReload:false
        if mObj == undefined then (
            messageBox "Credits ledger module unavailable." title:"Error"
        ) else (
            local res = (mObj.ms_redeem_key edt_seedKey.text) as string
            local parts = filterString res "|"
            if parts.count > 0 and parts[1] == "OK" then (
                edt_seedKey.text = ""
                refreshCreditsUI syncServer:false
                local msg = if parts.count >= 3 then parts[3] else "Key activated!"
                messageBox msg title:"Credits Added"
                lbl_status.text = msg
            ) else (
                local msg = if parts.count >= 3 then parts[3] else res
                messageBox msg title:"Activation Failed"
            )
        )
    )

    on btn_browseRef pressed do (
        local f = getOpenFileName caption:"Select Reference Image (Texture or Interior Photo)" types:"Images (*.png;*.jpg;*.jpeg;*.webp)|*.png;*.jpg;*.jpeg;*.webp|All (*.*)|*.*|"
        if f != undefined do edt_refPath.text = f
    )

    on btn_genPrompt pressed do (
        if edt_prompt.text == "" do (
            messageBox "Please enter a material prompt."
            return()
        )
        local resPx = getResPx()
        local cost = getSelectedCost()
        if not (confirmAndCheckCredits cost ("Prompt PBR (" + (resPx as string) + "px)")) do return()

        lbl_status.text = "Generating PBR in ComfyUI... (CoronaPhysicalMtl will auto-apply)"
        local pipeMode = getPipeMode()
        local applyStr = if chk_applySel.checked then "true" else "false"
        local dispStr = if chk_disp.checked then "true" else "false"
        local j = "{\n"
        j += "  \"type\": \"prompt\",\n"
        j += "  \"prompt\": \"" + (escapeJson edt_prompt.text) + "\",\n"
        j += "  \"res_px\": " + (resPx as string) + ",\n"
        j += "  \"pipeline_mode\": \"" + pipeMode + "\",\n"
        j += "  \"medit_slot\": " + (spn_slot.value as string) + ",\n"
        j += "  \"apply_to_selection\": " + applyStr + ",\n"
        j += "  \"uvw_box_mm\": " + (spn_uvw.value as string) + ",\n"
        j += "  \"bump_strength\": " + (spn_bump.value as string) + ",\n"
        j += "  \"enable_displacement\": " + dispStr + "\n"
        j += "}\n"
        local ioFile = dotNetClass "System.IO.File"
        local utf8 = dotNetClass "System.Text.Encoding"
        ioFile.WriteAllText jobJsonPath j utf8.UTF8
        launchPythonRunner createNoWindow:true
        if spn_slot.value < 24 do spn_slot.value += 1
    )

    on btn_genRef pressed do (
        if edt_refPath.text == "" or not (doesFileExist edt_refPath.text) do (
            messageBox "Please select a valid Reference Image file first."
            return()
        )
        local resPx = getResPx()
        local cost = getSelectedCost()
        if not (confirmAndCheckCredits cost ("Reference PBR (" + (resPx as string) + "px)")) do return()

        lbl_status.text = "Generating PBR from Reference in ComfyUI..."
        local pipeMode = getPipeMode()
        local refMode = getRefModeStr()
        local applyStr = if chk_applySel.checked then "true" else "false"
        local dispStr = if chk_disp.checked then "true" else "false"
        local j = "{\n"
        j += "  \"type\": \"reference\",\n"
        j += "  \"ref_path\": \"" + (escapeJson edt_refPath.text) + "\",\n"
        j += "  \"ref_mode\": \"" + refMode + "\",\n"
        j += "  \"prompt_hint\": \"" + (escapeJson edt_hint.text) + "\",\n"
        j += "  \"denoise\": " + (spn_denoise.value as string) + ",\n"
        j += "  \"res_px\": " + (resPx as string) + ",\n"
        j += "  \"pipeline_mode\": \"" + pipeMode + "\",\n"
        j += "  \"medit_slot\": " + (spn_slot.value as string) + ",\n"
        j += "  \"apply_to_selection\": " + applyStr + ",\n"
        j += "  \"uvw_box_mm\": " + (spn_uvw.value as string) + ",\n"
        j += "  \"bump_strength\": " + (spn_bump.value as string) + ",\n"
        j += "  \"enable_displacement\": " + dispStr + "\n"
        j += "}\n"
        local ioFile = dotNetClass "System.IO.File"
        local utf8 = dotNetClass "System.Text.Encoding"
        ioFile.WriteAllText jobJsonPath j utf8.UTF8
        launchPythonRunner createNoWindow:true
        if spn_slot.value < 24 do spn_slot.value += 1
    )

    on btn_openFullStudio pressed do (
        openCoronaComfyPBRDialog()
    )
)

fn openCoronaComfyPBRQt forceReload:false =
(
    local opened = false
    try (
        local pDirPy = substituteString (CoronaComfyPBR_ResolvePluginDir()) "\\" "/"
        local reloadCode = if forceReload then "import importlib, studio_qt_theme, pbr_credits_ledger, presets_data, comfy_to_corona; importlib.reload(studio_qt_theme); importlib.reload(pbr_credits_ledger); importlib.reload(presets_data); importlib.reload(comfy_to_corona); importlib.reload(corona_pbr_studio_qt); " else ""
        local reloadArg = if forceReload then "True" else "False"
        python.Execute ("import sys; d='" + pDirPy + "'; (sys.path.insert(0, d) if d not in sys.path else None); import corona_pbr_studio_qt; " + reloadCode + "corona_pbr_studio_qt.show_corona_pbr_studio_qt(force_reload=" + reloadArg + ")")
        opened = true
    ) catch (
        opened = false
    )
    opened
)

fn openCoronaComfyPBRDialog forceReload:false =
(
    try(destroyDialog ro_CoronaComfyPBRStudio) catch()
    local qtOk = openCoronaComfyPBRQt forceReload:forceReload
    if not qtOk do (
        createDialog ro_CoronaComfyPBRStudio pos:[180, 120]
    )
)

macroScript ComfyUICoronaPBRStudio
category:"AI ArchViz"
buttonText:"Corona ComfyPBR"
toolTip:"AI PBR Material Studio v2.0.8 — 3ds Max & Corona (435 Presets + Scene Tools + Credits)"
Icon:#("ComfyPBRStudio", 1)
(
    on execute do
    (
        openCoronaComfyPBRDialog()
    )
)
