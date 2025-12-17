"""
Fetch server metadata and hardware details for all UUIDs present in an SQLite DB
and store the aggregated information into a dedicated table without touching
existing schemas.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

SERVER_URL = "https://services.drova.io/server-manager/servers/public/"
HARDWARE_URL = "https://services.drova.io/server-manager/hardware/list/"
DEFAULT_TIMEOUT = 15


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch server info/hardware for UUIDs in the DB and store them in a "
            "new table without modifying existing ones."
        )
    )
    parser.add_argument(
        "db_path",
        help="Path to SQLite database containing station tables",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress information",
    )
    return parser.parse_args()


def fetch_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def gather_uuids(conn: sqlite3.Connection) -> List[str]:
    query = """
        SELECT DISTINCT uuid FROM (
            SELECT uuid FROM station_state
            UNION ALL
            SELECT uuid FROM station_changes
        )
        WHERE uuid IS NOT NULL
    """
    cur = conn.execute(query)
    uuids = [row[0] for row in cur.fetchall() if row[0]]
    return sorted(set(uuids))


def parse_server_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    product_list = payload.get("product_list")
    product_number = len(product_list) if isinstance(product_list, list) else None

    groups = payload.get("groups_list")
    free_trial = False
    if isinstance(groups, list):
        free_trial = any(str(g).strip().lower() == "free trial volunteers" for g in groups)

    return {
        "uuid": payload.get("uuid"),
        "name": payload.get("name"),
        "description": payload.get("description"),
        "product_number": product_number,
        "city_name": payload.get("city_name"),
        "free_trial": int(free_trial),
        "user_id": payload.get("user_id"),
        "longitude": payload.get("longitude"),
        "latitude": payload.get("latitude"),
        "product_id": payload.get("product_id"),
        "published": int(bool(payload.get("published"))) if payload.get("published") is not None else None,
        "distance": payload.get("distance"),
        "state": payload.get("state"),
    }


def parse_hardware_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    processor_info = payload.get("processor") or {}
    manufacturer = (processor_info.get("manufacturer") or "").strip()
    version = (processor_info.get("version") or "").strip()
    processor = " ".join(part for part in [manufacturer, version] if part).strip() or None

    ram_bytes = payload.get("ram_bytes")

    graphic = payload.get("graphic")
    graphic_names: List[str] = []
    graphic_ram = 0
    if isinstance(graphic, list):
        for item in graphic:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name:
                graphic_names.append(str(name))
            ram_val = item.get("ram_bytes")
            if isinstance(ram_val, (int, float)):
                graphic_ram += int(ram_val)

    return {
        "processor": processor,
        "ram_bytes": ram_bytes,
        "graphic_ram_bytes": graphic_ram if graphic_ram else None,
        "graphic_names": ", ".join(graphic_names) if graphic_names else None,
    }


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS server_info (
            uuid TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            product_number INTEGER,
            city_name TEXT,
            free_trial INTEGER,
            user_id TEXT,
            longitude REAL,
            latitude REAL,
            product_id TEXT,
            published INTEGER,
            distance REAL,
            state TEXT,
            processor TEXT,
            ram_bytes INTEGER,
            graphic_ram_bytes INTEGER,
            graphic_names TEXT,
            fetched_at TEXT
        )
        """
    )


def upsert_server(conn: sqlite3.Connection, record: Dict[str, Any]) -> None:
    columns = [
        "uuid",
        "name",
        "description",
        "product_number",
        "city_name",
        "free_trial",
        "user_id",
        "longitude",
        "latitude",
        "product_id",
        "published",
        "distance",
        "state",
        "processor",
        "ram_bytes",
        "graphic_ram_bytes",
        "graphic_names",
        "fetched_at",
    ]
    placeholders = ", ".join([":" + col for col in columns])
    conn.execute(
        f"""
        INSERT INTO server_info ({', '.join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(uuid) DO UPDATE SET
            name=excluded.name,
            description=excluded.description,
            product_number=excluded.product_number,
            city_name=excluded.city_name,
            free_trial=excluded.free_trial,
            user_id=excluded.user_id,
            longitude=excluded.longitude,
            latitude=excluded.latitude,
            product_id=excluded.product_id,
            published=excluded.published,
            distance=excluded.distance,
            state=excluded.state,
            processor=excluded.processor,
            ram_bytes=excluded.ram_bytes,
            graphic_ram_bytes=excluded.graphic_ram_bytes,
            graphic_names=excluded.graphic_names,
            fetched_at=excluded.fetched_at
        """,
        record,
    )


def main() -> None:
    args = parse_args()

    with sqlite3.connect(args.db_path) as conn:
        ensure_table(conn)
        uuids = gather_uuids(conn)
        if args.verbose:
            print(f"Found {len(uuids)} UUID(s) in database")

        for uuid in uuids:
            server_payload = fetch_json(f"{SERVER_URL}{uuid}")
            if not server_payload:
                if args.verbose:
                    print(f"Skipping {uuid}: server endpoint unavailable")
                continue

            hardware_payload = fetch_json(f"{HARDWARE_URL}{uuid}") or {}

            record = {
                **parse_server_payload(server_payload),
                **parse_hardware_payload(hardware_payload),
                "fetched_at": datetime.utcnow().isoformat(),
            }

            if not record.get("uuid"):
                if args.verbose:
                    print(f"Skipping entry without uuid from payload: {uuid}")
                continue

            upsert_server(conn, record)
            if args.verbose:
                print(f"Saved info for {uuid}")

        conn.commit()


if __name__ == "__main__":
    main()
