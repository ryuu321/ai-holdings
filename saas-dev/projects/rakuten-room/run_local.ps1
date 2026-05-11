# 楽天ROOM 自動投稿 - ローカル実行スクリプト
$dir = "C:\Users\ryuuM\ai-holdings\saas-dev\projects\rakuten-room"

# .env読み込み
Get-Content "C:\Users\ryuuM\ai-holdings\.env" | ForEach-Object {
    if ($_ -match "^([^#][^=]*)=(.*)$") {
        [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
    }
}

# 実行
python -u "$dir\main.py" >> "$dir\logs\run.log" 2>&1
