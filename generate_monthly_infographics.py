#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import concurrent.futures
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import requests


PRODUCTS_URL = "https://services.drova.io/product-manager/product/listfull2"
SERVER_PUBLIC_URL = "https://services.drova.io/server-manager/servers/public/"
DEFAULT_TIMEOUT_SECONDS = 20

RU_MONTHS = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


@dataclass(frozen=True)
class ReportPeriod:
    id: str
    label: str
    start: pd.Timestamp
    end_exclusive: pd.Timestamp
    display_end: pd.Timestamp
    is_partial: bool

    @property
    def period_label(self) -> str:
        return f"{format_date(self.start)} - {format_date(self.display_end)}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a static monthly Drova infographic from SQLite data."
    )
    parser.add_argument("--db", default="stations20260505.db", help="SQLite database path.")
    parser.add_argument(
        "--output",
        default="site/index.html",
        help="Output HTML path.",
    )
    parser.add_argument(
        "--template",
        default="reports/monthly_infographics_mockup.html",
        help="HTML mockup/template path.",
    )
    parser.add_argument(
        "--max-session-hours",
        type=float,
        default=30.0,
        help="Drop BUSY sessions longer than this raw duration.",
    )
    parser.add_argument(
        "--cache-dir",
        default="reports/.cache",
        help="Cache directory for product catalog and server product lists.",
    )
    parser.add_argument(
        "--cache-ttl-hours",
        type=float,
        default=24.0,
        help="Cache TTL for API payloads. Stale cache is used if refresh fails.",
    )
    parser.add_argument(
        "--fetch-workers",
        type=int,
        default=8,
        help="Parallel workers for server product-list fetches.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run small deterministic checks and exit.",
    )
    return parser.parse_args()


def format_date(value: pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%d.%m.%Y")


def month_start(value: pd.Timestamp) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return pd.Timestamp(year=value.year, month=value.month, day=1)


def add_month(value: pd.Timestamp) -> pd.Timestamp:
    value = pd.Timestamp(value)
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    return pd.Timestamp(year=year, month=month, day=1)


def month_last_day(value: pd.Timestamp) -> pd.Timestamp:
    value = pd.Timestamp(value)
    return pd.Timestamp(
        year=value.year,
        month=value.month,
        day=calendar.monthrange(value.year, value.month)[1],
    )


def iter_report_periods(data_min: pd.Timestamp, data_max: pd.Timestamp) -> list[ReportPeriod]:
    first_month = month_start(data_min)
    last_month = month_start(data_max)
    current = first_month if pd.Timestamp(data_min).day == 1 else add_month(first_month)

    periods: list[ReportPeriod] = []
    while current <= last_month:
        next_month = add_month(current)
        current_last_day = month_last_day(current)
        is_last_available_month = current == last_month
        is_partial = bool(
            is_last_available_month and pd.Timestamp(data_max).normalize() < current_last_day
        )
        end_exclusive = pd.Timestamp(data_max) if is_partial else next_month
        display_end = pd.Timestamp(data_max).normalize() if is_partial else current_last_day
        periods.append(
            ReportPeriod(
                id=current.strftime("%Y-%m"),
                label=f"{RU_MONTHS[current.month]} {current.year}",
                start=current,
                end_exclusive=end_exclusive,
                display_end=display_end,
                is_partial=is_partial,
            )
        )
        current = next_month
    return periods


def load_station_changes(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT
                id,
                uuid,
                old_state,
                new_state,
                old_product_id,
                new_product_id,
                changed_at
            FROM station_changes
            """,
            conn,
        )


def load_server_info(db_path: Path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(
            """
            SELECT
                uuid,
                name,
                processor,
                graphic_names
            FROM server_info
            """,
            conn,
        )


def clean_station_changes(df: pd.DataFrame) -> pd.DataFrame:
    cleaned = df.copy()
    cleaned["changed_at"] = pd.to_datetime(cleaned["changed_at"], errors="coerce")
    cleaned = cleaned.dropna(how="any").sort_values(["uuid", "changed_at", "id"])
    return cleaned.reset_index(drop=True)


def build_busy_intervals(df: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for uuid, group in df.groupby("uuid", sort=False):
        current_product = None
        start_ts = None
        for row in group.itertuples(index=False):
            new_state = str(row.new_state).upper()
            new_product = row.new_product_id
            timestamp = row.changed_at

            if current_product is None:
                if new_state == "BUSY" and pd.notna(new_product):
                    current_product = new_product
                    start_ts = timestamp
                continue

            if new_state == "BUSY":
                if new_product != current_product:
                    records.append(
                        {
                            "uuid": uuid,
                            "product_id": current_product,
                            "started_at": start_ts,
                            "ended_at": timestamp,
                        }
                    )
                    current_product = new_product
                    start_ts = timestamp
            else:
                records.append(
                    {
                        "uuid": uuid,
                        "product_id": current_product,
                        "started_at": start_ts,
                        "ended_at": timestamp,
                    }
                )
                current_product = None
                start_ts = None

        if current_product is not None:
            records.append(
                {
                    "uuid": uuid,
                    "product_id": current_product,
                    "started_at": start_ts,
                    "ended_at": pd.NaT,
                }
            )

    columns = ["uuid", "product_id", "started_at", "ended_at"]
    if not records:
        return pd.DataFrame(columns=columns)
    return (
        pd.DataFrame.from_records(records, columns=columns)
        .sort_values(["uuid", "started_at"])
        .reset_index(drop=True)
    )


def prepare_intervals(intervals: pd.DataFrame, max_session_hours: float) -> pd.DataFrame:
    if intervals.empty:
        return intervals.assign(raw_duration_sec=pd.Series(dtype="float64"))

    prepared = intervals.copy()
    prepared["started_at"] = pd.to_datetime(prepared["started_at"], errors="coerce")
    prepared["ended_at"] = pd.to_datetime(prepared["ended_at"], errors="coerce")
    prepared = prepared.dropna(subset=["started_at", "ended_at", "uuid", "product_id"])
    prepared["raw_duration_sec"] = (
        prepared["ended_at"] - prepared["started_at"]
    ).dt.total_seconds()
    max_seconds = float(max_session_hours) * 3600.0
    prepared = prepared[
        (prepared["raw_duration_sec"] > 0) & (prepared["raw_duration_sec"] <= max_seconds)
    ].copy()
    prepared["interval_id"] = range(len(prepared))
    return prepared.reset_index(drop=True)


def clip_intervals_to_period(intervals: pd.DataFrame, period: ReportPeriod) -> pd.DataFrame:
    if intervals.empty:
        return intervals.assign(duration_sec=pd.Series(dtype="float64"))

    clipped = intervals[
        (intervals["started_at"] < period.end_exclusive)
        & (intervals["ended_at"] > period.start)
    ].copy()
    if clipped.empty:
        return clipped.assign(duration_sec=pd.Series(dtype="float64"))

    clipped["clipped_started_at"] = clipped["started_at"].where(
        clipped["started_at"] > period.start,
        period.start,
    )
    clipped["clipped_ended_at"] = clipped["ended_at"].where(
        clipped["ended_at"] < period.end_exclusive,
        period.end_exclusive,
    )
    clipped["duration_sec"] = (
        clipped["clipped_ended_at"] - clipped["clipped_started_at"]
    ).dt.total_seconds()
    return clipped[clipped["duration_sec"] > 0].reset_index(drop=True)


def cache_read(path: Path, ttl_hours: float) -> tuple[Any | None, bool]:
    if not path.exists():
        return None, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, False
    age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    return data, age_hours > ttl_hours


def cache_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def get_json_with_cache(
    url: str,
    cache_path: Path,
    ttl_hours: float,
    *,
    required: bool,
) -> tuple[Any | None, str | None]:
    cached_data, is_stale = cache_read(cache_path, ttl_hours)
    if cached_data is not None and not is_stale:
        return cached_data, None

    try:
        response = requests.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        cache_write(cache_path, data)
        return data, None
    except Exception as exc:
        if cached_data is not None:
            return cached_data, f"Using stale cache for {url}: {exc}"
        if required:
            raise RuntimeError(f"Failed to fetch required API payload from {url}: {exc}") from exc
        return None, f"Missing optional API payload for {url}: {exc}"


def load_product_catalog(cache_dir: Path, ttl_hours: float) -> tuple[dict[str, dict[str, Any]], list[str]]:
    data, warning = get_json_with_cache(
        PRODUCTS_URL,
        cache_dir / "product_catalog.json",
        ttl_hours,
        required=True,
    )
    warnings = [warning] if warning else []
    if not isinstance(data, list):
        raise RuntimeError("Product catalog API returned a non-list payload.")

    catalog: dict[str, dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        product_id = item.get("productId")
        if not product_id:
            continue
        catalog[str(product_id)] = {
            "title": item.get("title") or item.get("displayName") or str(product_id),
            "useDefaultDesktop": item.get("useDefaultDesktop"),
        }
    return catalog, warnings


def fetch_server_payloads(
    uuids: list[str],
    cache_dir: Path,
    ttl_hours: float,
    workers: int,
) -> tuple[dict[str, dict[str, Any] | None], list[str]]:
    server_cache_dir = cache_dir / "servers_public"
    warnings: list[str] = []

    def fetch_one(uuid: str) -> tuple[str, dict[str, Any] | None, str | None]:
        data, warning = get_json_with_cache(
            f"{SERVER_PUBLIC_URL}{uuid}",
            server_cache_dir / f"{uuid}.json",
            ttl_hours,
            required=False,
        )
        if isinstance(data, dict):
            return uuid, data, warning
        return uuid, None, warning

    payloads: dict[str, dict[str, Any] | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(fetch_one, uuid) for uuid in uuids]
        for future in concurrent.futures.as_completed(futures):
            uuid, payload, warning = future.result()
            payloads[uuid] = payload
            if warning:
                warnings.append(warning)
    return payloads, warnings


def product_desktop_map(catalog: dict[str, dict[str, Any]]) -> dict[str, bool | None]:
    out: dict[str, bool | None] = {}
    for product_id, meta in catalog.items():
        value = meta.get("useDefaultDesktop")
        out[product_id] = value if isinstance(value, bool) else None
    return out


def classify_server_product_list(
    product_list: Any,
    product_is_desktop: dict[str, bool | None],
) -> bool | None:
    if not isinstance(product_list, list):
        return None
    has_unknown = False
    for product_id in product_list:
        product_class = product_is_desktop.get(str(product_id))
        if product_class is True:
            return True
        if product_class is None:
            has_unknown = True
    if has_unknown:
        return None
    return False


def classify_servers(
    payloads: dict[str, dict[str, Any] | None],
    product_is_desktop: dict[str, bool | None],
) -> dict[str, bool | None]:
    return {
        uuid: classify_server_product_list(
            payload.get("product_list") if isinstance(payload, dict) else None,
            product_is_desktop,
        )
        for uuid, payload in payloads.items()
    }


def ratio_for(df: pd.DataFrame, product_is_desktop: dict[str, bool | None]) -> tuple[dict[str, int], float]:
    if df.empty:
        return {"desktop": 0, "sandbox": 0}, 0.0

    classes = df["product_id"].astype(str).map(product_is_desktop)
    desktop_sec = float(df.loc[classes == True, "duration_sec"].sum())
    sandbox_sec = float(df.loc[classes == False, "duration_sec"].sum())
    known_sec = desktop_sec + sandbox_sec
    unknown_sec = float(df["duration_sec"].sum()) - known_sec
    return (
        {
            "desktop": int(round(desktop_sec / 3600.0)),
            "sandbox": int(round(sandbox_sec / 3600.0)),
        },
        max(0.0, unknown_sec / 3600.0),
    )


def station_ranking(df: pd.DataFrame, station_names: dict[str, str], top_n: int = 10) -> list[list[Any]]:
    if df.empty:
        return []
    grouped = (
        df.groupby("uuid", as_index=False)["duration_sec"]
        .sum()
        .sort_values("duration_sec", ascending=False)
        .head(top_n)
    )
    rows: list[list[Any]] = []
    for row in grouped.itertuples(index=False):
        uuid = str(row.uuid)
        rows.append(
            [
                station_names.get(uuid) or uuid,
                int(round(float(row.duration_sec) / 3600.0)),
                uuid,
            ]
        )
    return rows


def split_graphics(value: str | None) -> list[str]:
    if not value or str(value).strip().lower() == "nan":
        return ["Unknown"]
    parts = [part.strip() for part in str(value).split(",") if part.strip()]
    return parts or ["Unknown"]


def top_hardware(
    active_uuids: list[str],
    server_processors: dict[str, str],
    server_graphics: dict[str, str],
) -> tuple[list[list[Any]], list[list[Any]]]:
    cpu_counts: dict[str, int] = {}
    gpu_counts: dict[str, int] = {}

    for uuid in active_uuids:
        processor = server_processors.get(uuid) or "Unknown"
        cpu_counts[processor] = cpu_counts.get(processor, 0) + 1

        for graphic in set(split_graphics(server_graphics.get(uuid))):
            gpu_counts[graphic] = gpu_counts.get(graphic, 0) + 1

    def top_rows(counts: dict[str, int]) -> list[list[Any]]:
        return [
            [name, count]
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ]

    return top_rows(cpu_counts), top_rows(gpu_counts)


def build_month_payload(
    period: ReportPeriod,
    month_df: pd.DataFrame,
    product_is_desktop: dict[str, bool | None],
    server_has_desktop: dict[str, bool | None],
    station_names: dict[str, str],
    server_processors: dict[str, str],
    server_graphics: dict[str, str],
) -> dict[str, Any]:
    month_df = month_df.copy()
    month_df["has_desktop"] = month_df["uuid"].astype(str).map(server_has_desktop)

    active_uuids = sorted(str(uuid) for uuid in month_df["uuid"].dropna().astype(str).unique())
    known_server_uuids = [
        uuid for uuid in active_uuids if server_has_desktop.get(uuid) in (True, False)
    ]
    with_desktop = sum(1 for uuid in known_server_uuids if server_has_desktop.get(uuid) is True)
    without_desktop = sum(1 for uuid in known_server_uuids if server_has_desktop.get(uuid) is False)
    unknown_server_count = len(active_uuids) - len(known_server_uuids)

    title_ratio_all, unknown_product_hours_all = ratio_for(month_df, product_is_desktop)
    desktop_server_df = month_df[month_df["has_desktop"] == True].copy()
    title_ratio_desktop_servers, unknown_product_hours_desktop = ratio_for(
        desktop_server_df,
        product_is_desktop,
    )

    cpu, gpu = top_hardware(active_uuids, server_processors, server_graphics)
    warnings: list[str] = []
    if period.is_partial:
        warnings.append(f"Месяц частичный: данные за период {period.period_label}.")
    unknown_product_hours = unknown_product_hours_all + unknown_product_hours_desktop
    if unknown_product_hours > 0.5:
        warnings.append(
            "Не удалось классифицировать "
            f"{int(round(unknown_product_hours))} ч BUSY по desktop/sandbox "
            "из-за отсутствующих product metadata."
        )
    if unknown_server_count:
        warnings.append(
            f"{unknown_server_count} активных станций без доступного product_list "
            "не включены в срезы с desktop / без desktop."
        )

    return {
        "id": period.id,
        "label": period.label,
        "period": period.period_label,
        "isPartial": period.is_partial,
        "warnings": warnings,
        "kpis": {
            "busyHours": int(round(float(month_df["duration_sec"].sum()) / 3600.0)),
            "sessions": int(month_df["interval_id"].nunique()) if "interval_id" in month_df else 0,
            "activeStations": len(active_uuids),
        },
        "titleRatio": {
            "all": title_ratio_all,
            "desktopServers": title_ratio_desktop_servers,
        },
        "serverRatio": {
            "withDesktop": int(with_desktop),
            "withoutDesktop": int(without_desktop),
        },
        "stationRanks": {
            "all": station_ranking(month_df, station_names),
            "withDesktop": station_ranking(month_df[month_df["has_desktop"] == True], station_names),
            "withoutDesktop": station_ranking(
                month_df[month_df["has_desktop"] == False],
                station_names,
            ),
        },
        "cpu": cpu,
        "gpu": gpu,
    }


def build_report_data(
    db_path: Path,
    cache_dir: Path,
    cache_ttl_hours: float,
    max_session_hours: float,
    fetch_workers: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    raw_changes = load_station_changes(db_path)
    raw_changes["changed_at"] = pd.to_datetime(raw_changes["changed_at"], errors="coerce")
    data_min = pd.Timestamp(raw_changes["changed_at"].min())
    data_max = pd.Timestamp(raw_changes["changed_at"].max())
    periods = iter_report_periods(data_min, data_max)

    cleaned_changes = clean_station_changes(raw_changes)
    intervals = prepare_intervals(build_busy_intervals(cleaned_changes), max_session_hours)
    server_info = load_server_info(db_path)

    server_info["uuid"] = server_info["uuid"].astype(str)
    station_names = dict(
        zip(server_info["uuid"], server_info["name"].fillna("").astype(str), strict=False)
    )
    server_processors = dict(
        zip(server_info["uuid"], server_info["processor"].fillna("Unknown").astype(str), strict=False)
    )
    server_graphics = dict(
        zip(
            server_info["uuid"],
            server_info["graphic_names"].fillna("Unknown").astype(str),
            strict=False,
        )
    )

    catalog, api_warnings = load_product_catalog(cache_dir, cache_ttl_hours)
    product_is_desktop = product_desktop_map(catalog)

    if periods:
        report_start = periods[0].start
        report_end = periods[-1].end_exclusive
        report_intervals = intervals[
            (intervals["started_at"] < report_end) & (intervals["ended_at"] > report_start)
        ]
    else:
        report_intervals = intervals
    active_uuids = sorted(report_intervals["uuid"].dropna().astype(str).unique().tolist())
    server_payloads, server_warnings = fetch_server_payloads(
        active_uuids,
        cache_dir,
        cache_ttl_hours,
        fetch_workers,
    )
    server_has_desktop = classify_servers(server_payloads, product_is_desktop)

    months: list[dict[str, Any]] = []
    for period in periods:
        month_df = clip_intervals_to_period(intervals, period)
        months.append(
            build_month_payload(
                period=period,
                month_df=month_df,
                product_is_desktop=product_is_desktop,
                server_has_desktop=server_has_desktop,
                station_names=station_names,
                server_processors=server_processors,
                server_graphics=server_graphics,
            )
        )

    return months, api_warnings + server_warnings


def replace_report_data(template: str, months: list[dict[str, Any]]) -> str:
    report_json = json.dumps(months, ensure_ascii=False, separators=(",", ":"))
    report_json = report_json.replace("</", "<\\/")

    replaced = re.sub(
        r"const\s+MOCK_MONTHS\s*=\s*\[.*?\n    \];\n\n    const RANK_LABELS",
        f"const REPORT_MONTHS = {report_json};\n\n    const RANK_LABELS",
        template,
        flags=re.DOTALL,
    )
    if replaced == template:
        raise RuntimeError("Could not replace mock month data in the HTML template.")

    replaced = replaced.replace("MOCK_MONTHS", "REPORT_MONTHS")
    replaced = replaced.replace("Mockup / фиктивные данные", "Реальные данные / GitHub Pages")
    replaced = replaced.replace(
        "Срез активности серверов по desktop/sandbox, станциям и железу. "
        "Структура экрана зафиксирована для последующей подстановки реальных данных.",
        "Срез активности серверов по desktop/sandbox, станциям и железу. "
        "Отчёт сгенерирован из SQLite и публичных API Drova.",
    )
    replaced = replaced.replace(
        "Все значения в этом файле фиктивные. Реальная фаза заменит только источник данных, сохранив структуру блоков и CSS-контракт.",
        "Значения рассчитаны по закрытым BUSY-интервалам. Сессии длиннее выбранного лимита исключены; месячные значения клиппируются по границам месяца.",
    )
    return replaced


def write_html(output_path: Path, html: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def generate(
    db_path: Path,
    output_path: Path,
    template_path: Path,
    cache_dir: Path,
    cache_ttl_hours: float,
    max_session_hours: float,
    fetch_workers: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    months, warnings = build_report_data(
        db_path=db_path,
        cache_dir=cache_dir,
        cache_ttl_hours=cache_ttl_hours,
        max_session_hours=max_session_hours,
        fetch_workers=fetch_workers,
    )
    template = template_path.read_text(encoding="utf-8")
    html = replace_report_data(template, months)
    write_html(output_path, html)
    return months, warnings


def run_self_test() -> None:
    periods = iter_report_periods(
        pd.Timestamp("2025-07-14 13:32:40"),
        pd.Timestamp("2026-04-22 07:26:40"),
    )
    assert [period.id for period in periods] == [
        "2025-08",
        "2025-09",
        "2025-10",
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
    ]
    assert periods[-1].is_partial is True
    assert periods[-1].period_label == "01.04.2026 - 22.04.2026"

    sample = pd.DataFrame(
        [
            {
                "uuid": "u1",
                "product_id": "p1",
                "started_at": pd.Timestamp("2026-03-31 23:00:00"),
                "ended_at": pd.Timestamp("2026-04-01 01:00:00"),
                "interval_id": 1,
            }
        ]
    )
    april = ReportPeriod(
        id="2026-04",
        label="Апрель 2026",
        start=pd.Timestamp("2026-04-01"),
        end_exclusive=pd.Timestamp("2026-05-01"),
        display_end=pd.Timestamp("2026-04-30"),
        is_partial=False,
    )
    clipped = clip_intervals_to_period(sample, april)
    assert int(clipped["duration_sec"].sum()) == 3600

    product_classes = {"desktop": True, "sandbox": False}
    assert classify_server_product_list(["sandbox", "desktop"], product_classes) is True
    assert classify_server_product_list(["sandbox"], product_classes) is False
    assert classify_server_product_list(["missing"], product_classes) is None
    print("self-test ok")


def main() -> None:
    args = parse_args()
    if args.self_test:
        run_self_test()
        return

    months, warnings = generate(
        db_path=Path(args.db),
        output_path=Path(args.output),
        template_path=Path(args.template),
        cache_dir=Path(args.cache_dir),
        cache_ttl_hours=args.cache_ttl_hours,
        max_session_hours=args.max_session_hours,
        fetch_workers=args.fetch_workers,
    )
    print(f"Generated {args.output}")
    print("Months:", ", ".join(month["id"] for month in months))
    if warnings:
        print(f"API/cache warnings: {len(warnings)}")
        for warning in warnings[:10]:
            print(f"- {warning}")
        if len(warnings) > 10:
            print(f"- ... {len(warnings) - 10} more")


if __name__ == "__main__":
    main()
