param(
    [string]$TaskName = "AI-News-WSL-Autostart",
    [string]$DistroName = "Ubuntu-22.04",
    [string]$ProjectDir = "C:\Users\liziy\Code\AI-News",
    [string]$ServiceName = "ai-news-docker.service"
)

$startupScript = Join-Path $ProjectDir "scripts\windows\start-ai-news-wsl.ps1"

if (-not (Test-Path $startupScript)) {
    Write-Error "Startup script not found: $startupScript"
    exit 1
}

$pwsh = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path $pwsh)) {
    Write-Error "powershell.exe not found at $pwsh"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute $pwsh `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startupScript`" -DistroName `"$DistroName`" -ServiceName `"$ServiceName`""

$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Start AI News Monitor inside WSL at Windows startup"

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

Write-Output "Scheduled task registered: $TaskName"
Write-Output "Test it with:"
Write-Output "  Start-ScheduledTask -TaskName `"$TaskName`""
Write-Output "Check it with:"
Write-Output "  Get-ScheduledTask -TaskName `"$TaskName`""
