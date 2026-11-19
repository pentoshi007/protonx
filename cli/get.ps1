$ErrorActionPreference = 'Stop'

$Repo = 'pentoshi007/protonx'
$Ref = if ($env:PROTONX_REF) { $env:PROTONX_REF } else { 'main' }
$Work = Join-Path ([IO.Path]::GetTempPath()) ('protonx-' + [guid]::NewGuid().ToString('N'))
$Archive = "$Work.zip"

try {
    Write-Host "Downloading protonx CLI ($Ref)"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/$Repo/zip/$Ref" -OutFile $Archive
    Expand-Archive -Path $Archive -DestinationPath $Work
    $source = Get-ChildItem -Path $Work -Directory | Select-Object -First 1
    $installer = Join-Path $source.FullName 'cli\install-windows.ps1'
    if (-not (Test-Path $installer)) { throw "that revision has no Windows installer" }
    $shell = (Get-Process -Id $PID).Path
    & $shell -NoProfile -ExecutionPolicy Bypass -File $installer
    if ($LASTEXITCODE -ne 0) { throw "the installer failed" }
}
finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Work, $Archive
}
