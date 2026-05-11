"""はてなブログ AtomPub API 投稿モジュール"""
import httpx
import base64
from datetime import datetime, timezone, timedelta
from config.settings import settings

JST = timezone(timedelta(hours=9))

ATOM_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:app="http://www.w3.org/2007/app">
  <title>{title}</title>
  <author><name>{author}</name></author>
  <content type="text/html"><![CDATA[{content}]]></content>
  <updated>{updated}</updated>
  <app:control>
    <app:draft>no</app:draft>
  </app:control>
  {categories}
</entry>"""


class HatenaPublisher:
    def __init__(self, account: dict | None = None):
        if account:
            self.hatena_id = account["id"]
            self.blog_id   = account["blog_id"]
            self.api_key   = account["api_key"]
        else:
            self.hatena_id = settings.HATENA_ID
            self.blog_id   = settings.HATENA_BLOG_ID
            self.api_key   = settings.HATENA_API_KEY
        self.endpoint = f"https://blog.hatena.ne.jp/{self.hatena_id}/{self.blog_id}/atom/entry"

    def _auth_header(self) -> str:
        credentials = f"{self.hatena_id}:{self.api_key}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    async def publish(self, title: str, content: str, tags: list) -> dict:
        updated = datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")
        categories = "\n  ".join(
            f'<category term="{tag}" />' for tag in tags[:5]
        )

        body = ATOM_TEMPLATE.format(
            title     = title,
            author    = self.hatena_id,
            content   = content,
            updated   = updated,
            categories = categories,
        )

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.endpoint,
                content=body.encode("utf-8"),
                headers={
                    "Content-Type": "application/atom+xml; charset=utf-8",
                    "Authorization": self._auth_header(),
                }
            )

        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"はてなブログ投稿失敗: {response.status_code}\n{response.text[:300]}"
            )

        # レスポンスからURLを取得
        import re
        url_match = re.search(r"<link[^>]+rel=\"alternate\"[^>]+href=\"([^\"]+)\"", response.text)
        post_url = url_match.group(1) if url_match else ""

        id_match = re.search(r"<id>([^<]+)</id>", response.text)
        post_id = id_match.group(1).split("-")[-1] if id_match else ""

        print(f"  はてな投稿完了: {post_url}")
        return {"post_id": post_id, "post_url": post_url}
