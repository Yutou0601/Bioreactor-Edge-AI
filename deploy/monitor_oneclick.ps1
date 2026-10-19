# ===================================================================
#  ONE-CLICK INSTALL  --  monitoring PC, architecture B
#
#  Double-click deploy\monitor_oneclick.bat (or the copy on the USB kit).
#  It does, in order, what docs/system/<install checklist> says by hand:
#
#    1 find the project folder   (this script's own repo, or search disks)
#    2 update the code           (git pull if online; else the USB kit's
#                                 offline_files\, old files backed up first)
#    3 find the CSV folder       (the one the vendor logger is writing NOW)
#    4 read the ingest token     (USB kit ingest_token.txt, else .env)
#    5 write edge_backend\.env   (UTF-8 -- see note below)
#    6 park the old autostart    (architecture A: BTP_monitor.bat / START.bat
#                                 shortcuts -> Desktop backup folder, not deleted)
#    7 run monitor_uploader_setup.bat (python, USB link, test upload,
#                                 reconcile, autostart, desktop shortcuts)
#    8 open the control panel
#
#  -DryRun   show what it found and what it WOULD do; change nothing.
#  -Yes      do not ask for confirmation (CSV folder, project folder).
#
#  Why .env is written here, in UTF-8, before setup.bat runs:
#    setup.bat asks for the CSV folder with `set /p` and writes it with
#    cmd `echo`, i.e. in the ANSI codepage (cp950).  config.py reads .env
#    as UTF-8, so a folder name with Chinese characters becomes garbage and
#    the uploader cannot find it -- while setup.bat's own folder check (done
#    in cmd) still passes.  Pre-filling the keys means setup.bat never asks.
#
#  ASCII only: Windows PowerShell 5.1 reads .ps1 with the ANSI codepage.
# ===================================================================
param(
    [switch]$DryRun,
    [switch]$Yes,
    [string]$Project = '',
    [string]$CsvDir = ''
)
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$Utf8 = New-Object System.Text.UTF8Encoding $false

function Say([string]$m, [string]$c = 'Gray') { Write-Host ('  ' + $m) -ForegroundColor $c }
function Step([string]$m) { Write-Host ''; Write-Host ('== ' + $m) -ForegroundColor Cyan }
function Ask([string]$q) {
    if ($Yes -or $DryRun) { return $true }
    $a = Read-Host ('  ' + $q + ' [Y/n]')
    return ($a -eq '' -or $a -match '^[yY]')
}
# A full project has the backend entry point too. Checking config.py alone also matches a
# copied USB kit's offline_files\ (it carries config.py) -- the first test picked exactly that.
function Is-Project([string]$p) {
    $p -and (Test-Path (Join-Path $p 'edge_backend\core\config.py')) -and
        (Test-Path (Join-Path $p 'edge_backend\main.py'))
}
function Under([string]$child, [string]$parent) {
    if (-not $child -or -not $parent) { return $false }
    $c = [IO.Path]::GetFullPath($child).TrimEnd('\') + '\'
    $p = [IO.Path]::GetFullPath($parent).TrimEnd('\') + '\'
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

Write-Host ''
Write-Host '============================================================'
Write-Host '  Bioreactor -- ONE-CLICK install (monitoring PC, architecture B)'
if ($DryRun) { Write-Host '  DRY RUN: nothing will be changed' -ForegroundColor Yellow }
Write-Host '============================================================'

# The USB kit layout (when this script is run from the kit root):
#   <kit>\monitor_oneclick.ps1, <kit>\ingest_token.txt, <kit>\offline_files\...
$Kit = $Here
if (Is-Project (Split-Path $Here -Parent)) { $Kit = $null }     # running from inside a repo

# ---- 1  project folder -----------------------------------------------------
Step '1  project folder'
$proj = $null
if ($Project) {
    if (-not (Is-Project $Project)) { throw "Not a project folder: $Project" }
    $proj = $Project
} elseif (-not $Kit) {
    $proj = Split-Path $Here -Parent
} else {
    $roots = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('MyDocuments'))
    $roots += @(Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue |
                ForEach-Object { Join-Path $_.FullName 'Desktop' })
    $roots += @('C:\', 'D:\')
    $found = @{}
    foreach ($r in ($roots | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique)) {
        $depth = if ($r.Length -le 3) { 2 } else { 3 }
        Get-ChildItem $r -Directory -Filter 'edge_backend' -Recurse -Depth $depth -ErrorAction SilentlyContinue |
            ForEach-Object {
                $p = Split-Path $_.FullName -Parent
                if ((Is-Project $p) -and -not (Under $p $Here)) { $found[$p] = $true }
            }
    }
    # git checkouts first (that is how the July install was done), then most recently touched
    $cands = @($found.Keys | Sort-Object @{ Expression = { Test-Path (Join-Path $_ '.git') }; Descending = $true },
                                         @{ Expression = { (Get-Item (Join-Path $_ 'edge_backend')).LastWriteTime }; Descending = $true })
    if ($cands.Count -eq 0) { throw 'No project folder found (looked for edge_backend\core\config.py). Use -Project <path>.' }
    foreach ($c in $cands) {
        $g = if (Test-Path (Join-Path $c '.git')) { 'git' } else { 'no git' }
        Say ("candidate: $c  ($g)")
    }
    $proj = $cands[0]
    if ($cands.Count -gt 1 -and -not (Ask "Use the first one: $proj ?")) { throw 'Re-run with -Project <path>.' }
}
Say ("project: $proj") 'Green'
$EB = Join-Path $proj 'edge_backend'
$EnvF = Join-Path $EB '.env'

# ---- 2  update the code ----------------------------------------------------
Step '2  update the code'
$git = Get-Command git -ErrorAction SilentlyContinue
$env:GIT_TERMINAL_PROMPT = '0'          # never hang on a username/password prompt
$online = $false
if ($git -and (Test-Path (Join-Path $proj '.git'))) {
    & git -C $proj ls-remote --heads origin 2>$null | Out-Null
    $online = ($LASTEXITCODE -eq 0)
}
if ($online) {
    $dirty = @(& git -C $proj status --porcelain --untracked-files=no)
    Say ("git: online; HEAD " + (& git -C $proj log --oneline -1))
    if ($dirty.Count -gt 0) {
        Say ("$($dirty.Count) modified tracked file(s) -> git stash (kept, not lost)") 'Yellow'
        if (-not $DryRun) { & git -C $proj stash push -m "oneclick $Stamp" | Out-Null }
    }
    if ($DryRun) { Say 'would run: git pull --ff-only origin main' 'Yellow' }
    else {
        & git -C $proj pull --ff-only origin main
        if ($LASTEXITCODE -ne 0) { throw 'git pull failed (see above). Nothing else was changed.' }
        Say ("updated to " + (& git -C $proj log --oneline -1)) 'Green'
    }
} elseif ($Kit -and (Test-Path (Join-Path $Kit 'offline_files'))) {
    $src = Join-Path $Kit 'offline_files'
    $bak = Join-Path $proj ("backup_oneclick_" + $Stamp)
    $files = @(Get-ChildItem $src -File -Recurse)
    Say ("no git / offline -> copy $($files.Count) file(s) from the USB kit (old ones backed up to $bak)") 'Yellow'
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($src.Length).TrimStart('\')
        $dst = Join-Path $proj $rel
        if ($DryRun) { Say ("would copy: $rel"); continue }
        if (Test-Path $dst) {
            $b = Join-Path $bak $rel
            New-Item -ItemType Directory -Force (Split-Path $b -Parent) | Out-Null
            Copy-Item $dst $b -Force
        }
        New-Item -ItemType Directory -Force (Split-Path $dst -Parent) | Out-Null
        Copy-Item $f.FullName $dst -Force
    }
} else {
    Say 'no git/network and no USB offline_files: keeping the code already on this PC' 'Yellow'
}
if (-not (Test-Path (Join-Path $proj 'deploy\monitor_uploader_setup.bat')) -and -not $DryRun) {
    throw 'deploy\monitor_uploader_setup.bat is missing: the code on this PC is too old. Get the USB kit.'
}

# ---- 3  CSV folder -----------------------------------------------------------
Step '3  CSV folder (the one the vendor logger is writing now)'
function Env-Get([string]$key) {
    if (-not (Test-Path $EnvF)) { return $null }
    $line = [IO.File]::ReadAllLines($EnvF, $Utf8) | Where-Object { $_ -match ('^' + $key + '=') } | Select-Object -Last 1
    if ($line) { return $line.Substring($key.Length + 1).Trim().Trim('"') }
    return $null
}
$dirs = @{}
function Add-Dir([string]$d, [string]$why) {
    if ($d -and (Test-Path $d -PathType Container) -and -not (Under $d $proj) -and -not (Under $d $Here)) {
        if (-not $dirs.ContainsKey($d)) { $dirs[$d] = $why }
    }
}
if ($CsvDir) { Add-Dir $CsvDir 'given' }
Add-Dir (Env-Get 'REACTOR_DATA_DIR') '.env'
$lj = Join-Path $proj 'launcher.json'
if (Test-Path $lj) {
    try {
        $j = Get-Content $lj -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($j.csv_dir) { Add-Dir $j.csv_dir 'launcher.json csv_dir' }
        if ($j.recorder_path) { Add-Dir (Split-Path $j.recorder_path -Parent) 'launcher.json recorder' }
    } catch {}
}
Add-Dir 'C:\Users\BTP\Desktop\data' 'default'
$searchRoots = @(Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue |
                 ForEach-Object { Join-Path $_.FullName 'Desktop'; Join-Path $_.FullName 'Documents' })
$searchRoots += @('C:\data', 'D:\', 'C:\BTP')
foreach ($r in ($searchRoots | Where-Object { Test-Path $_ })) {
    Get-ChildItem $r -Filter 'BTP_Sensor_log-*.csv' -File -Recurse -Depth 3 -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty DirectoryName -Unique | ForEach-Object { Add-Dir $_ 'search' }
}
$rows = @()
foreach ($d in $dirs.Keys) {
    $csv = @(Get-ChildItem $d -Filter 'BTP_Sensor_log-*.csv' -File -ErrorAction SilentlyContinue)
    if ($csv.Count -eq 0) { continue }
    $new = ($csv | Sort-Object LastWriteTime -Descending)[0]
    $rows += [pscustomobject]@{ Dir = $d; Files = $csv.Count; Newest = $new.LastWriteTime;
        AgeMin = [math]::Round(((Get-Date) - $new.LastWriteTime).TotalMinutes, 1); Why = $dirs[$d] }
}
if ($rows.Count -eq 0) { throw 'No folder with BTP_Sensor_log-*.csv found. Re-run with -CsvDir <folder>.' }
$rows = @($rows | Sort-Object Newest -Descending)
if ($CsvDir) {
    # an explicitly given folder wins over "newest"; it still has to contain CSVs
    $given = @($rows | Where-Object { $_.Why -eq 'given' })
    if ($given.Count -eq 0) { throw "-CsvDir has no BTP_Sensor_log-*.csv: $CsvDir" }
    $rows = @($given) + @($rows | Where-Object { $_.Why -ne 'given' })
}
foreach ($r in $rows) {
    $live = if ($r.AgeMin -le 30) { 'LIVE' }
            elseif ($r.AgeMin -lt 120) { 'last write {0:N0} min ago' -f $r.AgeMin }
            elseif ($r.AgeMin -lt 2880) { 'last write {0:N1} h ago' -f ($r.AgeMin / 60) }
            else { 'last write {0:N0} days ago' -f ($r.AgeMin / 1440) }
    Say ("{0}  ({1} files, {2}, from {3})" -f $r.Dir, $r.Files, $live, $r.Why)
}
$data = $rows[0].Dir
if ($rows[0].AgeMin -gt 30) {
    Say 'WARNING: no CSV was written in the last 30 min. Is the vendor logger running?' 'Yellow'
}
if (-not (Ask "Use CSV folder: $data ?")) {
    $data = Read-Host '  Type the CSV folder path'
    if (-not (Test-Path $data -PathType Container)) { throw "Not a folder: $data" }
}
Say ("CSV folder: $data") 'Green'

# ---- 4  ingest token -----------------------------------------------------------
Step '4  ingest token'
$token = $null
if ($Kit -and (Test-Path (Join-Path $Kit 'ingest_token.txt'))) {
    $token = ([IO.File]::ReadAllText((Join-Path $Kit 'ingest_token.txt'))).Trim()
    Say ("from USB kit ingest_token.txt ({0} chars)" -f $token.Length) 'Green'
} elseif (Env-Get 'REACTOR_INGEST_TOKEN') {
    Say 'keeping the token already in .env' 'Green'
} else {
    Say 'no token found: setup.bat will ask for it (it is on paper / the USB kit)' 'Yellow'
}

# ---- 5  .env (UTF-8) ---------------------------------------------------------------
Step '5  settings edge_backend\.env (UTF-8)'
$want = [ordered]@{ REACTOR_DATA_DIR = $data }
if ($token) { $want['REACTOR_INGEST_TOKEN'] = $token }
if (-not (Env-Get 'REACTOR_UPLOAD_URL')) { $want['REACTOR_UPLOAD_URL'] = 'http://192.168.55.1:8000' }
if (-not (Env-Get 'REACTOR_STATION')) { $want['REACTOR_STATION'] = 'BTP-1' }
foreach ($k in $want.Keys) {
    $v = if ($k -eq 'REACTOR_INGEST_TOKEN') { '(hidden)' } else { $want[$k] }
    Say ("$k=$v")
}
if (-not $DryRun) {
    $lines = @()
    if (Test-Path $EnvF) {
        Copy-Item $EnvF ($EnvF + '.bak_' + $Stamp) -Force
        $lines = @([IO.File]::ReadAllLines($EnvF, $Utf8))
    } else {
        $lines = @("# created by monitor_oneclick.ps1 $Stamp")
    }
    $seen = @{}
    # @(...) keeps it an array even for a one-line .env (else += concatenates strings)
    $out = @(foreach ($l in $lines) {
        $k = ($l -split '=', 2)[0].Trim()
        if ($want.Contains($k) -and -not $l.TrimStart().StartsWith('#')) { "$k=$($want[$k])"; $seen[$k] = 1 }
        else { $l }
    })
    foreach ($k in $want.Keys) { if (-not $seen.ContainsKey($k)) { $out += "$k=$($want[$k])" } }
    [IO.File]::WriteAllText($EnvF, (($out -join "`n") + "`n"), $Utf8)
    Say ('written (old one kept as .env.bak_' + $Stamp + ')') 'Green'
}

# ---- 6  old autostart (architecture A) ---------------------------------------------
Step '6  old autostart (architecture A)'
$startup = [Environment]::GetFolderPath('Startup')
$sh = New-Object -ComObject WScript.Shell
$old = @()
foreach ($f in (Get-ChildItem $startup -File -ErrorAction SilentlyContinue)) {
    if ($f.Name -eq 'Bioreactor uploader.lnk' -or $f.Name -eq 'Bioreactor uploader.cmd') { continue }
    $hit = $f.Name -eq 'BTP_monitor.bat'
    if (-not $hit -and $f.Extension -eq '.lnk') {
        $l = $sh.CreateShortcut($f.FullName)
        $hit = ($l.TargetPath + ' ' + $l.Arguments) -match 'START\.bat|launcher\.pyw'
    } elseif (-not $hit -and $f.Extension -in '.bat', '.cmd') {
        $hit = (Get-Content $f.FullName -Raw) -match 'START\.bat|launcher\.pyw'
    }
    if ($hit) { $old += $f }
}
if ($old.Count -eq 0) { Say 'none found' 'Green' }
else {
    $park = Join-Path ([Environment]::GetFolderPath('Desktop')) ('old_autostart_backup_' + $Stamp)
    foreach ($f in $old) {
        if ($DryRun) { Say ("would move: $($f.Name) -> $park") 'Yellow'; continue }
        New-Item -ItemType Directory -Force $park | Out-Null
        Move-Item $f.FullName $park -Force
        Say ("moved $($f.Name) -> $park (not deleted: it is the fallback if the Jetson fails)") 'Green'
    }
}

# ---- 7  setup.bat --------------------------------------------------------------------
Step '7  install (deploy\monitor_uploader_setup.bat)'
if ($DryRun) {
    Say 'would run deploy\monitor_uploader_setup.bat (no questions: .env already filled)' 'Yellow'
    Write-Host ''
    Write-Host '  DRY RUN finished. Nothing was changed.' -ForegroundColor Yellow
    exit 0
}
# chcp 65001: setup.bat reads REACTOR_DATA_DIR back with cmd (findstr) to check the
# folder exists. Under the default ANSI codepage a UTF-8 Chinese path reads as garbage
# and the check fails even though the folder is there.
& cmd.exe /c ('chcp 65001 >nul & "' + (Join-Path $proj 'deploy\monitor_uploader_setup.bat') + '"')
$rc = $LASTEXITCODE
if ($rc -ne 0) { throw "setup.bat stopped with code $rc (see above). Autostart was NOT installed." }

# ---- 8  control panel -----------------------------------------------------------------
Step '8  control panel'
$panel = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Bioreactor panel.lnk'
if (Test-Path $panel) { Invoke-Item $panel; Say 'opened: all four cards should turn green' 'Green' }
else { Say 'panel shortcut not found; open monitor_panel.pyw by hand' 'Yellow' }
Write-Host ''
Write-Host '  Done. Checklist section 3.6 (acceptance) is next.' -ForegroundColor Green
