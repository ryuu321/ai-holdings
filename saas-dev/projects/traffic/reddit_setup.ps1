#!/usr/bin/env pwsh
# Reddit セッション作成 → GitHub Secret登録
# 実行: .\reddit_setup.ps1
# 所要時間: 5分

Set-Location $PSScriptRoot

Write-Host "`n=== Reddit セッション作成 ===" -ForegroundColor Cyan
Write-Host "Gumroadへのトラフィック最大化のため、Redditアカウントを設定します`n"

# 依存確認
Write-Host "依存パッケージを確認中..."
pip install playwright --quiet 2>$null
playwright install chromium --quiet 2>$null

# Redditログイン/作成
Write-Host "`nブラウザを開きます。"
Write-Host "  1. Redditアカウントをお持ちの場合: ログインしてください"
Write-Host "  2. ない場合: 新規作成してください (メール: ryuumg03@gmail.com 推奨)"
Write-Host ""
Write-Host "ホーム画面(reddit.com)が表示されてログイン済みになったら Enter を押してください`n"

python reddit.py --setup

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nRedditセットアップに失敗しました" -ForegroundColor Red
    exit 1
}

# Base64変換
if (Test-Path "data\reddit_session.json") {
    $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$PSScriptRoot\data\reddit_session.json"))

    # GitHub Secret登録
    Write-Host "`nGitHub Secret (REDDIT_SESSION_B64) を登録中..."
    $b64 | gh secret set REDDIT_SESSION_B64

    if ($LASTEXITCODE -eq 0) {
        Write-Host "`n✅ 完了！Redditトラフィックが明日から自動実行されます" -ForegroundColor Green
        Write-Host "対象サブレdit: r/ADHD, r/EtsySellers, r/Procreate, r/productivity など" -ForegroundColor Yellow
        Write-Host "Gumroad商品へのコメント投稿: 毎日JST11時に自動実行" -ForegroundColor Yellow
    } else {
        Write-Host "GitHub登録失敗。ghコマンドを確認してください" -ForegroundColor Red
    }
} else {
    Write-Host "セッションファイルが見つかりません" -ForegroundColor Red
}
