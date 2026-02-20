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


def build_rolling_window_metrics(
    filtered: pd.DataFrame,
    window_days: int,
    range_start: pd.Timestamp | None = None,
    range_end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    columns = ["date", "active_stations_window", "played_hours_window"]
    if filtered.empty:
        return pd.DataFrame(columns=columns)

    base = filtered.dropna(subset=["started_at", "uuid", "duration_sec"]).copy()
    if base.empty:
        return pd.DataFrame(columns=columns)

    base["date"] = pd.to_datetime(base["started_at"]).dt.normalize()
    if range_start is not None and range_end is not None:
        start = pd.Timestamp(range_start).normalize()
        end = pd.Timestamp(range_end).normalize()
        if start > end:
            start, end = end, start
        base = base[(base["date"] >= start) & (base["date"] <= end)].copy()
        if base.empty:
            full_dates = pd.date_range(start, end, freq="D")
            return pd.DataFrame(
                {
                    "date": full_dates,
                    "active_stations_window": [0] * len(full_dates),
                    "played_hours_window": [0.0] * len(full_dates),
                }
            )

    daily_hours = base.groupby("date")["duration_sec"].sum().sort_index()
    daily_station_sets = (
        base.groupby("date")["uuid"].agg(lambda s: set(s.dropna())).sort_index()
    )

    if range_start is not None and range_end is not None:
        full_dates = pd.date_range(
            pd.Timestamp(range_start).normalize(),
            pd.Timestamp(range_end).normalize(),
            freq="D",
        )
    else:
        full_dates = pd.date_range(daily_hours.index.min(), daily_hours.index.max(), freq="D")
    daily_hours_full = daily_hours.reindex(full_dates, fill_value=0.0)
    rolling_hours = (
        daily_hours_full.rolling(window=window_days, min_periods=1).sum() / 3600.0
    )

    station_sets_map = {
        pd.Timestamp(date).normalize(): stations
        for date, stations in daily_station_sets.items()
    }
    station_presence: dict[Any, int] = {}
    rolling_active_counts: list[int] = []

    for current_date in full_dates:
        for station_uuid in station_sets_map.get(current_date, set()):
            station_presence[station_uuid] = station_presence.get(station_uuid, 0) + 1

        drop_date = current_date - pd.Timedelta(days=window_days)
        for station_uuid in station_sets_map.get(drop_date, set()):
            next_count = station_presence.get(station_uuid, 0) - 1
            if next_count <= 0:
                station_presence.pop(station_uuid, None)
            else:
                station_presence[station_uuid] = next_count

        rolling_active_counts.append(len(station_presence))

    out = pd.DataFrame(
        {
            "date": full_dates,
            "active_stations_window": rolling_active_counts,
            "played_hours_window": rolling_hours.values,
        }
    )
    # Hide leading partial window points; first visible point is first full window.
    first_window_date = full_dates[0] + pd.Timedelta(days=max(window_days - 1, 0))
    out = out[out["date"] >= first_window_date].reset_index(drop=True)
    return out
