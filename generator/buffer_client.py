# generator/buffer_client.py
"""
Buffer GraphQL API istemcisi (https://api.buffer.com).

Kimlik: kisisel API anahtari, Bearer olarak. Buffer'da Settings > API'den
uretilir ve UCRETSIZ planda da calisir (hesap basina 1 anahtar).

Onemli kisit: Buffer'in medya yukleme ucu YOK. Gorseller herkese acik,
kimlik dogrulamasi istemeyen, kalici bir HTTPS adresinde durmali - bizde
GitHub Pages. Bu yuzden main.py, gorselin adresi gercekten 200 donmeden
postu zamanlamaz.
"""
import json
import logging

import httpx

log = logging.getLogger("buffer")

API_URL = "https://api.buffer.com"

CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}
"""

# Root query alanlarini kesfetmek icin - Buffer'in sema adlandirmasi hesaba
# gore degisebiliyor, bu yuzden channel/organization id'lerini tahmin etmek
# yerine `python -m generator.main probe` ile semayi okutuyoruz.
INTROSPECT = """
query { __schema {
  queryType { fields { name description } }
  mutationType { fields { name } }
} }
"""


class BufferError(RuntimeError):
    pass


class BufferClient:
    def __init__(self, api_key: str, timeout: int = 30):
        if not api_key:
            raise BufferError("BUFFER_API_KEY bos.")
        self._h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout

    async def gql(self, client: httpx.AsyncClient, query: str, variables: dict | None = None):
        r = await client.post(API_URL, headers=self._h, timeout=self._timeout,
                              json={"query": query, "variables": variables or {}})
        if r.status_code == 401:
            raise BufferError("401 - API anahtari gecersiz veya suresi dolmus.")
        if r.status_code == 429:
            raise BufferError("429 - Buffer hiz siniri. Bir sonraki turda tekrar denenecek.")
        if r.status_code >= 400:
            raise BufferError(f"HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        if body.get("errors"):
            raise BufferError("GraphQL: " + json.dumps(body["errors"])[:400])
        return body.get("data") or {}

    async def probe(self, client: httpx.AsyncClient) -> dict:
        """Semayi okur - kanal/organizasyon sorgusunun gercek adini bulmak icin."""
        return await self.gql(client, INTROSPECT)

    async def create_post(self, client: httpx.AsyncClient, *, channel_id: str, text: str,
                          due_at_iso: str, image_url: str | None = None) -> str:
        """
        Belirtilen kanala, verilen zamana planlanmis bir post olusturur.
        due_at_iso: '2026-09-05T17:00:00.000Z' (UTC, ISO 8601)
        """
        inp = {
            "channelId": channel_id,
            "text": text,
            "schedulingType": "automatic",   # Buffer kendisi yayinlar (bildirim degil)
            "mode": "customScheduled",       # tam zaman biz veriyoruz
            "dueAt": due_at_iso,
        }
        if image_url:
            inp["assets"] = [{"image": {"url": image_url}}]

        data = await self.gql(client, CREATE_POST, {"input": inp})
        res = data.get("createPost") or {}
        if res.get("__typename") == "PostActionSuccess":
            return str((res.get("post") or {}).get("id", ""))
        raise BufferError(f"createPost reddedildi: {res.get('message') or res}")
