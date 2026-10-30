<#
  Installs vinted-sniper on Windows 10 or 11. No Docker, no admin rights, nothing outside
  your own user folder.

  Open PowerShell (Start menu, type PowerShell, press Enter), paste this and press Enter:

    powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/jasp-nerd/vinted-sniper/main/install.ps1 | iex"

  What it does, in order:
    1. installs uv (https://docs.astral.sh/uv/), the tool that fetches Python and
       vinted-sniper, if you don't have it yet
    2. installs vinted-sniper with its own private copy of Python
    3. asks whether it should start by itself when you sign in
    4. starts it in the background and opens the dashboard in your browser

  Run the same command again to update. To remove it (your searches are kept):

    powershell -ExecutionPolicy ByPass -c '$env:VINTED_SNIPER_UNINSTALL=1; irm https://raw.githubusercontent.com/jasp-nerd/vinted-sniper/main/install.ps1 | iex'

  Downloaded as a file, it also takes switches:
    .\install.ps1 [-Uninstall] [-Autostart] [-NoAutostart] [-NoBrowser]

  Environment variables, for anyone scripting this:
    VINTED_SNIPER_AUTOSTART=yes|no   start at sign-in without asking / never
    VINTED_SNIPER_NO_BROWSER=1       don't open the dashboard at the end
    VINTED_SNIPER_UNINSTALL=1        same as -Uninstall
    VINTED_SNIPER_DATA_DIR=...       where the database and log live
    VINTED_SNIPER_WEB_PORT=...       dashboard port, if 8000 is taken
    VINTED_SNIPER_PACKAGE=...        what to install (see $PackageSpec below)
    UV_NO_MODIFY_PATH=1              leave your PATH setting alone

  This file is plain ASCII on purpose: Windows PowerShell 5.1 can garble anything else
  when it arrives through irm.
#>
param(
    [switch]$Uninstall,
    [switch]$Autostart,
    [switch]$NoAutostart,
    [switch]$NoBrowser
)

# Everything lives in functions and only the last line runs anything, so a download cut off
# halfway can never run half an install. Nothing here calls `exit`: under `irm | iex` that
# would close the user's PowerShell window along with the error message.

function Get-VsConfig {
    # Where vinted-sniper comes from: the latest release on PyPI. Set VINTED_SNIPER_PACKAGE
    # to install something else, such as a GitHub archive of an unreleased branch.
    $spec = 'vinted-sniper'
    if ($env:VINTED_SNIPER_PACKAGE) { $spec = $env:VINTED_SNIPER_PACKAGE }

    $dataDir = Join-Path $env:LOCALAPPDATA 'vinted-sniper'
    if ($env:VINTED_SNIPER_DATA_DIR) { $dataDir = $env:VINTED_SNIPER_DATA_DIR }

    $port = '8000'
    if ($env:VINTED_SNIPER_WEB_PORT) { $port = $env:VINTED_SNIPER_WEB_PORT }

    # Always set on Windows; the fallback only keeps a stripped-down profile from crashing.
    $startup = [Environment]::GetFolderPath('Startup')
    if (-not $startup) { $startup = $dataDir }

    $scriptUrl = 'https://raw.githubusercontent.com/jasp-nerd/vinted-sniper/main/install.ps1'
    return [pscustomobject]@{
        PackageSpec = $spec
        DataDir     = $dataDir
        DbPath      = Join-Path $dataDir 'app.db'
        LogPath     = Join-Path $dataDir 'vinted-sniper.log'
        Launcher    = Join-Path $dataDir 'start-vinted-sniper.ps1'
        Shortcut    = Join-Path $startup 'vinted-sniper.lnk'
        Port        = $port
        Url         = "http://localhost:$port"
        ScriptUrl   = $scriptUrl
    }
}

function Write-VsStep([string]$Text) { Write-Host $Text }

# Runs a native command and hides what it prints. Windows PowerShell 5.1 turns redirected
# stderr into errors, which 'Stop' would treat as fatal, so the preference is relaxed here.
function Invoke-VsQuiet([string]$Exe, [string[]]$Arguments) {
    $ErrorActionPreference = 'Continue'
    & $Exe @Arguments 2>&1 | Out-Null
}

# A value placed inside single quotes in a generated PowerShell file.
function ConvertTo-VsLiteral([string]$Text) { return "'" + ($Text -replace "'", "''") + "'" }

# --- uv ------------------------------------------------------------------------------

function Find-VsUv {
    $cmd = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @()
    if ($env:UV_INSTALL_DIR) { $candidates += (Join-Path $env:UV_INSTALL_DIR 'uv.exe') }
    $candidates += (Join-Path $env:USERPROFILE '.local\bin\uv.exe')
    $candidates += (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Get-VsUv {
    $uv = Find-VsUv
    if ($uv) { return $uv }
    Write-VsStep 'Installing uv, the helper that downloads Python and vinted-sniper for you...'
    # In a separate PowerShell, so uv's installer can't change anything in this session.
    & powershell.exe -NoProfile -ExecutionPolicy ByPass -Command 'irm https://astral.sh/uv/install.ps1 | iex' | Out-Host
    $uv = Find-VsUv
    if (-not $uv) { throw 'uv could not be installed (see the messages above).' }
    return $uv
}

# --- Questions -------------------------------------------------------------------------

function Test-VsInteractive {
    if (-not [Environment]::UserInteractive) { return $false }
    foreach ($arg in [Environment]::GetCommandLineArgs()) {
        if ($arg -like '-NonI*') { return $false }
    }
    return $true
}

function Test-VsWantAutostart([string]$Setting) {
    if ($Setting -match '^(yes|1|true)$') { return $true }
    if ($Setting -match '^(no|0|false)$') { return $false }
    if (-not (Test-VsInteractive)) { return $false }
    Write-Host ''
    try {
        $answer = Read-Host 'Start vinted-sniper by itself whenever you sign in to Windows? [Y/n]'
    } catch {
        return $false
    }
    return -not ($answer -match '^\s*[nN]')
}

# --- Stopping and starting ------------------------------------------------------------

# Finds the running app: uv's small vinted-sniper.exe launcher, the Python it starts, and
# the hidden cmd.exe that writes its log. Matched on the command line, because the Python
# process itself is the shared interpreter uv downloaded.
function Get-VsProcess {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and (
            $_.Name -eq 'vinted-sniper.exe' -or
            (($_.Name -like 'python*.exe' -or $_.Name -eq 'cmd.exe') -and
             $_.CommandLine -like '*vinted-sniper*run*')
        )
    }
}

function Stop-VsApp {
    $procs = @(Get-VsProcess)
    foreach ($proc in $procs) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($procs.Count -gt 0) { Start-Sleep -Seconds 2 }
}

function Test-VsPortInUse([string]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $attempt = $client.BeginConnect('127.0.0.1', [int]$Port, $null, $null)
        return ($attempt.AsyncWaitHandle.WaitOne(700) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# The launcher is what both the Startup shortcut and this installer run. It starts the app
# with no window, writing everything it prints to the log, and keeps that log from growing
# without limit. cmd.exe does the log redirection because it writes the text as-is, where
# Windows PowerShell 5.1 would turn it into UTF-16.
#
# It also stays, hidden, for as long as the app runs, because of updates. The app cannot
# replace its own files while it runs (Windows locks them), so when the dashboard's Update
# button is pressed the app exits with code 75 and the launcher runs the upgrade with
# nothing running, then starts it again. Any other exit, or a 75 within ten seconds of
# starting, ends the launcher too, so a broken start can never loop.
function Write-VsLauncher($S, [string]$Exe, [string]$Uv) {
    $exeQ = ConvertTo-VsLiteral $Exe
    $uvQ = ConvertTo-VsLiteral $Uv
    $dirQ = ConvertTo-VsLiteral $S.DataDir
    $dbQ = ConvertTo-VsLiteral $S.DbPath
    $logQ = ConvertTo-VsLiteral $S.LogPath
    $portQ = ConvertTo-VsLiteral $S.Port
    $content = @"
# Starts vinted-sniper in the background, and again after an update. Written by
# install.ps1; run by the shortcut in your Startup folder when you sign in. Running the
# installer again rewrites this file.
`$exe = $exeQ
`$uv = $uvQ
`$log = $logQ
`$env:VINTED_SNIPER_DB_PATH = $dbQ
`$env:VINTED_SNIPER_WEB_PORT = $portQ
`$env:VINTED_SNIPER_SUPERVISED = 'windows-launcher'
if ((Test-Path -LiteralPath `$log) -and ((Get-Item -LiteralPath `$log).Length -gt 5MB)) {
    Move-Item -LiteralPath `$log -Destination "`$log.old" -Force
}
`$command = '/d /s /c ""' + `$exe + '" run >> "' + `$log + '" 2>&1"'
`$upgrade = '/d /s /c ""' + `$uv + '" tool upgrade vinted-sniper --no-progress --color never >> "' + `$log + '" 2>&1"'
while (`$true) {
    `$started = Get-Date
    `$app = Start-Process -FilePath `$env:ComSpec -ArgumentList `$command -WorkingDirectory $dirQ -WindowStyle Hidden -PassThru
    # Reading the handle now is what keeps ExitCode readable after it exits (PowerShell 5.1).
    `$null = `$app.Handle
    `$app.WaitForExit()
    if (`$app.ExitCode -ne 75 -or ((Get-Date) - `$started).TotalSeconds -lt 10) { break }
    Start-Process -FilePath `$env:ComSpec -ArgumentList `$upgrade -WorkingDirectory $dirQ -WindowStyle Hidden -Wait
}
"@
    # UTF-8 with a byte order mark: the only way Windows PowerShell 5.1 reads a non-ASCII
    # user name in these paths correctly.
    [IO.File]::WriteAllText($S.Launcher, $content, (New-Object System.Text.UTF8Encoding $true))
}

function Get-VsLauncherCommandLine($S) {
    return '-NoProfile -ExecutionPolicy ByPass -WindowStyle Hidden -File "' + $S.Launcher + '"'
}

function Start-VsApp($S) {
    Start-Process -FilePath 'powershell.exe' -ArgumentList (Get-VsLauncherCommandLine $S) -WindowStyle Hidden
}

# A shortcut in the Startup folder needs no admin rights, unlike a scheduled task that runs
# at sign-in, and it is easy to find and remove by hand.
function New-VsStartupShortcut($S) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($S.Shortcut)
    $link.TargetPath = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
    $link.Arguments = Get-VsLauncherCommandLine $S
    $link.WorkingDirectory = $S.DataDir
    $link.WindowStyle = 7
    $link.Description = 'vinted-sniper: alerts for new Vinted listings'
    $link.Save()
}

# vinted-sniper answers on /healthz once it is up: 200 when healthy, 503 until the first
# check has run. Either means it started; anything else on the port does not count.
function Wait-VsDashboard($S) {
    for ($i = 0; $i -lt 45; $i++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "$($S.Url)/healthz" -TimeoutSec 2
            if ($response.Content -match '"alive"') { return $true }
        } catch {
            $status = $null
            if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
            if ($status -eq 503) { return $true }
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

# --- The two things this script does --------------------------------------------------

function Uninstall-VsApp($S) {
    Write-VsStep 'Removing vinted-sniper...'
    Stop-VsApp
    Remove-Item -LiteralPath $S.Shortcut -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $S.Launcher -Force -ErrorAction SilentlyContinue
    $uv = Find-VsUv
    if ($uv) { Invoke-VsQuiet $uv @('tool', 'uninstall', 'vinted-sniper') }
    [Environment]::SetEnvironmentVariable('VINTED_SNIPER_DB_PATH', $null, 'User')
    Write-Host ''
    Write-Host 'vinted-sniper is removed.'
    Write-Host 'Your searches and settings are still here, in case you come back:'
    Write-Host "  $($S.DataDir)"
    Write-Host 'Delete that folder if you want them gone too.'
    Write-Host 'uv, the helper used to install it, is still there for other tools. To remove it as well:'
    Write-Host '  https://docs.astral.sh/uv/getting-started/installation/#uninstallation'
}

function Install-VsApp($S, [string]$AutostartSetting, [bool]$OpenBrowser) {
    New-Item -ItemType Directory -Force -Path $S.DataDir | Out-Null
    $uv = Get-VsUv
    $bin = ((& $uv tool dir --bin) | Out-String).Trim()
    $exe = Join-Path $bin 'vinted-sniper.exe'

    $already = Test-Path -LiteralPath $exe
    if ($already) {
        Write-VsStep 'vinted-sniper is already installed. Updating it to the newest version...'
    } else {
        Write-VsStep 'Installing vinted-sniper. The first time this also downloads Python (about 30 MB),'
        Write-VsStep 'so give it a minute...'
    }
    # A running copy keeps its files locked, and the update would fail halfway.
    Stop-VsApp

    # --managed-python: a Python that uv looks after itself, so another Python on this PC
    # can never break the install. --reinstall-package: the archive URL never changes, so
    # without it a re-run would keep the old copy.
    & $uv tool install --quiet --upgrade --reinstall-package vinted-sniper --managed-python --python 3.13 $S.PackageSpec
    if ($LASTEXITCODE -ne 0) { throw 'The download or install failed (see the messages above).' }
    if (-not (Test-Path -LiteralPath $exe)) { throw "The install finished, but $exe is missing." }

    if (-not $env:UV_NO_MODIFY_PATH) { Invoke-VsQuiet $uv @('tool', 'update-shell') }
    # So `vinted-sniper status` typed in any new window reads the same database as the copy
    # running in the background.
    [Environment]::SetEnvironmentVariable('VINTED_SNIPER_DB_PATH', $S.DbPath, 'User')
    $version = ((& $exe --version) | Out-String).Trim()

    if (Test-VsPortInUse $S.Port) {
        Write-Host ''
        Write-Host "Something else is already using port $($S.Port) on this PC (maybe an older copy running in"
        Write-Host 'Docker?). Stop it, or choose another port by running this in PowerShell first:'
        Write-Host '  $env:VINTED_SNIPER_WEB_PORT = 8001'
        Write-Host 'and then the install command again.'
        throw "Port $($S.Port) is taken."
    }

    Write-VsLauncher $S $exe $uv
    $autostarted = Test-VsWantAutostart $AutostartSetting
    if ($autostarted) {
        New-VsStartupShortcut $S
        Write-Host 'It will now start by itself whenever you sign in.'
    } else {
        Remove-Item -LiteralPath $S.Shortcut -Force -ErrorAction SilentlyContinue
    }
    Start-VsApp $S

    Write-Host ''
    if (-not (Wait-VsDashboard $S)) {
        throw "It installed, but didn't start. The log may say why: $($S.LogPath)"
    }
    if ($already) {
        Write-Host "Updated and running: $version" -ForegroundColor Green
    } else {
        Write-Host "All done. $version is running." -ForegroundColor Green
    }
    if ($OpenBrowser) { Start-Process $S.Url }

    Write-Host ''
    Write-Host "  Dashboard:     $($S.Url)   (bookmark it)"
    Write-Host "  Your data:     $($S.DataDir)"
    Write-Host "  Log file:      $($S.LogPath)"
    Write-Host ''
    Write-Host 'Next: in the dashboard, add where alerts should go (Discord or Telegram), then paste'
    Write-Host 'a Vinted search. Alerts arrive while this PC is on, awake and online: in Settings,'
    Write-Host 'System, Power, set "Make my device sleep" to Never while plugged in.'
    Write-Host ''
    Write-Host "  Update:        the dashboard's Update button, or run the install command again"
    if (-not $autostarted) {
        Write-Host '  Start again:   run the install command again (after a restart, for example)'
    }
    Write-Host '  Stop:          Get-Process vinted-sniper | Stop-Process'
    Write-Host '                 (or in Task Manager, Details tab, end vinted-sniper.exe)'
    Write-Host "  Uninstall:     powershell -ExecutionPolicy ByPass -c '`$env:VINTED_SNIPER_UNINSTALL=1; irm $($S.ScriptUrl) | iex'"
}

function Invoke-VsInstaller([bool]$UninstallSwitch, [bool]$AutostartSwitch, [bool]$NoAutostartSwitch, [bool]$NoBrowserSwitch) {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    # GitHub and astral.sh only speak TLS 1.2 or newer; older Windows 10 builds don't offer
    # it to scripts by default.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    try {
        $S = Get-VsConfig
        if ($UninstallSwitch -or $env:VINTED_SNIPER_UNINSTALL) {
            Uninstall-VsApp $S
            return
        }
        $autostartSetting = 'ask'
        if ($env:VINTED_SNIPER_AUTOSTART) { $autostartSetting = $env:VINTED_SNIPER_AUTOSTART }
        if ($AutostartSwitch) { $autostartSetting = 'yes' }
        if ($NoAutostartSwitch) { $autostartSetting = 'no' }
        $openBrowser = -not ($NoBrowserSwitch -or $env:VINTED_SNIPER_NO_BROWSER)
        Install-VsApp $S $autostartSetting $openBrowser
    } catch {
        Write-Host ''
        Write-Host "Sorry, that didn't work: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "If you're stuck, open an issue and paste everything above:"
        Write-Host '  https://github.com/jasp-nerd/vinted-sniper/issues/new/choose'
    }
}

Invoke-VsInstaller ([bool]$Uninstall) ([bool]$Autostart) ([bool]$NoAutostart) ([bool]$NoBrowser)
