"""
ソースモジュールの win32 stdout UTF-8 ラッパーが pytest のキャプチャを壊す問題の対処。

旧アプローチ: sys.platform = "linux" → pytest-asyncio が os.getuid() を呼んで Windows で壊れる
新アプローチ: ソース側を `hasattr(sys.stdout, "buffer")` でガード済み → conftest は何もしない
"""
