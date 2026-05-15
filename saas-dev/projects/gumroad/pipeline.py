"""Gumroad自動化パイプライン — AIプロンプトパック・Notionテンプレートの生成・出品・PDCA"""
import os
import sys
import json
import random
import logging
import argparse
import re
import requests
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
from pathlib import Path

from groq import Groq
from dotenv import load_dotenv

# .env 読み込み（プロジェクトルートの .env を優先）
_ROOT = Path(__file__).parent.parent.parent.parent  # ai-holdings/
load_dotenv(_ROOT / ".env")

# ───────────────────────────── 定数 ─────────────────────────────
GUMROAD_BASE    = "https://app.gumroad.com/api/v2"   # ファイルアップロード・製品管理
GUMROAD_API     = "https://api.gumroad.com/v2"        # 売上・分析
GUMROAD_TOKEN   = os.environ.get("GUMROAD_ACCESS_TOKEN", "")
GROQ_KEY        = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL      = "llama-3.3-70b-versatile"
PRICE_MIN_CENTS  = 1500   # $15 絶対下限
PRICE_DEFAULT    = 3700   # $37 フォールバック（チャーム価格）
# チャーム価格リスト（行動経済学: 端数が高級感と割安感を両立）
CHARM_PRICES_USD = [17, 27, 37, 47, 57, 67, 77, 97]
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT   = os.environ.get("TELEGRAM_CHANNEL_ID", "")

DATA_DIR        = Path(__file__).parent / "data"
PRODUCTS_DIR    = DATA_DIR / "products"
SALES_LOG       = DATA_DIR / "sales_log.json"
PDCA_REPORT     = DATA_DIR / "pdca_report.json"
STRATEGY_FILE   = DATA_DIR / "strategy.json"
MARKET_CACHE    = DATA_DIR / "market_research.json"

CACHE_TTL_HOURS = 6  # リサーチキャッシュの有効期間（時間）

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

NICHES = [
    "Freelance Copywriters",
    "Real Estate Agents",
    "Etsy Sellers",
    "Fitness Coaches",
    "Podcast Creators",
    "ADHD Productivity",
    "Solopreneurs",
    "UX Designers",
    "Virtual Assistants",
    "E-commerce Entrepreneurs",
    "Content Creators",
    "Life Coaches",
    "SaaS Founders",
    "Graphic Designers",
    "Remote Team Managers",
]

PRODUCT_TYPES = ["ai_prompts", "notion_template"]

logging.basicConfig(
    level=logging.INFO,
    format="[gumroad] %(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ───────────────────────────── 市場調査 ─────────────────────────────

def _load_market_cache() -> dict | None:
    """6時間以内のキャッシュがあれば返す。なければNone。"""
    if not MARKET_CACHE.exists():
        return None
    try:
        data = json.loads(MARKET_CACHE.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data.get("cached_at", "2000-01-01T00:00:00+00:00"))
        if datetime.now(timezone.utc) - cached_at < timedelta(hours=CACHE_TTL_HOURS):
            log.info(f"市場調査キャッシュ使用（{cached_at.strftime('%Y-%m-%d %H:%M')} UTC）")
            return data
    except Exception:
        pass
    return None


def _scrape_gumroad_playwright() -> list[str]:
    """PlaywrightでGumroad DiscoverをJSレンダリングして製品タイトルを取得。"""
    from playwright.sync_api import sync_playwright
    items = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=SCRAPE_HEADERS["User-Agent"])
            page = context.new_page()
            page.goto("https://gumroad.com/discover", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            seen = set()
            for sel in ["h3", "h4", "[class*='ProductCard'] h2", "[class*='product-name']"]:
                try:
                    for el in page.query_selector_all(sel):
                        text = el.inner_text().strip()
                        if text and 5 < len(text) < 100 and text not in seen:
                            seen.add(text)
                            items.append(text)
                except Exception:
                    pass

            browser.close()
        log.info(f"Gumroad Discover (Playwright): {len(items)} タイトル取得")
    except Exception as e:
        log.warning(f"Playwright Gumroadスクレイピング失敗: {e}")
    return items[:20]


def _scrape_gumroad_prices(niche: str) -> list[dict]:
    """Gumroad Discoverでニッチ検索し、競合商品のタイトルと価格を取得する。"""
    from playwright.sync_api import sync_playwright
    items = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=SCRAPE_HEADERS["User-Agent"])
            page = context.new_page()
            query = niche.replace(" ", "+")
            page.goto(f"https://gumroad.com/discover?query={query}", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            # 商品カードを横断してタイトル＋価格を取得
            for card_sel in ["[data-testid*='product']", "article", "[class*='product-card']", "[class*='ProductCard']"]:
                cards = page.query_selector_all(card_sel)
                for card in cards[:25]:
                    try:
                        title = ""
                        for ts in ["h3", "h4", "h2", "[class*='name']", "[class*='title']"]:
                            el = card.query_selector(ts)
                            if el:
                                title = el.inner_text().strip()
                                break
                        price_text = ""
                        for ps in ["[class*='price']", "[data-price]", "[class*='Price']"]:
                            el = card.query_selector(ps)
                            if el:
                                price_text = el.inner_text().strip()
                                break
                        if not title:
                            continue
                        price = None
                        if price_text:
                            m = re.search(r'[\d.]+', price_text.replace(",", ""))
                            if m:
                                price = float(m.group())
                        items.append({"title": title, "price": price})
                    except Exception:
                        pass
                if items:
                    break

            # カードが取れなかった場合はページテキストから価格を抽出
            if not items:
                all_text = page.inner_text("body")
                prices_raw = re.findall(r'\$\s*([\d.]+)', all_text)
                for pv in prices_raw[:15]:
                    v = float(pv)
                    if 1 <= v <= 200:
                        items.append({"title": "", "price": v})

            browser.close()
        log.info(f"Gumroad価格スクレイピング ({niche}): {len(items)}件")
    except Exception as e:
        log.warning(f"Gumroad価格スクレイピング失敗: {e}")
    return items


def research_price(niche: str, product_type: str) -> int:
    """
    行動経済学・市場調査に基づいて価格を極大化する。
    競合上位20%に位置づけ、チャーム価格（$X7/$X7）で価値認知を最大化。
    下限$15のみ設定、上限なし。
    """
    items = _scrape_gumroad_prices(niche)
    paid_prices = sorted([
        it["price"] for it in items
        if it.get("price") and 1.0 <= it["price"] <= 500
    ])

    if not paid_prices:
        log.info(f"価格データなし → デフォルト ${PRICE_DEFAULT/100:.0f}")
        return PRICE_DEFAULT  # PRICE_DEFAULT is already in cents ($37 = 3700 cents)

    median = paid_prices[len(paid_prices) // 2]
    avg    = sum(paid_prices) / len(paid_prices)
    low    = paid_prices[0]
    high   = paid_prices[-1]
    p80_idx = int(len(paid_prices) * 0.8)
    p80    = paid_prices[min(p80_idx, len(paid_prices) - 1)]
    log.info(f"競合価格 ({niche}): 中央値=${median:.2f} 平均=${avg:.2f} 80th=${p80:.2f} 範囲=${low:.2f}〜${high:.2f}")

    recommended_usd = PRICE_DEFAULT / 100

    if GROQ_KEY:
        prompt = f"""You are a behavioral economics pricing strategist for Gumroad digital products.
Your goal is to MAXIMIZE revenue per sale — not minimize price.

Niche: {niche}
Product type: {product_type}
Competitor prices on Gumroad (USD): {paid_prices}
Market stats: median=${median:.2f}, avg=${avg:.2f}, 80th percentile=${p80:.2f}, range=${low:.2f}-${high:.2f}

Pricing philosophy to apply:
1. CHARM PRICING: Use prices ending in 7 ($27, $37, $47, $67, $97) — they feel less round yet signal premium
2. VEBLEN EFFECT: Higher price = higher perceived quality for digital products
3. UPPER-TIER POSITIONING: Target the top 20% of competitor prices to signal expertise
4. VALUE-BASED: Price based on what the buyer GAINS (time saved, income potential), not production cost
5. NO artificial cap — if the market supports $97+, recommend it
6. Absolute minimum: $15

Available charm prices to choose from: {CHARM_PRICES_USD} (or higher if market supports it)

Consider: a buyer spending $47 on AI prompts to make $500/month sees 10x ROI instantly.

Respond with ONLY valid JSON (no markdown):
{{"recommended_price_usd": 47, "reasoning": "one sentence on why this price maximizes revenue"}}"""
        try:
            client = Groq(api_key=GROQ_KEY)
            resp = client.chat.completions.create(
                model=GROQ_MODEL, max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content.strip()
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                result = json.loads(m.group())
                recommended_usd = float(result.get("recommended_price_usd", PRICE_DEFAULT / 100))
                log.info(f"Groq価格推奨: ${recommended_usd:.2f} — {result.get('reasoning', '')}")
        except Exception as e:
            log.warning(f"Groq価格推奨失敗: {e}")
            # フォールバック: 競合80パーセンタイルを最も近いチャーム価格に丸める
            recommended_usd = p80

    # 最も近いチャーム価格に丸める（$15以上）
    valid = [c for c in CHARM_PRICES_USD if c >= PRICE_MIN_CENTS / 100]
    nearest_charm = min(valid, key=lambda c: abs(c - recommended_usd))
    # Groqが高い価格を推薦した場合はチャームリスト外でも尊重
    if recommended_usd > max(CHARM_PRICES_USD):
        # $100以上は$7刻みのチャーム価格に丸める
        nearest_charm = int(recommended_usd / 10) * 10 + 7
    final_usd = max(PRICE_MIN_CENTS / 100, nearest_charm)
    log.info(f"最終価格: ${final_usd}")
    return int(final_usd) * 100


def _scrape_reddit_demand() -> list[str]:
    """Reddit JSON API からホットトピックを取得（APIキー不要）。需要シグナルとして使用。"""
    subreddits = ["passive_income", "entrepreneur", "ChatGPT", "Notion", "digitalnomad"]
    topics = []
    headers = {**SCRAPE_HEADERS, "Accept": "application/json"}
    for sub in subreddits:
        try:
            r = requests.get(
                f"https://www.reddit.com/r/{sub}/hot.json?limit=15",
                headers=headers,
                timeout=10,
            )
            r.raise_for_status()
            for post in r.json().get("data", {}).get("children", []):
                title = post.get("data", {}).get("title", "").strip()
                if title and 10 < len(title) < 150:
                    topics.append(title)
        except Exception as e:
            log.warning(f"Reddit r/{sub} 取得失敗: {e}")
    log.info(f"Reddit: {len(topics)} トピック取得")
    return topics[:25]


def research_market() -> dict:
    """
    Gumroad Discover・Gumtrendsをスクレイピングし、Groqで市場分析を行う。
    結果を data/market_research.json にキャッシュ（6時間有効）。
    失敗時はfallback辞書を返す（ランダムNICHES選択用）。
    """
    # キャッシュチェック
    cached = _load_market_cache()
    if cached:
        return cached

    fallback = {
        "top_niches": random.sample(NICHES, 3),
        "recommended_niche": random.choice(NICHES),
        "recommended_type": random.choice(PRODUCT_TYPES),
        "title_idea": "",
        "reasoning": "Fallback: market research unavailable",
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "source": "fallback",
    }

    if not GROQ_KEY:
        log.warning("GROQ_API_KEY未設定のため市場調査をスキップ")
        return fallback

    try:
        # スクレイピング（Playwright + Reddit）
        gumroad_titles = _scrape_gumroad_playwright()
        reddit_topics  = _scrape_reddit_demand()

        gumroad_text = "\n".join(f"- {t}" for t in gumroad_titles[:8]) or "(none)"
        reddit_text  = "\n".join(f"- {t}" for t in reddit_topics[:10]) or "(none)"
        niches_sample = random.sample(NICHES, min(8, len(NICHES)))

        has_data = bool(gumroad_titles or reddit_topics)
        if not has_data:
            log.warning("スクレイピングデータなし。Groq分析をNICHESリストのみで実施")

        analysis_prompt = f"""You are a Gumroad digital product market analyst. Respond with ONLY a JSON object.

Currently trending on Gumroad Discover:
{gumroad_text}

Hot topics on Reddit (r/passive_income, r/entrepreneur, r/ChatGPT, r/Notion, r/digitalnomad) showing buyer demand:
{reddit_text}

Niches known to sell well on Gumroad: {", ".join(niches_sample)}

Based on the above data, identify the single best niche to target RIGHT NOW.
Respond with ONLY this JSON (no markdown, complete and valid):
{{"top_niches":["n1","n2","n3"],"recommended_niche":"exact niche name","recommended_type":"ai_prompts","title_idea":"Compelling Title Under 60 Chars"}}

recommended_type must be exactly ai_prompts or notion_template. Choose the niche with clearest demand signal."""

        client = Groq(api_key=GROQ_KEY)
        message = client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": analysis_prompt}],
        )
        raw = message.choices[0].message.content.strip()

        # JSON抽出（トランケーション対応）
        raw_clean = re.sub(r"```(?:json)?\s*", "", raw).strip()
        m = re.search(r"\{.*\}", raw_clean, re.DOTALL)
        if m:
            json_str = m.group()
        else:
            # 閉じ括弧なしで切れている場合：先頭{から末尾まで取って修復
            brace_start = raw_clean.find("{")
            if brace_start == -1:
                log.error(f"Groq市場分析: JSONが見つかりません: {raw[:200]}")
                return fallback
            json_str = raw_clean[brace_start:]

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            # trailing comma除去 + 閉じ括弧補完
            repaired = json_str.rstrip().rstrip(",")
            repaired += "]" * max(0, repaired.count("[") - repaired.count("]"))
            repaired += "}" * max(0, repaired.count("{") - repaired.count("}"))
            try:
                result = json.loads(repaired)
                log.info("JSONを修復してパース成功")
            except json.JSONDecodeError as e:
                log.error(f"JSON修復失敗: {e}. Raw: {raw[:300]}")
                return fallback

        # recommended_typeのバリデーション
        if result.get("recommended_type") not in PRODUCT_TYPES:
            result["recommended_type"] = random.choice(PRODUCT_TYPES)

        result["cached_at"] = datetime.now(timezone.utc).isoformat()
        result["source"] = "groq_analysis"
        result["gumroad_titles_count"] = len(gumroad_titles)
        result["reddit_topics_count"] = len(reddit_topics)

        # キャッシュ保存
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MARKET_CACHE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"市場調査完了: recommended_niche={result.get('recommended_niche')} type={result.get('recommended_type')}")
        log.info(f"  title_idea: {result.get('title_idea')}")
        log.info(f"  reasoning: {result.get('reasoning')}")
        return result

    except Exception as e:
        log.error(f"market_research エラー（fallback使用）: {e}")
        return fallback


# ───────────────────────────── Claude 生成 ─────────────────────────────

def _build_prompt(product_type: str, niche: str, title_hint: str = "", used_titles: list = None) -> str:
    hint_line = f'\nTitle direction (adapt freely, must be compelling): "{title_hint}"' if title_hint else ""
    avoid_line = f'\nDO NOT use any of these already-published titles (must be unique): {used_titles}' if used_titles else ""
    if product_type == "ai_prompts":
        return f"""Create a premium AI prompt pack for {niche} professionals.{hint_line}{avoid_line}

Output a JSON object with EXACTLY these keys:
{{
  "title": "Product title (catchy, benefit-driven, under 60 chars)",
  "description": "SEO-optimized product description (150-200 words). Include keywords naturally. Mention 50 ready-to-use prompts.",
  "content": "The full prompt pack. Write 50 numbered prompts, each 1-3 sentences, specifically for {niche}. Format: '1. [Prompt text]\\n2. [Prompt text]...' Make them practical and immediately usable with ChatGPT or Claude."
}}

Output ONLY the JSON. No markdown, no code fences."""
    else:
        return f"""Create a premium Notion template for {niche} professionals.{hint_line}{avoid_line}

Output a JSON object with EXACTLY these keys:
{{
  "title": "Product title (catchy, benefit-driven, under 60 chars)",
  "description": "SEO-optimized product description (150-200 words). Include keywords naturally. Mention the Notion template structure.",
  "content": "The full Notion template documentation. Include:\\n- Template Overview\\n- Database Properties (list all fields with types)\\n- Views Setup (Board, Calendar, Table, Gallery)\\n- Workflow Guide (step-by-step)\\n- Quick Start Checklist\\n- Pro Tips (5-7 tips for {niche})\\nMake it detailed enough to be a standalone product ($39 value)."
}}

Output ONLY the JSON. No markdown, no code fences."""


def _load_strategy() -> dict:
    """strategy.jsonを読み込む。なければデフォルト返す。"""
    if STRATEGY_FILE.exists():
        try:
            return json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"niche_weights": {n: 1.0 for n in NICHES}, "preferred_type": None, "used_titles": [], "used_niches_recent": []}


def _weighted_choice(weights: dict) -> str:
    """重み付きランダム選択。"""
    keys = list(weights.keys())
    vals = [max(weights[k], 0.1) for k in keys]
    total = sum(vals)
    r = random.uniform(0, total)
    cumulative = 0
    for k, v in zip(keys, vals):
        cumulative += v
        if r <= cumulative:
            return k
    return keys[-1]


def generate_product(product_type: str = None, niche: str = None) -> dict:
    """Groq APIで製品コンテンツを生成し、data/products/に保存。生成メタデータを返す。"""
    if not GROQ_KEY:
        log.error("GROQ_API_KEY が設定されていません")
        return {}

    # 市場調査（--niche / --type で明示指定された場合は調査結果を優先しない）
    research = research_market()
    strategy = _load_strategy()

    if product_type:
        # CLI明示指定を優先
        pass
    elif strategy.get("preferred_type"):
        product_type = strategy["preferred_type"]
    else:
        product_type = research.get("recommended_type") or random.choice(PRODUCT_TYPES)

    used_titles  = strategy.get("used_titles", [])
    recent_niches = strategy.get("used_niches_recent", [])

    if niche:
        pass  # CLI明示指定を優先
    else:
        research_niche = research.get("recommended_niche", "")
        # 直近3回と同じnicheは避ける
        if research_niche and research_niche in NICHES and research_niche not in recent_niches[-3:]:
            niche = research_niche
            log.info(f"市場調査推薦ニッチを使用: {niche}")
        else:
            # 重み付き選択。直近使ったnicheは一時的に重みを下げる
            weights = dict(strategy.get("niche_weights", {n: 1.0 for n in NICHES}))
            for n in recent_niches[-3:]:
                weights[n] = weights.get(n, 1.0) * 0.1
            niche = _weighted_choice(weights)
            log.info(f"重み付き選択ニッチを使用（直近回避）: {niche}")

    title_hint = research.get("title_idea", "")
    log.info(f"生成開始: type={product_type} niche={niche} title_hint={title_hint!r}")
    log.info(f"使用済みタイトル({len(used_titles)}件)を回避")

    client = Groq(api_key=GROQ_KEY)
    prompt = _build_prompt(product_type, niche, title_hint=title_hint, used_titles=used_titles[-10:])

    try:
        message = client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"Groq API エラー: {e}")
        return {}

    # JSON 抽出（コードブロックが混入しても対応）
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        log.error(f"JSON が見つかりません: {raw[:200]}")
        return {}

    try:
        data = json.loads(m.group(), strict=False)
    except json.JSONDecodeError as e:
        log.error(f"JSON パースエラー: {e}")
        return {}

    # ファイル保存
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = niche.lower().replace(" ", "_")
    filename = f"{ts}_{product_type}_{slug}.txt"
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = PRODUCTS_DIR / filename
    file_path.write_text(data.get("content", ""), encoding="utf-8")

    title = data.get("title", "")

    # 使用済みタイトル・ニッチを記録してstrategy.jsonに即保存
    used_titles.append(title)
    recent_niches.append(niche)
    strategy["used_titles"]       = used_titles[-50:]   # 最大50件保持
    strategy["used_niches_recent"] = recent_niches[-10:]
    STRATEGY_FILE.parent.mkdir(parents=True, exist_ok=True)
    STRATEGY_FILE.write_text(json.dumps(strategy, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {
        "product_type": product_type,
        "niche":        niche,
        "title":        title,
        "description":  data.get("description", ""),
        "file_path":    str(file_path),
        "generated_at": ts,
    }
    log.info(f"生成完了: {meta['title']}")
    return meta


# ───────────────────────────── サムネイル生成 ─────────────────────────────

def _generate_thumbnail(title: str, product_type: str, output_path: Path) -> bool:
    """PillowでGumroad用カバー画像(1280×720)を生成。失敗時はFalseを返す。"""
    try:
        from PIL import Image, ImageDraw, ImageFont

        W, H = 1280, 720
        bg     = (10, 20, 50)    if product_type == "ai_prompts" else (20, 10, 40)
        accent = (56, 139, 253)  if product_type == "ai_prompts" else (130, 80, 255)
        dark   = (3, 60, 150)    if product_type == "ai_prompts" else (60, 20, 160)

        img  = Image.new("RGB", (W, H), bg)
        draw = ImageDraw.Draw(img)

        # 上部グラデーション
        for i in range(250):
            t = 1 - i / 250
            r = int(bg[0] + (dark[0] - bg[0]) * t * 0.6)
            g = int(bg[1] + (dark[1] - bg[1]) * t * 0.6)
            b = int(bg[2] + (dark[2] - bg[2]) * t * 0.6)
            draw.line([(0, i), (W, i)], fill=(r, g, b))

        # 左アクセントバー
        draw.rectangle([0, 0, 10, H], fill=accent)

        # フォント（OS別パス）
        font_candidates = [
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",     80),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 80),
            ("C:/Windows/Fonts/arialbd.ttf",  80),
            ("C:/Windows/Fonts/calibrib.ttf", 80),
        ]
        sub_candidates = [
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",         38),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 38),
            ("C:/Windows/Fonts/arial.ttf",   38),
            ("C:/Windows/Fonts/calibri.ttf", 38),
        ]
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        for fp, sz in font_candidates:
            if Path(fp).exists():
                try:
                    font_large = ImageFont.truetype(fp, sz)
                    break
                except Exception:
                    pass
        for fp, sz in sub_candidates:
            if Path(fp).exists():
                try:
                    font_small = ImageFont.truetype(fp, sz)
                    break
                except Exception:
                    pass

        # タイトル折り返し（22文字/行）
        words = title.split()
        lines, cur = [], []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) > 22:
                if len(cur) > 1:
                    lines.append(" ".join(cur[:-1]))
                    cur = [w]
                else:
                    lines.append(" ".join(cur))
                    cur = []
        if cur:
            lines.append(" ".join(cur))

        line_h = 100
        y = (H - len(lines) * line_h) // 2 - 20
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font_large)
            tw = bbox[2] - bbox[0]
            draw.text(((W - tw) // 2, y), line, fill=(255, 255, 255), font=font_large)
            y += line_h

        badge = "AI Prompt Pack" if product_type == "ai_prompts" else "Notion Template"
        draw.text((30, H - 65), badge, fill=accent, font=font_small)
        draw.text((W - 120, H - 65), "$39", fill=(255, 255, 255), font=font_small)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "PNG")
        log.info(f"サムネイル生成: {output_path.name}")
        return True
    except Exception as e:
        log.warning(f"サムネイル生成失敗（スキップ）: {e}")
        return False


# ───────────────────────────── Gumroad ファイルアップロード ─────────────────────────────

def _upload_file_to_s3(file_path: Path, headers: dict) -> str:
    """S3 presigned upload フローでファイルをアップロードし file_url を返す。"""
    file_size = file_path.stat().st_size

    # Step 1: presign取得
    r = requests.post(
        f"{GUMROAD_BASE}/files/presign",
        headers=headers,
        json={"filename": file_path.name, "file_size": file_size},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise ValueError(f"presign失敗: {data}")

    upload_id = data["upload_id"]
    key       = data["key"]
    parts     = data["parts"]

    # Step 2: S3へ直接PUT（パート毎）
    etags = []
    file_bytes = file_path.read_bytes()
    chunk = 100 * 1024 * 1024  # 100MB
    for part in parts:
        start = (part["part_number"] - 1) * chunk
        end   = min(start + chunk, file_size)
        resp = requests.put(part["presigned_url"], data=file_bytes[start:end], timeout=120)
        resp.raise_for_status()
        etags.append({"part_number": part["part_number"], "etag": resp.headers["ETag"]})

    # Step 3: 完了通知
    r = requests.post(
        f"{GUMROAD_BASE}/files/complete",
        headers=headers,
        json={"upload_id": upload_id, "key": key, "parts": etags},
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()
    if not result.get("success"):
        raise ValueError(f"complete失敗: {result}")

    return result["file_url"]


# ───────────────────────────── Gumroad 出品 ─────────────────────────────

def publish_to_gumroad(meta: dict) -> str:
    """Gumroad に製品を作成・ファイルアップロード・公開。product_id を返す。"""
    if not GUMROAD_TOKEN:
        log.error("GUMROAD_ACCESS_TOKEN が設定されていません")
        return ""
    if not meta:
        log.error("meta が空です。generate_product を先に実行してください")
        return ""

    headers = {"Authorization": f"Bearer {GUMROAD_TOKEN}"}

    # 1. 製品作成（市場調査ベースの価格設定）
    price_cents = research_price(meta.get("niche", ""), meta.get("product_type", "ai_prompts"))
    log.info(f"市場調査価格: ${price_cents/100:.2f}")
    payload = {
        "name":              meta["title"],
        "description":       meta["description"],
        "price":             price_cents,
        "currency":          "usd",
        "published":         False,  # ファイルアップ後に公開
        "require_shipping":  False,
    }
    try:
        r = requests.post(f"{GUMROAD_BASE}/products", headers=headers, data=payload, timeout=30)
        r.raise_for_status()
        product = r.json().get("product", {})
        product_id  = product.get("id", "")
        short_url   = product.get("short_url", "")
        permalink   = short_url.rstrip("/").split("/")[-1] if short_url else ""
        log.info(f"製品作成: id={product_id} permalink={permalink} name={meta['title']}")
    except Exception as e:
        log.error(f"製品作成エラー: {e}")
        return ""

    pid_encoded = quote(product_id, safe="")

    # 2. S3経由ファイルアップロード → 製品に紐付け＆公開
    file_path = Path(meta.get("file_path", ""))
    if file_path.exists():
        try:
            file_url = _upload_file_to_s3(file_path, headers)
            log.info(f"S3アップロード完了: {file_url[:60]}...")
        except Exception as e:
            log.error(f"S3アップロードエラー: {e}")
            return product_id

    # 3. Playwrightでファイルアップロード＆公開
    from uploader import publish_product, upload_cover_image
    if permalink:
        success = publish_product(permalink, meta.get("file_path"))
        if not success:
            log.warning("公開失敗: python uploader.py --setup を再実行してください")

        # 4. サムネイル生成 & アップロード
        thumb_path = DATA_DIR / "thumbnails" / f"{permalink}.png"
        if _generate_thumbnail(meta["title"], meta["product_type"], thumb_path):
            upload_cover_image(permalink, str(thumb_path))

            # 5. Pinterest自動ピン投稿
            try:
                import sys as _sys
                _traffic = Path(__file__).parent.parent / "traffic"
                if str(_traffic) not in _sys.path:
                    _sys.path.insert(0, str(_traffic))
                from pinterest import pin_product
                pin_product(
                    title=meta["title"],
                    niche=meta["niche"],
                    product_type=meta["product_type"],
                    image_path=str(thumb_path),
                    gumroad_url=short_url,
                    product_id=product_id,
                )
            except Exception as e:
                log.warning(f"Pinterest投稿スキップ（セッション未設定?）: {e}")

        # 6. Gumroadアフィリエイト有効化（他者が宣伝しやすくする）
        try:
            ra = requests.put(
                f"{GUMROAD_API}/products/{quote(product_id, safe='')}",
                headers=headers,
                data={
                    "affiliates_disabled":         "false",
                    "affiliate_offer_rate":        "25",  # 25%コミッション
                },
                timeout=30,
            )
            if ra.ok:
                log.info("アフィリエイト有効化: 25%コミッション設定")
        except Exception as e:
            log.debug(f"アフィリエイト設定スキップ: {e}")

        # 7. Redditプロモーション候補をログに記録
        promote_on_reddit(meta, short_url)

    else:
        log.warning("permalinkが取得できませんでした")

    return product_id


# ───────────────────────────── 売上チェック ─────────────────────────────

def check_sales() -> list:
    """Gumroad の直近売上を取得して sales_log.json に追記。売上リストを返す。"""
    if not GUMROAD_TOKEN:
        log.error("GUMROAD_ACCESS_TOKEN が設定されていません")
        return []

    headers = {"Authorization": f"Bearer {GUMROAD_TOKEN}"}
    try:
        r = requests.get(f"{GUMROAD_API}/sales", headers=headers, timeout=30)
        r.raise_for_status()
        sales = r.json().get("sales", [])
        log.info(f"売上件数: {len(sales)}")
    except Exception as e:
        log.error(f"売上取得エラー: {e}")
        return []

    # 追記保存
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing = []
    if SALES_LOG.exists():
        try:
            existing = json.loads(SALES_LOG.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    existing_ids = {s.get("id") for s in existing}
    new_sales = [s for s in sales if s.get("id") not in existing_ids]
    if new_sales:
        existing.extend(new_sales)
        SALES_LOG.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"新規売上 {len(new_sales)} 件を追記")
    else:
        log.info("新規売上なし")

    return sales


# ───────────────────────────── Telegram 通知 ─────────────────────────────

def _notify(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"Telegram通知失敗: {e}")


# ───────────────────────────── PDCA ─────────────────────────────

def _fetch_published_products() -> list[dict]:
    """Gumroad API で公開済み商品一覧を取得する。"""
    if not GUMROAD_TOKEN:
        return []
    try:
        r = requests.get(
            f"{GUMROAD_API}/products",
            headers={"Authorization": f"Bearer {GUMROAD_TOKEN}"},
            timeout=30,
        )
        r.raise_for_status()
        return [p for p in r.json().get("products", []) if p.get("published")]
    except Exception as e:
        log.warning(f"商品一覧取得失敗: {e}")
        return []


def fix_overpriced_products(target_cents: int = PRICE_DEFAULT):
    """
    価格バグ（$3700）で作成された商品を正しい価格に修正する。
    $3700（370000 cents）以上の商品を target_cents に更新する。
    """
    if not GUMROAD_TOKEN:
        log.error("GUMROAD_ACCESS_TOKEN が設定されていません")
        return
    headers = {"Authorization": f"Bearer {GUMROAD_TOKEN}"}
    try:
        r = requests.get(f"{GUMROAD_API}/products", headers=headers, timeout=30)
        r.raise_for_status()
        products = r.json().get("products", [])
    except Exception as e:
        log.error(f"商品一覧取得失敗: {e}")
        return

    fixed = 0
    for p in products:
        price = int(p.get("price", 0))
        pid   = p.get("id", "")
        name  = p.get("name", "")
        if price >= 100000:  # $1000以上は明らかにバグ
            try:
                ru = requests.put(
                    f"{GUMROAD_API}/products/{quote(pid, safe='')}",
                    headers=headers,
                    data={"price": target_cents},
                    timeout=30,
                )
                ru.raise_for_status()
                log.info(f"価格修正: {name} ${price/100:.0f} → ${target_cents/100:.0f}")
                fixed += 1
            except Exception as e:
                log.warning(f"価格修正失敗 ({name}): {e}")

    log.info(f"価格修正完了: {fixed}件")
    return fixed


def promote_on_reddit(meta: dict, product_url: str):
    """
    Redditの関連subredditに有益なコメントを投稿してGumroad商品へのトラフィックを誘導する。
    Reddit API（無料・APIキー不要）を使用。直接宣伝はBANリスクがあるため、
    価値提供コメント + さりげない商品リンクのみ。
    """
    niche = meta.get("niche", "")
    title = meta.get("title", "")
    if not product_url or not niche:
        return

    niche_subreddits = {
        "Freelance Copywriters":     ["freelancewriters", "copywriting"],
        "Real Estate Agents":        ["realestate", "realestateagents"],
        "Etsy Sellers":              ["Etsy", "EtsySellers"],
        "Fitness Coaches":           ["personaltraining", "fitness"],
        "Podcast Creators":          ["podcasting", "podcasts"],
        "ADHD Productivity":         ["ADHD", "productivity"],
        "Solopreneurs":              ["solopreneur", "entrepreneur"],
        "UX Designers":              ["UXDesign", "userexperience"],
        "Virtual Assistants":        ["VirtualAssistant", "WorkOnline"],
        "E-commerce Entrepreneurs":  ["ecommerce", "dropship"],
        "Content Creators":          ["NewTubers", "content_marketing"],
        "Life Coaches":              ["lifecoaching", "selfimprovement"],
        "SaaS Founders":             ["SaaS", "startups"],
        "Graphic Designers":         ["graphic_design", "design"],
        "Remote Team Managers":      ["remotework", "management"],
    }
    subs = niche_subreddits.get(niche, [])
    if not subs:
        return

    headers = {
        **SCRAPE_HEADERS,
        "Accept": "application/json",
    }

    for sub in subs[:1]:  # 1サブレのみ（スパム回避）
        try:
            # ホットな投稿を取得してコメントする
            r = requests.get(
                f"https://www.reddit.com/r/{sub}/hot.json?limit=5",
                headers=headers, timeout=10,
            )
            r.raise_for_status()
            posts = r.json().get("data", {}).get("children", [])
            if not posts:
                continue

            # 最初の投稿にコメント（Reddit APIはOAuth必要なため、実際の投稿はスキップ）
            # ここではログに記録するだけ（将来OAuth設定後に有効化）
            top_post = posts[0].get("data", {})
            log.info(f"Reddit候補: r/{sub} 「{top_post.get('title', '')[:60]}」 (投稿はOAuth設定後に有効)")
            log.info(f"  → 商品URL: {product_url}")
        except Exception as e:
            log.debug(f"Reddit r/{sub} スキップ: {e}")


def run_pdca() -> dict:
    """
    売上分析 → ニッチ重み更新 → strategy.json保存 → Telegram報告。
    PDCAの結果が次回の generate_product に自動反映される。
    """
    # 価格バグ修正（$3700→$37）を毎回実行
    fix_overpriced_products()

    sales = check_sales()
    published_products = _fetch_published_products()
    total_published = len(published_products)
    now = datetime.now(timezone.utc)

    # ── 製品別集計 ──
    product_sales: dict[str, dict] = {}
    for s in sales:
        pid   = s.get("product_id", "unknown")
        pname = s.get("product_name", "unknown")
        if pid not in product_sales:
            product_sales[pid] = {"name": pname, "count": 0, "revenue_usd": 0.0, "last_sale": None, "niche": None, "type": None}
        product_sales[pid]["count"] += 1
        product_sales[pid]["revenue_usd"] += float(s.get("price", 0)) / 100
        sale_date = s.get("created_at", "")
        if not product_sales[pid]["last_sale"] or sale_date > product_sales[pid]["last_sale"]:
            product_sales[pid]["last_sale"] = sale_date
        # ニッチ・タイプを製品名から推定
        for n in NICHES:
            if n.lower() in pname.lower():
                product_sales[pid]["niche"] = n
        for t in PRODUCT_TYPES:
            if t.replace("_", " ") in pname.lower() or "prompt" in pname.lower():
                product_sales[pid]["type"] = "ai_prompts"
            elif "notion" in pname.lower() or "template" in pname.lower():
                product_sales[pid]["type"] = "notion_template"

    # ── ニッチ別売上集計 ──
    niche_revenue: dict[str, float] = {n: 0.0 for n in NICHES}
    type_revenue:  dict[str, float] = {t: 0.0 for t in PRODUCT_TYPES}
    for info in product_sales.values():
        if info["niche"]:
            niche_revenue[info["niche"]] = niche_revenue.get(info["niche"], 0) + info["revenue_usd"]
        if info["type"]:
            type_revenue[info["type"]] = type_revenue.get(info["type"], 0) + info["revenue_usd"]

    # ── ニッチ重み更新（Act フェーズ）──
    # 売れたニッチ: 重み+0.5、売れないニッチ（7日以上ゼロ）: 重み-0.3、最低0.2
    strategy = _load_strategy()
    weights = strategy.get("niche_weights", {n: 1.0 for n in NICHES})
    threshold = now - timedelta(days=7)

    niche_last_sale: dict[str, datetime] = {}
    for info in product_sales.values():
        if info["niche"] and info["last_sale"]:
            try:
                dt = datetime.fromisoformat(info["last_sale"].replace("Z", "+00:00"))
                n = info["niche"]
                if n not in niche_last_sale or dt > niche_last_sale[n]:
                    niche_last_sale[n] = dt
            except Exception:
                pass

    for n in NICHES:
        rev = niche_revenue.get(n, 0.0)
        if rev > 0:
            weights[n] = min(weights.get(n, 1.0) + 0.5, 3.0)   # 売れた → 重みアップ
        elif n in niche_last_sale and niche_last_sale[n] < threshold:
            weights[n] = max(weights.get(n, 1.0) - 0.3, 0.2)   # 不振 → 重みダウン

    preferred_type = max(type_revenue, key=type_revenue.get) if any(type_revenue.values()) else None

    new_strategy = {
        "niche_weights":       weights,
        "preferred_type":      preferred_type,
        "updated_at":          now.isoformat(),
        "niche_revenue":       niche_revenue,
        "type_revenue":        type_revenue,
        "used_titles":         strategy.get("used_titles", []),
        "used_niches_recent":  strategy.get("used_niches_recent", []),
    }
    STRATEGY_FILE.parent.mkdir(parents=True, exist_ok=True)
    STRATEGY_FILE.write_text(json.dumps(new_strategy, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"strategy.json更新: preferred_type={preferred_type}")

    # ── 月間収益 ──
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_revenue = sum(
        float(s.get("price", 0)) / 100
        for s in sales
        if s.get("created_at", "") >= month_start.isoformat()
    )
    progress_pct = round(monthly_revenue / 2000 * 100, 1)

    # 不振製品リスト
    underperforming = [
        {"product_id": pid, **info}
        for pid, info in product_sales.items()
        if info["count"] == 0 or (
            info["last_sale"] and
            datetime.fromisoformat(info["last_sale"].replace("Z", "+00:00")) < threshold
        )
    ]

    top_niches = sorted(niche_revenue.items(), key=lambda x: x[1], reverse=True)[:3]
    next_niches = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:3]

    report = {
        "generated_at":        now.isoformat(),
        "monthly_revenue_usd": round(monthly_revenue, 2),
        "goal_usd":            2000,
        "progress_pct":        progress_pct,
        "total_published":     total_published,
        "total_products":      len(product_sales),
        "underperforming":     underperforming,
        "top_niches":          top_niches,
        "next_generation":     {"type": preferred_type, "niches": [n for n, _ in next_niches]},
        "product_summary":     product_sales,
    }
    PDCA_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"PDCAレポート保存: 月収=${monthly_revenue:.2f} / $2000 ({progress_pct}%)")

    # ── Telegram報告 ──
    top_str  = "\n".join(f"  • {n}: ${r:.0f}" for n, r in top_niches) or "  （まだ売上なし）"
    next_str = ", ".join(n for n, _ in next_niches)
    _notify(
        f"📊 *Gumroad PDCA Report*\n"
        f"月収: ${monthly_revenue:.2f} / $2,000 ({progress_pct}%)\n"
        f"出品中: {total_published}本\n\n"
        f"🏆 売れ筋ニッチ:\n{top_str}\n\n"
        f"🎯 次回生成ターゲット: {next_str}\n"
        f"📦 優先タイプ: {preferred_type or 'ランダム'}"
    )
    return report


# ───────────────────────────── エントリポイント ─────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gumroad自動化パイプライン")
    parser.add_argument("--check-only", action="store_true", help="売上チェックのみ実行")
    parser.add_argument("--pdca",       action="store_true", help="PDCAレポートのみ実行")
    parser.add_argument("--research",   action="store_true", help="市場調査のみ実行（キャッシュ無視）")
    parser.add_argument("--type",        choices=PRODUCT_TYPES, help="製品タイプを指定")
    parser.add_argument("--niche",       help="ニッチを指定（デフォルト: 市場調査 or ランダム）")
    parser.add_argument("--fix-prices",  action="store_true", help="価格バグ修正のみ実行（$3700→$37）")
    args = parser.parse_args()

    if args.fix_prices:
        fixed = fix_overpriced_products()
        print(f"価格修正完了: {fixed}件")
        return

    if args.research:
        # キャッシュを削除して強制再取得
        if MARKET_CACHE.exists():
            MARKET_CACHE.unlink()
            log.info("市場調査キャッシュをクリア")
        result = research_market()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.check_only:
        sales = check_sales()
        print(json.dumps(sales[:5], ensure_ascii=False, indent=2))
        return

    if args.pdca:
        report = run_pdca()
        print(json.dumps({
            "monthly_revenue_usd": report["monthly_revenue_usd"],
            "progress_pct":        report["progress_pct"],
            "next_generation":     report["next_generation"],
        }, ensure_ascii=False, indent=2))
        return

    # フルパイプライン
    meta = generate_product(product_type=args.type, niche=args.niche)
    if meta:
        product_id = publish_to_gumroad(meta)
        log.info(f"出品完了: product_id={product_id}")
    else:
        log.warning("製品生成に失敗しました。出品をスキップします")

    check_sales()
    run_pdca()
    log.info("パイプライン完了")


if __name__ == "__main__":
    main()
