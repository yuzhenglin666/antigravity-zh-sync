[CmdletBinding()]
param([ValidateSet('Status', 'CheckNow')][string]$Action = 'Status')

$ErrorActionPreference = 'Stop'
$taskName = 'AntigravityZhSync'
$root = Join-Path $env:LOCALAPPDATA $taskName
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($task -and -not (Test-Path -LiteralPath (Join-Path $root 'Manage.ps1') -PathType Leaf)) {
    throw 'Reinstall the watcher with the current release before using this command.'
}

if ($Action -eq 'CheckNow') {
    if (-not $task -or $task.State -eq 'Disabled') {
        throw 'The background task must be installed and enabled before requesting a check.'
    }
    [IO.File]::WriteAllText((Join-Path $root 'check-now.request'), '')
    if ($task.State -ne 'Running') {
        Start-ScheduledTask -TaskName $taskName
    }
    Write-Host 'Check requested. Run Manage.ps1 -Action Status to view the result.'
    return
}

$taskState = if ($task) { $task.State } else { 'Not registered' }
Write-Host "Background task: $taskState"
$configPath = Join-Path $root 'config.json'
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    Write-Host 'No installation details found. Run Install.ps1 first.'
    return
}

$config = Get-Content -Raw -LiteralPath $configPath -Encoding UTF8 | ConvertFrom-Json
$statusArgs = @('-B', (Join-Path $root 'Watch.py'), '--status')
if (-not $task -or $task.State -eq 'Disabled') {
    $statusArgs += '--task-inactive'
}
& $config.python @statusArgs
if ($LASTEXITCODE -ne 0) { throw 'Unable to read localization status.' }
