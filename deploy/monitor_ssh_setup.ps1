# ===================================================================
#  MONITOR SSH SETUP  --  run on the MONITORING PC, as Administrator
#
#  Lets the Jetson (and engineers who jump through it) reach this PC
#  over SSH, and NOTHING else:
#
#     home --Tailscale--> Jetson --SSH (key only, from Jetson IP only)--> this PC
#                                        the web UI stays on 127.0.0.1:8000
#                                        and is reached through the SSH tunnel
#
#  Why only SSH: the backend API has no login and has endpoints that
#  delete records. It must never listen on a network interface. SSH
#  gives authentication, encryption and port forwarding in one hole.
#
#  Why not Windows file sharing (SMB): it is the main ransomware path,
#  which is exactly what the lab is worried about.
#
#  Usage (elevated PowerShell):
#    .\monitor_ssh_setup.ps1 -JetsonIP 192.168.55.1 -PubKeys jetson.pub,eng1.pub
#    .\monitor_ssh_setup.ps1 ... -MsiPath D:\OpenSSH-Win64-v9.8.msi   # no network
#    .\monitor_ssh_setup.ps1 -Uninstall                               # undo
#
#  The monitoring PC has no internet, so Add-WindowsCapability cannot
#  download anything there. Bring the Win32-OpenSSH MSI on a USB stick
#  (github.com/PowerShell/Win32-OpenSSH/releases) and pass -MsiPath.
#
#  ASCII only: Windows PowerShell 5.1 reads .ps1 with the ANSI codepage.
# ===================================================================
param(
    [string[]]$JetsonIP = @('192.168.55.1'),
    [string[]]$PubKeys = @(),
    [string]$MsiPath = '',
    [ValidateSet('Automatic', 'Manual')]
    [string]$StartupType = 'Automatic',
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$RuleName = 'Reactor-SSH-from-Jetson'
$SshDir = Join-Path $env:ProgramData 'ssh'
$Config = Join-Path $SshDir 'sshd_config'
$Marker = '# --- reactor-remote (managed by monitor_ssh_setup.ps1) ---'

function Say($m) { Write-Host ('  ' + $m) }

$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this from an elevated (Administrator) PowerShell.'
}

# ---- undo ----------------------------------------------------------
if ($Uninstall) {
    if (Get-Service sshd -ErrorAction SilentlyContinue) {
        Stop-Service sshd -ErrorAction SilentlyContinue
        Set-Service sshd -StartupType Disabled
        Say 'sshd stopped and disabled'
    }
    Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Say "firewall rule $RuleName removed"
    Say '(OpenSSH itself is left installed; remove it in Settings > Optional features)'
    return
}

# ---- 1  install ----------------------------------------------------
if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
    if ($MsiPath) {
        Say "installing OpenSSH from $MsiPath"
        $p = Start-Process msiexec.exe -ArgumentList @('/i', "`"$MsiPath`"", '/qn', 'ADDLOCAL=Server') -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "msiexec failed: exit $($p.ExitCode)" }
    } else {
        Say 'installing OpenSSH Server (Windows optional feature, needs network)'
        Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
    }
}
# First start writes the host keys and the default sshd_config.
if (-not (Test-Path $Config)) { Start-Service sshd; Start-Sleep 2; Stop-Service sshd }

# ---- 2  sshd_config: key only --------------------------------------
# sshd uses the FIRST value it reads for each keyword, so our lines go
# at the very top, before the default 'Match Group administrators'.
$lines = @(Get-Content $Config)
$start = [array]::IndexOf($lines, $Marker)
$end = [array]::IndexOf($lines, $Marker + ' end')
if ($start -ge 0 -and $end -ge $start) {
    # Re-running replaces our block instead of stacking a second copy.
    $lines = @(for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($i -lt $start -or $i -gt $end) { $lines[$i] } })
}
$ours = @(
    $Marker,
    'PasswordAuthentication no',
    'KbdInteractiveAuthentication no',
    'PermitEmptyPasswords no',
    'PubkeyAuthentication yes',
    'AllowTcpForwarding local',
    ($Marker + ' end')
)
Set-Content -Path $Config -Value ($ours + $lines) -Encoding Ascii
Say 'sshd_config: password login off, key only, local forwarding only'

# ---- 3  authorized keys --------------------------------------------
# Windows OpenSSH ignores ~/.ssh/authorized_keys for members of
# Administrators and reads administrators_authorized_keys instead.
# That file is IGNORED unless only Administrators and SYSTEM can read it.
$isAdminUser = (Get-LocalGroupMember -SID 'S-1-5-32-544' |
    Where-Object { $_.Name -like "*\$env:USERNAME" }) -ne $null
if ($isAdminUser) {
    $keyFile = Join-Path $SshDir 'administrators_authorized_keys'
} else {
    $keyFile = Join-Path $env:USERPROFILE '.ssh\authorized_keys'
    New-Item -ItemType Directory -Force (Split-Path $keyFile) | Out-Null
}
$have = @()
if (Test-Path $keyFile) { $have = Get-Content $keyFile }
foreach ($pk in $PubKeys) {
    $k = (Get-Content $pk -Raw).Trim()
    if ($have -notcontains $k) { Add-Content -Path $keyFile -Value $k -Encoding Ascii; Say "key added: $(Split-Path $pk -Leaf)" }
    else { Say "key already present: $(Split-Path $pk -Leaf)" }
}
if ($isAdminUser -and (Test-Path $keyFile)) {
    icacls $keyFile /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
    Say "ACL fixed on $keyFile"
}

# ---- 4  firewall: port 22 from the Jetson only ---------------------
# The built-in rule allows port 22 from ANY address. Turn it off and
# allow only the Jetson link address(es).
Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue | Disable-NetFirewallRule
Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name $RuleName -DisplayName $RuleName -Direction Inbound -Protocol TCP `
    -LocalPort 22 -RemoteAddress $JetsonIP -Action Allow -Profile Any | Out-Null
Say "firewall: TCP 22 allowed only from $($JetsonIP -join ', ')"

# ---- 5  service ----------------------------------------------------
Set-Service sshd -StartupType $StartupType
Restart-Service sshd
Say "sshd running ($StartupType start)"
# The MSI installs to Program Files, the optional feature to System32.
$sshdExe = ((Get-CimInstance Win32_Service -Filter "Name='sshd'").PathName).Trim('"')
& $sshdExe -T 2>$null |
    Select-String -Pattern '^(passwordauthentication|pubkeyauthentication|allowtcpforwarding) ' |
    ForEach-Object { Say ('effective: ' + $_.Line) }
