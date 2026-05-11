"""
楽天アフィリエイト規約コンプライアンスチェッカー
- 自動生成コンテンツが規約に準拠しているか自動検証
- ステマ規制（景品表示法）対応チェック
"""
import re
from loguru import logger
from typing import Dict, Any, List

PROHIBITED_EXPRESSIONS = [
    # 誇大表現
    "確実に", "必ず", "絶対に", "100%",
    # 虚偽の成果
    "痩せる保証", "儲かる保証", "確実に稼げる",
    # 自己購入誘導
    "自分で購入して試した",  # ※自己アフィリは規約違反
]

REQUIRED_DISCLOSURES = ["PR", "広告", "プロモーション", "アフィリエイト"]

class ComplianceChecker:
    
    async def check_article(self, article: dict) -> dict:
        """記事全体のコンプライアンスチェック"""
        warnings = []
        errors = []
        
        content = article.get("content", "")
        title = article.get("title", "")
        
        # 1. PR/広告表記チェック
        has_disclosure = any(d in content[:500] for d in REQUIRED_DISCLOSURES)
        if not has_disclosure:
            errors.append("CRITICAL: PR/広告表記がファーストビューにありません")
        
        # 2. 禁止表現チェック
        for expr in PROHIBITED_EXPRESSIONS:
            if expr in content:
                warnings.append(f"禁止表現検出: '{expr}'")
        
        # 3. 楽天クレジットバナーチェック
        if "webservice.rakuten.co.jp" not in content:
            warnings.append("楽天Web Serviceクレジットバナーがありません")
        
        # 4. rel="sponsored"属性チェック
        # 注: 楽天アフィリエイトリンクのドメイン hb.afl.rakuten.co.jp を含むリンクをチェック
        affiliate_links = re.findall(r'<a[^>]+href="[^"]*rakuten\.co\.jp[^"]*"[^>]*>', content)
        for link in affiliate_links:
            if 'rel="nofollow sponsored"' not in link and 'rel="sponsored"' not in link:
                warnings.append(f"アフィリエイトリンクにrel=sponsored属性がありません: {link[:50]}...")
                break
        
        # 5. タイトル文字数チェック
        if len(title) > 60:
            warnings.append(f"タイトルが長すぎます: {len(title)}文字")
        
        return {
            "passed": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    def validate_sns_post(self, post_text: str, platform: str) -> dict:
        """SNS投稿のコンプライアンスチェック"""
        errors = []
        
        # PR表記チェック
        has_pr = any(d in post_text for d in ["#PR", "#広告", "【PR】", "【広告】"])
        if not has_pr:
            errors.append("SNS投稿にPR表記が必要です")
        
        # Twitterの文字数制限チェック
        if platform == "twitter":
            if len(post_text) > 280:
                errors.append(f"Twitterの文字数制限超過: {len(post_text)}文字")
        
        return {"passed": len(errors) == 0, "errors": errors}

    def inject_disclosure(self, content: str) -> str:
        disclosure = '<div class="pr-disclosure" style="background:#f8f9fa;padding:10px;border:1px solid #ddd;margin-bottom:20px;">※本記事はアフィリエイト広告を利用しています。</div>'
        return disclosure + content
