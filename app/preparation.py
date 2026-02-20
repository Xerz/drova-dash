from typing import Any

import pandas as pd


def prepare_intervals_with_duration(intervals: pd.DataFrame) -> pd.DataFrame:
    intervals_with_duration = intervals.copy()
    intervals_with_duration["duration_sec"] = (
        intervals_with_duration["ended_at"] - intervals_with_duration["started_at"]
    ).dt.total_seconds()
    intervals_with_duration["duration_minutes"] = (
        intervals_with_duration["duration_sec"] / 60
    )
    return intervals_with_duration


def enrich_intervals_with_metadata(
    intervals_with_duration: pd.DataFrame,
    server_info_df: pd.DataFrame,
    uuid_to_name: dict[Any, Any],
    uuid_to_city: dict[Any, Any],
    pid_to_title: dict[Any, Any],
) -> pd.DataFrame:
    enriched = intervals_with_duration.merge(server_info_df, on="uuid", how="left")
    enriched["station_name"] = enriched["uuid"].map(uuid_to_name)
    enriched["product_title"] = enriched["product_id"].map(pid_to_title)
    enriched["city_name"] = enriched["city_name"].fillna(
        enriched["uuid"].map(uuid_to_city)
    )
    enriched["city_name"] = enriched["city_name"].fillna("Unknown")
    enriched["processor"] = enriched["processor"].fillna("Unknown")
    enriched["graphic_names"] = enriched["graphic_names"].fillna("Unknown")
    enriched["free_trial"] = enriched["free_trial"].fillna(0)
    return enriched
