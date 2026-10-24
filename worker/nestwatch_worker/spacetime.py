"""Talking to Spacetime over plain HTTP (same encoding as vision/nestwatch_vision/sync.py).

  reducer call : POST /v1/database/<db>/call/<reducer>   body = JSON array of the arguments, in order
                 products are arrays in field order; an option is {"some": x} or {"none": []}
  SQL read     : POST /v1/database/<db>/sql              body = the SQL text; rows come back with a schema
"""
import json
import re

import httpx

SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")       # everything we put inside SQL quotes must match this


class Rejected(Exception):
    """Spacetime answered and refused the call (wrong role, bad arguments, state check)."""


def decode(value, t):
    """One SQL cell to plain Python using its schema type (None for an empty option, seconds for a timestamp)."""
    (kind, body), = t.items()
    if kind == "Array":
        return [decode(v, body) for v in value]
    if kind == "Product":
        names = [e["name"].get("some") or str(i) for i, e in enumerate(body["elements"])]
        if names == ["__timestamp_micros_since_unix_epoch__"]:
            return value[0] / 1e6
        return {n: decode(v, e["algebraic_type"]) for n, v, e in zip(names, value, body["elements"])}
    if kind == "Sum":
        tag, payload = value
        variant = body["variants"][tag]
        name = variant["name"].get("some")
        if {v["name"].get("some") for v in body["variants"]} == {"some", "none"}:   # an option
            return None if name == "none" else decode(payload, variant["algebraic_type"])
        return {name: decode(payload, variant["algebraic_type"])}
    return value


def camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w.title() for w in rest)


def rows(result: dict) -> list[dict]:
    """Rows as dicts with camelCase keys (alert_id -> alertId), the same names the module and the apps use."""
    types = [(camel(e["name"].get("some")), e["algebraic_type"]) for e in result["schema"]["elements"]]
    return [{n: decode(v, t) for (n, t), v in zip(types, row)} for row in result["rows"]]


def opt(v):
    return {"none": []} if v is None else {"some": v}


def quoted(v: str) -> str:
    if not SAFE_ID.match(v):
        raise ValueError(f"unsafe id {v!r}")
    return f"'{v}'"


class Spacetime:
    def __init__(self, uri: str, db: str, token: str, timeout: float = 3.0):
        self.base = f"{uri.rstrip('/')}/v1/database/{db}"
        self.token = token
        self.http = httpx.AsyncClient(timeout=timeout)

    def _headers(self, token: str | None) -> dict:
        return {"Authorization": f"Bearer {token or self.token}", "Content-Type": "application/json"}

    async def call(self, reducer: str, args: list) -> None:
        r = await self.http.post(f"{self.base}/call/{reducer}", headers=self._headers(None), content=json.dumps(args))
        if r.status_code != 200:
            raise Rejected(f"{reducer}: {r.status_code} {r.text[:200]}")

    async def sql(self, query: str, token: str | None = None) -> list[dict]:
        """Run a query as the worker, or as `token` (used to ask Spacetime who a caller is)."""
        r = await self.http.post(f"{self.base}/sql", headers=self._headers(token), content=query)
        if r.status_code != 200:
            raise Rejected(f"sql: {r.status_code} {r.text[:200]}")
        return rows(r.json()[0])

    async def close(self) -> None:
        await self.http.aclose()
