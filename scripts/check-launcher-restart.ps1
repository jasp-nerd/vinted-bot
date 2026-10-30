<#
  Checks the launcher install.ps1 writes: when the app exits with code 75 (an update from
  the dashboard), the launcher runs the upgrade and starts the app again, telling it it is
  supervised; when the app exits that way within seconds of starting, it stops instead.

  Uses install.ps1's own Write-VsLauncher with stand-ins for the app and for uv, in a
  temporary folder, so nothing is installed. Run by .github/workflows/installers.yml on
  Windows. Plain ASCII, like install.ps1, for Windows PowerShell 5.1.
#>
$ErrorActionPreference = 'Stop'

# install.ps1 without its last line, which runs the installer, is just its functions.
$installer = Get-Content -Raw (Join-Path $PSScriptRoot '..\install.ps1')
. ([ScriptBlock]::Create(($installer -replace '(?m)^Invoke-VsInstaller .*$', '')))

function Test-VsLauncherRun([int]$FirstRunSeconds) {
    $work = Join-Path ([IO.Path]::GetTempPath()) ('vs-launcher-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $work | Out-Null
    $env:VINTED_SNIPER_DATA_DIR = $work
    $S = Get-VsConfig

    # The app: exits 75 the first time (after FirstRunSeconds), 0 the second.
    $app = Join-Path $work 'app.cmd'
    $wait = $FirstRunSeconds + 1
    Set-Content -Encoding ASCII -LiteralPath $app -Value @"
@echo off
echo %VINTED_SNIPER_SUPERVISED%>> "%~dp0starts.txt"
if exist "%~dp0first-run-done" exit /b 0
echo done> "%~dp0first-run-done"
ping -n $wait 127.0.0.1 > nul
exit /b 75
"@
    $uv = Join-Path $work 'uv.cmd'
    Set-Content -Encoding ASCII -LiteralPath $uv -Value @'
@echo off
echo %*>> "%~dp0upgrades.txt"
'@

    Write-VsLauncher $S $app $uv
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy ByPass -File $S.Launcher

    $starts = @(Get-Content -LiteralPath (Join-Path $work 'starts.txt') | ForEach-Object { $_.Trim() })
    $upgrades = @()
    $upgradeLog = Join-Path $work 'upgrades.txt'
    if (Test-Path -LiteralPath $upgradeLog) { $upgrades = @(Get-Content -LiteralPath $upgradeLog) }
    return [pscustomobject]@{ Starts = $starts; Upgrades = $upgrades }
}

$updated = Test-VsLauncherRun 12
if ($updated.Starts.Count -ne 2) { throw "expected the app to be started twice, got $($updated.Starts.Count)" }
if (($updated.Starts | Select-Object -Unique) -ne 'windows-launcher') {
    throw "the app was not told it is supervised: $($updated.Starts -join ', ')"
}
if ($updated.Upgrades.Count -ne 1 -or $updated.Upgrades[0] -notmatch '^tool upgrade vinted-sniper\b') {
    throw "expected one 'uv tool upgrade vinted-sniper', got: $($updated.Upgrades -join ' | ')"
}
Write-Host 'Exit code 75 after a while: upgraded once and started again, supervised.'

$quick = Test-VsLauncherRun 0
if ($quick.Starts.Count -ne 1 -or $quick.Upgrades.Count -ne 0) {
    throw "an exit within seconds of starting should end the launcher; starts $($quick.Starts.Count), upgrades $($quick.Upgrades.Count)"
}
Write-Host 'Exit code 75 straight after starting: stopped, no upgrade, no loop.'
