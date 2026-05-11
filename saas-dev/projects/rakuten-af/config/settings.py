"""設定管理"""
import os
from pathlib import Path

def _load_env():
    env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

class Settings:
    # 楽天
    RAKUTEN_APP_ID       = os.environ.get("RAKUTEN_APP_ID", "")
    RAKUTEN_ACCESS_KEY   = os.environ.get("RAKUTEN_ACCESS_KEY", "")
    RAKUTEN_AFFILIATE_ID = os.environ.get("RAKUTEN_AFFILIATE_ID", "")

    # Groq
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

    # はてなブログ（1アカウント・複数ブログ対応）
    # 共通: HATENA_ID, HATENA_API_KEY
    # ブログ追加: HATENA_BLOG_1_ID, HATENA_BLOG_2_ID, HATENA_BLOG_3_ID ...
    HATENA_ID      = os.environ.get("HATENA_ID", "")
    HATENA_BLOG_ID = os.environ.get("HATENA_BLOG_ID", "")
    HATENA_API_KEY = os.environ.get("HATENA_API_KEY", "")

    HATENA_ACCOUNTS: list = []
    _hid = HATENA_ID
    _key = HATENA_API_KEY
    if _hid:
        _i = 1
        while True:
            _blog_id = os.environ.get(f"HATENA_BLOG_{_i}_ID")
            if not _blog_id:
                break
            HATENA_ACCOUNTS.append({"id": _hid, "blog_id": _blog_id, "api_key": _key})
            _i += 1
        # HATENA_BLOG_N_ID が未設定なら旧形式の単一ブログにフォールバック
        if not HATENA_ACCOUNTS and HATENA_BLOG_ID:
            HATENA_ACCOUNTS.append({"id": _hid, "blog_id": HATENA_BLOG_ID, "api_key": _key})

    # X (Twitter)
    TWITTER_API_KEY              = os.environ.get("TWITTER_API_KEY", "")
    TWITTER_API_SECRET           = os.environ.get("TWITTER_API_SECRET", "")
    TWITTER_ACCESS_TOKEN         = os.environ.get("TWITTER_ACCESS_TOKEN", "")
    TWITTER_ACCESS_TOKEN_SECRET  = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "")

    # システム設定
    ARTICLES_PER_DAY = int(os.environ.get("ARTICLES_PER_DAY", "3"))
    DB_PATH = str(Path(__file__).parent.parent / "data" / "rakuten_af.db")

    # A/Bテスト設定
    # A: 多ニッチ×7日クールダウン（広範囲SEO狙い）
    # B: 少ニッチ×1日クールダウン（特定キーワード深堀り）
    AB_WINNER = os.environ.get("AB_WINNER", "both")  # "A" / "B" / "both"
    COOLDOWN_A = 7
    COOLDOWN_B = 1

    NICHES_A = [
        # コスメ・美容（多様）
        "プチプラコスメおすすめ", "韓国コスメ人気ランキング", "スキンケア乾燥肌",
        "日焼け止めおすすめ", "マスカラ人気", "リップクリームおすすめ",
        "シャンプーおすすめ", "ヘアオイルおすすめ", "洗顔料おすすめ",
        "美容液おすすめ", "化粧水おすすめ", "クレンジングおすすめ",
        # 食品・グルメ
        "お取り寄せグルメおすすめ", "スイーツお取り寄せ", "ラーメンお取り寄せ",
        "コーヒーおすすめ", "お茶おすすめ", "プロテインおすすめ",
        "健康食品おすすめ", "調味料おすすめ", "お酒ギフト",
        "チョコレートおすすめ", "おせちおすすめ", "ふるさと納税グルメ",
        # 家電・ガジェット
        "ワイヤレスイヤホンおすすめ", "スマートウォッチおすすめ",
        "モバイルバッテリーおすすめ", "ロボット掃除機おすすめ",
        "空気清浄機おすすめ", "電気ケトルおすすめ", "炊飯器おすすめ",
        "ドライヤーおすすめ", "加湿器おすすめ", "除湿機おすすめ",
        # キッチン・生活用品
        "フライパンおすすめ", "水筒おすすめ", "弁当箱おすすめ",
        "包丁おすすめ", "まな板おすすめ", "食器洗い洗剤おすすめ",
        "ラップおすすめ", "保存容器おすすめ", "キッチングッズおすすめ",
        # インテリア・収納
        "収納グッズおすすめ", "ルームフレグランスおすすめ",
        "枕おすすめ", "布団おすすめ", "タオルおすすめ",
        "カーテンおすすめ", "ラグおすすめ", "照明おすすめ",
        # ファッション
        "レディーストップスおすすめ", "メンズスニーカーおすすめ",
        "バッグおすすめ", "財布おすすめ", "時計おすすめ",
        "サングラスおすすめ", "帽子おすすめ", "マフラーおすすめ",
        # スポーツ・アウトドア
        "ヨガマットおすすめ", "ランニングシューズおすすめ",
        "ダンベルおすすめ", "テントおすすめ", "登山リュックおすすめ",
        # ベビー・キッズ
        "ベビー用品おすすめ", "おもちゃおすすめ", "絵本おすすめ",
        "ランドセルおすすめ", "子供服おすすめ",
        # ペット
        "猫用品おすすめ", "犬用おやつおすすめ", "ペットシーツおすすめ",
        # 健康
        "サプリメントおすすめ", "マッサージグッズおすすめ",
        "入浴剤おすすめ", "ホットアイマスクおすすめ",
        # 旅行・季節
        "旅行グッズおすすめ", "海水浴グッズおすすめ",
        "キャンプ用品おすすめ", "クリスマスプレゼントおすすめ",
    ]

    NICHES_B = [
        # 購買率が高いカテゴリに絞る（毎日投稿で深堀り）
        "プチプラコスメおすすめ", "韓国コスメ人気ランキング",
        "お取り寄せグルメおすすめ", "スイーツお取り寄せ",
        "ワイヤレスイヤホンおすすめ", "ロボット掃除機おすすめ",
        "プロテインおすすめ", "収納グッズおすすめ",
        "ベビー用品おすすめ", "キャンプ用品おすすめ",
    ]

    # 後方互換（旧コードが参照する場合のフォールバック）
    TARGET_NICHES = NICHES_A

settings = Settings()
