# Redbubble 自動投稿 - ローカル実行スクリプト
$dir = "C:\Users\ryuuM\ai-holdings\saas-dev\projects\redbubble"
$logDir = "$dir\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# .env 読み込み
Get-Content "C:\Users\ryuuM\ai-holdings\.env" | ForEach-Object {
    if ($_ -match "^([^#][^=]*)=(.*)$") {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
    }
}

Set-Location $dir
python -u "$dir\main.py" >> "$logDir\run.log" 2>&1
