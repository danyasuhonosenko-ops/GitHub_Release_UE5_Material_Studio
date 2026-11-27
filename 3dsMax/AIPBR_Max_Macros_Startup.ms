-- ============================================================================
-- Silent Startup Macro Loader for Corona -> UE5 Exporter (installed 3ds Max)
-- Loads Corona_to_UE5_Exporter.ms cleanly without auto-popping the window at boot.
-- ============================================================================
(
    global CoronaToUE5_SilentLoad = true
    local candidates = #(
        (getDir #userScripts) + @"\AIPBRMaterialStudio\Corona_to_UE5_Exporter.ms",
        (getDir #userStartupScripts) + @"\AIPBRMaterialStudio\Corona_to_UE5_Exporter.ms"
    )
    for p in candidates do (
        if doesFileExist p do (
            try (fileIn p) catch ()
            exit
        )
    )
    CoronaToUE5_SilentLoad = false
)
