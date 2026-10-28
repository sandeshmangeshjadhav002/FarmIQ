"""Seed the curated farming-methods reference content into Supabase.

Run from the ``backend/`` directory after applying migration 0003:

    python scripts/seed_farming_methods.py

The bundled file ``app/data/farming_methods.json`` is the single source of
truth. This script upserts it into ``public.farming_methods`` and
``public.organic_alternatives`` using the service-role key (server-side only).
It is idempotent: re-running it refreshes the rows in place.

The API also serves the same file directly as a fallback when the tables are
absent or empty, so this script is an optimisation of how content is stored,
not a prerequisite for the feature to work.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))  # noqa: E402 - allow `python scripts/...`

from app.config import get_settings  # noqa: E402

DATA_FILE = BACKEND_DIR / "app" / "data" / "farming_methods.json"


def main() -> int:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set in backend/.env — nothing to seed.")
        return 1

    from supabase import create_client

    content = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    last_updated = content["metadata"]["last_updated"]
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    method_rows = [
        {"id": m["id"], "sort_order": i + 1, "payload": m, "last_updated": last_updated}
        for i, m in enumerate(content["methods"])
    ]
    alt_rows = [
        {
            "id": a["id"],
            "category": a.get("category"),
            "crops": a.get("crops") or ["*"],
            "payload": a,
            "last_updated": a.get("last_updated", last_updated),
        }
        for a in content["alternatives"]
    ]

    client.table("farming_methods").upsert(method_rows).execute()
    client.table("organic_alternatives").upsert(alt_rows).execute()

    print(f"Seeded {len(method_rows)} farming methods and {len(alt_rows)} organic alternatives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
