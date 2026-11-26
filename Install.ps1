[CmdletBinding()]
param(
    [string]$AntigravityPath,
    [string]$PythonPath,
    [string]$NodePath,
    [switch]$NoNotifications
)
$ErrorActionPreference = 'Stop'
$taskName = 'AntigravityZhSync'
$target = Join-Path $env:LOCALAPPDATA 'AntigravityZhSync'

if ($PSVersionTable.PSEdition -ne 'Core' -and $PSVersionTable.PSVersion.Major -lt 5) {
    throw 'Windows PowerShell 5.1 or PowerShell 7 is required.'
}
if (Get-ScheduledTask -TaskName 'AntigravityLocalizationSync' -ErrorAction SilentlyContinue) {
    throw 'An earlier local watcher is installed. Stop and remove the earlier task before installing this edition.'
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Antigravity Zh Sync is already installed. Run Uninstall.ps1 first to reinstall.'
}
if (-not $AntigravityPath) {
    $installations = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\antigravity\Antigravity.exe'),
        (Join-Path $env:ProgramFiles 'antigravity\Antigravity.exe'),
        (Join-Path $env:ProgramFiles 'Google Antigravity\Antigravity.exe')
    )
    $AntigravityPath = $installations | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $AntigravityPath) {
    throw 'Desktop Antigravity was not found. Pass -AntigravityPath "C:\path\to\Antigravity.exe".'
}
$agy = Get-Item -LiteralPath $AntigravityPath
if ($agy.Name -ne 'Antigravity.exe' -or
    -not (Test-Path -LiteralPath (Join-Path $agy.DirectoryName 'resources\app.asar') -PathType Leaf)) {
    throw 'Pass the path to the desktop Antigravity.exe with a resources\app.asar archive.'
}

if (-not $PythonPath) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $PythonPath = & $launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1
    } else {
        $PythonPath = (Get-Command python.exe -ErrorAction Stop).Source
    }
}
if (-not $PythonPath -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Install Python 3.12 or newer, or pass -PythonPath.'
}
$PythonPath = (Get-Item -LiteralPath $PythonPath).FullName
& $PythonPath -c "import sys; raise SystemExit(int(sys.version_info < (3, 12)))"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required.' }
$windowless = Join-Path (Split-Path -Parent $PythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $windowless -PathType Leaf)) { throw 'The Python installation has no pythonw.exe.' }

if (-not $NodePath) { $NodePath = (Get-Command node.exe -ErrorAction Stop).Source }
$NodePath = (Get-Item -LiteralPath $NodePath).FullName
& $NodePath -e "process.exit(Number(process.versions.node.split('.')[0]) < 22 ? 1 : 0)"
if ($LASTEXITCODE -ne 0) { throw 'Node.js 22 or newer is required.' }
$nodeDir = Split-Path -Parent $NodePath
$npm = Join-Path $nodeDir 'npm.cmd'
$npx = Join-Path $nodeDir 'npx.cmd'
if (-not (Test-Path -LiteralPath $npm -PathType Leaf) -or
    -not (Test-Path -LiteralPath $npx -PathType Leaf)) {
    throw 'Use a Node.js installation that includes npm.cmd and npx.cmd.'
}

[void][IO.Directory]::CreateDirectory($target)
[void][IO.Directory]::CreateDirectory((Join-Path $target 'patcher\core'))
[void][IO.Directory]::CreateDirectory((Join-Path $target 'patcher\dict\scoped'))
[void][IO.Directory]::CreateDirectory((Join-Path $target 'translations'))
$files = @(
    'Watch.py', 'verify.js', 'LICENSE', 'README.md', 'Uninstall.ps1', 'Manage.ps1', 'Notify.ps1',
    'translations\zh-CN-2.35.2-v3.3.65.json',
    'patcher\cli.js', 'patcher\LICENSE', 'patcher\package.json', 'patcher\package-lock.json',
    'patcher\dict\scoped\official-plugin-descriptions.json', 'patcher\dict\scoped\swarm.json'
)
foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination (Join-Path $target $file) -Force
}
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'patcher\core') -File -Filter '*.js' |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $target 'patcher\core') -Force }
$oldPath = $env:PATH
try {
    $env:PATH = $nodeDir + ';' + $oldPath
    & $npm ci --prefix (Join-Path $target 'patcher') --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Installing the locked ASAR dependency failed.' }
} finally {
    $env:PATH = $oldPath
}

$config = [ordered]@{
    antigravity = $agy.FullName
    python = $PythonPath
    node = $NodePath
    notifications = -not $NoNotifications.IsPresent
}
[IO.File]::WriteAllText((Join-Path $target 'config.json'), ($config | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
& $PythonPath -B (Join-Path $target 'Watch.py') --validate
if ($LASTEXITCODE -ne 0) { throw 'The installed watcher failed preflight.' }

$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $windowless -Argument ('-B "' + (Join-Path $target 'Watch.py') + '"') -WorkingDirectory $target
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Keep desktop Antigravity Simplified Chinese localization in sync.' | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Antigravity Zh Sync is running. Log: $target\watch.log"
