import os
import urllib.parse
import urllib.request
import streamlit as st
from platforms import PLATFORMS
from prompt import generate, PROMPT_VERSION
from validation import validate_inputs, ValidationError, EXTRA_MAX

FEEDBACK_FORM_URL = st.secrets.get("FEEDBACK_FORM_URL", "")

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
    """Google Form に POST してスプレッドシートへ記録する。失敗してもサイレントに無視する。"""
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
else:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

FREE_TRIAL_LIMIT = 5
PAID_PLAN_PRICE = "¥8,980/月"
CONTACT_EMAIL = "ryuumg03@gmail.com"

st.set_page_config(
    page_title="不動産説明文AI | FudoText",
    page_icon="🏠",
    layout="centered",
)

# ── セッション状態の初期化 ────────────────────────────────────────────────────
if "request_count" not in st.session_state:
    st.session_state.request_count = 0
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "feedback_sent" not in st.session_state:
    st.session_state.feedback_sent = False
if "show_bad_reason" not in st.session_state:
    st.session_state.show_bad_reason = False
if "last_target" not in st.session_state:
    st.session_state.last_target = ""
if "last_platform" not in st.session_state:
    st.session_state.last_platform = ""

# ── ヘッダー ──────────────────────────────────────────────────────────────────
st.title("🏠 FudoText — 物件説明文AI生成")
st.caption("物件情報を入力するだけ。SUUMO/at home/HOMES対応の説明文を30秒で生成します。")

# 残り件数バッジ
remaining = FREE_TRIAL_LIMIT - st.session_state.request_count
if remaining > 0:
    if remaining <= 2:
        st.warning(f"無料トライアル残り **{remaining}件** — 続けて使うには有料プラン（{PAID_PLAN_PRICE}）をご検討ください。")
    else:
        st.info(f"無料トライアル: **{remaining} / {FREE_TRIAL_LIMIT}件** 残り")

# ── 上限到達時: 有料プランCTA ─────────────────────────────────────────────────
if st.session_state.request_count >= FREE_TRIAL_LIMIT:
    st.error("無料トライアル（5件）を使い切りました。")
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
- 月無制限
- 複数ユーザー対応
- 優先サポート
- **¥19,800/月**
""")
    st.markdown("---")
    mailto = f"mailto:{CONTACT_EMAIL}?subject=FudoText%20有料プラン申込&body=プラン名:%0A会社名:%0A担当者名:%0Aご質問:"
    st.link_button("📧 有料プランに申し込む（メールで問い合わせ）", mailto, type="primary", use_container_width=True)
    st.caption(f"※ 現在はメール受付での対応となります。折り返し1営業日以内にご連絡します。")
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
        st.session_state.request_count += 1
        st.session_state.last_result = result
        st.session_state.feedback_sent = False
        st.session_state.last_target = target
        st.session_state.last_platform = platform

# ── 結果表示（session_state から常に描画）────────────────────────────────────
if st.session_state.get("last_result"):
    result = st.session_state.last_result
    platform_info = PLATFORMS[st.session_state.last_platform]

    st.success("生成完了！内容を確認してから貼り付けてください。")
    st.caption(f"プロンプトバージョン: {result.get('prompt_version', '?')}　"
               f"今回のセッションで{st.session_state.request_count}回目の生成")

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
            st.success(f"ありがとうございます！（{regen}回目の生成で満足）")
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

# ── フッター ──────────────────────────────────────────────────────────────────
st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.caption("**無料: 月5件** / 有料: ¥8,980〜/月 | 📧 ryuumg03@gmail.com")
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

**第6条（個人情報）** 入力情報はサーバーに保存しません。詳細はプライバシーポリシーをご参照ください。

**第7条（準拠法）** 本規約は日本法に準拠します。紛争は運営者所在地の管轄裁判所を第一審とします。
""")

with st.expander("プライバシーポリシー"):
    st.markdown("""
**収集する情報:** 入力された物件情報はAI生成のみに使用し、サーバーには**保存しません**。セッション終了とともに消去されます。

**収集しない情報:** 氏名・住所・電話番号等の個人情報、IPログ、Cookie追跡は行いません。

**第三者提供:** 文章生成のためGoogle Gemini API（Google LLC）に物件情報を送信します。それ以外の第三者提供はありません。

**お問い合わせ:** ryuumg03@gmail.com
""")

with st.expander("特定商取引法に基づく表記"):
    st.markdown("""
| 項目 | 内容 |
|------|------|
| 販売事業者 | 請求があり次第、遅滞なく開示します |
| 所在地 | 請求があり次第、遅滞なく開示します |
| メールアドレス | ryuumg03@gmail.com |
| 販売価格 | スタンダード ¥8,980/月 / プロ ¥19,800/月（無料トライアル: 月5件まで） |
| 支払方法 | 銀行振込 / その他（お申し込み後にご案内） |
| 返品・キャンセル | デジタルサービスのため提供済み期間の返金不可。翌月更新日前日までの解約で翌月以降の請求なし。 |

※ お申し込みは ryuumg03@gmail.com までメールにてご連絡ください。
""")

st.caption("© 2026 FudoText　📧 ryuumg03@gmail.com")
