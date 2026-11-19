#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Target = Join-Path $env:LOCALAPPDATA 'protonx'
$Engine = Join-Path $Target 'engine'
$Venv = Join-Path $Target 'venv'
$Bin = Join-Path $Target 'bin'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$WireGuard = Join-Path $env:ProgramFiles 'WireGuard\wireguard.exe'

function Ok($text) { Write-Host "[ok] $text" }
function Info($text) { Write-Host "  $text" }
function Fail($text) { Write-Host "[!!] $text" -ForegroundColor Red; exit 1 }

function Find-Python {
    $ErrorActionPreference = 'Continue'
    foreach ($candidate in @('py -3', 'python', 'python3')) {
        $parts = $candidate -split ' '
        $command = Get-Command $parts[0] -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $prefix = @($parts | Select-Object -Skip 1)
        & $command.Source @prefix -c 'import sys, venv; sys.exit(sys.version_info < (3, 9))' 2>$null
        if ($LASTEXITCODE -eq 0) { return @{ Exe = $command.Source; Prefix = $prefix } }
    }
    return $null
}

function Install-WithWinget($id, $label) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "$label is missing and winget is unavailable. Install $label manually, then re-run."
    }
    Info "installing $label with winget"
    winget install --exact --id $id --silent --accept-package-agreements --accept-source-agreements | Out-Null
}

Write-Host "`nprotonx CLI installer for Windows`n---------------------------------"

$found = Find-Python
if (-not $found) {
    Install-WithWinget 'Python.Python.3.12' 'Python 3'
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $found = Find-Python
    if (-not $found) { Fail 'Python 3.9 or newer is required. Open a new terminal and re-run this installer.' }
}
$prefix = $found.Prefix
Ok "python $(& $found.Exe @prefix -c 'import sys; print(sys.version.split()[0])')"

if (-not (Test-Path $WireGuard)) { Install-WithWinget 'WireGuard.WireGuard' 'WireGuard for Windows' }
if (-not (Test-Path $WireGuard)) { Fail 'WireGuard for Windows is required: https://www.wireguard.com/install/' }
Ok 'WireGuard for Windows present'

Write-Host "`ninstalling engine`n-----------------"
foreach ($path in @($Engine, $Venv)) { if (Test-Path $path) { Remove-Item -Recurse -Force $path } }
New-Item -ItemType Directory -Force -Path $Engine, $Bin | Out-Null
Copy-Item -Recurse (Join-Path $Root 'protonxlib') $Engine
Copy-Item (Join-Path $Root 'protonx') $Engine
Get-ChildItem $Engine -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
$version = (Select-String -Path (Join-Path $Root 'protonxlib\__init__.py') -Pattern '"(.+)"').Matches[0].Groups[1].Value
Set-Content -Path (Join-Path $Target 'VERSION') -Value $version -NoNewline
Ok "engine installed to $Engine"

& $found.Exe @prefix -m venv $Venv
if ($LASTEXITCODE -ne 0) { Fail 'could not create the Python environment' }
& $VenvPython -m pip install --quiet --disable-pip-version-check cryptography bcrypt certifi
if ($LASTEXITCODE -ne 0) { Fail 'pip could not install cryptography, bcrypt and certifi (check the network, then re-run)' }
Ok "python environment ready at $Venv"

$launcher = "@echo off`r`n`"$VenvPython`" `"$Engine\protonx`" %*`r`n"
Set-Content -Path (Join-Path $Bin 'protonx.cmd') -Value $launcher -NoNewline -Encoding ASCII
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not (($userPath -split ';') -contains $Bin)) {
    [Environment]::SetEnvironmentVariable('Path', (@($userPath, $Bin) | Where-Object { $_ }) -join ';', 'User')
    Info "added $Bin to your PATH"
}
$env:Path = "$env:Path;$Bin"
Ok 'command installed: protonx'

Write-Host "`nverifying`n---------"
& $VenvPython (Join-Path $Engine 'protonx') doctor

Write-Host "`nDone. Open a new terminal as Administrator (needed to start the tunnel) and type: protonx`n"
