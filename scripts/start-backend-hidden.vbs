' Hidden launcher for 老马AI工作台 backend (ASCII-only; resolves paths at runtime)
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
bat = dir & "\start-backend-detached.bat"
sh.Run """" & bat & """", 0, False
