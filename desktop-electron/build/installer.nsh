!macro KillLaomaProcess imageName
  DetailPrint "Stopping ${imageName} if running..."
  nsExec::ExecToLog 'taskkill /IM ${imageName}'
  Sleep 800
  nsExec::ExecToLog 'taskkill /F /T /IM ${imageName}'
!macroend

!macro customInit
  ; Stop the packaged app and all managed child processes before install.
  !insertmacro KillLaomaProcess "LaomaAI.exe"
  !insertmacro KillLaomaProcess "supervisor.exe"
  !insertmacro KillLaomaProcess "backend.exe"
  !insertmacro KillLaomaProcess "automation-worker.exe"
  !insertmacro KillLaomaProcess "celery-worker.exe"
  !insertmacro KillLaomaProcess "redis-server.exe"
  Sleep 1500
!macroend

!macro customInstall
  CreateShortCut "$DESKTOP\老马AI工作台.lnk" "$INSTDIR\LaomaAI.exe"
!macroend

!macro customUnInstall
  Delete "$DESKTOP\老马AI工作台.lnk"
!macroend
