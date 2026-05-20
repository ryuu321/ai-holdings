import csv
import datetime
import io
import os
import urllib.parse
import urllib.request
import streamlit as st
from platforms import PLATFORMS
from prompt import generate, PROMPT_VERSION
from validation import validate_inputs, ValidationError, EXTRA_MAX

FEEDBACK_FORM_URL = st.secrets.get("FEEDBACK_FORM_URL", "")
STRIPE_STANDARD_URL = st.secrets.get("STRIPE_STANDARD_URL", "")
STRIPE_PRO_URL = st.secrets.get("STRIPE_PRO_URL", "")

PLAN_LIMITS = {
    "standard": 50,
    "pro": 200,
}

_FORM_ID = "1FAIpQLSdJbKRfutIcFXqWVwTgqX7-JnxIk2niVEZjBzIm4u3Lw9UMmA"
_FORM_SUBMIT_URL = f"https://docs.google.com/forms/d/e/{_FORM_ID}/formResponse"
_ENTRY = {
    "target":      "entry.1762736429",
    "platform":    "entry.1865439297",
    "rating":      "entry.251541218",
    "regen_count": "entry.991722311",
    "reasons":     "entry.1743656141",
}


def _submit_feedback(target: str, platform: str, rating: str, regen_count: int, reasons: str = "") -> None:
    try:
        data = {
            _ENTRY["target"]:      target,
            _ENTRY["platform"]:    platform,
            _ENTRY["rating"]:      rating,
            _ENTRY["regen_count"]: str(regen_count),
            _ENTRY["reasons"]:     reasons,
        }
        payload = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(_FORM_SUBMIT_URL, data=payload, method="POST")
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


# Streamlit Cloud → st.secrets。ローカル → .env
if "GEMINI_API_KEY" in st.secrets:
    os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]
    os.environ["SUPABASE_URL"] = st.secrets.get("SUPABASE_URL", "")
    os.environ["SUPABASE_ANON_KEY"] = st.secrets.get("SUPABASE_ANON_KEY", "")
else:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

_USE_DB = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_ANON_KEY"))
if _USE_DB:
    from db import (get_or_create_user, increment_count, set_plan, validate_code,
                    save_generation, get_history, get_stats)

FREE_TRIAL_LIMIT = 5
PAID_PLAN_PRICE = "¥8,980/月"
CONTACT_EMAIL = "ryuumg03@gmail.com"

st.set_page_config(
    page_title="不動産説明文AI | FudoText",
    page_icon="🏠",
    layout="centered",
)

# ── セッション状態の初期化 ────────────────────────────────────────────────────
for key, default in [
    ("user_email", None),
    ("db_loaded", False),
    ("request_count", 0),
    ("paid_plan", None),
    ("last_result", None),
    ("feedback_sent", False),
    ("show_bad_reason", False),
    ("last_target", ""),
    ("last_platform", ""),
    ("generation_stats", {"week": 0, "month": 0}),
    ("generation_history", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── ヘッダー ──────────────────────────────────────────────────────────────────
st.title("🏠 FudoText — 物件説明文AI生成")
st.caption("物件情報を入力するだけ。SUUMO/at home/HOMES対応の説明文を30秒で生成します。")

# ── メール入力（初回のみ） ────────────────────────────────────────────────────
if st.session_state.user_email is None:
    st.markdown("### 無料トライアルを開始する")
    st.caption(f"メールアドレスを入力するだけで、今すぐ{FREE_TRIAL_LIMIT}件無料でお試しいただけます。")
    with st.form("email_form"):
        email_input = st.text_input("メールアドレス", placeholder="example@company.co.jp")
        if st.form_submit_button("無料で試す →", type="primary", use_container_width=True):
            email_input = email_input.strip().lower()
            if "@" not in email_input or "." not in email_input.split("@")[-1]:
                st.error("正しいメールアドレスを入力してください。")
            else:
                st.session_state.user_email = email_input
                if _USE_DB:
                    try:
                        user = get_or_create_user(email_input)
                        st.session_state.request_count = user.get("count", 0)
                        st.session_state.paid_plan = user.get("plan")
                        st.session_state.generation_stats = get_stats(email_input)
                        st.session_state.generation_history = get_history(email_input)
                    except Exception as e:
                        base = os.environ.get("SUPABASE_URL", "未設定").rstrip("/")
                        st.error(f"DB接続エラー: {e} | URL先頭: {base[:40]}")
                        st.stop()
                st.session_state.db_loaded = True
                st.rerun()
    st.caption("※ メールアドレスは利用回数管理のみに使用します。スパムメールは送りません。")
    st.stop()

# ── DB未ロードの場合はロード（セッション復元） ────────────────────────────────
if not st.session_state.db_loaded and _USE_DB:
    try:
        user = get_or_create_user(st.session_state.user_email)
    except Exception as e:
        st.error(f"DB接続エラー: {e}")
        st.stop()
    st.session_state.request_count = user.get("count", 0)
    st.session_state.paid_plan = user.get("plan")
    st.session_state.generation_stats = get_stats(st.session_state.user_email)
    st.session_state.generation_history = get_history(st.session_state.user_email)
    st.session_state.db_loaded = True

# ── 残り件数バッジ ────────────────────────────────────────────────────────────
_plan = st.session_state.paid_plan
_limit = PLAN_LIMITS.get(_plan, FREE_TRIAL_LIMIT) if _plan else FREE_TRIAL_LIMIT
remaining = _limit - st.session_state.request_count

if _plan:
    plan_label = "スタンダード" if _plan == "standard" else "プロ"
    st.success(f"{plan_label}プラン: **{max(0, remaining)} / {_limit}件** 残り（今月）")
elif remaining > 0:
    if remaining <= 2:
        st.warning(f"無料トライアル残り **{remaining}件** — 続けて使うには有料プラン（{PAID_PLAN_PRICE}）をご検討ください。")
    else:
        st.info(f"無料トライアル: **{remaining} / {FREE_TRIAL_LIMIT}件** 残り")

# ── 上限到達時: 有料プランCTA ─────────────────────────────────────────────────
if st.session_state.request_count >= _limit:
    if _plan:
        st.error(f"今月の上限（{_limit}件）に達しました。プランアップグレードをご検討ください。")
    else:
        st.error(f"無料トライアル（{FREE_TRIAL_LIMIT}件）を使い切りました。")
    st.markdown("---")
    st.markdown("### 📋 有料プランのご案内")
    col_plan1, col_plan2 = st.columns(2)
    with col_plan1:
        st.markdown(f"""
**スタンダードプラン**
- 月50件まで生成
- SUUMO / at home / HOMES 対応
- ターゲット別最適化
- **{PAID_PLAN_PRICE}**
""")
    with col_plan2:
        st.markdown(f"""
**プロプラン**
- 月200件まで生成
- 複数ユーザー対応
- 優先サポート
- **¥19,800/月**
""")
    st.markdown("---")
    col_cta1, col_cta2 = st.columns(2)
    with col_cta1:
        if STRIPE_STANDARD_URL:
            st.link_button("💳 スタンダードに申し込む", STRIPE_STANDARD_URL, type="primary", use_container_width=True)
        else:
            mailto_std = f"mailto:{CONTACT_EMAIL}?subject=FudoText%20スタンダードプラン申込&body=会社名:%0A担当者名:%0A"
            st.link_button("📧 スタンダードに申し込む", mailto_std, type="primary", use_container_width=True)
    with col_cta2:
        if STRIPE_PRO_URL:
            st.link_button("💳 プロプランに申し込む", STRIPE_PRO_URL, use_container_width=True)
        else:
            mailto_pro = f"mailto:{CONTACT_EMAIL}?subject=FudoText%20プロプラン申込&body=会社名:%0A担当者名:%0A"
            st.link_button("📧 プロプランに申し込む", mailto_pro, use_container_width=True)
    st.caption("※ お申し込み後、アクセスコードをメールでお送りします。")

    st.markdown("---")
    st.markdown("#### すでにアクセスコードをお持ちの方")
    code_input = st.text_input("アクセスコードを入力", placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", label_visibility="collapsed")
    if st.button("コードで解除する", type="secondary"):
        c = code_input.strip()
        new_plan = validate_code(c) if _USE_DB else None
        if new_plan:
            st.session_state.paid_plan = new_plan
            st.session_state.request_count = 0
            set_plan(st.session_state.user_email, new_plan)
            st.rerun()
        else:
            st.error("コードが正しくありません。メールに記載のコードをご確認ください。")
    st.stop()

# ── 入力フォーム ──────────────────────────────────────────────────────────────
with st.form("property_form"):
    col1, col2 = st.columns(2)
    with col1:
        madori = st.text_input("間取り", placeholder="例: 2LDK", max_chars=20)
        eki_toho = st.number_input("駅徒歩（分）", min_value=1, max_value=60, value=5)
        chikunensuu = st.number_input("築年数（年）", min_value=0, max_value=80, value=10)
        muki = st.selectbox("向き", ["南", "南東", "南西", "東", "西", "北東", "北西", "北"])
    with col2:
        menseki = st.number_input("専有面積（㎡）", min_value=10.0, max_value=300.0, value=65.0, step=0.5)
        target = st.selectbox(
            "ターゲット層",
            ["ファミリー", "カップル・DINKS", "単身者（社会人）", "単身者（学生）", "シニア", "投資家"],
        )
        platform = st.selectbox("掲載先ポータル", list(PLATFORMS.keys()))

    setsubi_options = [
        "オートロック", "宅配ボックス", "浴室乾燥機", "追炊き",
        "床暖房", "システムキッチン", "食洗機", "ウォシュレット",
        "エアコン付き", "独立洗面台", "クローゼット", "駐車場",
        "ペット可", "2階以上", "角部屋", "室内洗濯機置き場",
    ]
    setsubi = st.multiselect("設備（複数選択可）", setsubi_options)
    extra = st.text_area(
        f"補足情報（任意・{EXTRA_MAX}文字以内）",
        placeholder="例: リノベーション済み、眺望良好、閑静な住宅街など",
        max_chars=EXTRA_MAX,
    )

    submitted = st.form_submit_button("✨ 説明文を生成する", type="primary", use_container_width=True)

# ── 生成処理 ──────────────────────────────────────────────────────────────────
if submitted:
    try:
        madori_clean, extra_clean = validate_inputs(madori, extra)
    except ValidationError as e:
        st.error(str(e))
        st.stop()

    platform_info = PLATFORMS[platform]
    with st.spinner("AI生成中...（10〜20秒かかります）"):
        result = generate(
            madori=madori_clean,
            eki_toho=str(eki_toho),
            chikunensuu=str(chikunensuu),
            muki=muki,
            menseki=str(menseki),
            setsubi=setsubi,
            target=target,
            platform=platform,
            platform_info=platform_info,
            extra=extra_clean,
        )

    if not result["ok"]:
        st.error(result["error"])
    else:
        if _USE_DB:
            new_count = increment_count(st.session_state.user_email)
            st.session_state.request_count = new_count
            save_generation(
                st.session_state.user_email,
                {"madori": madori_clean, "menseki": menseki, "platform": platform, "target": target},
                result,
            )
            stats = st.session_state.generation_stats
            st.session_state.generation_stats = {
                "week": stats["week"] + 1,
                "month": stats["month"] + 1,
            }
            new_entry = {
                "madori": madori_clean, "menseki": str(menseki),
                "platform": platform, "target": target,
                "catch": result["catch"], "body": result["body"],
                "prompt_version": result.get("prompt_version", ""),
                "created_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M"),
            }
            hist = st.session_state.generation_history or []
            st.session_state.generation_history = ([new_entry] + hist)[:10]
        else:
            st.session_state.request_count += 1
        st.session_state.last_result = result
        st.session_state.feedback_sent = False
        st.session_state.last_target = target
        st.session_state.last_platform = platform

# ── 結果表示 ──────────────────────────────────────────────────────────────────
if st.session_state.get("last_result"):
    result = st.session_state.last_result
    platform_info = PLATFORMS[st.session_state.last_platform]

    st.success("生成完了！内容を確認してから貼り付けてください。")
    _stats = st.session_state.generation_stats
    st.caption(
        f"プロンプトバージョン: {result.get('prompt_version', '?')}　"
        f"今月{_stats['month']}件 / 今週{_stats['week']}件"
    )

    st.subheader(platform_info["catch_label"])
    catch_color = "🟢" if result["catch_len"] <= result["catch_max"] else "🔴"
    st.caption(f"{catch_color} {result['catch_len']} / {result['catch_max']} 文字")
    st.code(result["catch"], language=None)

    st.subheader(platform_info["body_label"])
    body_color = "🟢" if result["body_len"] <= result["body_max"] else "🔴"
    st.caption(f"{body_color} {result['body_len']} / {result['body_max']} 文字")
    st.code(result["body"], language=None)

    st.warning(
        "⚠️ **AIが生成したコンテンツです。** "
        "掲載前に必ず内容（事実確認・文字数・表現）を人が確認してください。"
    )

# ── フィードバック ────────────────────────────────────────────────────────────
if st.session_state.get("last_result") and not st.session_state.get("feedback_sent"):
    st.divider()
    st.markdown("**この文章は使えましたか？**")
    col_good, col_bad = st.columns(2)
    with col_good:
        if st.button("👍 使えた", use_container_width=True):
            regen = st.session_state.request_count
            _submit_feedback(
                target=st.session_state.last_target,
                platform=st.session_state.last_platform,
                rating="good",
                regen_count=regen,
            )
            st.session_state.feedback_sent = True
            st.success(f"ありがとうございます！（{regen}件目の生成で満足）")
    with col_bad:
        if st.button("👎 使えなかった", use_container_width=True):
            st.session_state.show_bad_reason = True

if st.session_state.get("show_bad_reason") and not st.session_state.get("feedback_sent"):
    reasons = st.multiselect(
        "どの点が問題でしたか？（複数選択可）",
        ["文章が短すぎる", "文章が不自然", "ターゲットに合っていない",
         "補足情報が反映されていない", "文字数が合っていない", "その他"],
    )
    if st.button("送信", type="primary"):
        regen = st.session_state.request_count
        _submit_feedback(
            target=st.session_state.last_target,
            platform=st.session_state.last_platform,
            rating="bad",
            regen_count=regen,
            reasons=", ".join(reasons) if reasons else "",
        )
        st.session_state.feedback_sent = True
        st.session_state.show_bad_reason = False
        st.info("フィードバックを記録しました。改善に役立てます。")

# ── 生成履歴（データロック） ──────────────────────────────────────────────────
if _USE_DB and st.session_state.user_email and st.session_state.generation_history:
    with st.expander(f"📋 過去の生成履歴（{len(st.session_state.generation_history)}件）"):
        for i, h in enumerate(st.session_state.generation_history):
            created = h.get("created_at", "")[:16].replace("T", " ")
            label = f"{i+1}. {created} | {h.get('madori','')}{h.get('menseki','')}㎡ | {h.get('platform','')} | {h.get('target','')}"
            st.caption(label)
            if h.get("catch"):
                st.code(h["catch"], language=None)
            if h.get("body"):
                st.code(h["body"], language=None)
            if i < len(st.session_state.generation_history) - 1:
                st.divider()

# ── 一括生成（CSV） ────────────────────────────────────────────────────────────
st.divider()
st.markdown("### 📊 一括生成（CSV）")
st.caption("複数物件を一度に生成。ChatGPTでは絶対にできない。")

_remaining_bulk = max(0, _limit - st.session_state.request_count)

_BULK_COLS = ["madori","menseki","eki_toho","chikunensuu","muki","setsubi","target","platform","extra"]
_VALID_MUKI = ["南","南東","南西","東","西","北東","北西","北"]
_VALID_TARGET = ["ファミリー","カップル・DINKS","単身者（社会人）","単身者（学生）","シニア","投資家"]

_tmpl_buf = io.StringIO()
_tmpl_w = csv.writer(_tmpl_buf)
_tmpl_w.writerow(_BULK_COLS)
_tmpl_w.writerows([
    ["2LDK","65.0","5","10","南","オートロック,宅配ボックス","ファミリー","SUUMO","南向き角部屋"],
    ["1K","30.0","8","3","東","エアコン付き","単身者（社会人）","at home",""],
])
st.download_button(
    "📥 テンプレートCSVをダウンロード",
    _tmpl_buf.getvalue().encode("utf-8-sig"),
    "fudotext_template.csv",
    "text/csv",
)

_uploaded = st.file_uploader("物件CSVをアップロード", type=["csv"], key="bulk_upload")

if _uploaded:
    try:
        _content = _uploaded.read().decode("utf-8-sig")
        _reader = csv.DictReader(io.StringIO(_content))
        _rows = [r for r in _reader]
    except Exception as _e:
        st.error(f"CSV読み込みエラー: {_e}")
        _rows = []

    if _rows:
        _n = len(_rows)
        if _n > _remaining_bulk:
            st.warning(f"残り枠{_remaining_bulk}件のため、先頭{_remaining_bulk}件のみ生成します。")
            _rows = _rows[:_remaining_bulk]
            _n = _remaining_bulk

        st.info(f"{_n}件を一括生成します（現在の残り枠: {_remaining_bulk}件）")

        if st.button("✨ 一括生成スタート", type="primary", key="bulk_start") and _n > 0:
            _results = []
            _prog = st.progress(0)
            _status = st.empty()

            for _i, _row in enumerate(_rows):
                try:
                    _m = _row.get("madori","").strip()
                    _ms = float(_row.get("menseki","65") or 65)
                    _ek = int(float(_row.get("eki_toho","5") or 5))
                    _ch = int(float(_row.get("chikunensuu","10") or 10))
                    _mu = _row.get("muki","南").strip()
                    if _mu not in _VALID_MUKI:
                        _mu = "南"
                    _se = [s.strip() for s in _row.get("setsubi","").split(",") if s.strip()]
                    _tg = _row.get("target","ファミリー").strip()
                    if _tg not in _VALID_TARGET:
                        _tg = "ファミリー"
                    _pl = _row.get("platform","SUUMO").strip()
                    if _pl not in PLATFORMS:
                        _pl = list(PLATFORMS.keys())[0]
                    _ex = _row.get("extra","").strip()

                    _status.caption(f"生成中 {_i+1}/{_n}件目: {_m} {_ms}㎡ / {_pl} / {_tg}")

                    try:
                        _mc, _ec = validate_inputs(_m, _ex)
                    except ValidationError as _ve:
                        _results.append({**_row, "catch":"", "body":"", "error":str(_ve)})
                        _prog.progress((_i+1)/_n)
                        continue

                    _pinfo = PLATFORMS[_pl]
                    _res = generate(
                        madori=_mc, eki_toho=str(_ek), chikunensuu=str(_ch),
                        muki=_mu, menseki=str(_ms), setsubi=_se,
                        target=_tg, platform=_pl, platform_info=_pinfo, extra=_ec,
                    )

                    if _res["ok"]:
                        if _USE_DB:
                            _nc = increment_count(st.session_state.user_email)
                            st.session_state.request_count = _nc
                            save_generation(
                                st.session_state.user_email,
                                {"madori":_mc,"menseki":_ms,"platform":_pl,"target":_tg},
                                _res,
                            )
                        else:
                            st.session_state.request_count += 1
                        _results.append({**_row, "catch":_res["catch"], "body":_res["body"], "error":""})
                    else:
                        _results.append({**_row, "catch":"", "body":"", "error":_res.get("error","生成失敗")})

                except Exception as _e2:
                    _results.append({**_row, "catch":"", "body":"", "error":str(_e2)})

                _prog.progress((_i+1)/_n)

            _ok_count = sum(1 for r in _results if r.get("catch"))
            _status.success(f"完了！ {_ok_count}/{_n}件成功")

            _out_buf = io.StringIO()
            if _results:
                _out_w = csv.DictWriter(_out_buf, fieldnames=list(_results[0].keys()))
                _out_w.writeheader()
                _out_w.writerows(_results)
            st.download_button(
                "📤 結果CSVをダウンロード",
                _out_buf.getvalue().encode("utf-8-sig"),
                "fudotext_results.csv",
                "text/csv",
                type="primary",
            )

# ── フッター ──────────────────────────────────────────────────────────────────
st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.caption("**無料: 5件** / 有料: ¥8,980〜/月 | 📧 ryuumg03@gmail.com")
with col_b:
    mailto = f"mailto:{CONTACT_EMAIL}?subject=FudoText%20有料プラン申込&body=プラン名:%0A会社名:%0A担当者名:%0Aご質問:"
    st.markdown(f'<a href="{mailto}" style="font-size:0.8rem;">有料プランのお問い合わせ</a>', unsafe_allow_html=True)

with st.expander("利用規約"):
    st.markdown("""
**第1条（適用）** 本規約は FudoText の利用条件を定めます。ご利用をもって同意とみなします。

**第2条（サービスの内容）** 本サービスは物件説明文の草案を生成するAIツールです。掲載前に利用者自身が内容を確認・編集してください。

**第3条（禁止事項）** 虚偽情報の入力・違法コンテンツの生成・不正アクセス・第三者への再販等を禁止します。

**第4条（免責事項）** 生成文章の正確性・完全性を保証しません。生成結果の使用による損害について運営者は責任を負いません。宅建業法・景品表示法等の法令適合は利用者の責任で確認してください。

**第5条（知的財産）** システム・デザインの権利は運営者に帰属します。生成文章の著作権は利用者に帰属します。

**第6条（個人情報）** 利用回数管理のためメールアドレスを収集します。詳細はプライバシーポリシーをご参照ください。

**第7条（準拠法）** 本規約は日本法に準拠します。紛争は運営者所在地の管轄裁判所を第一審とします。
""")

with st.expander("プライバシーポリシー"):
    st.markdown("""
**収集する情報:** メールアドレス（利用回数管理のため）。入力された物件情報はAI生成のみに使用します。

**保存期間:** メールアドレスおよび利用回数はサービス利用中のみ保持します。

**収集しない情報:** 氏名・住所・電話番号等、IPログ、Cookie追跡は行いません。

**第三者提供:** 文章生成のためGoogle Gemini API（Google LLC）に物件情報を送信します。利用回数管理のためSupabase（Supabase Inc.）にメールアドレスを保存します。それ以外の第三者提供はありません。

**お問い合わせ:** ryuumg03@gmail.com
""")

with st.expander("特定商取引法に基づく表記"):
    st.markdown("""
| 項目 | 内容 |
|------|------|
| 販売事業者 | 請求があり次第、遅滞なく開示します |
| 所在地 | 請求があり次第、遅滞なく開示します |
| メールアドレス | ryuumg03@gmail.com |
| 販売価格 | スタンダード ¥8,980/月 / プロ ¥19,800/月（無料トライアル: 5件まで） |
| 支払方法 | 銀行振込 / その他（お申し込み後にご案内） |
| 返品・キャンセル | デジタルサービスのため提供済み期間の返金不可。翌月更新日前日までの解約で翌月以降の請求なし。 |

※ お申し込みは ryuumg03@gmail.com までメールにてご連絡ください。
""")

st.caption("© 2026 FudoText　📧 ryuumg03@gmail.com")
