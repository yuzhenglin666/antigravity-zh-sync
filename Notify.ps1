[CmdletBinding()]
param([Parameter(Mandatory)][ValidateSet('ready', 'installed')][string]$Event)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
try {
    $icon.Icon = [System.Drawing.SystemIcons]::Information
    $icon.Visible = $true
    $icon.BalloonTipTitle = 'Antigravity 汉化同步'
    $icon.BalloonTipText = if ($Event -eq 'ready') {
        '补丁已准备好。完成当前工作后，从系统托盘退出 Antigravity 即可自动安装。'
    } else {
        '汉化补丁已安装，可以重新打开 Antigravity。'
    }
    $icon.ShowBalloonTip(6500)
    Start-Sleep -Seconds 8
} finally {
    $icon.Dispose()
}
