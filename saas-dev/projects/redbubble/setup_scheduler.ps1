# Redbubble 自動投稿 — Windows Task Scheduler 登録
# 管理者権限不要、毎日12:00 JST に実行

$taskName = "RedbubbleDailyUpload"
$dir      = "C:\Users\ryuuM\ai-holdings\saas-dev\projects\redbubble"
$script   = "$dir\run_local.ps1"

$action  = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -File `"$script`""

$trigger = New-ScheduledTaskTrigger -Daily -At "12:00"

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $taskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Force | Out-Null

Write-Host "✓ タスク登録完了: $taskName (毎日 12:00)"
Write-Host "確認: Get-ScheduledTask -TaskName '$taskName'"
Write-Host "今すぐテスト: Start-ScheduledTask -TaskName '$taskName'"
