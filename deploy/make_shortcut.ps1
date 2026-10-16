# ===================================================================
#  Create a .lnk shortcut.  Used by monitor_uploader_setup.bat.
#
#  Lives in its own file because building this one-liner inside cmd needs
#  nested quotes, and paths on the monitoring PC contain spaces
#  ("C:\Users\C.F USER\...").
#
#  ASCII only: Windows PowerShell 5.1 reads .ps1 with the ANSI codepage.
# ===================================================================
param(
    [Parameter(Mandatory = $true)][string]$Lnk,
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$WorkDir = ''
)
$ErrorActionPreference = 'Stop'
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($Lnk)
$s.TargetPath = $Target
$s.Arguments = '"' + $Script + '"'
if ($WorkDir) { $s.WorkingDirectory = $WorkDir }
$s.WindowStyle = 7          # minimized; pythonw shows no window anyway
$s.Save()
