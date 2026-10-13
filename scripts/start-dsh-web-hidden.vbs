' Hidden launcher for dsh web UI (ASCII-only; resolves paths at runtime)
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
bat = dir & "\start-dsh-web-detached.bat"
sh.Run """" & bat & """", 0, False
