import re

MADORI_MAX = 20
EXTRA_MAX = 200

# プロンプト構造を壊す可能性のあるパターン
_INJECTION_PATTERNS = [
    r"CATCH\s*:",
    r"BODY\s*:",
    r"【出力",
    r"【物件情報】",
    r"ignore\s+previous",
    r"前の指示を無視",
    r"system\s*:",
    r"---+",
]


class ValidationError(ValueError):
    pass


def sanitize_text(text: str, max_len: int, field_name: str) -> str:
    """改行・制御文字を除去し、長さを制限する。"""
    text = text.strip()
    # 改行・タブをスペースに正規化
    text = re.sub(r"[\r\n\t]+", " ", text)
    # 連続スペースを1つに
    text = re.sub(r" {2,}", " ", text)
    if len(text) > max_len:
        raise ValidationError(f"{field_name}は{max_len}文字以内で入力してください（現在{len(text)}文字）。")
    return text


def check_injection(text: str, field_name: str) -> None:
    """プロンプトインジェクションの疑いがあれば拒否する。"""
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            raise ValidationError(f"{field_name}に使用できない文字列が含まれています。")


def validate_inputs(madori: str, extra: str) -> tuple[str, str]:
    """
    入力値を検証・サニタイズして返す。
    問題があれば ValidationError を raise する。
    """
    madori = sanitize_text(madori, MADORI_MAX, "間取り")
    if not madori:
        raise ValidationError("間取りを入力してください。")
    check_injection(madori, "間取り")

    extra = sanitize_text(extra, EXTRA_MAX, "補足情報")
    check_injection(extra, "補足情報")

    return madori, extra
