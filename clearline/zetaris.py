"""Zetaris access.

The REST contract here is copied from the Zetaris getting-started client
(scripts/zetaris_api.py and scripts/zetaris_sql.py), not guessed:

    POST {ZETARIS_REST_URL}/sql-editor/sqls/run
    headers: Authorization: Bearer <key>, X-Org-ID, X-Request-ID (fresh UUID)
    body:    {"queryId": <uuid>, "sql": <one statement>, "source": "SqlEditor",
              "limit": <int>}
    returns: {"data": [[...row...], ...]}

One statement per call -- Lightning SQL does not take a batch.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .matching import rank

load_dotenv()

REST_URL = os.environ.get("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0").rstrip("/")
ORG_ID = os.environ.get("ZETARIS_ORG_ID", "1")
SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


class ZetarisError(RuntimeError):
    pass


def sample_mode() -> bool:
    return os.environ.get("SAMPLE_MODE", "true").lower() in {"1", "true", "yes"}


def run_sql(sql: str, limit: int = 200, timeout: int = 60) -> list[list[Any]]:
    """Run one Lightning SQL statement and return rows as a list of lists."""
    key = os.environ.get("ZETARIS_API_KEY")
    if not key:
        raise ZetarisError("ZETARIS_API_KEY is not set -- see .env.example")

    try:
        response = requests.post(
            f"{REST_URL}/sql-editor/sqls/run",
            headers={
                "Authorization": f"Bearer {key}",
                "X-Org-ID": ORG_ID,
                "X-Request-ID": str(uuid.uuid4()),
                "Content-Type": "application/json",
            },
            json={
                "queryId": str(uuid.uuid4()),
                "sql": sql,
                "source": "SqlEditor",
                "limit": limit,
            },
            timeout=timeout,
        )
    except requests.RequestException as error:
        raise ZetarisError(f"cannot reach Zetaris at {REST_URL}: {error}") from error

    if response.status_code == 401:
        raise ZetarisError("Zetaris returned 401 -- the API key is missing, wrong or expired")
    if response.status_code == 400:
        raise ZetarisError(f"Zetaris returned 400 -- check X-Org-ID and the SQL: {response.text[:300]}")
    if not response.ok:
        raise ZetarisError(f"Zetaris HTTP {response.status_code}: {response.text[:300]}")

    payload = response.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    return rows or []


def ping() -> bool:
    """SELECT 1 round trip. Used by the smoke test."""
    rows = run_sql("SELECT 1", limit=1)
    return bool(rows) and str(rows[0][0]) == "1"


# --- source access ----------------------------------------------------------
# Day 1 reads the local sample so the skeleton runs end to end before the REST
# tables exist. Day 2 registers the same files as Lightning REST tables and
# these functions switch to SQL. The SAMPLE_MODE branch stays all week: it is
# the fallback the submission requires, and it keeps the demo alive if a source
# is down during judging.


def _load_sample(name: str, key: str) -> list[dict]:
    path = SAMPLE_DIR / name
    if not path.exists():
        raise ZetarisError(f"{path} missing -- run: python scripts/gen_vendor_master.py")
    return json.loads(path.read_text(encoding="utf-8"))[key]


def get_vendor(vendor_id: str) -> dict | None:
    if sample_mode():
        for vendor in _load_sample("vendor_master.json", "vendors"):
            if vendor["vendor_id"] == vendor_id:
                return vendor
        return None

    rows = run_sql(
        "SELECT vendor_id, legal_name, trading_name, tax_id, country, "
        "bank_country, annual_spend_usd, category "
        f"FROM clearline.vendor_master_table WHERE vendor_id = '{vendor_id}'",
        limit=1,
    )
    if not rows:
        return None
    cols = ["vendor_id", "legal_name", "trading_name", "tax_id", "country",
            "bank_country", "annual_spend_usd", "category"]
    return dict(zip(cols, rows[0]))


def search_sanctions(vendor: dict, top_n: int = 5) -> list[dict]:
    """Candidate generation: block, score and cap.

    Scoring is deterministic (clearline.matching) and each candidate carries
    its features under `_features`, so the resolver judges evidence rather than
    re-deriving it. Day 1 scanned every entity with substring matching and
    handed the model whatever came back; that cost 9,660 reasoning tokens a run.
    """
    entities = _load_sample("sanctions_sample.json", "entities") if sample_mode() else         _sanctions_from_zetaris()
    return rank(vendor, entities, top_n=top_n)


def _sanctions_from_zetaris() -> list[dict]:
    """Live path: read the registered watchlist through the semantic layer.

    One row per alias, folded back into one record per entity.
    """
    rows = run_sql(
        "SELECT entity_id, caption, country, dataset, alias "
        "FROM clearline.sanctions_table",
        limit=5000,
    )
    by_id: dict[str, dict] = {}
    for entity_id, caption, country, dataset, alias in rows:
        entity = by_id.setdefault(entity_id, {
            "id": entity_id, "caption": caption, "country": country,
            "dataset": dataset, "topics": ["sanction"], "aliases": [],
        })
        if alias:
            entity["aliases"].append(alias)
    return list(by_id.values())


USL = "lightning.metastore.clearline.counterparty_usl"


_DQ_CACHE: dict[tuple, dict] = {}


def dq_report(table: str = f"{USL}.counterparty",
              columns: list[str] | None = None,
              timeout: int = 8) -> dict[str, Any]:
    """Data quality, read from Zetaris, that the agents act on at RUNTIME.

    Two things are asked of the platform and combined:

      RUN DQ TABLE <usl>   the constraints DECLARED in the semantic layer --
                           primary keys, foreign keys -- checked by Zetaris
                           rather than asserted by us
      a null-rate query    coverage of the specific columns the decision rests
                           on, which is the signal that moves the evidence bar

    Falls back to computing the null rates locally if Zetaris is unreachable,
    so a run still completes offline -- with `source` saying which it was, since
    a quality report that hides its own provenance is worth little.
    """
    columns = columns or ["tax_id", "country", "bank_country"]
    # Memoised per process. Data quality does not change within a batch of
    # screenings, and without this the test suite made fifteen round trips and
    # went from 1.5s to 60s -- losing the fast offline guard it exists to be.
    key = (table, tuple(columns))
    if key in _DQ_CACHE:
        return _DQ_CACHE[key]

    out: dict[str, Any] = {"table": table, "source": "zetaris", "columns": {}, "constraints": []}

    try:
        for row in run_sql(f"RUN DQ TABLE {table}", limit=50, timeout=timeout):
            # [column, table, check, total, valid, invalid]
            if len(row) >= 6:
                total, valid, invalid = (_as_int(row[3]), _as_int(row[4]), _as_int(row[5]))
                out["constraints"].append({
                    "column": row[0], "check": row[2],
                    "total": total, "valid": valid, "invalid": invalid,
                    "passed": invalid == 0,
                })

        selected = ", ".join(
            f"COUNT(*) AS n_{i}, COUNT({c}) AS present_{i}" for i, c in enumerate(columns)
        )
        rows = run_sql(f"SELECT {selected} FROM {table}", limit=1, timeout=timeout)
        if rows:
            values = rows[0]
            for i, column in enumerate(columns):
                total = _as_int(values[i * 2]) or 0
                present = _as_int(values[i * 2 + 1]) or 0
                out["columns"][column] = {
                    "n": total,
                    "null_rate": round((total - present) / total, 3) if total else 0.0,
                }
        _DQ_CACHE[key] = out
        return out

    except ZetarisError as error:
        out = {"table": table, "source": "local-fallback",
               "note": f"Zetaris unavailable ({str(error)[:80]}); null rates computed locally",
               "columns": {}, "constraints": []}
        vendors = _load_sample("vendor_master.json", "vendors")
        for column in columns:
            total = len(vendors)
            nulls = sum(1 for v in vendors if not v.get(column))
            out["columns"][column] = {
                "null_rate": round(nulls / total, 3) if total else 0.0, "n": total,
            }
        _DQ_CACHE[key] = out
        return out


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
