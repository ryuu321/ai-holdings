import streamlit as st

st.set_page_config(page_title="プライバシーポリシー | FudoText", page_icon="🏠")
st.title("プライバシーポリシー")
st.caption("最終更新: 2026年5月19日")

st.markdown("""
## 1. 収集する情報

本サービスは、利用者が入力した物件情報（間取り・面積・設備等）をAI文章生成のためにのみ使用します。
これらの情報はサーバーに**保存されません**。セッション終了とともに消去されます。

## 2. 利用しない情報

本サービスは以下の情報を収集・保存しません。

- 氏名・住所・電話番号等の個人を特定できる情報
- IPアドレスのログ（Streamlit Cloudの基盤システムによるものを除く）
- Cookieを使った追跡

## 3. 第三者へのデータ提供

入力された物件情報は、文章生成のためGoogle Gemini API（Google LLC）に送信されます。
Googleのプライバシーポリシーは [https://policies.google.com/privacy](https://policies.google.com/privacy) をご参照ください。

本サービスはそれ以外の第三者に利用者の情報を提供しません。

## 4. Streamlit Cloud について

本サービスはStreamlit Cloud（Snowflake Inc.）上で動作しています。
Streamlit Cloudのプライバシーポリシーは [https://streamlit.io/privacy-policy](https://streamlit.io/privacy-policy) をご参照ください。

## 5. お問い合わせ

プライバシーに関するご質問は下記までご連絡ください。

📧 ryuumg03@gmail.com
""")
