# Rakuten ROOM Task Scheduler Setup (Run as Administrator)

$scriptPath = "C:\Users\ryuuM\ai-holdings\saas-dev\projects\rakuten-room\run_local.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -WindowStyle Hidden -File $scriptPath"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2)

$tasks = @(
    @{ Name = "RakutenRoom_0030"; Time = "00:30" },
    @{ Name = "RakutenRoom_0500"; Time = "05:00" },
    @{ Name = "RakutenRoom_0930"; Time = "09:30" },
    @{ Name = "RakutenRoom_1400"; Time = "14:00" },
    @{ Name = "RakutenRoom_1800"; Time = "18:00" },
    @{ Name = "RakutenRoom_2230"; Time = "22:30" }
)

foreach ($t in $tasks) {
    $trigger = New-ScheduledTaskTrigger -Daily -At $t.Time
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force
    Write-Host "OK: $($t.Name) ($($t.Time))"
}

Write-Host ""
Write-Host "Registered tasks:"
Get-ScheduledTask | Where-Object { $_.TaskName -like "RakutenRoom*" } | Select-Object TaskName | Sort-Object TaskName
