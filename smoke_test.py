"""Three checks: Zetaris is up, Zetaris runs SQL over REST, Nemotron replies.

    python smoke_test.py

Secrets are read from .env and never printed. A FAIL line shows the error, not
the credential.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

results: list[tuple[str, str, str]] = []


def check(name, fn):
    try:
        fn()
        results.append(("PASS", name, ""))
    except Exception as error:  # noqa: BLE001 -- a smoke test reports, it does not raise
        results.append(("FAIL", name, str(error)[:180]))


def need(*names):
    for name in names:
        if not os.environ.get(name):
            raise AssertionError(f"{name} is missing from .env")


def zetaris_web():
    url = os.environ.get("ZETARIS_BASE_URL", "http://localhost:3000")
    requests.get(url, timeout=10).raise_for_status()


def zetaris_sql():
    need("ZETARIS_REST_URL", "ZETARIS_ORG_ID", "ZETARIS_API_KEY")
    from clearline.zetaris import ping
    assert ping(), "SELECT 1 did not return 1"


def nemotron():
    need("MODEL_BASE_URL", "MODEL_API_KEY", "NEMOTRON_MODEL")
    from openai import OpenAI
    client = OpenAI(
        base_url=os.environ["MODEL_BASE_URL"],
        api_key=os.environ["MODEL_API_KEY"],
        timeout=180.0,
    )
    reply = client.chat.completions.create(
        model=os.environ["NEMOTRON_MODEL"],
        messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        max_tokens=16,
    )
    assert reply.choices, "no reply from the model"


def sample_data():
    from pathlib import Path
    import json
    path = Path("data/sample/vendor_master.json")
    assert path.exists(), "run: python scripts/gen_vendor_master.py"
    vendors = json.loads(path.read_text(encoding="utf-8"))["vendors"]
    assert len(vendors) >= 100, f"only {len(vendors)} vendors"


check("Data:  Zetaris web interface", zetaris_web)
check("Data:  Zetaris runs SQL over REST", zetaris_sql)
check("Data:  local sample present", sample_data)
check("Power: Nemotron replies", nemotron)

width = max(len(name) for _, name, _ in results)
for status, name, detail in results:
    print(f"{status}  {name.ljust(width)}  {detail}")

raise SystemExit(0 if all(s == "PASS" for s, _, _ in results) else 1)
