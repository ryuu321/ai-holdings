#!/usr/bin/env pwsh
# 楽天ROOM auth更新 → GitHub Secret自動登録
# 実行: .\update_auth.ps1
# 所要時間: 約5分

Set-Location $PSScriptRoot

Write-Host "`n=== 楽天ROOM Auth更新スクリプト ===" -ForegroundColor Cyan
Write-Host "Step1: ブラウザでROOMにログインします"

# Step1: ブラウザでROOMにログイン
python capture_auth.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "capture_auth.py が失敗しました" -ForegroundColor Red
    exit 1
}

# Step2: クッキーを必要最小限に絞り込んでBase64化
Write-Host "`nStep2: auth.jsonをBase64変換中..."
python slim_auth.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "slim_auth.py が失敗しました" -ForegroundColor Red
    exit 1
}

# Step3: GitHub Secretに登録
Write-Host "`nStep3: GitHub Secret (RAKUTEN_AUTH_JSON) を更新中..."
Get-Content auth_base64.txt | gh secret set RAKUTEN_AUTH_JSON

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n完了！次の楽天ROOMワークフローから新しいセッションが使われます" -ForegroundColor Green
    Write-Host "次回実行時間: JST 22:00 (今夜)" -ForegroundColor Yellow
} else {
    Write-Host "GitHub Secret更新に失敗しました。ghコマンドがインストールされているか確認してください" -ForegroundColor Red
}
