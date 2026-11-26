[CmdletBinding()]
param([switch]$RestoreEnglish)
$ErrorActionPreference = 'Stop'
$taskName = 'AntigravityZhSync'
$root = Join-Path $env:LOCALAPPDATA 'AntigravityZhSync'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq 'Running') { Stop-ScheduledTask -TaskName $taskName }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') { break }
        Start-Sleep -Milliseconds 200
    }
    if ((Get-ScheduledTask -TaskName $taskName).State -eq 'Running') {
        throw 'The watcher is still running.'
    }
}
if ($RestoreEnglish) {
    $config = Get-Content -Raw -LiteralPath (Join-Path $root 'config.json') | ConvertFrom-Json
    & $config.python -B (Join-Path $root 'Watch.py') --restore
    if ($LASTEXITCODE -ne 0) {
        if ($task) { Start-ScheduledTask -TaskName $taskName }
        throw 'Restore failed. The original files have been retained.'
    }
}
if ($task) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
Write-Host "Background task removed. Logs and backups: $root"
