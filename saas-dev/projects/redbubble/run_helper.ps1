# MidnightTorii — 手動アップロードヘルパー起動スクリプト
# ダブルクリックまたは PowerShell から実行: .\run_helper.ps1

$dir = "C:\Users\ryuuM\ai-holdings\saas-dev\projects\redbubble"
Set-Location $dir

# UTF-8 出力（日本語・記号が化けないよう設定）
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

Write-Host ""
Write-Host "MidnightTorii アップロードヘルパーを起動します..." -ForegroundColor Cyan
Write-Host ""

python -u "$dir\manual_upload_helper.py" $args

Write-Host ""
Write-Host "Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
