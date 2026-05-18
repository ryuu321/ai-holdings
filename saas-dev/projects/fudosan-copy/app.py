import os
import streamlit as st
from platforms import PLATFORMS
from prompt import generate

# Streamlit Cloud → st.secrets。ローカル → .env
if "GEMINI_API_KEY" in st.secrets:
    os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]
else:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../.env"))

st.set_page_config(
    page_title="不動産説明文AI | FudoText",
    page_icon="🏠",
    layout="centered",
)

st.title("🏠 FudoText — 物件説明文AI生成")
st.caption("物件情報を入力するだけ。SUUMO/at home/HOMES対応の説明文を30秒で生成します。")

with st.form("property_form"):
    col1, col2 = st.columns(2)
    with col1:
        madori = st.text_input("間取り", placeholder="例: 2LDK")
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
    extra = st.text_area("補足情報（任意）", placeholder="例: リノベーション済み、眺望良好、閑静な住宅街など")

    submitted = st.form_submit_button("✨ 説明文を生成する", type="primary", use_container_width=True)

if submitted:
    if not madori:
        st.error("間取りを入力してください。")
    else:
        platform_info = PLATFORMS[platform]
        with st.spinner("AI生成中...（10〜20秒かかります）"):
            result = generate(
                madori=madori,
                eki_toho=str(eki_toho),
                chikunensuu=str(chikunensuu),
                muki=muki,
                menseki=str(menseki),
                setsubi=setsubi,
                target=target,
                platform=platform,
                platform_info=platform_info,
                extra=extra,
            )

        if not result["ok"]:
            st.error(result["error"])
        else:
            st.success("生成完了！コピーして貼り付けてください。")

            st.subheader(platform_info["catch_label"])
            catch_color = "🟢" if result["catch_len"] <= result["catch_max"] else "🔴"
            st.caption(f"{catch_color} {result['catch_len']} / {result['catch_max']} 文字")
            st.code(result["catch"], language=None)

            st.subheader(platform_info["body_label"])
            body_color = "🟢" if result["body_len"] <= result["body_max"] else "🔴"
            st.caption(f"{body_color} {result['body_len']} / {result['body_max']} 文字")
            st.code(result["body"], language=None)

st.divider()
st.caption("© 2026 FudoText — 無料トライアル中")
