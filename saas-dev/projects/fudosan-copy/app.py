import os
import streamlit as st
from platforms import PLATFORMS
from prompt import generate, PROMPT_VERSION
from validation import validate_inputs, ValidationError, EXTRA_MAX

FEEDBACK_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSdummy/viewform"  # 後で差し替え

# Streamlit Cloud → st.secrets。ローカル → .env
if "GEMINI_API_KEY" in st.secrets:
    os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]
else:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

FREE_TRIAL_LIMIT = 10

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

# ── ヘッダー ──────────────────────────────────────────────────────────────────
st.title("🏠 FudoText — 物件説明文AI生成")
st.caption("物件情報を入力するだけ。SUUMO/at home/HOMES対応の説明文を30秒で生成します。")

remaining = FREE_TRIAL_LIMIT - st.session_state.request_count
if remaining <= 3:
    st.info(f"無料トライアル残り **{remaining}回**")

# ── レート制限チェック ────────────────────────────────────────────────────────
if st.session_state.request_count >= FREE_TRIAL_LIMIT:
    st.warning(
        f"無料トライアルの上限（{FREE_TRIAL_LIMIT}回/セッション）に達しました。"
        "ご意見・継続ご希望の方は📧 ryuumg03@gmail.com までご連絡ください。"
    )
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
            st.session_state.feedback_sent = True
            regen = st.session_state.request_count
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
        st.session_state.feedback_sent = True
        st.session_state.show_bad_reason = False
        regen = st.session_state.request_count
        mailto = (
            f"mailto:ryuumg03@gmail.com"
            f"?subject=FudoText%20フィードバック%20({PROMPT_VERSION})"
            f"&body=再生成回数: {regen}回%0A問題点: {', '.join(reasons) if reasons else 'なし'}"
        )
        st.markdown(f"[詳細を送る（任意）]({mailto})")
        st.info("フィードバックを記録しました。改善に役立てます。")

# ── フッター ──────────────────────────────────────────────────────────────────
st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.caption("**無料トライアル中** — 正式リリース後: ¥5,000〜/月（予定）")
with col_b:
    st.caption("📧 ryuumg03@gmail.com")

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
| 販売価格 | 無料トライアル中（正式版: ¥5,000〜/月・予定） |
| 支払方法 | クレジットカード決済（予定） |
| 返品・キャンセル | デジタルサービスのため提供済み期間の返金不可。次回更新日前日までの解約で翌月以降の請求なし。 |

※ 現在は無料トライアル期間中のため有償取引は発生していません。
""")

st.caption("© 2026 FudoText　📧 ryuumg03@gmail.com")
