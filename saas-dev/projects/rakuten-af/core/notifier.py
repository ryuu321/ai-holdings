"""エラー通知（スタブ実装）"""
import os


class EmailNotifier:
    @staticmethod
    def send_error_notification(subject: str, body: str):
        print(f"[NOTIFY] {subject}: {body[:100]}")
