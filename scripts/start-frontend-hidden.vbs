' Hidden launcher for 老马AI工作台 frontend dev server (ASCII-only; resolves paths at runtime)
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
bat = dir & "\start-frontend-detached.bat"
sh.Run """" & bat & """", 0, False
