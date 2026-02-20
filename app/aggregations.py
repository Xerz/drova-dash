from typing import Any

import pandas as pd


def _normalize_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def _product_window_share(
    base: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.Series:
    window = base[(base["date"] >= start) & (base["date"] <= end)]
    if window.empty:
        return pd.Series(dtype="float64")
    per_product = window.groupby("product_id")["duration_sec"].sum()
    total = float(per_product.sum())
    if total <= 0:
        return pd.Series(dtype="float64")
    return (per_product / total) * 100.0


def build_product_share_wow_mom(filtered: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    columns = [
        "product_id",
        "duration_hours",
        "share_pct",
        "wow_delta_pp",
        "mom_delta_pp",
    ]
    if filtered.empty:
        return pd.DataFrame(columns=columns)

    base = filtered.dropna(subset=["started_at", "product_id", "duration_sec"]).copy()
    if base.empty:
        return pd.DataFrame(columns=columns)

    base["date"] = _normalize_dates(base["started_at"])
    base = base.dropna(subset=["date"])
    if base.empty:
        return pd.DataFrame(columns=columns)

    total_duration = base["duration_sec"].sum()
    if total_duration <= 0:
        return pd.DataFrame(columns=columns)

    per_product = (
        base.groupby("product_id", as_index=False)["duration_sec"]
        .sum()
        .assign(
            duration_hours=lambda d: d["duration_sec"] / 3600.0,
            share_pct=lambda d: (d["duration_sec"] / total_duration) * 100.0,
        )
    )

    end_date = pd.Timestamp(base["date"].max()).normalize()
    wow_days = 7
    mom_days = 30
    wow_current_start = end_date - pd.Timedelta(days=wow_days - 1)
    wow_prev_end = wow_current_start - pd.Timedelta(days=1)
    wow_prev_start = wow_prev_end - pd.Timedelta(days=wow_days - 1)
    mom_current_start = end_date - pd.Timedelta(days=mom_days - 1)
    mom_prev_end = mom_current_start - pd.Timedelta(days=1)
    mom_prev_start = mom_prev_end - pd.Timedelta(days=mom_days - 1)

    wow_current_share = _product_window_share(base, wow_current_start, end_date)
    wow_prev_share = _product_window_share(base, wow_prev_start, wow_prev_end)
    mom_current_share = _product_window_share(base, mom_current_start, end_date)
    mom_prev_share = _product_window_share(base, mom_prev_start, mom_prev_end)

    per_product["wow_delta_pp"] = (
        per_product["product_id"].map(wow_current_share).fillna(0.0)
        - per_product["product_id"].map(wow_prev_share).fillna(0.0)
    )
    per_product["mom_delta_pp"] = (
        per_product["product_id"].map(mom_current_share).fillna(0.0)
        - per_product["product_id"].map(mom_prev_share).fillna(0.0)
    )

    return per_product.sort_values("duration_hours", ascending=False).head(top_n)


def build_product_adoption(filtered: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    columns = [
        "product_id",
        "new_stations_7d",
        "new_stations_30d",
        "adoption_rate_7d_pct",
        "adoption_rate_30d_pct",
    ]
    if filtered.empty:
        return pd.DataFrame(columns=columns)

    base = filtered.dropna(subset=["started_at", "product_id", "uuid"]).copy()
    if base.empty:
        return pd.DataFrame(columns=columns)

    base["date"] = _normalize_dates(base["started_at"])
    base = base.dropna(subset=["date"])
    if base.empty:
        return pd.DataFrame(columns=columns)

    end_date = pd.Timestamp(base["date"].max()).normalize()
    start_7d = end_date - pd.Timedelta(days=6)
    start_30d = end_date - pd.Timedelta(days=29)

    first_seen = (
        base.groupby(["product_id", "uuid"], as_index=False)["date"]
        .min()
        .rename(columns={"date": "first_date"})
    )

    new_7d = (
        first_seen[first_seen["first_date"] >= start_7d]
        .groupby("product_id")["uuid"]
        .nunique()
    )
    new_30d = (
        first_seen[first_seen["first_date"] >= start_30d]
        .groupby("product_id")["uuid"]
        .nunique()
    )

    active_7d = base[base["date"] >= start_7d]["uuid"].nunique()
    active_30d = base[base["date"] >= start_30d]["uuid"].nunique()

    all_products = (
        base[["product_id"]]
        .drop_duplicates()
        .assign(
            new_stations_7d=lambda d: d["product_id"].map(new_7d).fillna(0).astype(int),
            new_stations_30d=lambda d: d["product_id"].map(new_30d).fillna(0).astype(int),
        )
    )
    all_products["adoption_rate_7d_pct"] = (
        all_products["new_stations_7d"] / active_7d * 100.0 if active_7d else 0.0
    )
    all_products["adoption_rate_30d_pct"] = (
        all_products["new_stations_30d"] / active_30d * 100.0 if active_30d else 0.0
    )

    return (
        all_products.sort_values(["new_stations_30d", "new_stations_7d"], ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )


def build_free_trial_impact(
    filtered: pd.DataFrame,
) -> tuple[dict[str, float], pd.DataFrame]:
    summary = {
        "busy_hours_total": 0.0,
        "busy_hours_free_trial": 0.0,
        "free_trial_share_pct": 0.0,
        "free_trial_share_delta_7d_pp": 0.0,
    }
    columns = [
        "date",
        "free_trial_hours",
        "paid_hours",
        "total_hours",
        "free_trial_share_pct",
    ]
    if filtered.empty:
        return summary, pd.DataFrame(columns=columns)

    base = filtered.dropna(subset=["started_at", "duration_sec"]).copy()
    if base.empty:
        return summary, pd.DataFrame(columns=columns)

    base["date"] = _normalize_dates(base["started_at"])
    base = base.dropna(subset=["date"])
    if base.empty:
        return summary, pd.DataFrame(columns=columns)

    free_trial_numeric = pd.to_numeric(base["free_trial"], errors="coerce").fillna(0)
    base["is_free_trial"] = free_trial_numeric.astype(int) == 1

    daily = (
        base.groupby(["date", "is_free_trial"])["duration_sec"]
        .sum()
        .unstack(fill_value=0)
        .rename(columns={False: "paid_sec", True: "free_trial_sec"})
        .reset_index()
    )
    if "paid_sec" not in daily.columns:
        daily["paid_sec"] = 0.0
    if "free_trial_sec" not in daily.columns:
        daily["free_trial_sec"] = 0.0

    daily["free_trial_hours"] = daily["free_trial_sec"] / 3600.0
    daily["paid_hours"] = daily["paid_sec"] / 3600.0
    daily["total_hours"] = daily["free_trial_hours"] + daily["paid_hours"]
    daily["free_trial_share_pct"] = (
        daily["free_trial_hours"] / daily["total_hours"] * 100.0
    ).fillna(0.0)
    daily = daily.sort_values("date").reset_index(drop=True)

    free_total = float(daily["free_trial_hours"].sum())
    all_total = float(daily["total_hours"].sum())
    share_total = (free_total / all_total * 100.0) if all_total else 0.0

    end_date = pd.Timestamp(daily["date"].max()).normalize()
    current_start = end_date - pd.Timedelta(days=6)
    prev_end = current_start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=6)
    current_window = daily[daily["date"] >= current_start]
    prev_window = daily[(daily["date"] >= prev_start) & (daily["date"] <= prev_end)]

    current_total = float(current_window["total_hours"].sum())
    prev_total = float(prev_window["total_hours"].sum())
    current_share = (
        float(current_window["free_trial_hours"].sum()) / current_total * 100.0
        if current_total
        else 0.0
    )
    prev_share = (
        float(prev_window["free_trial_hours"].sum()) / prev_total * 100.0
        if prev_total
        else 0.0
    )

    summary = {
        "busy_hours_total": all_total,
        "busy_hours_free_trial": free_total,
        "free_trial_share_pct": share_total,
        "free_trial_share_delta_7d_pp": current_share - prev_share,
    }
    return summary, daily[columns]


def build_demand_heatmap(filtered: pd.DataFrame) -> pd.DataFrame:
    columns = ["weekday_num", "weekday", "hour", "busy_hours"]
    if filtered.empty:
        return pd.DataFrame(columns=columns)

    base = filtered.dropna(subset=["started_at", "duration_sec"]).copy()
    if base.empty:
        return pd.DataFrame(columns=columns)

    started = pd.to_datetime(base["started_at"], errors="coerce")
    base = base.assign(
        weekday_num=started.dt.dayofweek,
        hour=started.dt.hour,
    ).dropna(subset=["weekday_num", "hour"])
    if base.empty:
        return pd.DataFrame(columns=columns)

    weekday_map = {
        0: "Mon",
        1: "Tue",
        2: "Wed",
        3: "Thu",
        4: "Fri",
        5: "Sat",
        6: "Sun",
    }
    heat = (
        base.groupby(["weekday_num", "hour"], as_index=False)["duration_sec"]
        .sum()
        .assign(
            weekday=lambda d: d["weekday_num"].astype(int).map(weekday_map),
            busy_hours=lambda d: d["duration_sec"] / 3600.0,
        )[["weekday_num", "weekday", "hour", "busy_hours"]]
    )

    full = pd.MultiIndex.from_product(
        [range(7), range(24)], names=["weekday_num", "hour"]
    ).to_frame(index=False)
    full["weekday"] = full["weekday_num"].map(weekday_map)
    return (
        full.merge(heat, on=["weekday_num", "weekday", "hour"], how="left")
        .fillna({"busy_hours": 0.0})
        .sort_values(["weekday_num", "hour"])
        .reset_index(drop=True)
    )


def build_product_cannibalization(
    filtered: pd.DataFrame, lookback_days: int = 7, top_n: int = 15
) -> tuple[pd.DataFrame, pd.DataFrame]:
    shift_columns = [
        "product_id",
        "current_share_pct",
        "previous_share_pct",
        "delta_pp",
    ]
    pair_columns = [
        "loser_product_id",
        "gainer_product_id",
        "loser_delta_pp",
        "gainer_delta_pp",
        "compensation_pct",
    ]
    if filtered.empty:
        return pd.DataFrame(columns=shift_columns), pd.DataFrame(columns=pair_columns)

    base = filtered.dropna(subset=["started_at", "product_id", "duration_sec"]).copy()
    if base.empty:
        return pd.DataFrame(columns=shift_columns), pd.DataFrame(columns=pair_columns)
    base["date"] = _normalize_dates(base["started_at"])
    base = base.dropna(subset=["date"])
    if base.empty:
        return pd.DataFrame(columns=shift_columns), pd.DataFrame(columns=pair_columns)

    end_date = pd.Timestamp(base["date"].max()).normalize()
    current_start = end_date - pd.Timedelta(days=max(lookback_days - 1, 0))
    previous_end = current_start - pd.Timedelta(days=1)
    previous_start = previous_end - pd.Timedelta(days=max(lookback_days - 1, 0))

    share_current = _product_window_share(base, current_start, end_date)
    share_previous = _product_window_share(base, previous_start, previous_end)
    product_ids = pd.Index(share_current.index).union(share_previous.index)

    shift = pd.DataFrame({"product_id": product_ids})
    shift["current_share_pct"] = shift["product_id"].map(share_current).fillna(0.0)
    shift["previous_share_pct"] = shift["product_id"].map(share_previous).fillna(0.0)
    shift["delta_pp"] = shift["current_share_pct"] - shift["previous_share_pct"]
    shift = shift.sort_values("delta_pp", ascending=True).reset_index(drop=True)

    gainers = shift[shift["delta_pp"] > 0].sort_values("delta_pp", ascending=False)
    losers = shift[shift["delta_pp"] < 0].sort_values("delta_pp", ascending=True)
    pairs: list[dict[str, Any]] = []
    gainer_rows = list(gainers.head(top_n).itertuples(index=False))
    for idx, loser in enumerate(losers.head(top_n).itertuples(index=False)):
        if idx >= len(gainer_rows):
            break
        gainer = gainer_rows[idx]
        lost = abs(float(loser.delta_pp))
        gained = float(gainer.delta_pp)
        compensation = min(gained, lost) / lost * 100.0 if lost else 0.0
        pairs.append(
            {
                "loser_product_id": loser.product_id,
                "gainer_product_id": gainer.product_id,
                "loser_delta_pp": loser.delta_pp,
                "gainer_delta_pp": gainer.delta_pp,
                "compensation_pct": compensation,
            }
        )

    pairs_df = pd.DataFrame(pairs, columns=pair_columns)
    shift_df = shift.sort_values("delta_pp", key=lambda s: s.abs(), ascending=False).head(top_n)
    return shift_df.reset_index(drop=True), pairs_df.reset_index(drop=True)


def build_utilization_metrics(
    filtered: pd.DataFrame,
    station_scope: pd.DataFrame,
    selected_start: pd.Timestamp | None,
    selected_end: pd.Timestamp | None,
) -> tuple[dict[str, float], pd.DataFrame]:
    summary = {
        "busy_hours": 0.0,
        "station_count": 0.0,
        "days": 0.0,
        "capacity_hours": 0.0,
        "utilization_pct": 0.0,
    }
    columns = [
        "city",
        "busy_hours",
        "station_count",
        "capacity_hours",
        "utilization_pct",
    ]

    if selected_start is not None and selected_end is not None:
        start_date = pd.Timestamp(selected_start).normalize()
        end_date = pd.Timestamp(selected_end).normalize()
        if end_date < start_date:
            start_date, end_date = end_date, start_date
        days = float((end_date - start_date).days + 1)
    elif filtered.empty:
        return summary, pd.DataFrame(columns=columns)
    else:
        dates = _normalize_dates(filtered["started_at"])
        start_date = pd.Timestamp(dates.min()).normalize()
        end_date = pd.Timestamp(dates.max()).normalize()
        days = float((end_date - start_date).days + 1)

    busy_hours_total = (
        float(filtered["duration_sec"].sum()) / 3600.0 if "duration_sec" in filtered else 0.0
    )
    scope_station_count = (
        float(station_scope["uuid"].nunique()) if not station_scope.empty else 0.0
    )
    if scope_station_count <= 0 and not filtered.empty:
        scope_station_count = float(filtered["uuid"].nunique())
    capacity_hours = scope_station_count * 24.0 * days if days > 0 else 0.0
    utilization_pct = busy_hours_total / capacity_hours * 100.0 if capacity_hours else 0.0

    summary = {
        "busy_hours": busy_hours_total,
        "station_count": scope_station_count,
        "days": days,
        "capacity_hours": capacity_hours,
        "utilization_pct": utilization_pct,
    }

    if filtered.empty:
        return summary, pd.DataFrame(columns=columns)

    busy_city = (
        filtered.assign(city=lambda d: d["city_name"].fillna("Unknown"))
        .groupby("city", as_index=False)["duration_sec"]
        .sum()
        .rename(columns={"duration_sec": "busy_sec"})
    )
    busy_city["busy_hours"] = busy_city["busy_sec"] / 3600.0

    if station_scope.empty:
        stations_city = (
            filtered.assign(city=lambda d: d["city_name"].fillna("Unknown"))
            .groupby("city", as_index=False)["uuid"]
            .nunique()
            .rename(columns={"uuid": "station_count"})
        )
    else:
        stations_city = (
            station_scope.assign(city=lambda d: d["city_name"].fillna("Unknown"))
            .groupby("city", as_index=False)["uuid"]
            .nunique()
            .rename(columns={"uuid": "station_count"})
        )

    city = busy_city.merge(stations_city, on="city", how="left")
    city["station_count"] = city["station_count"].fillna(0.0)
    city["capacity_hours"] = city["station_count"] * 24.0 * days
    city["utilization_pct"] = city["busy_hours"] / city["capacity_hours"] * 100.0
    city["utilization_pct"] = (
        city["utilization_pct"]
        .replace([float("inf"), float("-inf")], 0.0)
        .fillna(0.0)
    )
    return (
        summary,
        city[columns].sort_values("utilization_pct", ascending=False).reset_index(drop=True),
    )


def build_idle_station_metrics(
    filtered: pd.DataFrame,
    station_scope: pd.DataFrame,
) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    summary = {
        "stations_in_scope": 0.0,
        "active_stations": 0.0,
        "idle_stations": 0.0,
        "idle_ratio_pct": 0.0,
    }
    city_columns = ["city", "stations_in_scope", "idle_stations", "idle_ratio_pct"]
    idle_columns = ["uuid", "name", "city_name", "processor", "graphic_names"]

    if station_scope.empty:
        return summary, pd.DataFrame(columns=city_columns), pd.DataFrame(columns=idle_columns)

    scope = station_scope.drop_duplicates("uuid").copy()
    scope["city_name"] = scope["city_name"].fillna("Unknown")
    active_uuids = set(filtered["uuid"].dropna().unique()) if not filtered.empty else set()
    scope["is_active"] = scope["uuid"].isin(active_uuids)
    scope["is_idle"] = ~scope["is_active"]

    stations_in_scope = float(scope["uuid"].nunique())
    active_stations = float(scope["is_active"].sum())
    idle_stations = float(scope["is_idle"].sum())
    idle_ratio = idle_stations / stations_in_scope * 100.0 if stations_in_scope else 0.0
    summary = {
        "stations_in_scope": stations_in_scope,
        "active_stations": active_stations,
        "idle_stations": idle_stations,
        "idle_ratio_pct": idle_ratio,
    }

    city_df = (
        scope.assign(city=lambda d: d["city_name"])
        .groupby("city", as_index=False)
        .agg(
            stations_in_scope=("uuid", "nunique"),
            idle_stations=("is_idle", "sum"),
        )
        .assign(
            idle_ratio_pct=lambda d: d["idle_stations"] / d["stations_in_scope"] * 100.0
        )
        .sort_values("idle_ratio_pct", ascending=False)
        .reset_index(drop=True)
    )

    idle_df = scope[scope["is_idle"]][idle_columns].reset_index(drop=True)
    return summary, city_df[city_columns], idle_df


def _concentration_for_key(filtered: pd.DataFrame, key: str) -> tuple[pd.DataFrame, float, float]:
    grouped = (
        filtered.dropna(subset=[key, "duration_sec"])
        .groupby(key, as_index=False)["duration_sec"]
        .sum()
        .sort_values("duration_sec", ascending=False)
        .reset_index(drop=True)
    )
    if grouped.empty:
        grouped["share_pct"] = pd.Series(dtype="float64")
        return grouped, 0.0, 0.0

    total = float(grouped["duration_sec"].sum())
    grouped["share_pct"] = grouped["duration_sec"] / total * 100.0 if total else 0.0
    top10_share = float(grouped.head(10)["share_pct"].sum())
    shares_fraction = grouped["share_pct"] / 100.0
    hhi = float((shares_fraction.pow(2)).sum() * 10000.0)
    return grouped, top10_share, hhi


def build_concentration_metrics(
    filtered: pd.DataFrame,
) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    summary = {
        "station_top10_share_pct": 0.0,
        "station_hhi": 0.0,
        "product_top10_share_pct": 0.0,
        "product_hhi": 0.0,
    }
    if filtered.empty:
        return summary, pd.DataFrame(), pd.DataFrame()

    station_df, station_top10, station_hhi = _concentration_for_key(filtered, "uuid")
    product_df, product_top10, product_hhi = _concentration_for_key(filtered, "product_id")
    summary = {
        "station_top10_share_pct": station_top10,
        "station_hhi": station_hhi,
        "product_top10_share_pct": product_top10,
        "product_hhi": product_hhi,
    }
    return summary, station_df, product_df


def _volatility_by_group(
    base: pd.DataFrame,
    group_col: str,
    group_label: str,
    full_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    daily = (
        base.assign(group=lambda d: d[group_col].fillna(group_label))
        .groupby(["group", "date"])["duration_sec"]
        .sum()
        .unstack(fill_value=0.0)
        .reindex(columns=full_dates, fill_value=0.0)
    )
    if daily.empty:
        return pd.DataFrame(
            columns=[
                "group",
                "total_hours",
                "mean_daily_hours",
                "std_daily_hours",
                "cv_pct",
                "active_days",
            ]
        )

    daily_hours = daily / 3600.0
    stats = pd.DataFrame(
        {
            "group": daily_hours.index,
            "total_hours": daily_hours.sum(axis=1).values,
            "mean_daily_hours": daily_hours.mean(axis=1).values,
            "std_daily_hours": daily_hours.std(axis=1, ddof=0).values,
            "active_days": (daily_hours > 0).sum(axis=1).values,
        }
    )
    stats["cv_pct"] = stats["std_daily_hours"] / stats["mean_daily_hours"] * 100.0
    stats["cv_pct"] = stats["cv_pct"].replace([float("inf"), float("-inf")], 0.0).fillna(0.0)
    return stats.sort_values("cv_pct", ascending=False).reset_index(drop=True)


def build_volatility_metrics(
    filtered: pd.DataFrame,
) -> tuple[dict[str, float], pd.DataFrame, pd.DataFrame]:
    summary = {
        "network_mean_daily_hours": 0.0,
        "network_std_daily_hours": 0.0,
        "network_cv_pct": 0.0,
    }
    empty = pd.DataFrame(
        columns=[
            "group",
            "total_hours",
            "mean_daily_hours",
            "std_daily_hours",
            "cv_pct",
            "active_days",
        ]
    )
    if filtered.empty:
        return summary, empty.copy(), empty.copy()

    base = filtered.dropna(subset=["started_at", "duration_sec", "uuid"]).copy()
    if base.empty:
        return summary, empty.copy(), empty.copy()

    base["date"] = _normalize_dates(base["started_at"])
    base = base.dropna(subset=["date"])
    if base.empty:
        return summary, empty.copy(), empty.copy()

    full_dates = pd.date_range(base["date"].min(), base["date"].max(), freq="D")
    daily_network = (
        base.groupby("date")["duration_sec"]
        .sum()
        .reindex(full_dates, fill_value=0.0)
        / 3600.0
    )
    mean_daily = float(daily_network.mean())
    std_daily = float(daily_network.std(ddof=0))
    summary = {
        "network_mean_daily_hours": mean_daily,
        "network_std_daily_hours": std_daily,
        "network_cv_pct": (std_daily / mean_daily * 100.0) if mean_daily else 0.0,
    }

    city_stats = _volatility_by_group(base, "city_name", "Unknown", full_dates)
    station_stats = _volatility_by_group(base, "uuid", "Unknown", full_dates)
    return summary, city_stats, station_stats


def build_station_retention_metrics(filtered: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "window_days",
        "previous_active_stations",
        "current_active_stations",
        "retained_stations",
        "new_stations",
        "churned_stations",
        "retention_pct",
    ]
    if filtered.empty:
        return pd.DataFrame(columns=columns)

    base = filtered.dropna(subset=["started_at", "uuid"]).copy()
    if base.empty:
        return pd.DataFrame(columns=columns)

    base["date"] = _normalize_dates(base["started_at"])
    base = base.dropna(subset=["date"])
    if base.empty:
        return pd.DataFrame(columns=columns)

    end_date = pd.Timestamp(base["date"].max()).normalize()
    rows: list[dict[str, Any]] = []
    for window_days in [7, 30]:
        current_start = end_date - pd.Timedelta(days=window_days - 1)
        previous_end = current_start - pd.Timedelta(days=1)
        previous_start = previous_end - pd.Timedelta(days=window_days - 1)

        current_set = set(
            base.loc[(base["date"] >= current_start) & (base["date"] <= end_date), "uuid"]
            .dropna()
            .unique()
        )
        previous_set = set(
            base.loc[
                (base["date"] >= previous_start) & (base["date"] <= previous_end),
                "uuid",
            ]
            .dropna()
            .unique()
        )
        retained = previous_set.intersection(current_set)
        new_set = current_set.difference(previous_set)
        churned = previous_set.difference(current_set)
        retention_pct = (
            len(retained) / len(previous_set) * 100.0 if previous_set else 0.0
        )
        rows.append(
            {
                "window_days": int(window_days),
                "previous_active_stations": int(len(previous_set)),
                "current_active_stations": int(len(current_set)),
                "retained_stations": int(len(retained)),
                "new_stations": int(len(new_set)),
                "churned_stations": int(len(churned)),
                "retention_pct": retention_pct,
            }
        )

    return pd.DataFrame(rows, columns=columns)


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
    # Hide partial windows: require full window by selected range and by actual data span.
    window_offset = pd.Timedelta(days=max(window_days - 1, 0))
    first_window_by_range = full_dates[0] + window_offset
    first_data_date = pd.Timestamp(base["date"].min()).normalize()
    first_window_by_data = first_data_date + window_offset
    visible_start = (
        first_window_by_range
        if first_window_by_range >= first_window_by_data
        else first_window_by_data
    )
    out = out[out["date"] >= visible_start].reset_index(drop=True)
    return out
