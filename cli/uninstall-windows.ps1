param([switch]$Purge)
$ErrorActionPreference = 'Stop'

$Target = Join-Path $env:LOCALAPPDATA 'protonx'
$Bin = Join-Path $Target 'bin'
$Launcher = Join-Path $Bin 'protonx.cmd'

Write-Host "`nprotonx-cli uninstaller for Windows`n-----------------------------------"

if (Test-Path $Launcher) { & $Launcher disconnect | Out-Null }
if (Test-Path $Target) { Remove-Item -Recurse -Force $Target }
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$kept = ($userPath -split ';') | Where-Object { $_ -and $_ -ne $Bin }
[Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User')
Write-Host '[ok] command and engine removed'

$data = Join-Path $env:APPDATA 'protonx'
if ($Purge) {
    if (Test-Path $data) { Remove-Item -Recurse -Force $data }
    Write-Host '[ok] session, identity, cached servers and preferences removed'
}
else {
    Write-Host "  kept $data (use -Purge to delete)"
}
