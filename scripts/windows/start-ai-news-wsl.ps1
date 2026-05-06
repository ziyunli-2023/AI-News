param(
    [string]$DistroName = "Ubuntu-22.04",
    [string]$ServiceName = "ai-news-docker.service"
)

$wsl = Join-Path $env:SystemRoot "System32\wsl.exe"

if (-not (Test-Path $wsl)) {
    Write-Error "wsl.exe not found at $wsl"
    exit 1
}

$arguments = @(
    "-d", $DistroName,
    "-u", "root",
    "--",
    "bash", "-lc",
    "systemctl start $ServiceName && systemctl is-active $ServiceName"
)

$output = & $wsl @arguments 2>&1
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Error ($output | Out-String)
    exit $exitCode
}

Write-Output ($output | Out-String)
