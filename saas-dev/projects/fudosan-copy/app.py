import os
import streamlit as st
from platforms import PLATFORMS
from prompt import generate
from validation import validate_inputs, ValidationError, EXTRA_MAX

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

        st.success("生成完了！内容を確認してから貼り付けてください。")

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

# ── フッター ──────────────────────────────────────────────────────────────────
st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.caption("**無料トライアル中** — 正式リリース後: ¥5,000〜/月（予定）")
with col_b:
    st.caption("📧 ryuumg03@gmail.com")

st.caption("利用規約 / プライバシーポリシー / 特定商取引法に基づく表記 → 左サイドバーからご確認ください")
st.caption("© 2026 FudoText")
