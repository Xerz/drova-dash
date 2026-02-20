from typing import Any

import pandas as pd


def _session_stats(df: pd.DataFrame, key: str) -> pd.DataFrame:
    return (
        df.groupby(key)["duration_sec"]
        .agg(
            session_mean_sec="mean",
            session_p25_sec=lambda s: s.quantile(0.25),
            session_p75_sec=lambda s: s.quantile(0.75),
        )
        .reset_index()
        .assign(
            session_mean_hours=lambda d: d["session_mean_sec"] / 3600,
            session_p25_hours=lambda d: d["session_p25_sec"] / 3600,
            session_p75_hours=lambda d: d["session_p75_sec"] / 3600,
        )
    )


def build_station_product_rankings(
    filtered: pd.DataFrame,
    intervals_with_duration: pd.DataFrame,
    uuid_to_name: dict[Any, Any],
    pid_to_title: dict[Any, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    stats_uuid = _session_stats(filtered, "uuid")
    stats_prod = _session_stats(filtered, "product_id")

    agg_uuid = (
        filtered.groupby("uuid", as_index=False)["duration_sec"]
        .sum()
        .assign(duration_hours=lambda d: d["duration_sec"] / 3600)
        .sort_values("duration_hours", ascending=False)
        .merge(stats_uuid, on="uuid", how="left")
    )

    station_attributes = (
        intervals_with_duration[
            [
                "uuid",
                "city_name",
                "product_number",
                "processor",
                "graphic_names",
                "free_trial",
                "ram_bytes",
                "graphic_ram_bytes",
                "longitude",
                "latitude",
            ]
        ]
        .drop_duplicates("uuid")
    )
    agg_uuid = agg_uuid.merge(station_attributes, on="uuid", how="left")

    agg_prod = (
        filtered.groupby("product_id", as_index=False)["duration_sec"]
        .sum()
        .assign(duration_hours=lambda d: d["duration_sec"] / 3600)
        .sort_values("duration_hours", ascending=False)
        .merge(stats_prod, on="product_id", how="left")
    )

    agg_uuid["uuid_label"] = agg_uuid["uuid"].map(uuid_to_name).fillna(agg_uuid["uuid"])
    agg_prod["product_label"] = agg_prod["product_id"].map(pid_to_title).fillna(
        agg_prod["product_id"]
    )

    return agg_uuid, agg_prod


def build_city_ranking(filtered: pd.DataFrame) -> pd.DataFrame:
    return (
        filtered.assign(city=lambda d: d["city_name"].fillna("Unknown"))
        .groupby("city", as_index=False)
        .agg(
            duration_sec=("duration_sec", "sum"),
            n_stations=("uuid", "nunique"),
        )
        .assign(
            duration_hours=lambda d: d["duration_sec"] / 3600,
            hours_per_station=lambda d: (d["duration_sec"] / 3600) / d["n_stations"],
        )
        .sort_values("duration_hours", ascending=False)
    )


def build_group_ranking(df: pd.DataFrame, column: str) -> pd.DataFrame:
    return (
        df.assign(group=lambda d: d[column].fillna("Unknown"))
        .groupby("group", as_index=False)
        .agg(
            duration_sec=("duration_sec", "sum"),
            n_stations=("uuid", "nunique"),
        )
        .assign(
            duration_hours=lambda d: d["duration_sec"] / 3600,
            hours_per_station=lambda d: (d["duration_sec"] / 3600) / d["n_stations"],
        )
        .sort_values("duration_hours", ascending=False)
    )


def build_map_data(filtered: pd.DataFrame) -> pd.DataFrame:
    return (
        filtered.dropna(subset=["latitude", "longitude"])
        .groupby(["latitude", "longitude"], as_index=False)
        .agg(duration_minutes=("duration_minutes", "sum"))
    )
