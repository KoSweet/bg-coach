' bg-coach launcher for Windows: starts the app WITHOUT a console window.
' Double-click this file (or the "bg-coach" shortcut). Quit from the app's Quit button
' or the overlay's x menu. Output goes to data\app.log.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
pyw = dir & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pyw) Then
  ' first run: install (shows one window while it downloads), then set up logging + shortcut
  rc = sh.Run("cmd /c uv sync && .venv\Scripts\python.exe -m bgcoach.cli setup --shortcut || pause", 1, True)
  If Not fso.FileExists(pyw) Then
    MsgBox "bg-coach could not be installed. Install uv from https://docs.astral.sh/uv/ and try again.", 16, "bg-coach"
    WScript.Quit 1
  End If
End If
sh.Run """" & pyw & """ -m bgcoach.cli ui", 0, False
