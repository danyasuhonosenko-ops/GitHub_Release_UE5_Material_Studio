-- ============================================================================
-- Corona -> UE5 Clean Scene & Asset Exporter (with Scene Material Audit, Credits & Live Sync)
-- Exports FBX + corona_to_ue_manifest.json (Materials, Objects, CoronaLight, CoronaSun, CoronaCam)
-- Identifies all objects & materials, calculates required AI Generations (0.5/mat + 0.5/LayerB),
-- syncs with the unified UE5 & Corona ComfyPBR wallet, and supports Full/Selected export.
-- ============================================================================

global CoronaToUE5ExporterRollout
global CoronaToUE5LiveCallback
global CoronaToUE5_SilentLoad

global CoronaToUE5_ResolveSelfFile
fn CoronaToUE5_ResolveSelfFile = (
    local sf = try (getSourceFileName()) catch ""
    if sf != undefined and sf != "" and doesFileExist sf do return sf
    local cand1 = (getDir #userScripts) + @"\AIPBRMaterialStudio\Corona_to_UE5_Exporter.ms"
    if doesFileExist cand1 do return cand1
    local cand2 = (getDir #userStartupScripts) + @"\AIPBRMaterialStudio\Corona_to_UE5_Exporter.ms"
    if doesFileExist cand2 do return cand2
    cand1
)

global CoronaToUE5_ResolvePluginDir
fn CoronaToUE5_ResolvePluginDir = (
    local sf = CoronaToUE5_ResolveSelfFile()
    local baseDir = if sf != undefined and sf != "" then (getFilenamePath sf) else ""
    if baseDir != "" do (
        if doesFileExist (baseDir + "corona_ue5_exporter_qt.py") do return baseDir
        if doesFileExist (baseDir + @"Corona_ComfyUI_PBR_Plugin\corona_ue5_exporter_qt.py") do return (baseDir + @"Corona_ComfyUI_PBR_Plugin\")
    )
    local cand1 = (getDir #userScripts) + @"\AIPBRMaterialStudio\"
    if doesFileExist (cand1 + "corona_ue5_exporter_qt.py") do return cand1
    local cand2 = (getDir #userStartupScripts) + @"\AIPBRMaterialStudio\"
    if doesFileExist (cand2 + "corona_ue5_exporter_qt.py") do return cand2
    cand1
)

global CoronaToUE5_DefaultExportDir
fn CoronaToUE5_DefaultExportDir = (
    local sf = CoronaToUE5_ResolveSelfFile()
    local baseDir = if sf != undefined and sf != "" then (getFilenamePath sf) else ""
    if baseDir != "" and doesDirectoryExist (baseDir + "UE5_Export_Package") do return (baseDir + "UE5_Export_Package")
    local docsDir = ((systemTools.getEnvVariable "USERPROFILE") as string) + @"\Documents\UE5_Export_Package"
    docsDir
)

global CoronaToUE5_LoadedFileDate = getFileModDate (CoronaToUE5_ResolveSelfFile())
try(callbacks.removeScripts id:#CoronaToUE5SelCB)catch()
try(destroyDialog CoronaToUE5ExporterRollout)catch()
CoronaToUE5LiveCallback = undefined

fn CoronaToUE5_OnNodeChanged ev nds = (
    if CoronaToUE5ExporterRollout != undefined do (
        if CoronaToUE5ExporterRollout.qtActive then (
            if CoronaToUE5ExporterRollout.optLiveWatchSelected and selection.count > 0 do (
                try (
                    python.Execute "import corona_ue5_exporter_qt; corona_ue5_exporter_qt.on_maxscript_node_changed()"
                ) catch ()
            )
        ) else if CoronaToUE5ExporterRollout.open and CoronaToUE5ExporterRollout.chkLiveWatchSelected.checked and selection.count > 0 do (
            CoronaToUE5ExporterRollout.tmrLiveDebounce.active = false
            CoronaToUE5ExporterRollout.tmrLiveDebounce.active = true
            CoronaToUE5ExporterRollout.lblStatus.text = "Обнаружено изменение выделенного объекта -> ожидание 0.9 сек для авто-реимпорта..."
        )
    )
)

rollout CoronaToUE5ExporterRollout "Corona -> UE5 Clean Exporter, Layer Explorer & Credits" width:560 height:830
(
    group "0. Баланс AI-генераций (единый кошелёк с UE5 и Corona ComfyPBR)"
    (
        label lblCopyId "Copy ID: определение..." align:#left across:2
        label lblCreditsBal "Баланс: синхронизация..." align:#right
        button btnSyncCredits "↻ Обновить баланс" width:258 height:24 across:2
        button btnOpenWalletStudio "🔑 Пополнить / Ввести ключ в ComfyPBR" width:258 height:24
    )

    group "1. Идентификация объектов, материалов, Layer Explorer и расчёт Gens"
    (
        button btnScanAll "🔍 Вся сцена" width:108 height:24 across:4
        button btnScanSel "🎯 Выделенное" width:106 height:24
        button btnScanLayers "🗂 Layer Explorer" width:114 height:24
        dropdownlist ddlScanView "" items:#("По материалам (Смета)", "По объектам (Мат + Слой)", "Layer Explorer (Отметьте слои)") selection:1 width:188
        label lblScanSummary "Объекты, слои и материалы: выполняется сканирование..." align:#left
        label lblCostEstimate "Смета генераций: расчёт..." align:#left
        multiListBox lbxSceneAudit "Спецификация (в Layer Explorer выберите один/несколько слоёв для экспорта; 2x-клик — выделить):" height:7 width:526
    )

    group "2. Диагностика полигонажа, Corona Real-World Map Size и Displacement"
    (
        label lblPolyInfo "Всего в сцене: подсчёт..." align:#left
        button btnDisableDisp "Отключить тяжелый Displacement на мебели" width:526 height:24
        button btnConvertRWMSAll "🔄 Убрать Real-World Size + UVW (Вся сцена)" width:258 height:24 across:2
        button btnConvertRWMSSel "🔄 Убрать RWMS + UVW (Выделенное)" width:258 height:24
        multiListBox lbxPolys "Топ объектов по полигонам (двойной клик — выделить в сцене):" height:4 width:526
        button btnRefreshPolys "Обновить таблицу полигонов" width:258 height:22 across:2
        button btnOpenSummary "Открыть стандартный Summary Info" width:258 height:22
    )

    group "3. Прямой экспорт, выборочный реимпорт и экспорт по слоям в UE5"
    (
        editText edtExportDir "Папка:" text:(CoronaToUE5_DefaultExportDir()) width:526
        checkbox chkBakeProcedural "Авто-запекать CoronaColorCorrect / Mix / Falloff в PNG" checked:true across:2
        checkbox chkExportLightsCams "Экспортировать CoronaSun / Light / Cam (Lumen)" checked:true
        checkbox chkAutoFixNormals "Авто-исправлять вывернутые нормали и Mirror (Proxy ResetXForm)" checked:true
        checkbox chkAutoSendUE5 "Сразу запускать Python-сборку в UE5" checked:true across:2
        checkbox chkLiveWatchSelected "АВТО-РЕИМПОРТ выделенного при изменении" checked:false
        checkbox chkSkipExistingUE5 "Авто-пропуск существующих матов в UE5 (реимпорт при изменении в Max)" checked:true
        button btnReimportSelected "⚡ РЕИМПОРТ ВЫДЕЛЕННОГО (0 Gens)" width:258 height:30 across:2
        button btnExportLayers "🗂 ЭКСПОРТ ВЫБР. СЛОЁВ (0 Gens)" width:258 height:30
        button btnExportUE5 "🚀 ПОЛНЫЙ ЭКСПОРТ ВСЕЙ СЦЕНЫ В UE5 (0 Gens)" width:526 height:32
        progressBar pbExport "Прогресс экспорта" value:0 color:(color 35 185 255) width:526 height:14
        label lblProgressStage "Прогресс: 0% — Ожидание запуска" align:#left
        label lblStatus "Готов к экспорту сцены, слоёв Layer Explorer или выделенного в UE5." align:#left
    )

    timer tmrLiveDebounce "LiveSyncDebounce" interval:900 active:false

    local sortedNodes = #()
    local auditRowType = #()      -- "mat", "obj", or "layer"
    local auditRowNodes = #()     -- node or array of nodes per row in lbxSceneAudit
    local auditRowLayerNames = #() -- layer full path per row when in Layer Explorer view
    local cachedBalance = 0.0
    local cachedCopyId = "PBR-UNKNOWN"
    local lastFullCost = 0.0
    local lastSelCost = 0.0
    local lastLayersCost = 0.0
    local lastScanScope = #all
    local isExportingNow = false

    -- Headless Qt UI backing state (used when qtActive == true without legacy rollout open)
    local qtActive = false
    local optExportDir = CoronaToUE5_DefaultExportDir()
    local optBakeProcedural = true
    local optExportLightsCams = true
    local optAutoFixNormals = true
    local optAutoSendUE5 = true
    local optLiveWatchSelected = false
    local optSkipExistingUE5 = true
    local ue5IndexStatus = "NONE|0|"
    local optScanViewMode = 1
    local optSelectedLayerIndices = #{}
    local auditDisplayItems = #()
    local auditDefaultLayerSel = #{}
    local polyDisplayItems = #()
    local lastPolyInfoText = "Всего полигонов в сцене: подсчёт..."
    local lastScanSummaryText = "Объекты, слои и материалы: выполняется сканирование..."
    local lastCostEstimateText = "Смета генераций: расчёт..."

    fn isValidExportGeom o = (isValidNode o and o.name != "00_Floorplan_Reference" and canConvertTo o Editable_Mesh and not isKindOf o Targetobject and not isKindOf o BoneGeometry)

    fn safeJsonNum v = (
        local f = try (v as float) catch 0.0
        local s = f as string
        local bad = (matchPattern s pattern:"*#*") or (matchPattern s pattern:"*inf*") or (matchPattern s pattern:"*nan*") or (matchPattern s pattern:"*ind*")
        if bad then "0.0" else s
    )

    fn roundHalfGen v = (
        local f = try (v as float) catch 0.0
        if f < 0.0 do f = 0.0
        ((floor (f * 2.0 + 0.5)) / 2.0)
    )

    fn fmtGens v = (
        local f = try (v as float) catch 0.0
        local isNeg = f < 0.0
        local af = abs f
        local r2 = ((floor (af * 100.0 + 0.5)) / 100.0)
        local iv = ((floor (r2 + 0.5)) as integer)
        local outStr = if (abs (r2 - (iv as float))) < 0.005 then (
            iv as string
        ) else (
            local r1 = ((floor (af * 10.0 + 0.5)) / 10.0)
            if (abs (r2 - r1)) < 0.005 then (
                formattedPrint r1 format:".1f"
            ) else (
                formattedPrint r2 format:".2f"
            )
        )
        if isNeg and outStr != "0" then ("-" + outStr) else outStr
    )
    local lastStatusText = "Готов к экспорту сцены, слоёв Layer Explorer или выделенного в UE5."
    local lastProgressPct = 0
    local lastProgressStage = "Ожидание запуска"

    fn getEffScanView = (
        if qtActive then optScanViewMode else ddlScanView.selection
    )

    fn getEffLayerSel = (
        if qtActive then optSelectedLayerIndices else lbxSceneAudit.selection
    )

    fn setStatusText txt = (
        lastStatusText = txt as string
        if CoronaToUE5ExporterRollout.open do lblStatus.text = lastStatusText
    )

    fn notifyQtProgress pct stageText statusText = (
        lastProgressPct = pct
        lastProgressStage = stageText
        if statusText != "" do lastStatusText = statusText
        if qtActive do (
            try (
                python.Execute "import corona_ue5_exporter_qt; corona_ue5_exporter_qt.on_maxscript_progress()"
            ) catch ()
        )
    )

    fn getCreditsMod forceReload:false = (
        local mObj = undefined
        try (
            local pDirPy = substituteString (CoronaToUE5_ResolvePluginDir()) "\\" "/"
            if forceReload then (
                python.Execute ("import sys, importlib; d='" + pDirPy + "'; (sys.path.insert(0, d) if d not in sys.path else None); import pbr_credits_ledger; importlib.reload(pbr_credits_ledger)")
            ) else (
                python.Execute ("import sys; d='" + pDirPy + "'; (sys.path.insert(0, d) if d not in sys.path else None)")
            )
            mObj = python.Import "pbr_credits_ledger"
        ) catch (
            try (format "[Corona->UE5] Credits bridge warning: %\n" (getCurrentException())) catch ()
        )
        mObj
    )

    fn refreshCreditsUI syncServer:false forceReload:false = (
        local mObj = getCreditsMod forceReload:forceReload
        if mObj != undefined then (
            try (cachedCopyId = (mObj.ms_get_instance_id()) as string) catch ()
            try (cachedBalance = (mObj.ms_get_balance syncServer) as float) catch ()
            local tagTxt = if cachedBalance > 10.0 then "OK" else if cachedBalance > 0.0 then "МАЛО" else "0 — ПОПОЛНИТЬ"
            if CoronaToUE5ExporterRollout.open do (
                lblCopyId.text = "Copy ID: " + cachedCopyId
                lblCreditsBal.text = "Баланс: " + (fmtGens cachedBalance) + " Gens (" + tagTxt + ")"
            )
        ) else (
            if CoronaToUE5ExporterRollout.open do (
                lblCopyId.text = "Copy ID: недоступен (Python bridge)"
                lblCreditsBal.text = "Баланс: ошибка синхронизации"
            )
        )
    )

    fn collectHierarchyNodes rootArr = (
        local result = #()
        local q = for r in rootArr where isValidNode r collect r
        while q.count > 0 do (
            local curr = q[q.count]
            deleteItem q q.count
            if findItem result curr == 0 do (
                append result curr
                for c in curr.children do append q c
            )
        )
        result
    )

    fn sanitizeName str = (
        local out = ""
        local rus = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        local lat = #("a","b","v","g","d","e","yo","zh","z","i","y","k","l","m","n","o","p","r","s","t","u","f","kh","ts","ch","sh","shch","","y","","e","yu","ya",
                      "A","B","V","G","D","E","Yo","Zh","Z","I","Y","K","L","M","N","O","P","R","S","T","U","F","Kh","Ts","Ch","Sh","Shch","","Y","","E","Yu","Ya")
        for i = 1 to str.count do (
            local ch = str[i]
            local idx = findString rus ch
            if idx != undefined then out += lat[idx]
            else if (ch >= "a" and ch <= "z") or (ch >= "A" and ch <= "Z") or (ch >= "0" and ch <= "9") or ch == "_" or ch == "-" then out += ch
            else out += "_"
        )
        out
    )

    fn getLayerFullPath lyr = (
        local lyrPath = "0"
        try (
            if lyr != undefined do (
                lyrPath = lyr.name
                local par = lyr.getParent()
                while par != undefined do (
                    lyrPath = par.name + "/" + lyrPath
                    par = par.getParent()
                )
            )
        ) catch ()
        substituteString lyrPath "\\" "/"
    )

    fn getNodeLayerPath o = (
        local lyr = undefined
        try (lyr = o.layer) catch ()
        getLayerFullPath lyr
    )

    fn getTransformDeterminant mat = (
        local d = 1.0
        try (d = dot (cross mat.row1 mat.row2) mat.row3) catch ()
        d
    )

    fn inspectNodeWindingAndVolume o = (
        local detNeg = (getTransformDeterminant o.transform) < -1e-5
        local sc = [1, 1, 1]
        try (sc = o.scale) catch ()
        local nonUni = (abs(sc.x - sc.y) > 0.002) or (abs(sc.y - sc.z) > 0.002) or (sc.x < 0.0) or (sc.y < 0.0) or (sc.z < 0.0)
        local estFaces = 0
        try (estFaces = (getPolygonCount o)[1]) catch ()
        -- Heavy meshes (>12k faces) skip expensive MaxScript snapshot/weld/volume loops and rely on transform determinant
        if estFaces > 12000 do return #(detNeg, false, nonUni, false, 0.0)
        local isClosed = false
        local closedInv = false
        local vol6 = 0.0
        local sm = undefined
        try (
            sm = snapshotAsMesh o
            if sm != undefined and sm.numfaces >= 4 and sm.numfaces <= 12000 and sm.numverts >= 4 do (
                local openEdges = 1
                try (openEdges = (meshop.getOpenEdges sm).numberSet) catch ()
                if openEdges > 0 and sm.numverts <= 6000 do (
                    -- Weld split smooth-group vertices on compact shells so winding check catches inverted extrusions
                    try (
                        meshop.weldVertsByThreshold sm #{1..sm.numverts} 0.01
                        openEdges = (meshop.getOpenEdges sm).numberSet
                    ) catch ()
                )
                isClosed = (openEdges == 0)
                if isClosed do (
                    local nv = sm.numverts
                    local cent = [0, 0, 0]
                    for vi = 1 to nv do (
                        cent += getVert sm vi
                        if mod vi 2500 == 0 do try (windows.processPostedMessages()) catch ()
                    )
                    cent = cent / (nv as float)
                    for fi = 1 to sm.numfaces do (
                        local fv = getFace sm fi
                        local p0 = (getVert sm (fv.x as integer)) - cent
                        local p1 = (getVert sm (fv.y as integer)) - cent
                        local p2 = (getVert sm (fv.z as integer)) - cent
                        vol6 += dot (cross p0 p1) p2
                        if mod fi 2500 == 0 do try (windows.processPostedMessages()) catch ()
                    )
                    if vol6 < -1.0 do closedInv = true
                )
            )
        ) catch ()
        if sm != undefined do try (delete sm) catch ()
        #(detNeg, closedInv, nonUni, isClosed, vol6)
    )

    fn collectObjectLeafMaterials obj fastScan:true = (
        local leafMtls = #()
        if obj == undefined or not (isValidNode obj) do return leafMtls
        local m = undefined
        try (m = obj.material) catch ()
        if m == undefined do return leafMtls

        if classOf m == Multimaterial then (
            local numSubs = 0
            try (numSubs = m.numsubs) catch ()
            local usedIds = #()
            local scannedFaces = false
            local maxSamples = if fastScan then 450 else 1800
            try (
                local objCls = classOf obj
                if objCls == Editable_Poly then (
                    local nf = polyop.getNumFaces obj
                    if nf > 0 do (
                        scannedFaces = true
                        local fStep = if nf > maxSamples then (amax #(1, (nf / maxSamples) as integer)) else 1
                        for f = 1 to nf by fStep do (
                            local fid = polyop.getFaceMatID obj f
                            appendIfUnique usedIds fid
                            if numSubs > 0 and usedIds.count >= numSubs do exit
                        )
                    )
                ) else if objCls == Editable_Mesh then (
                    local nf = obj.numfaces
                    if nf > 0 do (
                        scannedFaces = true
                        local fStep = if nf > maxSamples then (amax #(1, (nf / maxSamples) as integer)) else 1
                        for f = 1 to nf by fStep do (
                            local fid = getFaceMatID obj f
                            appendIfUnique usedIds fid
                            if numSubs > 0 and usedIds.count >= numSubs do exit
                        )
                    )
                )
            ) catch (scannedFaces = false)

            if scannedFaces and usedIds.count > 0 and numSubs > 0 then (
                for fid in usedIds do (
                    local subMtl = undefined
                    try (
                        local idList = m.materialIDList
                        local slotIdx = if idList != undefined then (findItem idList fid) else 0
                        if slotIdx > 0 and slotIdx <= numSubs then (
                            subMtl = m[slotIdx]
                        ) else (
                            local modIdx = ((mod (fid - 1) numSubs) as integer) + 1
                            if modIdx >= 1 and modIdx <= numSubs do subMtl = m[modIdx]
                        )
                    ) catch ()
                    if subMtl != undefined do appendIfUnique leafMtls subMtl
                )
            )
            if leafMtls.count == 0 do (
                for i = 1 to numSubs do (
                    try (
                        if m[i] != undefined do appendIfUnique leafMtls m[i]
                    ) catch ()
                )
            )
        ) else (
            append leafMtls m
        )
        leafMtls
    )

    fn isFabricTextMatch s = (
        if s == undefined or s == "" do return false
        local pats = #("*fabric*","*cloth*","*velvet*","*velour*","*velyur*","*bukle*","*boucle*","*linen*","*cotton*","*wool*","*textile*","*tkan*","*tkany*","*tekst*","*barhat*","*rogozh*","*chenill*","*jacquard*","*suede*","*zamsha*","*pillow*","*podushk*","*cushion*","*mattress*","*matras*","*bed*","*krovat*","*blanket*","*odeyal*","*pled*","*plaid*","*divan*","*sofa*","*couch*","*kreslo*","*pouf*","*armchair*","*curtain*","*shtor*","*drap*","*tulle*","*tyul*","*carpet*","*kover*","*rug*","*obivk*","*upholst*")
        for p in pats do if matchPattern s pattern:p do return true
        false
    )

    fn analyzeMaterialMeta m = (
        local cls = (classOf m) as string
        local ueMaster = "MM_ComfyPBR_Master"
        local extraLayers = 0
        local srcMtl = m

        if cls == "CoronaLayeredMtl" do (
            try (if m.baseMtl != undefined do srcMtl = m.baseMtl) catch ()
            try (
                for idx = 1 to m.layers.count do (
                    if m.layers[idx] != undefined and m.layersOn[idx] == true and m.amounts[idx] > 0.0 do (
                        extraLayers = 1
                        exit
                    )
                )
            ) catch ()
        )

        local srcCls = (classOf srcMtl) as string
        if srcCls == "CoronaLightMtl" then (
            ueMaster = "MM_ArchViz_Emissive"
        ) else (
            local emis = 0.0; local refr = 0.0; local sheen = 0.0; local hasOpacTex = false
            try (emis = srcMtl.selfIllumLevel) catch ()
            try (refr = srcMtl.refractionAmount) catch ()
            try (if refr == 0.0 do refr = srcMtl.levelRefract) catch ()
            try (sheen = srcMtl.sheenAmount) catch ()
            try (if srcMtl.opacityTexmapOn and srcMtl.opacityTexmap != undefined do hasOpacTex = true) catch ()
            try (if (not hasOpacTex) and srcMtl.texmapOnOpacity and srcMtl.texmapOpacity != undefined do hasOpacTex = true) catch ()
            local diffPathHint = ""
            try (if isProperty srcMtl #baseTexmap and srcMtl.baseTexmap != undefined and isProperty srcMtl.baseTexmap #filename do diffPathHint = srcMtl.baseTexmap.filename as string) catch ()

            if emis > 0.1 then ueMaster = "MM_ArchViz_Emissive"
            else if refr > 0.2 or matchPattern m.name pattern:"*glass*" or matchPattern m.name pattern:"*stekl*" or matchPattern m.name pattern:"*window*" or matchPattern m.name pattern:"*water*" then ueMaster = "MM_ArchViz_Glass"
            else if hasOpacTex or matchPattern m.name pattern:"*leaf*" or matchPattern m.name pattern:"*leaves*" or matchPattern m.name pattern:"*foliage*" or matchPattern m.name pattern:"*trava*" then ueMaster = "MM_ArchViz_Foliage"
            else if sheen > 0.1 or (isFabricTextMatch m.name) or (isFabricTextMatch diffPathHint) then ueMaster = "MM_ArchViz_Fabric"
        )

        local cost = 0.5 * (1 + extraLayers)
        #(cls, ueMaster, extraLayers, cost)
    )

    fn getEffSkipExistingUE5 = (
        if qtActive then optSkipExistingUE5 else chkSkipExistingUE5.checked
    )

    fn jsonEscapeSafe s = (
        local out = try (s as string) catch ""
        out = substituteString out "\\" "/"
        out = substituteString out "\"" "'"
        out
    )

    fn getExporterPyMod = (
        local mObj = undefined
        try (
            local pDirPy = substituteString (CoronaToUE5_ResolvePluginDir()) "\\" "/"
            python.Execute ("import sys; d='" + pDirPy + "'; (sys.path.insert(0, d) if d not in sys.path else None)")
            mObj = python.Import "corona_ue5_exporter_qt"
        ) catch ()
        mObj
    )

    fn refreshUE5MaterialIndex = (
        local pyMod = getExporterPyMod()
        if pyMod != undefined then (
            local outDir = if qtActive then optExportDir else edtExportDir.text
            try (
                ue5IndexStatus = (pyMod.ms_refresh_ue5_materials outDir) as string
            ) catch (
                ue5IndexStatus = "NONE|0|"
            )
        ) else (
            ue5IndexStatus = "NONE|0|"
        )
        pyMod
    )

    fn describeTexmapFingerprint tmap depth:0 = (
        if tmap == undefined do return ""
        local cls = (classOf tmap) as string
        if depth > 3 do return (sanitizeName cls)
        if classOf tmap == Bitmaptexture or cls == "CoronaBitmap" then (
            local fname = ""
            try (fname = tmap.filename as string) catch ()
            local sz = "0"
            local dt = ""
            if fname != "" and doesFileExist fname do (
                try (sz = (getFileSize fname) as string) catch ()
                try (dt = (getFileModDate fname) as string) catch ()
            )
            local bName = sanitizeName (filenameFromPath fname)
            return ((sanitizeName cls) + "(" + bName + ":" + sz + ":" + (sanitizeName dt) + ")")
        )
        if cls == "CoronaNormal" then (
            local inner = undefined
            local mult = "1"
            try (inner = tmap.normalMap) catch ()
            try (mult = safeJsonNum tmap.multiplier) catch ()
            return ("CN(" + mult + "," + (describeTexmapFingerprint inner depth:(depth + 1)) + ")")
        )
        local tag = (sanitizeName cls) + "("
        try (if isProperty tmap #color do tag += "c=" + ((tmap.color.r as integer) as string) + "_" + ((tmap.color.g as integer) as string) + "_" + ((tmap.color.b as integer) as string) + ";") catch ()
        try (if isProperty tmap #brightness do tag += "br=" + (safeJsonNum tmap.brightness) + ";") catch ()
        try (if isProperty tmap #contrast do tag += "ct=" + (safeJsonNum tmap.contrast) + ";") catch ()
        try (if isProperty tmap #saturation do tag += "st=" + (safeJsonNum tmap.saturation) + ";") catch ()
        try (if isProperty tmap #mixAmount do tag += "ma=" + (safeJsonNum tmap.mixAmount) + ";") catch ()
        local nSub = 0
        try (nSub = amin #(3, getNumSubTexmaps tmap)) catch ()
        for ti = 1 to nSub do (
            local sub = undefined
            try (sub = getSubTexmap tmap ti) catch ()
            if sub != undefined do (
                tag += "s" + (ti as string) + "=" + (describeTexmapFingerprint sub depth:(depth + 1)) + ";"
            )
        )
        tag += ")"
        tag
    )

    fn computeMaterialMaxSig m pyMod:undefined = (
        if m == undefined do return ""
        local cls = (classOf m) as string
        local srcMtl = m
        local lbSig = ""
        if cls == "CoronaLayeredMtl" do (
            try (if m.baseMtl != undefined do srcMtl = m.baseMtl) catch ()
            try (
                for idx = 1 to m.layers.count do (
                    if m.layers[idx] != undefined and m.layersOn[idx] == true and m.amounts[idx] > 0.0 do (
                        local lm = m.layers[idx]
                        local lbc = "0_0_0"
                        try (lbc = ((lm.baseColor.r as integer) as string) + "_" + ((lm.baseColor.g as integer) as string) + "_" + ((lm.baseColor.b as integer) as string)) catch ()
                        local lr = try (safeJsonNum lm.baseRoughness) catch "0.5"
                        local lmVal = try (if lm.metalnessMode == 1 then "1" else "0") catch "0"
                        local ltA = try (if lm.baseTexmapOn and lm.baseTexmap != undefined then (describeTexmapFingerprint lm.baseTexmap) else "") catch ""
                        local ltR = try (if lm.baseRoughnessTexmapOn and lm.baseRoughnessTexmap != undefined then (describeTexmapFingerprint lm.baseRoughnessTexmap) else "") catch ""
                        local ltN = try (if lm.baseBumpTexmapOn and lm.baseBumpTexmap != undefined then (describeTexmapFingerprint lm.baseBumpTexmap) else "") catch ""
                        local ltM = try (if m.masksOn[idx] == true and m.mixmaps[idx] != undefined then (describeTexmapFingerprint m.mixmaps[idx]) else "") catch ""
                        lbSig = "|LB=" + (safeJsonNum m.amounts[idx]) + ":" + lbc + ":" + lr + ":" + lmVal + ":" + ltA + ":" + ltR + ":" + ltN + ":" + ltM
                        exit
                    )
                )
            ) catch ()
        )

        local srcCls = (classOf srcMtl) as string
        local colTag = "204_204_204"
        local rTag = "0.5"
        local mTag = "0"
        local refTag = "0"
        local iorTag = "1.52"
        local shTag = "0"
        local emTag = "0"
        local tA = ""; local tR = ""; local tN = ""; local tM = ""; local tO = ""

        if srcCls == "CoronaLightMtl" then (
            try (colTag = ((srcMtl.color.r as integer) as string) + "_" + ((srcMtl.color.g as integer) as string) + "_" + ((srcMtl.color.b as integer) as string)) catch ()
            try (emTag = safeJsonNum srcMtl.intensity) catch ()
            try (tA = describeTexmapFingerprint srcMtl.texmap) catch ()
        ) else (
            try (colTag = ((srcMtl.baseColor.r as integer) as string) + "_" + ((srcMtl.baseColor.g as integer) as string) + "_" + ((srcMtl.baseColor.b as integer) as string)) catch ()
            try (rTag = safeJsonNum srcMtl.baseRoughness) catch ()
            try (if srcMtl.metalnessMode == 1 do mTag = "1") catch ()
            try (iorTag = safeJsonNum srcMtl.ior) catch ()
            try (refTag = safeJsonNum srcMtl.refractionAmount) catch ()
            try (if refTag == "0.0" do refTag = safeJsonNum srcMtl.levelRefract) catch ()
            try (shTag = safeJsonNum srcMtl.sheenAmount) catch ()
            try (emTag = safeJsonNum srcMtl.selfIllumLevel) catch ()
            try (if srcMtl.baseTexmapOn do tA = describeTexmapFingerprint srcMtl.baseTexmap) catch ()
            try (if srcMtl.baseRoughnessTexmapOn do tR = describeTexmapFingerprint srcMtl.baseRoughnessTexmap) catch ()
            try (if srcMtl.baseBumpTexmapOn do tN = describeTexmapFingerprint srcMtl.baseBumpTexmap) catch ()
            try (if srcMtl.metalnessTexmapOn do tM = describeTexmapFingerprint srcMtl.metalnessTexmap) catch ()
            try (if srcMtl.opacityTexmapOn and srcMtl.opacityTexmap != undefined do tO = describeTexmapFingerprint srcMtl.opacityTexmap) catch ()
            try (if tO == "" and srcMtl.texmapOnOpacity and srcMtl.texmapOpacity != undefined do tO = describeTexmapFingerprint srcMtl.texmapOpacity) catch ()
        )

        local rawSig = (sanitizeName cls) + "|" + (sanitizeName srcCls) + "|c=" + colTag + "|r=" + rTag + "|m=" + mTag + "|rf=" + refTag + "|ior=" + iorTag + "|sh=" + shTag + "|em=" + emTag + "|A=" + tA + "|R=" + tR + "|N=" + tN + "|M=" + tM + "|O=" + tO + lbSig
        if pyMod != undefined then (
            try (return ((pyMod.ms_hash_sig rawSig) as string)) catch ()
        )
        rawSig
    )

    fn classifyMaterialAgainstUE5 m pyMod:undefined = (
        local effPy = if pyMod != undefined then pyMod else (getExporterPyMod())
        local safeName = sanitizeName m.name
        local sig = computeMaterialMaxSig m pyMod:effPy
        if not (getEffSkipExistingUE5()) do return #("NEW", "", sig)
        if effPy == undefined do return #("NEW", "", sig)
        try (
            local raw = (effPy.ms_classify_material safeName m.name sig) as string
            local sepIdx = findString raw "|"
            if sepIdx != undefined then (
                local stTag = substring raw 1 (sepIdx - 1)
                local ueP = substring raw (sepIdx + 1) (raw.count - sepIdx)
                return #(stTag, ueP, sig)
            )
        ) catch ()
        #("NEW", "", sig)
    )

    fn computeCostForNodes nodeArr fastScan:true refreshUE5:false = (
        local pyModExp = if refreshUE5 then (refreshUE5MaterialIndex()) else (getExporterPyMod())
        local uMtls = #()
        local totalCost = 0.0
        local layeredCnt = 0
        local newCnt = 0
        local reusedCnt = 0
        local updatedCnt = 0
        local oi = 0
        for o in nodeArr where isValidNode o and superClassOf o == GeometryClass and o.name != "00_Floorplan_Reference" do (
            oi += 1
            local leaves = collectObjectLeafMaterials o fastScan:fastScan
            for lm in leaves do (
                if findItem uMtls lm == 0 do (
                    append uMtls lm
                    local meta = analyzeMaterialMeta lm
                    local clsInfo = classifyMaterialAgainstUE5 lm pyMod:pyModExp
                    local stTag = clsInfo[1]
                    if stTag == "REUSE" then (
                        reusedCnt += 1
                    ) else if stTag == "UPDATE" then (
                        updatedCnt += 1
                    ) else (
                        newCnt += 1
                        totalCost += meta[4]
                        if meta[3] > 0 do layeredCnt += 1
                    )
                )
            )
            if mod oi 100 == 0 do try (windows.processPostedMessages()) catch ()
        )
        totalCost = roundHalfGen totalCost
        #(totalCost, uMtls.count, layeredCnt, newCnt, reusedCnt, updatedCnt)
    )

    fn collectHierarchyLayers parentLyr depth outLayers outDepths = (
        for i = 0 to (LayerManager.count - 1) do (
            local lyr = LayerManager.getLayer i
            if lyr != undefined do (
                local par = undefined
                try (par = lyr.getParent()) catch ()
                if par == parentLyr do (
                    append outLayers lyr
                    append outDepths depth
                    collectHierarchyLayers lyr (depth + 1) outLayers outDepths
                )
            )
        )
    )

    fn getNodesForSelectedLayers = (
        local selNodes = #()
        local curView = getEffScanView()
        if auditRowType.count == 0 or curView != 3 do (
            -- Fallback to all ON layers containing geometry
            for o in geometry where isValidExportGeom o do (
                local isOn = true
                try (if o.layer != undefined do isOn = o.layer.on) catch ()
                if isOn do append selNodes o
            )
            return selNodes
        )
        local effSel = getEffLayerSel()
        for idx in effSel do (
            if idx >= 1 and idx <= auditRowNodes.count do (
                for o in auditRowNodes[idx] where isValidNode o do appendIfUnique selNodes o
            )
        )
        selNodes
    )

    fn getSelectedLayerNamesList = (
        local res = #()
        if (getEffScanView()) == 3 do (
            local effSel = getEffLayerSel()
            for idx in effSel do (
                if idx >= 1 and idx <= auditRowLayerNames.count do (
                    append res auditRowLayerNames[idx]
                )
            )
        )
        res
    )

    fn updateExportButtonCaptions recalcFull:true recalcLayers:true recalcSel:true = (
        if recalcFull or lastFullCost <= 0.0 do (
            local fullNodes = for o in geometry where isValidExportGeom o collect o
            local fullStats = computeCostForNodes fullNodes fastScan:true
            lastFullCost = fullStats[1]
        )

        if recalcSel do (
            local selStats = #(0.0, 0, 0)
            if selection.count > 0 do (
                local selTree = collectHierarchyNodes (selection as array)
                local selGeom = for o in selTree where superClassOf o == GeometryClass and isValidExportGeom o collect o
                selStats = computeCostForNodes selGeom fastScan:true
            )
            lastSelCost = selStats[1]
        )

        if recalcLayers do (
            local lyrNodes = getNodesForSelectedLayers()
            local lyrStats = computeCostForNodes lyrNodes fastScan:true
            lastLayersCost = lyrStats[1]
        )

        if CoronaToUE5ExporterRollout.open do (
            btnExportUE5.caption = "🚀 ПОЛНЫЙ ЭКСПОРТ ВСЕЙ СЦЕНЫ В UE5 (" + (fmtGens lastFullCost) + " Gens)"
            btnReimportSelected.caption = "⚡ РЕИМПОРТ ВЫДЕЛЕННОГО (" + (fmtGens lastSelCost) + " Gens)"
            btnExportLayers.caption = "🗂 ЭКСПОРТ ВЫБР. СЛОЁВ (" + (fmtGens lastLayersCost) + " Gens)"
        )
    )

    fn updateSelectedLayersSummary = (
        if (getEffScanView()) != 3 do return()
        local pyModExp = getExporterPyMod()
        local lyrNodes = getNodesForSelectedLayers()
        local objWithM = 0
        local objNoM = 0
        local uMtls = #()
        local totalCost = 0.0
        local lCount = 0
        local newCnt = 0
        local reusedCnt = 0
        local updatedCnt = 0
        for oi = 1 to lyrNodes.count do (
            local o = lyrNodes[oi]
            local leaves = collectObjectLeafMaterials o fastScan:true
            if leaves.count > 0 then objWithM += 1 else objNoM += 1
            for lm in leaves do (
                if findItem uMtls lm == 0 do (
                    append uMtls lm
                    local meta = analyzeMaterialMeta lm
                    local clsInfo = classifyMaterialAgainstUE5 lm pyMod:pyModExp
                    if clsInfo[1] == "REUSE" then (
                        reusedCnt += 1
                    ) else if clsInfo[1] == "UPDATE" then (
                        updatedCnt += 1
                    ) else (
                        newCnt += 1
                        totalCost += meta[4]
                        if meta[3] > 0 do lCount += 1
                    )
                )
            )
            if mod oi 120 == 0 do try (windows.processPostedMessages()) catch ()
        )
        totalCost = roundHalfGen totalCost
        local uCount = uMtls.count
        local selCnt = (getEffLayerSel()).numberSet
        lastLayersCost = totalCost

        lastScanSummaryText = "Layer Explorer: выбрано слоёв " + (selCnt as string) + " (" + (lyrNodes.count as string) + " об., с матами: " + (objWithM as string) + ") | Уник. матов: " + (uCount as string) + " (Новых: " + (newCnt as string) + " | В UE5: " + (reusedCnt as string) + " | Изм: " + (updatedCnt as string) + ")"
        local estSuffix = if totalCost <= 0.0 then "не требуется списание"
            else if (cachedBalance + 0.001) >= totalCost then ("хватает — останется " + (fmtGens (amax #(0.0, cachedBalance - totalCost))) + " Gens")
            else ("НЕ ХВАТАЕТ " + (fmtGens (amax #(0.0, totalCost - cachedBalance))) + " Gens!")
        lastCostEstimateText = "К списанию (Выбр. слои): " + (fmtGens totalCost) + " Gens (0.5/нов.мат + 0.5 за LayerB) | Баланс: " + (fmtGens cachedBalance) + " (" + estSuffix + ")"
        if CoronaToUE5ExporterRollout.open do (
            lblScanSummary.text = lastScanSummaryText
            lblCostEstimate.text = lastCostEstimateText
        )
        updateExportButtonCaptions recalcFull:false recalcLayers:false recalcSel:false
    )

    fn setQtLayerIndices idxArr = (
        local bs = #{}
        for i in idxArr do (
            local ii = (i as integer)
            if ii >= 1 do append bs ii
        )
        optSelectedLayerIndices = bs
        updateSelectedLayersSummary()
    )

    fn selectAuditRow idx = (
        if idx >= 1 and idx <= auditRowNodes.count then (
            local nodesArr = for n in auditRowNodes[idx] where isValidNode n collect n
            if nodesArr.count > 0 do (
                select nodesArr
                max tool zoomextents
            )
            nodesArr.count
        ) else 0
    )

    fn selectPolyRow idx = (
        if idx >= 1 and idx <= sortedNodes.count and isValidNode sortedNodes[idx] then (
            select sortedNodes[idx]
            max tool zoomextents
            true
        ) else false
    )

    fn scanSceneMaterialsAndCost scopeMode:#all refreshList:true = (
        lastScanScope = scopeMode
        local pyModExp = refreshUE5MaterialIndex()
        local curView = getEffScanView()
        if curView == 3 and scopeMode == #layers do (
            if refreshList do (
                auditRowType = #()
                auditRowNodes = #()
                auditRowLayerNames = #()
                local allLyrs = #()
                local allDepths = #()
                collectHierarchyLayers undefined 0 allLyrs allDepths
                local lyrBuckets = for li = 1 to allLyrs.count collect #()
                local allGeom = for o in geometry where isValidExportGeom o collect o
                for oi = 1 to allGeom.count do (
                    local o = allGeom[oi]
                    local lIdx = findItem allLyrs o.layer
                    if lIdx > 0 do append lyrBuckets[lIdx] o
                    if mod oi 150 == 0 do try (windows.processPostedMessages()) catch ()
                )
                local displayItems = #()
                local defaultSel = #{}
                for li = 1 to allLyrs.count do (
                    local lyr = allLyrs[li]
                    local depth = allDepths[li]
                    local indent = ""
                    for d = 1 to depth do indent += "  "
                    if depth > 0 do indent += "└─ "
                    local lyrPath = getLayerFullPath lyr
                    local lyrGeom = lyrBuckets[li]
                    local lyrStats = computeCostForNodes lyrGeom fastScan:true refreshUE5:false
                    local visTag = if lyr.on then "[ON]" else "[OFF]"
                    local rowStr = indent + visTag + " " + lyr.name + "  (" + (lyrGeom.count as string) + " об. | " + (lyrStats[2] as string) + " матов | " + (fmtGens lyrStats[1]) + " Gens)"
                    append displayItems rowStr
                    append auditRowType "layer"
                    append auditRowNodes lyrGeom
                    append auditRowLayerNames lyrPath
                    if lyr.on and lyrGeom.count > 0 do append defaultSel li
                    if mod li 15 == 0 do try (windows.processPostedMessages()) catch ()
                )
                auditDisplayItems = displayItems
                auditDefaultLayerSel = defaultSel
                if qtActive do (
                    optSelectedLayerIndices = #{}
                    for bi in defaultSel do append optSelectedLayerIndices bi
                )
                if CoronaToUE5ExporterRollout.open do (
                    lbxSceneAudit.items = displayItems
                    lbxSceneAudit.selection = defaultSel
                )
            )
            updateSelectedLayersSummary()
            return #(0, 0, 0, lastLayersCost)
        )

        local targetNodes = #()
        if scopeMode == #selected then (
            if selection.count > 0 do (
                local selTree = collectHierarchyNodes (selection as array)
                targetNodes = for o in selTree where superClassOf o == GeometryClass and isValidExportGeom o collect o
            )
        ) else (
            targetNodes = for o in geometry where isValidExportGeom o collect o
        )

        local objCount = targetNodes.count
        local objWithMtlCount = 0
        local objNoMtlCount = 0
        local uniqueMtls = #()
        local uniqueMeta = #()
        local uniqueClassInfo = #()
        local uniqueUserNodes = #()
        local objAuditLines = #()
        local objAuditRefs = #()
        local totalGensCost = 0.0
        local layeredCount = 0
        local newCount = 0
        local reusedCount = 0
        local updatedCount = 0

        local oi_scan = 0
        for o in targetNodes do (
            oi_scan += 1
            local leaves = collectObjectLeafMaterials o fastScan:true
            if leaves.count > 0 then objWithMtlCount += 1 else objNoMtlCount += 1
            local oCost = 0.0
            local matLabelArr = #()
            for lm in leaves do (
                local meta = analyzeMaterialMeta lm
                local clsInfo = classifyMaterialAgainstUE5 lm pyMod:pyModExp
                local mCost = if clsInfo[1] == "NEW" then meta[4] else 0.0
                local uIdx = findItem uniqueMtls lm
                if uIdx == 0 then (
                    append uniqueMtls lm
                    append uniqueMeta meta
                    append uniqueClassInfo clsInfo
                    append uniqueUserNodes #(o)
                    totalGensCost += mCost
                    if clsInfo[1] == "REUSE" then (
                        reusedCount += 1
                    ) else if clsInfo[1] == "UPDATE" then (
                        updatedCount += 1
                    ) else (
                        newCount += 1
                        if meta[3] > 0 do layeredCount += 1
                    )
                ) else (
                    appendIfUnique uniqueUserNodes[uIdx] o
                )
                oCost += mCost
                append matLabelArr lm.name
            )
            local matJoined = if matLabelArr.count > 0 then "" else "[БЕЗ МАТЕРИАЛА]"
            for mi = 1 to (amin #(3, matLabelArr.count)) do (
                if mi > 1 do matJoined += ", "
                matJoined += matLabelArr[mi]
            )
            if matLabelArr.count > 3 do matJoined += " (+ещё " + ((matLabelArr.count - 3) as string) + ")"
            local lyrPath = getNodeLayerPath o
            local lineStr = o.name + "  [" + lyrPath + " | " + (leaves.count as string) + " мат / " + (fmtGens (roundHalfGen oCost)) + " Gens] -> " + matJoined
            append objAuditLines lineStr
            append objAuditRefs o
            if mod oi_scan 80 == 0 do try (windows.processPostedMessages()) catch ()
        )
        totalGensCost = roundHalfGen totalGensCost

        if refreshList do (
            auditRowType = #()
            auditRowNodes = #()
            auditRowLayerNames = #()
            local displayItems = #()
            if curView == 3 then (
                return (scanSceneMaterialsAndCost scopeMode:#layers refreshList:true)
            ) else if curView == 1 then (
                for i = 1 to uniqueMtls.count do (
                    local m = uniqueMtls[i]
                    local meta = uniqueMeta[i]
                    local clsInfo = uniqueClassInfo[i]
                    local stTag = clsInfo[1]
                    local uObjs = uniqueUserNodes[i]
                    local lyrBadge = if meta[3] > 0 then (" | +LayerB") else ""
                    local rowCost = if stTag == "NEW" then meta[4] else 0.0
                    local costPad = fmtGens rowCost
                    if costPad.count == 1 do costPad = "  " + costPad
                    local statusBadge = if stTag == "REUSE" then "[В UE5]" else if stTag == "UPDATE" then "[ОБНОВИТЬ]" else "[НОВЫЙ]"
                    local rowStr = costPad + " Gen | " + statusBadge + " " + m.name + "  (" + meta[1] + lyrBadge + " -> " + meta[2] + ")  [Объектов: " + (uObjs.count as string) + "]"
                    append displayItems rowStr
                    append auditRowType "mat"
                    append auditRowNodes uObjs
                )
            ) else (
                for i = 1 to objAuditLines.count do (
                    append displayItems objAuditLines[i]
                    append auditRowType "obj"
                    append auditRowNodes #(objAuditRefs[i])
                )
            )
            auditDisplayItems = displayItems
            auditDefaultLayerSel = #{}
            if CoronaToUE5ExporterRollout.open do lbxSceneAudit.items = displayItems
        )

        local scopeTag = if scopeMode == #selected then "Выделение" else "Вся сцена"
        lastScanSummaryText = scopeTag + ": " + (objCount as string) + " объектов (с матами: " + (objWithMtlCount as string) + ", без: " + (objNoMtlCount as string) + ") | Уник. матов: " + (uniqueMtls.count as string) + " (Новых: " + (newCount as string) + " | В UE5: " + (reusedCount as string) + " | Изм: " + (updatedCount as string) + ")"

        local estSuffix = if totalGensCost <= 0.0 then "не требуется списание"
            else if (cachedBalance + 0.001) >= totalGensCost then ("хватает — останется " + (fmtGens (amax #(0.0, cachedBalance - totalGensCost))) + " Gens")
            else ("НЕ ХВАТАЕТ " + (fmtGens (amax #(0.0, totalGensCost - cachedBalance))) + " Gens!")
        lastCostEstimateText = "К списанию (" + scopeTag + "): " + (fmtGens totalGensCost) + " Gens (0.5/нов.мат + 0.5 за LayerB) | Баланс: " + (fmtGens cachedBalance) + " (" + estSuffix + ")"

        if CoronaToUE5ExporterRollout.open do (
            lblScanSummary.text = lastScanSummaryText
            lblCostEstimate.text = lastCostEstimateText
        )

        if scopeMode == #all then lastFullCost = totalGensCost else if scopeMode == #selected do lastSelCost = totalGensCost
        updateExportButtonCaptions recalcFull:(scopeMode != #all and lastFullCost <= 0.0) recalcLayers:false recalcSel:(scopeMode != #selected)
        #(objCount, uniqueMtls.count, layeredCount, totalGensCost)
    )

    fn updateSelectionCostOnly = (
        updateExportButtonCaptions recalcFull:false recalcLayers:false
        if lastScanScope == #selected do (
            scanSceneMaterialsAndCost scopeMode:#selected refreshList:true
        )
    )

    fn refreshPolyTable = (
        sortedNodes = #()
        local items = #()
        local totalP = 0
        local pi = 0
        for o in geometry where isValidExportGeom o do (
            pi += 1
            local pc = #(0, 0)
            try (pc = getPolygonCount o) catch ()
            totalP += pc[1]
            append items #(pc[1], o.name, (classOf o as string), o)
            if mod pi 120 == 0 do try (windows.processPostedMessages()) catch ()
        )
        fn cmpFn a b = (if a[1] > b[1] then -1 else if a[1] < b[1] then 1 else 0)
        qsort items cmpFn
        local strList = #()
        for i = 1 to (amin #(50, items.count)) do (
            local it = items[i]
            append sortedNodes it[4]
            append strList ((formattedPrint it[1] format:"8d") + " полигонов  |  " + it[2] + "  (" + it[3] + ")")
        )
        polyDisplayItems = strList
        lastPolyInfoText = "Всего полигонов в сцене: " + (totalP as string) + " (показаны Топ-50 объектов)"
        if CoronaToUE5ExporterRollout.open do (
            lbxPolys.items = strList
            lblPolyInfo.text = lastPolyInfoText
        )
    )

    fn disableHeavyDisplacement = (
        local count = 0
        local mi = 0
        for m in sceneMaterials do (
            mi += 1
            local rawSubs = if classOf m == Multimaterial then (for i=1 to m.numsubs where m[i] != undefined collect m[i]) else #(m)
            local subs = #()
            for rm in rawSubs do (
                append subs rm
                if (classOf rm as string) == "CoronaLayeredMtl" do (
                    try (if rm.baseMtl != undefined do append subs rm.baseMtl) catch ()
                    try (for k=1 to rm.layers.count where rm.layers[k] != undefined do append subs rm.layers[k]) catch ()
                )
            )
            for sm in subs do (
                try (
                    if sm.displacementTexmap != undefined and sm.displacementTexmapOn == true do (
                        sm.displacementTexmapOn = false
                        count += 1
                    )
                ) catch ()
                try (
                    if sm.texmapDisplacement != undefined and sm.texmapOnDisplacement == true do (
                        sm.texmapOnDisplacement = false
                        count += 1
                    )
                ) catch ()
            )
            if mod mi 25 == 0 do try (windows.processPostedMessages()) catch ()
        )
        setStatusText ("Отключен Displacement на " + (count as string) + " материалах (включая CoronaLayeredMtl)!")
        count
    )

    fn collectBitmapsRecursive rootObj outBitmaps visited = (
        if rootObj == undefined do return()
        if findItem visited rootObj != 0 do return()
        append visited rootObj
        local cls = (classOf rootObj) as string
        if cls == "CoronaBitmap" or classOf rootObj == Bitmaptexture do (
            appendIfUnique outBitmaps rootObj
        )
        local nSub = 0
        try (nSub = getNumSubTexmaps rootObj) catch ()
        for ti = 1 to nSub do (
            local sub = undefined
            try (sub = getSubTexmap rootObj ti) catch ()
            if sub != undefined do collectBitmapsRecursive sub outBitmaps visited
        )
    )

    fn getBitmapRealWorldDims bmp = (
        local w = 100.0
        local h = 100.0
        local isRwms = false
        try (
            if (classOf bmp as string) == "CoronaBitmap" then (
                if bmp.realWorldScale == true do (
                    isRwms = true
                    local sc = bmp.uvwScale
                    if sc.x > 1e-8 do w = 1.0 / sc.x
                    if sc.y > 1e-8 do h = 1.0 / sc.y
                )
            ) else if classOf bmp == Bitmaptexture do (
                if bmp.coords.realWorldScale == true do (
                    isRwms = true
                    if bmp.coords.realWorldWidth > 1e-5 do w = bmp.coords.realWorldWidth
                    if bmp.coords.realWorldHeight > 1e-5 do h = bmp.coords.realWorldHeight
                )
            )
        ) catch ()
        #(isRwms, w, h)
    )

    fn getMaterialSubMaterialsRecursive m outMtls visited = (
        if m == undefined do return()
        if findItem visited m != 0 do return()
        append visited m
        appendIfUnique outMtls m
        local cls = (classOf m) as string
        if cls == "Multimaterial" then (
            for i = 1 to m.numsubs do (
                try (if m[i] != undefined do getMaterialSubMaterialsRecursive m[i] outMtls visited) catch ()
            )
        ) else if cls == "CoronaLayeredMtl" do (
            try (if m.baseMtl != undefined do getMaterialSubMaterialsRecursive m.baseMtl outMtls visited) catch ()
            try (
                for k = 1 to m.layers.count do (
                    if m.layers[k] != undefined do getMaterialSubMaterialsRecursive m.layers[k] outMtls visited
                )
            ) catch ()
        )
    )

    fn convertRealWorldMapSizeToUVW scopeMode:#all = (
        local targetNodes = if scopeMode == #selected then (
            local selTree = collectHierarchyNodes (selection as array)
            for o in selTree where isValidNode o and superClassOf o == GeometryClass and not isKindOf o Targetobject and not isKindOf o BoneGeometry collect o
        ) else (
            for o in geometry where isValidNode o and not isKindOf o Targetobject and not isKindOf o BoneGeometry collect o
        )
        if scopeMode == #selected and targetNodes.count == 0 do (
            setStatusText "Выделите объекты для снятия Real-World Map Size и назначения UVW Map!"
            return false
        )

        local rootMtls = #()
        for o in targetNodes where o.material != undefined do appendIfUnique rootMtls o.material
        if scopeMode == #all do (
            for sm in sceneMaterials do appendIfUnique rootMtls sm
        )

        local allLeafMtls = #()
        local visM = #()
        for rm in rootMtls do getMaterialSubMaterialsRecursive rm allLeafMtls visM

        local convertedMtls = #()
        local convertedBaseSizes = #()
        local bmpCount = 0

        local mi_rw = 0
        for lm in allLeafMtls do (
            mi_rw += 1
            if mod mi_rw 20 == 0 do try (windows.processPostedMessages()) catch ()
            local bms = #()
            local visT = #()
            collectBitmapsRecursive lm bms visT

            local rwmsBms = #()
            local rwmsDims = #()
            for b in bms do (
                local dInfo = getBitmapRealWorldDims b
                if dInfo[1] == true do (
                    append rwmsBms b
                    append rwmsDims #(dInfo[2], dInfo[3])
                )
            )

            if rwmsBms.count > 0 do (
                local baseW = rwmsDims[1][1]
                local baseH = rwmsDims[1][2]
                -- Prefer primary Albedo/Diffuse map dimensions for the object Box UVW size
                local primaryBms = #()
                try (if isProperty lm #baseTexmap and lm.baseTexmap != undefined do collectBitmapsRecursive lm.baseTexmap primaryBms #()) catch ()
                if primaryBms.count == 0 do try (if isProperty lm #texmapDiffuse and lm.texmapDiffuse != undefined do collectBitmapsRecursive lm.texmapDiffuse primaryBms #()) catch ()
                if primaryBms.count > 0 do (
                    local pdInfo = getBitmapRealWorldDims primaryBms[1]
                    if pdInfo[1] == true do (
                        baseW = pdInfo[2]
                        baseH = pdInfo[3]
                    )
                )

                for bi = 1 to rwmsBms.count do (
                    local b = rwmsBms[bi]
                    local rwW = amax #(1e-4, rwmsDims[bi][1])
                    local rwH = amax #(1e-4, rwmsDims[bi][2])
                    local tU = baseW / rwW
                    local tV = baseH / rwH
                    try (
                        if (classOf b as string) == "CoronaBitmap" then (
                            b.realWorldScale = false
                            b.uvwScale = [tU, tV, 1.0]
                        ) else if classOf b == Bitmaptexture do (
                            b.coords.realWorldScale = false
                            b.coords.U_Tiling = tU
                            b.coords.V_Tiling = tV
                        )
                        bmpCount += 1
                    ) catch ()
                )
                append convertedMtls lm
                append convertedBaseSizes #(baseW, baseH)
            )
        )

        local fixedObjCount = 0
        if convertedMtls.count > 0 do (
            local oi_rw = 0
            for o in targetNodes where o.material != undefined do (
                oi_rw += 1
                if mod oi_rw 100 == 0 do try (windows.processPostedMessages()) catch ()
                local objMtls = #()
                local visO = #()
                getMaterialSubMaterialsRecursive o.material objMtls visO
                local matchedSize = undefined
                for om in objMtls do (
                    local mIdx = findItem convertedMtls om
                    if mIdx > 0 do (
                        matchedSize = convertedBaseSizes[mIdx]
                        exit
                    )
                )
                if matchedSize != undefined do (
                    local bw = matchedSize[1]
                    local bh = matchedSize[2]
                    local bd = (bw + bh) * 0.5
                    try (if isProperty o #realWorldMapSize do o.realWorldMapSize = false) catch ()
                    local hadUvwMod = false
                    for md in o.modifiers where classOf md == Uvwmap do (
                        hadUvwMod = true
                        try (
                            local wasRwms = false
                            try (wasRwms = md.realWorldMapSize) catch ()
                            md.realWorldMapSize = false
                            if wasRwms or (md.width <= 2.0 and md.length <= 2.0) do (
                                md.maptype = 4
                                md.width = bw
                                md.length = bh
                                md.height = bd
                                md.utile = 1.0
                                md.vtile = 1.0
                                md.wtile = 1.0
                            )
                        ) catch ()
                    )
                    if not hadUvwMod do (
                        try (
                            addModifier o (Uvwmap maptype:4 width:bw length:bh height:bd utile:1.0 vtile:1.0 wtile:1.0 realWorldMapSize:false)
                        ) catch ()
                    )
                    fixedObjCount += 1
                )
            )
        )
        redrawViews()
        local scopeLabel = if scopeMode == #selected then "Выделение" else "Сцена"
        setStatusText ("RWMS (" + scopeLabel + "): снято с " + (bmpCount as string) + " карт (" + (convertedMtls.count as string) + " мат.), UVW Map назначен на " + (fixedObjCount as string) + " объектов!")
        #(bmpCount, convertedMtls.count, fixedObjCount)
    )

    fn extractOrBakeTexmap tmap slotName mtlSafeName texDir doBake forceOverwrite:false = (
        if tmap == undefined do return ""
        local cls = classOf tmap as string
        if classOf tmap == Bitmaptexture or cls == "CoronaBitmap" then (
            local fname = ""
            try (fname = tmap.filename) catch ()
            if fname != "" and doesFileExist fname then (
                local ext = getFilenameType fname
                local srcBase = sanitizeName (getFilenameFile fname)
                if srcBase == "" do srcBase = mtlSafeName + "_" + slotName
                local destFile = texDir + "\\T_" + srcBase + ext
                local needCopy = forceOverwrite or (not (doesFileExist destFile))
                if not needCopy do (
                    try (
                        if (getFileSize fname) != (getFileSize destFile) or (getFileModDate fname) != (getFileModDate destFile) do needCopy = true
                    ) catch ()
                )
                if needCopy do (
                    if doesFileExist destFile do try (deleteFile destFile) catch ()
                    copyFile fname destFile
                )
                return ( substituteString destFile "\\" "/" )
            )
        )
        if cls == "CoronaNormal" then (
            local inner = undefined
            try (inner = tmap.normalMap) catch ()
            if inner != undefined do return (extractOrBakeTexmap inner slotName mtlSafeName texDir doBake forceOverwrite:forceOverwrite)
        )
        if doBake then (
            try (
                local destPng = texDir + "\\" + mtlSafeName + "_" + slotName + "_baked.png"
                if forceOverwrite and doesFileExist destPng do try (deleteFile destPng) catch ()
                if not (doesFileExist destPng) do (
                    local bmp = renderMap tmap size:[1024,1024] fileName:destPng
                    save bmp
                    close bmp
                )
                if doesFileExist destPng do return ( substituteString destPng "\\" "/" )
            ) catch ()
        )
        ""
    )

    fn serializeSingleMtl m texDir doBake maxSig:"" ueAssetPath:"" forceUpdate:false = (
        local safeName = sanitizeName m.name
        local cls = classOf m as string
        local ueMaster = "MM_ComfyPBR_Master"
        local rCol = 0.8; local gCol = 0.8; local bCol = 0.8
        local rough = 0.5; local metal = 0.0; local opac = 1.0; local ior = 1.52; local emis = 0.0; local sheen = 0.0; local refr = 0.0
        local albedoPath = ""; local roughPath = ""; local normPath = ""; local metalPath = ""; local opacPath = ""
        local lbEnabled = false
        local lbAmount = 1.0
        local lbR = 0.8; local lbG = 0.8; local lbB = 0.8
        local lbRough = 0.5; local lbMetal = 0.0
        local lbAlbedoPath = ""; local lbRoughPath = ""; local lbNormPath = ""; local lbMaskPath = ""

        local srcMtl = m
        if cls == "CoronaLayeredMtl" do (
            try (if m.baseMtl != undefined do srcMtl = m.baseMtl) catch ()
            try (
                for idx = 1 to m.layers.count do (
                    if (not lbEnabled) and m.layers[idx] != undefined and m.layersOn[idx] == true and m.amounts[idx] > 0.0 do (
                        local lm = m.layers[idx]
                        lbEnabled = true
                        lbAmount = (m.amounts[idx] as float) / 100.0
                        try (lbR = lm.baseColor.r / 255.0; lbG = lm.baseColor.g / 255.0; lbB = lm.baseColor.b / 255.0) catch ()
                        try (lbRough = lm.baseRoughness) catch ()
                        try (if lm.metalnessMode == 1 do lbMetal = 1.0) catch ()
                        try (if lm.baseTexmapOn and lm.baseTexmap != undefined do lbAlbedoPath = extractOrBakeTexmap lm.baseTexmap "LayerB_Albedo" safeName texDir doBake forceOverwrite:forceUpdate) catch ()
                        try (if lm.baseRoughnessTexmapOn and lm.baseRoughnessTexmap != undefined do lbRoughPath = extractOrBakeTexmap lm.baseRoughnessTexmap "LayerB_Roughness" safeName texDir doBake forceOverwrite:forceUpdate) catch ()
                        try (if lm.baseBumpTexmapOn and lm.baseBumpTexmap != undefined do lbNormPath = extractOrBakeTexmap lm.baseBumpTexmap "LayerB_Normal" safeName texDir doBake forceOverwrite:forceUpdate) catch ()
                        try (if m.masksOn[idx] == true and m.mixmaps[idx] != undefined do lbMaskPath = extractOrBakeTexmap m.mixmaps[idx] "BlendMask" safeName texDir doBake forceOverwrite:forceUpdate) catch ()
                    )
                )
            ) catch ()
        )

        local srcCls = classOf srcMtl as string
        if srcCls == "CoronaLightMtl" then (
            ueMaster = "MM_ArchViz_Emissive"
            try (
                rCol = srcMtl.color.r / 255.0; gCol = srcMtl.color.g / 255.0; bCol = srcMtl.color.b / 255.0
                emis = srcMtl.intensity
                albedoPath = extractOrBakeTexmap srcMtl.texmap "Emissive" safeName texDir doBake forceOverwrite:forceUpdate
            ) catch ()
        ) else (
            try (
                rCol = srcMtl.baseColor.r / 255.0; gCol = srcMtl.baseColor.g / 255.0; bCol = srcMtl.baseColor.b / 255.0
                rough = srcMtl.baseRoughness
                if srcMtl.metalnessMode == 1 do metal = 1.0
            ) catch ()
            try (ior = srcMtl.ior) catch ()
            try (refr = srcMtl.refractionAmount) catch ()
            try (if refr == 0.0 do refr = srcMtl.levelRefract) catch ()
            try (sheen = srcMtl.sheenAmount) catch ()
            try (emis = srcMtl.selfIllumLevel) catch ()
            try (if srcMtl.baseTexmapOn do albedoPath = extractOrBakeTexmap srcMtl.baseTexmap "Albedo" safeName texDir doBake forceOverwrite:forceUpdate) catch ()
            try (if srcMtl.baseRoughnessTexmapOn do roughPath = extractOrBakeTexmap srcMtl.baseRoughnessTexmap "Roughness" safeName texDir doBake forceOverwrite:forceUpdate) catch ()
            try (if srcMtl.baseBumpTexmapOn do normPath = extractOrBakeTexmap srcMtl.baseBumpTexmap "Normal" safeName texDir doBake forceOverwrite:forceUpdate) catch ()
            try (if srcMtl.metalnessTexmapOn do metalPath = extractOrBakeTexmap srcMtl.metalnessTexmap "Metallic" safeName texDir doBake forceOverwrite:forceUpdate) catch ()
            try (if srcMtl.opacityTexmapOn and srcMtl.opacityTexmap != undefined do opacPath = extractOrBakeTexmap srcMtl.opacityTexmap "Opacity" safeName texDir doBake forceOverwrite:forceUpdate) catch ()
            try (if opacPath == "" and srcMtl.texmapOnOpacity and srcMtl.texmapOpacity != undefined do opacPath = extractOrBakeTexmap srcMtl.texmapOpacity "Opacity" safeName texDir doBake forceOverwrite:forceUpdate) catch ()

            if emis > 0.1 then (
                ueMaster = "MM_ArchViz_Emissive"
            ) else if refr > 0.2 or matchPattern m.name pattern:"*glass*" or matchPattern m.name pattern:"*stekl*" or matchPattern m.name pattern:"*window*" or matchPattern m.name pattern:"*water*" then (
                ueMaster = "MM_ArchViz_Glass"
                if refr < 0.2 do refr = 0.9
                opac = amax #(0.08, 1.0 - (refr * 0.88))
                if rough > 0.15 and refr > 0.8 do rough = 0.03
            ) else if opacPath != "" or matchPattern m.name pattern:"*leaf*" or matchPattern m.name pattern:"*leaves*" or matchPattern m.name pattern:"*foliage*" or matchPattern m.name pattern:"*trava*" then (
                ueMaster = "MM_ArchViz_Foliage"
            ) else if sheen > 0.1 or (isFabricTextMatch m.name) or (isFabricTextMatch albedoPath) then (
                ueMaster = "MM_ArchViz_Fabric"
                if sheen < 0.15 do sheen = 0.35
            )
        )

        local js = "    {\n"
        js += "      \"name\": \"" + safeName + "\",\n"
        js += "      \"original_name\": \"" + (jsonEscapeSafe m.name) + "\",\n"
        js += "      \"max_class\": \"" + cls + "\",\n"
        js += "      \"ue_master_material\": \"" + ueMaster + "\",\n"
        js += "      \"ue_asset_path\": \"" + (jsonEscapeSafe ueAssetPath) + "\",\n"
        js += "      \"force_update\": " + (if forceUpdate then "true" else "false") + ",\n"
        js += "      \"max_sig\": \"" + (jsonEscapeSafe maxSig) + "\",\n"
        js += "      \"base_color\": [" + (safeJsonNum rCol) + ", " + (safeJsonNum gCol) + ", " + (safeJsonNum bCol) + "],\n"
        js += "      \"roughness\": " + (safeJsonNum rough) + ",\n"
        js += "      \"metallic\": " + (safeJsonNum metal) + ",\n"
        js += "      \"opacity\": " + (safeJsonNum opac) + ",\n"
        js += "      \"refraction\": " + (safeJsonNum refr) + ",\n"
        js += "      \"ior\": " + (safeJsonNum ior) + ",\n"
        js += "      \"sheen\": " + (safeJsonNum sheen) + ",\n"
        js += "      \"emissive_intensity\": " + (safeJsonNum emis) + ",\n"
        js += "      \"textures\": {\n"
        js += "        \"albedo\": \"" + albedoPath + "\",\n"
        js += "        \"roughness\": \"" + roughPath + "\",\n"
        js += "        \"normal\": \"" + normPath + "\",\n"
        js += "        \"metallic\": \"" + metalPath + "\",\n"
        js += "        \"opacity\": \"" + opacPath + "\"\n"
        js += "      },\n"
        js += "      \"layer_b\": {\n"
        js += "        \"enabled\": " + (if lbEnabled then "true" else "false") + ",\n"
        js += "        \"amount\": " + (safeJsonNum lbAmount) + ",\n"
        js += "        \"base_color\": [" + (safeJsonNum lbR) + ", " + (safeJsonNum lbG) + ", " + (safeJsonNum lbB) + "],\n"
        js += "        \"roughness\": " + (safeJsonNum lbRough) + ",\n"
        js += "        \"metallic\": " + (safeJsonNum lbMetal) + ",\n"
        js += "        \"albedo\": \"" + lbAlbedoPath + "\",\n"
        js += "        \"roughness_tex\": \"" + lbRoughPath + "\",\n"
        js += "        \"normal\": \"" + lbNormPath + "\",\n"
        js += "        \"mask\": \"" + lbMaskPath + "\"\n"
        js += "      }\n"
        js += "    }"
        js
    )

    fn setExportProgress pct stageText statusText:"" = (
        if CoronaToUE5ExporterRollout.open do (
            pbExport.value = pct
            lblProgressStage.text = "Прогресс: " + ((pct as integer) as string) + "% — " + stageText
            if statusText != "" do lblStatus.text = statusText
        )
        notifyQtProgress pct stageText statusText
        try (windows.processPostedMessages()) catch ()
    )

    fn exportScenePackage partialOnly:false scopeMode:unsupplied = (
        if isExportingNow do return false
        local effScope = if scopeMode != unsupplied then scopeMode else (if partialOnly then #selected else #full)
        local isPartialScope = (effScope != #full)

        if effScope == #selected and selection.count == 0 do (
            setStatusText "Выделите хотя бы один объект в сцене для выборочного реимпорта!"
            return false
        )

        local selWithChildren = #()
        local exportNodes = #()
        local selectedLayerNames = #()
        if effScope == #selected then (
            selWithChildren = collectHierarchyNodes (selection as array)
            exportNodes = for o in selWithChildren where superClassOf o == GeometryClass and isValidExportGeom o collect o
        ) else if effScope == #layers then (
            if (getEffScanView()) != 3 do (
                if qtActive then optScanViewMode = 3 else ddlScanView.selection = 3
                scanSceneMaterialsAndCost scopeMode:#layers refreshList:true
            )
            exportNodes = getNodesForSelectedLayers()
            selectedLayerNames = getSelectedLayerNamesList()
            if exportNodes.count == 0 do (
                messageBox "Выберите хотя бы один слой с геометрией в списке '1. Layer Explorer'!" title:"Экспорт по слоям"
                setStatusText "Экспорт отменён: в выбранных слоях нет геометрии."
                return false
            )
        ) else (
            exportNodes = for o in geometry where isValidExportGeom o collect o
        )

        -- 1. Refresh UE5 material index & identify exact generation cost before export
        setExportProgress 2 "Сверка материалов с Unreal Engine 5 и расчёт сметы..."
        local pyModExp = refreshUE5MaterialIndex()
        local preStats = computeCostForNodes exportNodes fastScan:false refreshUE5:false
        local reqCost = roundHalfGen preStats[1]
        local preUniqueCount = preStats[2]
        local preLayeredCount = preStats[3]
        local preNewCount = preStats[4]
        local preReusedCount = preStats[5]
        local preUpdatedCount = preStats[6]

        refreshCreditsUI syncServer:false forceReload:false
        local mObj = getCreditsMod forceReload:false
        if reqCost > 0.0 then (
            if mObj == undefined then (
                messageBox "Не удалось подключиться к модулю биллинга (pbr_credits_ledger.py).\nЭкспорт остановлен для защиты баланса." title:"Corona -> UE5 Credits Error"
                return false
            )
            if (cachedBalance + 0.001) < reqCost do (
                messageBox ("Недостаточно AI-генераций!\n\nТребуется: " + (fmtGens reqCost) + " Gens (" + (preNewCount as string) + " новых из " + (preUniqueCount as string) + " матов, Layered: " + (preLayeredCount as string) + ")\nДоступно: " + (fmtGens cachedBalance) + " Gens\n\nПополните баланс или активируйте ключ в плагине Corona ComfyPBR.") title:"Недостаточно генераций"
                setStatusText ("Экспорт отменён: недостаточно генераций (" + (fmtGens cachedBalance) + " < " + (fmtGens reqCost) + ").")
                return false
            )
            local scopeLabel = case effScope of (
                #selected: "Выборочный реимпорт"
                #layers: ("Экспорт слоёв Scene Explorer (" + (selectedLayerNames.count as string) + " сл.)")
                default: "Полный экспорт сцены"
            )
            local afterBal = amax #(0.0, cachedBalance - reqCost)
            local qMsg = scopeLabel + " в UE5:\n\n" +
                "• Объектов геометрии: " + (exportNodes.count as string) + "\n" +
                "• Уникальных материалов: " + (preUniqueCount as string) + " (новых: " + (preNewCount as string) + ", в UE5 без изменений: " + (preReusedCount as string) + ", обновить: " + (preUpdatedCount as string) + ", Layer B: " + (preLayeredCount as string) + ")\n" +
                "• СТОИМОСТЬ: " + (fmtGens reqCost) + " генераций (0.5/нов.мат + 0.5 за LayerB; уже существующие в UE5 — 0 Gens)\n" +
                "• Баланс после экспорта: " + (fmtGens afterBal) + " Gens\n\n" +
                "Начать экспорт и списать " + (fmtGens reqCost) + " Gens?"
            if not (queryBox qMsg title:"Подтверждение экспорта Corona -> UE5") do (
                setStatusText "Экспорт отменён пользователем (баланс не списан)."
                return false
            )
            local detPrefix = if effScope == #selected then "partial:" else if effScope == #layers then "layers:" else "full:"
            local detStr = detPrefix + "objs=" + (exportNodes.count as string) + ",mtls=" + (preUniqueCount as string) + ",layered=" + (preLayeredCount as string)
            local consRes = (mObj.ms_consume_credits reqCost "corona_export_consumed" detStr) as string
            local consParts = filterString consRes "|"
            if consParts.count == 0 or consParts[1] != "OK" do (
                local errTxt = if consParts.count >= 3 then consParts[3] else consRes
                messageBox ("Ошибка списания генераций:\n" + errTxt) title:"Ошибка биллинга"
                refreshCreditsUI syncServer:false
                return false
            )
            if consParts.count >= 2 do (
                try (cachedBalance = consParts[2] as float) catch ()
                refreshCreditsUI syncServer:false
            )
        )

        isExportingNow = true
        local consumedOk = (reqCost > 0.0)
        try (
            setExportProgress 5 "Подготовка папок и сбор геометрии..."

            local outDir = if qtActive then optExportDir else edtExportDir.text
            local texDir = outDir + "\\Textures"
            makeDir outDir all:true
            makeDir texDir all:true

            local doBake = if qtActive then optBakeProcedural else chkBakeProcedural.checked

            local progMsg12 = if effScope == #selected then "Анализ материалов выделенного объекта..." else if effScope == #layers then "Анализ материалов выбранных слоёв..." else "Анализ материалов и слоёв всей сцены..."
            setExportProgress 12 progMsg12
            local uniqueMtls = #()
            local objJsonList = #()
            for oi = 1 to exportNodes.count do (
                local o = exportNodes[oi]
                local mNames = #()
                local leafMtls = collectObjectLeafMaterials o fastScan:false
                for lm in leafMtls do (
                    if findItem uniqueMtls lm == 0 do append uniqueMtls lm
                    append mNames ("\"" + (sanitizeName lm.name) + "\"")
                )
                local mArrStr = "["
                for k = 1 to mNames.count do (
                    mArrStr += mNames[k]
                    if k < mNames.count do mArrStr += ", "
                )
                mArrStr += "]"
                local hnd = 0
                try (hnd = o.inode.handle) catch ()
                local lyrPath = getNodeLayerPath o
                local oCent = [0, 0, 0]
                try (oCent = o.center) catch ()
                local posStr = "[" + (safeJsonNum oCent.x) + ", " + (safeJsonNum (-oCent.y)) + ", " + (safeJsonNum oCent.z) + "]"
                local ojs = "    { \"name\": \"" + (sanitizeName o.name) + "\", \"original_name\": \"" + (substituteString o.name "\"" "'") + "\", \"layer\": \"" + (substituteString lyrPath "\"" "'") + "\", \"max_handle\": " + (hnd as string) + ", \"ue_pos_cm\": " + posStr + ", \"materials\": " + mArrStr + " }"
                append objJsonList ojs
                if mod oi 40 == 0 do try (windows.processPostedMessages()) catch ()
            )

            local mtlJsonList = #()
            local reusedMtlJsonList = #()
            local totalM = amax #(1, uniqueMtls.count)
            for idx = 1 to uniqueMtls.count do (
                local m = uniqueMtls[idx]
                local curPct = 15 + ((45.0 * idx / totalM) as integer)
                local clsInfo = classifyMaterialAgainstUE5 m pyMod:pyModExp
                local stTag = clsInfo[1]
                local uePath = clsInfo[2]
                local mSig = clsInfo[3]
                if stTag == "REUSE" then (
                    setExportProgress curPct ("Проверка материалов (" + (idx as string) + " / " + (uniqueMtls.count as string) + ")") statusText:("Уже в UE5 (пропуск): " + m.name)
                    local rjs = "    { \"name\": \"" + (sanitizeName m.name) + "\", \"original_name\": \"" + (jsonEscapeSafe m.name) + "\", \"ue_asset_path\": \"" + (jsonEscapeSafe uePath) + "\", \"max_sig\": \"" + (jsonEscapeSafe mSig) + "\" }"
                    append reusedMtlJsonList rjs
                ) else (
                    local isUpd = (stTag == "UPDATE")
                    local stVerb = if isUpd then "Реимпорт изменённого: " else "Новый материал: "
                    setExportProgress curPct ("Обработка материалов и текстур (" + (idx as string) + " / " + (uniqueMtls.count as string) + ")") statusText:(stVerb + m.name)
                    append mtlJsonList (serializeSingleMtl m texDir doBake maxSig:mSig ueAssetPath:uePath forceUpdate:isUpd)
                )
            )

            setExportProgress 65 "Сбор источников света CoronaSun / CoronaLight и камер..."

            local lightJsonList = #()
            local camJsonList = #()
            local doLights = if qtActive then optExportLightsCams else chkExportLightsCams.checked
            if doLights do (
                local candLightsCams = if effScope == #selected then selWithChildren else if effScope == #layers then (
                    for o in objects where isValidNode o and findItem selectedLayerNames (getNodeLayerPath o) != 0 collect o
                ) else (objects as array)
                for o in candLightsCams where superClassOf o == light or superClassOf o == camera or matchPattern (classOf o as string) pattern:"*Corona*" do (
                    local cls = classOf o as string
                    local hnd = 0
                    try (hnd = o.inode.handle) catch ()
                    local lyrPath = getNodeLayerPath o
                    local rotE = eulerAngles 0 0 0
                    try (rotE = o.transform.rotationPart as eulerAngles) catch ()
                    local hasTgt = (o.target != undefined)
                    local tgtPosStr = "null"
                    if hasTgt do (
                        tgtPosStr = "[" + (safeJsonNum o.target.pos.x) + ", " + (safeJsonNum (-o.target.pos.y)) + ", " + (safeJsonNum o.target.pos.z) + "]"
                    )
                    if cls == "CoronaSun" then (
                        local ljs = "    {\n"
                        ljs += "      \"name\": \"" + (sanitizeName o.name) + "\",\n"
                        ljs += "      \"layer\": \"" + (substituteString lyrPath "\"" "'") + "\",\n"
                        ljs += "      \"max_handle\": " + (hnd as string) + ",\n"
                        ljs += "      \"type\": \"CoronaSun\",\n"
                        ljs += "      \"ue_actor_class\": \"DirectionalLight\",\n"
                        ljs += "      \"pos_cm\": [" + (safeJsonNum o.pos.x) + ", " + (safeJsonNum (-o.pos.y)) + ", " + (safeJsonNum o.pos.z) + "],\n"
                        ljs += "      \"target_pos_cm\": " + tgtPosStr + ",\n"
                        ljs += "      \"rot_deg\": [" + (safeJsonNum rotE.x) + ", " + (safeJsonNum (-rotE.y)) + ", " + (safeJsonNum (-rotE.z)) + "],\n"
                        ljs += "      \"lumen_intensity_lux\": 10.0\n"
                        ljs += "    }"
                        append lightJsonList ljs
                    ) else if cls == "CoronaLight" then (
                        local w = 50.0; local l = 50.0; local intens = 15.0
                        try (w = o.width; l = o.length; intens = o.intensity) catch ()
                        local ljs = "    {\n"
                        ljs += "      \"name\": \"" + (sanitizeName o.name) + "\",\n"
                        ljs += "      \"layer\": \"" + (substituteString lyrPath "\"" "'") + "\",\n"
                        ljs += "      \"max_handle\": " + (hnd as string) + ",\n"
                        ljs += "      \"type\": \"CoronaLight\",\n"
                        ljs += "      \"ue_actor_class\": \"RectLight\",\n"
                        ljs += "      \"pos_cm\": [" + (safeJsonNum o.pos.x) + ", " + (safeJsonNum (-o.pos.y)) + ", " + (safeJsonNum o.pos.z) + "],\n"
                        ljs += "      \"target_pos_cm\": " + tgtPosStr + ",\n"
                        ljs += "      \"rot_deg\": [" + (safeJsonNum rotE.x) + ", " + (safeJsonNum (-rotE.y)) + ", " + (safeJsonNum (-rotE.z)) + "],\n"
                        ljs += "      \"width_cm\": " + (safeJsonNum w) + ",\n"
                        ljs += "      \"length_cm\": " + (safeJsonNum l) + ",\n"
                        ljs += "      \"corona_intensity\": " + (safeJsonNum intens) + "\n"
                        ljs += "    }"
                        append lightJsonList ljs
                    ) else if cls == "CoronaCam" then (
                        local fovDeg = 60.0
                        try (fovDeg = o.fov) catch ()
                        local cjs = "    {\n"
                        cjs += "      \"name\": \"" + (sanitizeName o.name) + "\",\n"
                        cjs += "      \"layer\": \"" + (substituteString lyrPath "\"" "'") + "\",\n"
                        cjs += "      \"max_handle\": " + (hnd as string) + ",\n"
                        cjs += "      \"type\": \"CoronaCam\",\n"
                        cjs += "      \"ue_actor_class\": \"CineCameraActor\",\n"
                        cjs += "      \"pos_cm\": [" + (safeJsonNum o.pos.x) + ", " + (safeJsonNum (-o.pos.y)) + ", " + (safeJsonNum o.pos.z) + "],\n"
                        cjs += "      \"target_pos_cm\": " + tgtPosStr + ",\n"
                        cjs += "      \"rot_deg\": [" + (safeJsonNum rotE.x) + ", " + (safeJsonNum (-rotE.y)) + ", " + (safeJsonNum (-rotE.z)) + "],\n"
                        cjs += "      \"fov_deg\": " + (safeJsonNum fovDeg) + "\n"
                        cjs += "    }"
                        append camJsonList cjs
                    )
                )
            )

            local fbxFileName = if isPartialScope then "selected_patch.fbx" else "scene_geometry.fbx"
            local fbxPath = outDir + "\\" + fbxFileName

            local manifestPath = outDir + "\\corona_to_ue_manifest.json"
            local mf = createFile manifestPath encoding:#utf8
            format "{\n" to:mf
            format "  \"project\": \"Corona_to_UE5_Clean_Package\",\n" to:mf
            local scopeStrJson = if effScope == #selected then "partial" else if effScope == #layers then "layers" else "full"
            format "  \"export_scope\": \"%\",\n" scopeStrJson to:mf
            format "  \"is_partial_reimport\": %,\n" (if isPartialScope then "true" else "false") to:mf
            local lyrJson = "["
            for li = 1 to selectedLayerNames.count do (
                lyrJson += "\"" + (substituteString selectedLayerNames[li] "\"" "'") + "\""
                if li < selectedLayerNames.count do lyrJson += ", "
            )
            lyrJson += "]"
            format "  \"exported_layers\": %,\n" lyrJson to:mf
            format "  \"fbx_file\": \"%\",\n" (substituteString fbxPath "\\" "/") to:mf
            format "  \"objects_count\": %,\n" objJsonList.count to:mf
            format "  \"materials_count\": %,\n" mtlJsonList.count to:mf
            format "  \"reused_materials_count\": %,\n" reusedMtlJsonList.count to:mf
            format "  \"unique_materials_count\": %,\n" preUniqueCount to:mf
            format "  \"layered_materials_count\": %,\n" preLayeredCount to:mf
            format "  \"credits_cost\": %,\n" (safeJsonNum reqCost) to:mf
            format "  \"lights_count\": %,\n" lightJsonList.count to:mf
            format "  \"cameras_count\": %,\n" camJsonList.count to:mf
            format "  \"objects\": [\n" to:mf
            for i = 1 to objJsonList.count do (
                format "%" objJsonList[i] to:mf
                if i < objJsonList.count then format ",\n" to:mf else format "\n" to:mf
            )
            format "  ],\n" to:mf
            format "  \"materials\": [\n" to:mf
            for i = 1 to mtlJsonList.count do (
                format "%" mtlJsonList[i] to:mf
                if i < mtlJsonList.count then format ",\n" to:mf else format "\n" to:mf
            )
            format "  ],\n" to:mf
            format "  \"reused_materials\": [\n" to:mf
            for i = 1 to reusedMtlJsonList.count do (
                format "%" reusedMtlJsonList[i] to:mf
                if i < reusedMtlJsonList.count then format ",\n" to:mf else format "\n" to:mf
            )
            format "  ],\n" to:mf
            format "  \"lights\": [\n" to:mf
            for i = 1 to lightJsonList.count do (
                format "%" lightJsonList[i] to:mf
                if i < lightJsonList.count then format ",\n" to:mf else format "\n" to:mf
            )
            format "  ],\n" to:mf
            format "  \"cameras\": [\n" to:mf
            for i = 1 to camJsonList.count do (
                format "%" camJsonList[i] to:mf
                if i < camJsonList.count then format ",\n" to:mf else format "\n" to:mf
            )
            format "  ]\n" to:mf
            format "}\n" to:mf
            close mf

            local fixedNormalsCount = 0
            local tempProxyNodes = #()
            local renamedOrigNodes = #()
            local renamedOrigNames = #()
            local fbxExportList = #()

            if exportNodes.count > 0 do (
                setExportProgress 78 ("Экспорт 3D-геометрии и центрирование пивотов (" + fbxFileName + ")...") statusText:("Подготовка и выгрузка FBX (" + (exportNodes.count as string) + " объектов)...")
                local prevSel = selection as array
                local hiddenLayers = #()
                for i = 0 to (LayerManager.count - 1) do (
                    local lyr = LayerManager.getLayer i
                    if not lyr.on do (
                        append hiddenLayers lyr
                        lyr.on = true
                    )
                )
                local hiddenNodes = for o in exportNodes where o.isNodeHidden collect o
                for o in hiddenNodes do o.isNodeHidden = false

                disableSceneRedraw()
                try (
                    with undo off (
                        local doFixNorm = if qtActive then optAutoFixNormals else chkAutoFixNormals.checked
                        local nTotalExp = amax #(1, exportNodes.count)
                        for oi_exp = 1 to exportNodes.count do (
                            local o = exportNodes[oi_exp]
                            if mod oi_exp 5 == 0 or oi_exp == 1 do (
                                local ep = 75 + ((11.0 * oi_exp / nTotalExp) as integer)
                                setExportProgress ep ("Подготовка геометрии и пивотов (" + (oi_exp as string) + " / " + (nTotalExp as string) + ")...") statusText:("Меш: " + o.name)
                            )
                            local wInfo = if doFixNorm then (inspectNodeWindingAndVolume o) else #(false, false, false, false, 0.0)
                            local detNeg = wInfo[1]
                            local closedInv = wInfo[2]
                            local isClosed = wInfo[4]
                            local needsFlip = doFixNorm and (closedInv or ((not isClosed) and detNeg))

                            local origName = o.name
                            local px = undefined
                            try (
                                o.name = "__MAX_UE5_ORIG_" + origName
                                append renamedOrigNodes o
                                append renamedOrigNames origName
                                px = snapshot o
                                if px != undefined then (
                                    try (px.parent = undefined) catch ()
                                    px.name = origName
                                    px.material = o.material
                                    px.pivot = o.center
                                    if needsFlip do (
                                        meshop.flipNormals px #{1..px.numfaces}
                                        update px
                                        fixedNormalsCount += 1
                                    )
                                    append tempProxyNodes px
                                    append fbxExportList px
                                ) else (
                                    append fbxExportList o
                                )
                            ) catch (
                                if px != undefined do try (delete px) catch ()
                                append fbxExportList o
                            )
                        )

                        setExportProgress 88 ("Экспорт FBX (" + (fbxExportList.count as string) + " мешей)...") statusText:"Запись FBX на диск (подождите)..."
                        select fbxExportList
                        FBXExporterSetParam "SmoothingGroups" true
                        FBXExporterSetParam "TangentsandBinormals" true
                        FBXExporterSetParam "EmbedTextures" false
                        FBXExporterSetParam "UpAxis" "Z"
                        FBXExporterSetParam "ConvertUnit" "cm"
                        exportFile fbxPath #noPrompt selectedOnly:true using:FBXEXP
                    )
                ) catch ()
                try (
                    with undo off (
                        for px in tempProxyNodes do try (delete px) catch ()
                        for ri = 1 to renamedOrigNodes.count do (
                            try (
                                if isValidNode renamedOrigNodes[ri] do renamedOrigNodes[ri].name = renamedOrigNames[ri]
                            ) catch ()
                        )
                    )
                ) catch ()
                enableSceneRedraw()

                for o in hiddenNodes do o.isNodeHidden = true
                for lyr in hiddenLayers do lyr.on = false
                select prevSel
            )

            local doAutoUE5 = if qtActive then optAutoSendUE5 else chkAutoSendUE5.checked
            if doAutoUE5 then (
                setExportProgress 92 "Передача пакета в открытый Unreal Engine 5..."
                try (
                    local flagF = createFile (outDir + "\\ue_auto_import.flag")
                    format "import_ready" to:flagF
                    close flagF
                    local pDirPy = substituteString (CoronaToUE5_ResolvePluginDir()) "\\" "/"
                    local outDirPy = substituteString outDir "\\" "/"
                    python.Execute ("import sys; d='" + pDirPy + "'; (sys.path.insert(0, d) if d not in sys.path else None); import corona_ue5_exporter_qt; corona_ue5_exporter_qt.trigger_ue5_bridge_async(r'" + outDirPy + "')")
                ) catch ()
                local normTag = if fixedNormalsCount > 0 then (" | фикс нормалей: " + (fixedNormalsCount as string)) else ""
                local reuseTag = if reusedMtlJsonList.count > 0 then (", из UE5: " + (reusedMtlJsonList.count as string)) else ""
                if effScope == #selected then (
                    setExportProgress 100 "Выборочный реимпорт отправлен в UE5!" statusText:("Обновлено мешей: " + (objJsonList.count as string) + ", матов экспортир: " + (mtlJsonList.count as string) + reuseTag + " (" + (fmtGens reqCost) + " Gens" + normTag + ")")
                ) else if effScope == #layers then (
                    setExportProgress 100 "Слои Scene Explorer отправлены в UE5!" statusText:("Слоёв: " + (selectedLayerNames.count as string) + ", мешей: " + (objJsonList.count as string) + ", матов экспортир: " + (mtlJsonList.count as string) + reuseTag + " (" + (fmtGens reqCost) + " Gens" + normTag + ")")
                ) else (
                    setExportProgress 100 "Полная сцена отправлена в UE5!" statusText:("Объектов: " + (objJsonList.count as string) + ", матов экспортир: " + (mtlJsonList.count as string) + reuseTag + " (" + (fmtGens reqCost) + " Gens" + normTag + ")")
                )
            ) else (
                local normTag = if fixedNormalsCount > 0 then (" | фикс нормалей: " + (fixedNormalsCount as string)) else ""
                local reuseTag = if reusedMtlJsonList.count > 0 then (", из UE5: " + (reusedMtlJsonList.count as string)) else ""
                setExportProgress 100 "Пакет сохранен на диск!" statusText:("Мешей: " + (objJsonList.count as string) + ", матов экспортир: " + (mtlJsonList.count as string) + reuseTag + " (" + (fmtGens reqCost) + " Gens" + normTag + ")")
            )
            refreshCreditsUI syncServer:false
            scanSceneMaterialsAndCost scopeMode:lastScanScope refreshList:false
            isExportingNow = false
            true
        ) catch (
            local errMsg = getCurrentException()
            if consumedOk and mObj != undefined do (
                try (mObj.ms_refund_credits reqCost "corona_export_error") catch ()
            )
            refreshCreditsUI syncServer:false
            scanSceneMaterialsAndCost scopeMode:lastScanScope refreshList:false
            setExportProgress 0 "Ошибка экспорта (генерации возвращены)" statusText:("Ошибка: " + errMsg)
            isExportingNow = false
            false
        )
    )

    on CoronaToUE5ExporterRollout open do (
        refreshCreditsUI syncServer:true forceReload:true
        refreshPolyTable()
        scanSceneMaterialsAndCost scopeMode:#all refreshList:true
        CoronaToUE5LiveCallback = NodeEventCallback mouseUp:true delay:400 controllerOtherEvent:CoronaToUE5_OnNodeChanged geometryChanged:CoronaToUE5_OnNodeChanged materialStructured:CoronaToUE5_OnNodeChanged materialOtherEvent:CoronaToUE5_OnNodeChanged nameChanged:CoronaToUE5_OnNodeChanged
        try (
            callbacks.addScript #selectionSetChanged "try (if CoronaToUE5ExporterRollout != undefined and CoronaToUE5ExporterRollout.open do CoronaToUE5ExporterRollout.updateSelectionCostOnly()) catch ()" id:#CoronaToUE5SelCB
        ) catch ()
    )
    on CoronaToUE5ExporterRollout close do (
        tmrLiveDebounce.active = false
        CoronaToUE5LiveCallback = undefined
        try(callbacks.removeScripts id:#CoronaToUE5SelCB)catch()
        gc light:true
    )
    on tmrLiveDebounce tick do (
        tmrLiveDebounce.active = false
        if chkLiveWatchSelected.checked and selection.count > 0 do (
            exportScenePackage partialOnly:true
        )
    )
    on btnSyncCredits pressed do (
        refreshCreditsUI syncServer:true forceReload:true
        scanSceneMaterialsAndCost scopeMode:lastScanScope refreshList:false
        lblStatus.text = "Баланс синхронизирован с сервером: " + (fmtGens cachedBalance) + " Gens."
    )
    on btnOpenWalletStudio pressed do (
        try (
            if openCoronaComfyPBRDialog != undefined then openCoronaComfyPBRDialog()
            else (
                local studioMs = (getDir #userStartupScripts) + @"\Corona_ComfyPBR_Studio.ms"
                if not (doesFileExist studioMs) do studioMs = (CoronaToUE5_ResolvePluginDir()) + "Corona_ComfyPBR_Studio.ms"
                if doesFileExist studioMs do fileIn studioMs
            )
            lblStatus.text = "Открыт Corona ComfyPBR Studio (кошелёк и ввод ключей в разделе Account)."
        ) catch (
            local mObj = getCreditsMod forceReload:false
            if mObj != undefined do try (mObj.ms_open_buy_url()) catch ()
        )
    )
    on btnScanAll pressed do (
        if ddlScanView.selection == 3 do ddlScanView.selection = 1
        scanSceneMaterialsAndCost scopeMode:#all refreshList:true
    )
    on btnScanSel pressed do (
        if ddlScanView.selection == 3 do ddlScanView.selection = 2
        scanSceneMaterialsAndCost scopeMode:#selected refreshList:true
    )
    on btnScanLayers pressed do (
        ddlScanView.selection = 3
        scanSceneMaterialsAndCost scopeMode:#layers refreshList:true
    )
    on ddlScanView selected idx do (
        if idx == 3 then scanSceneMaterialsAndCost scopeMode:#layers refreshList:true
        else scanSceneMaterialsAndCost scopeMode:(if lastScanScope == #selected then #selected else #all) refreshList:true
    )
    on lbxSceneAudit selectionEnd do (
        if ddlScanView.selection == 3 do updateSelectedLayersSummary()
    )
    on lbxSceneAudit doubleClicked idx do (
        if idx > 0 and idx <= auditRowNodes.count do (
            local nodesArr = for n in auditRowNodes[idx] where isValidNode n collect n
            if nodesArr.count > 0 do (
                select nodesArr
                max tool zoomextents
            )
        )
    )
    on btnRefreshPolys pressed do refreshPolyTable()
    on btnDisableDisp pressed do disableHeavyDisplacement()
    on btnConvertRWMSAll pressed do convertRealWorldMapSizeToUVW scopeMode:#all
    on btnConvertRWMSSel pressed do convertRealWorldMapSizeToUVW scopeMode:#selected
    on btnOpenSummary pressed do (max file summary)
    on lbxPolys doubleClicked idx do (
        if idx > 0 and idx <= sortedNodes.count and isValidNode sortedNodes[idx] do (
            select sortedNodes[idx]
            max tool zoomextents
        )
    )
    on chkLiveWatchSelected changed state do (
        optLiveWatchSelected = state
    )
    on chkSkipExistingUE5 changed state do (
        optSkipExistingUE5 = state
        scanSceneMaterialsAndCost scopeMode:lastScanScope refreshList:true
    )
    on btnReimportSelected pressed do exportScenePackage partialOnly:true scopeMode:#selected
    on btnExportLayers pressed do exportScenePackage partialOnly:false scopeMode:#layers
    on btnExportUE5 pressed do exportScenePackage partialOnly:false scopeMode:#full
)

global openCoronaToUE5ExporterQt
fn openCoronaToUE5ExporterQt forceReload:false = (
    local opened = false
    try (
        local pDirPy = substituteString (CoronaToUE5_ResolvePluginDir()) "\\" "/"
        local reloadCode = if forceReload then "import importlib, studio_qt_theme, pbr_credits_ledger; importlib.reload(studio_qt_theme); importlib.reload(pbr_credits_ledger); importlib.reload(corona_ue5_exporter_qt); " else ""
        local reloadArg = if forceReload then "True" else "False"
        python.Execute ("import sys; d='" + pDirPy + "'; (sys.path.insert(0, d) if d not in sys.path else None); import corona_ue5_exporter_qt; " + reloadCode + "corona_ue5_exporter_qt.show_corona_ue5_exporter_qt(force_reload=" + reloadArg + ")")
        opened = true
    ) catch (
        opened = false
    )
    opened
)

global openCoronaToUE5ExporterDialog
fn openCoronaToUE5ExporterDialog forceReload:false = (
    try(destroyDialog CoronaToUE5ExporterRollout)catch()
    local qtOk = openCoronaToUE5ExporterQt forceReload:forceReload
    if not qtOk do (
        createDialog CoronaToUE5ExporterRollout
    )
)

macroScript CoronaToUE5Exporter
category:"AI ArchViz"
buttonText:"Corona -> UE5"
toolTip:"Open Corona -> UE5 Clean Exporter, Scene Audit & Credits"
(
    on execute do (
        local msFile = CoronaToUE5_ResolveSelfFile()
        if CoronaToUE5ExporterRollout != undefined and openCoronaToUE5ExporterDialog != undefined and CoronaToUE5_LoadedFileDate == (getFileModDate msFile) then (
            openCoronaToUE5ExporterDialog()
        ) else (
            fileIn msFile
        )
    )
)

macroScript CoronaToUE5QuickReimport
category:"AI ArchViz"
buttonText:"UE5 Reimport Sel"
toolTip:"Quick reimport selected object into Unreal Engine 5"
(
    on execute do (
        local msFile = CoronaToUE5_ResolveSelfFile()
        if CoronaToUE5ExporterRollout == undefined or CoronaToUE5_LoadedFileDate != (getFileModDate msFile) do fileIn msFile
        CoronaToUE5ExporterRollout.exportScenePackage partialOnly:true
    )
)

if CoronaToUE5_SilentLoad != true do openCoronaToUE5ExporterDialog forceReload:true
