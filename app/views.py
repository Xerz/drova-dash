import inspect

import altair as alt
import pandas as pd
import plotly.express as px
import streamlit as st

from app.aggregations import (
    build_city_ranking,
    build_concentration_metrics,
    build_demand_heatmap,
    build_free_trial_impact,
    build_group_ranking,
    build_idle_station_metrics,
    build_map_data,
    build_product_adoption,
    build_product_cannibalization,
    build_product_share_wow_mom,
    build_station_retention_metrics,
    build_utilization_metrics,
    build_volatility_metrics,
)


def _patch_streamlit_width_compat() -> None:
    # Newer Streamlit uses `width=...`; older versions still expect `use_container_width=...`.
    # Keep a single code path in views and map width dynamically when needed.
    for name in ("altair_chart", "dataframe", "plotly_chart"):
        fn = getattr(st, name, None)
        if fn is None:
            continue
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            continue
        if "width" in params or "use_container_width" not in params:
            continue

        def _wrapped(*args, __fn=fn, **kwargs):
            width = kwargs.pop("width", None)
            if width is not None and "use_container_width" not in kwargs:
                if width == "stretch":
                    kwargs["use_container_width"] = True
                elif width == "content":
                    kwargs["use_container_width"] = False
            return __fn(*args, **kwargs)

        setattr(st, name, _wrapped)


_patch_streamlit_width_compat()


def render_session_range_header(filtered: pd.DataFrame) -> None:
    min_date = filtered["started_at"].min()
    max_date = filtered["ended_at"].max()
    if pd.notna(min_date) and pd.notna(max_date):
        st.markdown(f"### Информация по сессиям с {min_date:%d.%m.%Y} по {max_date:%d.%m.%Y}")
    elif pd.notna(min_date):
        st.markdown(f"### Информация по сессиям начиная с {min_date:%d.%m.%Y}")
    else:
        st.markdown("### Информация по сессиям")


def render_rolling_window_charts(
    rolling_metrics: pd.DataFrame, window_days: int
) -> None:
    st.markdown(f"### Скользящие метрики (окно {window_days} дн.)")
    if rolling_metrics.empty:
        st.info("Недостаточно данных для скользящих метрик.")
        return

    left, right = st.columns(2)
    with left:
        st.subheader("Активные станции в окне")
        active_chart = (
            alt.Chart(rolling_metrics)
            .mark_line()
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("active_stations_window:Q", title="Stations"),
                tooltip=[
                    alt.Tooltip("date:T", title="Date"),
                    alt.Tooltip(
                        "active_stations_window:Q",
                        title="Active stations",
                        format=",.0f",
                    ),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(active_chart, width="stretch")

    with right:
        st.subheader("Сыграно часов в окне")
        hours_chart = (
            alt.Chart(rolling_metrics)
            .mark_line()
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("played_hours_window:Q", title="Hours"),
                tooltip=[
                    alt.Tooltip("date:T", title="Date"),
                    alt.Tooltip(
                        "played_hours_window:Q",
                        title="Played hours",
                        format=",.2f",
                    ),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(hours_chart, width="stretch")


def render_product_share_wow_mom(filtered: pd.DataFrame, agg_prod: pd.DataFrame) -> None:
    st.markdown("### Product share (BUSY hours) + WoW/MoM")
    st.caption(
        "Доля каждого продукта в суммарных BUSY-часах за выбранный период. "
        "WoW/MoM показывают изменение доли в процентных пунктах относительно "
        "предыдущих 7/30 дней."
    )
    share_df = build_product_share_wow_mom(filtered, top_n=20)
    if share_df.empty:
        st.info("Недостаточно данных для долей продуктов.")
        return

    labels = agg_prod[["product_id", "product_label"]].drop_duplicates("product_id")
    share_df = share_df.merge(labels, on="product_id", how="left")
    share_df["product_label"] = share_df["product_label"].fillna(share_df["product_id"])

    top10 = share_df.head(10)
    chart = (
        alt.Chart(top10)
        .mark_bar()
        .encode(
            x=alt.X("share_pct:Q", title="Share, %"),
            y=alt.Y("product_label:N", sort="-x", title="Product"),
            tooltip=[
                alt.Tooltip("product_label:N", title="Product"),
                alt.Tooltip("duration_hours:Q", format=",.2f", title="BUSY hours"),
                alt.Tooltip("share_pct:Q", format=",.2f", title="Share, %"),
                alt.Tooltip("wow_delta_pp:Q", format="+,.2f", title="WoW delta, pp"),
                alt.Tooltip("mom_delta_pp:Q", format="+,.2f", title="MoM delta, pp"),
            ],
        )
        .properties(height=360)
    )
    st.altair_chart(chart, width="stretch")
    st.dataframe(
        share_df[
            [
                "product_label",
                "product_id",
                "duration_hours",
                "share_pct",
                "wow_delta_pp",
                "mom_delta_pp",
            ]
        ],
        width="stretch",
    )


def render_product_adoption(filtered: pd.DataFrame, agg_prod: pd.DataFrame) -> None:
    st.markdown("### Product adoption (new stations in 7/30d)")
    st.caption(
        "Сколько станций впервые запустили продукт за последние 7 и 30 дней, "
        "и какую долю от активной базы станций это составляет."
    )
    adoption_df = build_product_adoption(filtered, top_n=20)
    if adoption_df.empty:
        st.info("Недостаточно данных для adoption-метрик.")
        return

    labels = agg_prod[["product_id", "product_label"]].drop_duplicates("product_id")
    adoption_df = adoption_df.merge(labels, on="product_id", how="left")
    adoption_df["product_label"] = adoption_df["product_label"].fillna(adoption_df["product_id"])

    top10 = adoption_df.head(10)
    chart = (
        alt.Chart(top10)
        .mark_bar()
        .encode(
            x=alt.X("new_stations_30d:Q", title="New stations (30d)"),
            y=alt.Y("product_label:N", sort="-x", title="Product"),
            tooltip=[
                alt.Tooltip("product_label:N", title="Product"),
                alt.Tooltip("new_stations_7d:Q", title="New stations (7d)"),
                alt.Tooltip("new_stations_30d:Q", title="New stations (30d)"),
                alt.Tooltip("adoption_rate_7d_pct:Q", format=",.2f", title="Adoption rate 7d, %"),
                alt.Tooltip(
                    "adoption_rate_30d_pct:Q",
                    format=",.2f",
                    title="Adoption rate 30d, %",
                ),
            ],
        )
        .properties(height=360)
    )
    st.altair_chart(chart, width="stretch")
    st.dataframe(
        adoption_df[
            [
                "product_label",
                "product_id",
                "new_stations_7d",
                "new_stations_30d",
                "adoption_rate_7d_pct",
                "adoption_rate_30d_pct",
            ]
        ],
        width="stretch",
    )


def render_free_trial_impact(filtered: pd.DataFrame) -> None:
    st.markdown("### Free-trial impact")
    st.caption(
        "Вклад free-trial станций в общее потребление: доля BUSY-часов, абсолютные часы "
        "и изменение доли за последние 7 дней к предыдущим 7 дням."
    )
    summary, daily = build_free_trial_impact(filtered)
    if daily.empty:
        st.info("Недостаточно данных для free-trial метрик.")
        return

    k1, k2, k3 = st.columns(3)
    k1.metric("Free-trial share, %", f"{summary['free_trial_share_pct']:.2f}")
    k2.metric("Free-trial BUSY hours", f"{summary['busy_hours_free_trial']:.2f}")
    k3.metric("Free-trial share delta (7d), pp", f"{summary['free_trial_share_delta_7d_pp']:+.2f}")

    chart = (
        alt.Chart(daily)
        .mark_line()
        .encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("free_trial_share_pct:Q", title="Free-trial share, %"),
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("free_trial_hours:Q", format=",.2f", title="Free-trial hours"),
                alt.Tooltip("paid_hours:Q", format=",.2f", title="Paid hours"),
                alt.Tooltip("free_trial_share_pct:Q", format=",.2f", title="Share, %"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(chart, width="stretch")


def render_demand_heatmap(filtered: pd.DataFrame) -> None:
    st.markdown("### Demand heatmap (weekday x hour)")
    st.caption(
        "Когда наблюдается наибольший спрос: распределение BUSY-часов по дню недели и часу старта сессии."
    )
    heat = build_demand_heatmap(filtered)
    if heat.empty:
        st.info("Недостаточно данных для heatmap.")
        return

    weekday_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    chart = (
        alt.Chart(heat)
        .mark_rect()
        .encode(
            x=alt.X("hour:O", title="Hour of day"),
            y=alt.Y("weekday:N", sort=weekday_order, title="Weekday"),
            color=alt.Color("busy_hours:Q", title="BUSY hours", scale=alt.Scale(scheme="blues")),
            tooltip=[
                alt.Tooltip("weekday:N", title="Weekday"),
                alt.Tooltip("hour:O", title="Hour"),
                alt.Tooltip("busy_hours:Q", format=",.2f", title="BUSY hours"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(chart, width="stretch")


def render_product_cannibalization(filtered: pd.DataFrame, agg_prod: pd.DataFrame) -> None:
    st.markdown("### Product churn/cannibalization (7d vs previous 7d)")
    st.caption(
        "Какие продукты теряют/набирают долю за последние 7 дней относительно предыдущих 7 дней. "
        "Пары ниже — эвристическая подсказка потенциальной каннибализации."
    )
    shift, pairs = build_product_cannibalization(filtered, lookback_days=7, top_n=20)
    if shift.empty:
        st.info("Недостаточно данных для churn/cannibalization метрик.")
        return

    labels = agg_prod[["product_id", "product_label"]].drop_duplicates("product_id")
    shift = shift.merge(labels, on="product_id", how="left")
    shift["product_label"] = shift["product_label"].fillna(shift["product_id"])

    chart = (
        alt.Chart(shift)
        .mark_bar()
        .encode(
            x=alt.X("delta_pp:Q", title="Share delta, pp"),
            y=alt.Y("product_label:N", sort=alt.SortField("delta_pp", order="descending"), title="Product"),
            color=alt.condition(alt.datum.delta_pp >= 0, alt.value("#2b8a3e"), alt.value("#c92a2a")),
            tooltip=[
                alt.Tooltip("product_label:N", title="Product"),
                alt.Tooltip("previous_share_pct:Q", format=",.2f", title="Previous share, %"),
                alt.Tooltip("current_share_pct:Q", format=",.2f", title="Current share, %"),
                alt.Tooltip("delta_pp:Q", format="+,.2f", title="Delta, pp"),
            ],
        )
        .properties(height=360)
    )
    st.altair_chart(chart, width="stretch")
    st.dataframe(
        shift[
            [
                "product_label",
                "product_id",
                "previous_share_pct",
                "current_share_pct",
                "delta_pp",
            ]
        ],
        width="stretch",
    )

    if pairs.empty:
        return

    pairs = (
        pairs.merge(
            labels.rename(
                columns={"product_id": "loser_product_id", "product_label": "loser_product_label"}
            ),
            on="loser_product_id",
            how="left",
        )
        .merge(
            labels.rename(
                columns={"product_id": "gainer_product_id", "product_label": "gainer_product_label"}
            ),
            on="gainer_product_id",
            how="left",
        )
    )
    pairs["loser_product_label"] = pairs["loser_product_label"].fillna(pairs["loser_product_id"])
    pairs["gainer_product_label"] = pairs["gainer_product_label"].fillna(pairs["gainer_product_id"])
    st.caption("Potential cannibalization pairs (heuristic).")
    st.dataframe(
        pairs[
            [
                "loser_product_label",
                "loser_product_id",
                "loser_delta_pp",
                "gainer_product_label",
                "gainer_product_id",
                "gainer_delta_pp",
                "compensation_pct",
            ]
        ],
        width="stretch",
    )


def render_utilization_metrics(
    filtered: pd.DataFrame,
    station_scope: pd.DataFrame,
    selected_start: pd.Timestamp | None,
    selected_end: pd.Timestamp | None,
) -> None:
    st.markdown("### Utilization rate (network and city)")
    st.caption(
        "Загрузка инфраструктуры: BUSY hours / (stations in scope × 24 × days). "
        "Показывает, какая часть доступной ёмкости реально используется."
    )
    summary, city_df = build_utilization_metrics(
        filtered,
        station_scope=station_scope,
        selected_start=selected_start,
        selected_end=selected_end,
    )
    if summary["station_count"] <= 0:
        st.info("Недостаточно данных для utilization-метрик.")
        return

    k1, k2, k3 = st.columns(3)
    k1.metric("Network utilization, %", f"{summary['utilization_pct']:.2f}")
    k2.metric("BUSY hours", f"{summary['busy_hours']:.2f}")
    k3.metric("Stations in scope", f"{int(summary['station_count'])}")

    if city_df.empty:
        return

    top10 = city_df.head(10)
    chart = (
        alt.Chart(top10)
        .mark_bar()
        .encode(
            x=alt.X("utilization_pct:Q", title="Utilization, %"),
            y=alt.Y("city:N", sort="-x", title="City"),
            tooltip=[
                alt.Tooltip("city:N", title="City"),
                alt.Tooltip("utilization_pct:Q", format=",.2f", title="Utilization, %"),
                alt.Tooltip("busy_hours:Q", format=",.2f", title="BUSY hours"),
                alt.Tooltip("station_count:Q", format=",.0f", title="Stations"),
            ],
        )
        .properties(height=360)
    )
    st.altair_chart(chart, width="stretch")
    st.dataframe(city_df, width="stretch")


def render_idle_station_metrics(filtered: pd.DataFrame, station_scope: pd.DataFrame) -> None:
    st.markdown("### Idle station ratio")
    st.caption(
        "Доля станций без единой BUSY-сессии в выбранном периоде среди станций в текущем scope фильтров."
    )
    summary, city_df, idle_df = build_idle_station_metrics(filtered, station_scope)
    if summary["stations_in_scope"] <= 0:
        st.info("Недостаточно данных для idle station ratio.")
        return

    k1, k2, k3 = st.columns(3)
    k1.metric("Idle ratio, %", f"{summary['idle_ratio_pct']:.2f}")
    k2.metric("Idle stations", f"{int(summary['idle_stations'])}")
    k3.metric("Stations in scope", f"{int(summary['stations_in_scope'])}")

    if not city_df.empty:
        top10 = city_df.head(10)
        chart = (
            alt.Chart(top10)
            .mark_bar()
            .encode(
                x=alt.X("idle_ratio_pct:Q", title="Idle ratio, %"),
                y=alt.Y("city:N", sort="-x", title="City"),
                tooltip=[
                    alt.Tooltip("city:N", title="City"),
                    alt.Tooltip("stations_in_scope:Q", title="Stations"),
                    alt.Tooltip("idle_stations:Q", title="Idle"),
                    alt.Tooltip("idle_ratio_pct:Q", format=",.2f", title="Idle ratio, %"),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(chart, width="stretch")

    if not idle_df.empty:
        st.dataframe(idle_df, width="stretch")


def render_concentration_metrics(
    filtered: pd.DataFrame,
    agg_uuid: pd.DataFrame,
    agg_prod: pd.DataFrame,
) -> None:
    st.markdown("### Risk concentration (top-10 share and HHI)")
    st.caption(
        "Концентрация риска: какая доля BUSY-часов сосредоточена у top-10 станций/продуктов и "
        "насколько распределение монополизировано (HHI)."
    )
    summary, station_df, product_df = build_concentration_metrics(filtered)
    if station_df.empty and product_df.empty:
        st.info("Недостаточно данных для concentration-метрик.")
        return

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Stations top-10 share, %", f"{summary['station_top10_share_pct']:.2f}")
    k2.metric("Stations HHI", f"{summary['station_hhi']:.0f}")
    k3.metric("Products top-10 share, %", f"{summary['product_top10_share_pct']:.2f}")
    k4.metric("Products HHI", f"{summary['product_hhi']:.0f}")

    left, right = st.columns(2)
    with left:
        if not station_df.empty:
            station_labels = agg_uuid[["uuid", "uuid_label"]].drop_duplicates("uuid")
            station_top = station_df.head(10).merge(station_labels, on="uuid", how="left")
            station_top["uuid_label"] = station_top["uuid_label"].fillna(station_top["uuid"])
            station_chart = (
                alt.Chart(station_top)
                .mark_bar()
                .encode(
                    x=alt.X("share_pct:Q", title="Share, %"),
                    y=alt.Y("uuid_label:N", sort="-x", title="Station"),
                    tooltip=[
                        alt.Tooltip("uuid_label:N", title="Station"),
                        alt.Tooltip("share_pct:Q", format=",.2f", title="Share, %"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(station_chart, width="stretch")
    with right:
        if not product_df.empty:
            product_labels = agg_prod[["product_id", "product_label"]].drop_duplicates("product_id")
            product_top = product_df.head(10).merge(product_labels, on="product_id", how="left")
            product_top["product_label"] = product_top["product_label"].fillna(product_top["product_id"])
            product_chart = (
                alt.Chart(product_top)
                .mark_bar()
                .encode(
                    x=alt.X("share_pct:Q", title="Share, %"),
                    y=alt.Y("product_label:N", sort="-x", title="Product"),
                    tooltip=[
                        alt.Tooltip("product_label:N", title="Product"),
                        alt.Tooltip("share_pct:Q", format=",.2f", title="Share, %"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(product_chart, width="stretch")


def render_volatility_metrics(filtered: pd.DataFrame, agg_uuid: pd.DataFrame) -> None:
    st.markdown("### Volatility index (daily BUSY-hours instability)")
    st.caption(
        "Стабильность спроса: сравниваем средние дневные часы и разброс (std/CV). "
        "Чем выше CV, тем менее предсказуемо потребление."
    )
    summary, city_stats, station_stats = build_volatility_metrics(filtered)
    if city_stats.empty and station_stats.empty:
        st.info("Недостаточно данных для volatility-метрик.")
        return

    k1, k2, k3 = st.columns(3)
    k1.metric("Network CV, %", f"{summary['network_cv_pct']:.2f}")
    k2.metric("Mean daily hours", f"{summary['network_mean_daily_hours']:.2f}")
    k3.metric("Std daily hours", f"{summary['network_std_daily_hours']:.2f}")

    left, right = st.columns(2)
    with left:
        if not city_stats.empty:
            city_top = city_stats.head(10).copy()
            city_chart = (
                alt.Chart(city_top)
                .mark_bar()
                .encode(
                    x=alt.X("cv_pct:Q", title="CV, %"),
                    y=alt.Y("group:N", sort="-x", title="City"),
                    tooltip=[
                        alt.Tooltip("group:N", title="City"),
                        alt.Tooltip("total_hours:Q", format=",.2f", title="Total hours"),
                        alt.Tooltip("mean_daily_hours:Q", format=",.2f", title="Mean daily"),
                        alt.Tooltip("std_daily_hours:Q", format=",.2f", title="Std daily"),
                        alt.Tooltip("cv_pct:Q", format=",.2f", title="CV, %"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(city_chart, width="stretch")
            st.dataframe(city_stats.head(20), width="stretch")

    with right:
        if not station_stats.empty:
            station_labels = agg_uuid[["uuid", "uuid_label"]].drop_duplicates("uuid")
            station_top = (
                station_stats.head(10)
                .merge(station_labels, left_on="group", right_on="uuid", how="left")
                .assign(station_label=lambda d: d["uuid_label"].fillna(d["group"]))
            )
            station_chart = (
                alt.Chart(station_top)
                .mark_bar()
                .encode(
                    x=alt.X("cv_pct:Q", title="CV, %"),
                    y=alt.Y("station_label:N", sort="-x", title="Station"),
                    tooltip=[
                        alt.Tooltip("station_label:N", title="Station"),
                        alt.Tooltip("total_hours:Q", format=",.2f", title="Total hours"),
                        alt.Tooltip("mean_daily_hours:Q", format=",.2f", title="Mean daily"),
                        alt.Tooltip("std_daily_hours:Q", format=",.2f", title="Std daily"),
                        alt.Tooltip("cv_pct:Q", format=",.2f", title="CV, %"),
                    ],
                )
                .properties(height=320)
            )
            st.altair_chart(station_chart, width="stretch")
            st.dataframe(station_stats.head(20), width="stretch")


def render_station_retention_metrics(filtered: pd.DataFrame) -> None:
    st.markdown("### Station retention")
    st.caption(
        "Удержание активных станций: какая доля станций из предыдущего окна осталась активной "
        "в текущем окне (7 и 30 дней), плюс новые и ушедшие станции."
    )
    retention_df = build_station_retention_metrics(filtered)
    if retention_df.empty:
        st.info("Недостаточно данных для retention-метрик.")
        return

    row_7d = retention_df[retention_df["window_days"] == 7]
    row_30d = retention_df[retention_df["window_days"] == 30]

    k1, k2, k3 = st.columns(3)
    if not row_7d.empty:
        k1.metric("Retention 7d, %", f"{float(row_7d.iloc[0]['retention_pct']):.2f}")
    if not row_30d.empty:
        k2.metric("Retention 30d, %", f"{float(row_30d.iloc[0]['retention_pct']):.2f}")
    if not row_7d.empty:
        k3.metric("Retained stations (7d)", f"{int(row_7d.iloc[0]['retained_stations'])}")

    chart = (
        alt.Chart(retention_df)
        .mark_bar()
        .encode(
            x=alt.X("window_days:O", title="Window, days"),
            y=alt.Y("retention_pct:Q", title="Retention, %"),
            tooltip=[
                alt.Tooltip("window_days:Q", title="Window, days"),
                alt.Tooltip("previous_active_stations:Q", format=",.0f", title="Previous active"),
                alt.Tooltip("current_active_stations:Q", format=",.0f", title="Current active"),
                alt.Tooltip("retained_stations:Q", format=",.0f", title="Retained"),
                alt.Tooltip("new_stations:Q", format=",.0f", title="New"),
                alt.Tooltip("churned_stations:Q", format=",.0f", title="Churned"),
                alt.Tooltip("retention_pct:Q", format=",.2f", title="Retention, %"),
            ],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch")
    st.dataframe(retention_df, width="stretch")


def render_strategic_metrics(
    filtered: pd.DataFrame,
    agg_uuid: pd.DataFrame,
    agg_prod: pd.DataFrame,
    station_scope: pd.DataFrame,
    selected_start: pd.Timestamp | None,
    selected_end: pd.Timestamp | None,
) -> None:
    render_product_share_wow_mom(filtered, agg_prod)
    render_product_adoption(filtered, agg_prod)
    render_free_trial_impact(filtered)
    render_demand_heatmap(filtered)
    render_product_cannibalization(filtered, agg_prod)
    render_utilization_metrics(filtered, station_scope, selected_start, selected_end)
    render_idle_station_metrics(filtered, station_scope)
    render_concentration_metrics(filtered, agg_uuid, agg_prod)
    render_volatility_metrics(filtered, agg_uuid)
    render_station_retention_metrics(filtered)


def render_station_product_rankings(agg_uuid: pd.DataFrame, agg_prod: pd.DataFrame) -> None:
    st.markdown("### 📈 Rankings by total BUSY duration (filtered)")
    agg_uuid_top20 = agg_uuid.head(20).copy()
    agg_prod_top20 = agg_prod.head(20).copy()

    left, right = st.columns(2)
    with left:
        st.subheader("By station (top-20)")
        if not agg_uuid_top20.empty:
            chart_uuid = (
                alt.Chart(agg_uuid_top20)
                .mark_bar()
                .encode(
                    x=alt.X("duration_hours:Q", title="Total BUSY hours"),
                    y=alt.Y("uuid_label:N", sort="-x", title="Station"),
                    tooltip=[
                        alt.Tooltip("uuid_label:N", title="Station"),
                        alt.Tooltip("uuid:N", title="uuid"),
                        alt.Tooltip("duration_hours:Q", format=",.2f", title="Total (h)"),
                        alt.Tooltip("duration_sec:Q", format=",.0f", title="Total (sec)"),
                        alt.Tooltip("session_mean_hours:Q", format=",.2f", title="Avg session (h)"),
                        alt.Tooltip("session_p25_hours:Q", format=",.2f", title="P25 session (h)"),
                        alt.Tooltip("session_p75_hours:Q", format=",.2f", title="P75 session (h)"),
                        alt.Tooltip("session_mean_sec:Q", format=",.0f", title="Avg session (sec)"),
                        alt.Tooltip("session_p25_sec:Q", format=",.0f", title="P25 session (sec)"),
                        alt.Tooltip("session_p75_sec:Q", format=",.0f", title="P75 session (sec)"),
                    ],
                )
                .properties(height=800)
            )
            st.altair_chart(chart_uuid, width="stretch")
        else:
            st.info("No data after filters.")

    with right:
        st.subheader("By product (top-20)")
        if not agg_prod_top20.empty:
            chart_prod = (
                alt.Chart(agg_prod_top20)
                .mark_bar()
                .encode(
                    x=alt.X("duration_hours:Q", title="Total BUSY hours"),
                    y=alt.Y("product_label:N", sort="-x", title="Product"),
                    tooltip=[
                        alt.Tooltip("product_label:N", title="Product"),
                        alt.Tooltip("product_id:N", title="product_id"),
                        alt.Tooltip("duration_hours:Q", format=",.2f", title="Total (h)"),
                        alt.Tooltip("duration_sec:Q", format=",.0f", title="Total (sec)"),
                        alt.Tooltip("session_mean_hours:Q", format=",.2f", title="Avg session (h)"),
                        alt.Tooltip("session_p25_hours:Q", format=",.2f", title="P25 session (h)"),
                        alt.Tooltip("session_p75_hours:Q", format=",.2f", title="P75 session (h)"),
                        alt.Tooltip("session_mean_sec:Q", format=",.0f", title="Avg session (sec)"),
                        alt.Tooltip("session_p25_sec:Q", format=",.0f", title="P25 session (sec)"),
                        alt.Tooltip("session_p75_sec:Q", format=",.0f", title="P75 session (sec)"),
                    ],
                )
                .properties(height=800)
            )
            st.altair_chart(chart_prod, width="stretch")
        else:
            st.info("No data after filters.")

    st.subheader("Полный рейтинг по станциям")
    st.dataframe(
        agg_uuid.assign(
            Station=agg_uuid["uuid_label"],
            City=agg_uuid["city_name"],
            Product_number=agg_uuid["product_number"],
            Processor=agg_uuid["processor"],
            Graphic_card=agg_uuid["graphic_names"],
            Free_trial_enabled=agg_uuid["free_trial"],
            RAM_bytes=agg_uuid["ram_bytes"],
            Graphic_RAM_bytes=agg_uuid["graphic_ram_bytes"],
            Longitude=agg_uuid["longitude"],
            Latitude=agg_uuid["latitude"],
        )[
            [
                "Station",
                "uuid",
                "duration_hours",
                "duration_sec",
                "session_mean_hours",
                "session_p25_hours",
                "session_p75_hours",
                "City",
                "Product_number",
                "Processor",
                "Graphic_card",
                "Free_trial_enabled",
                "RAM_bytes",
                "Graphic_RAM_bytes",
                "Longitude",
                "Latitude",
            ]
        ],
        width="stretch",
    )

    st.subheader("Полный рейтинг по продуктам")
    st.dataframe(
        agg_prod.assign(Product=agg_prod["product_label"])[
            [
                "Product",
                "product_id",
                "duration_hours",
                "duration_sec",
                "session_mean_hours",
                "session_p25_hours",
                "session_p75_hours",
            ]
        ],
        width="stretch",
    )


def render_product_treemap(agg_prod: pd.DataFrame) -> None:
    if agg_prod.empty:
        return
    fig = px.treemap(
        agg_prod,
        path=["product_label"],
        values="duration_hours",
        color="duration_hours",
        color_continuous_scale="Blues",
        title="Treemap по BUSY часам (Products)",
    )
    st.plotly_chart(fig, width="stretch")


def render_city_rankings(agg_city: pd.DataFrame) -> None:
    agg_city_top20 = agg_city.head(20).copy()

    st.subheader("By city (top-20 по BUSY часам)")
    if not agg_city_top20.empty:
        chart_city = (
            alt.Chart(agg_city_top20)
            .mark_bar()
            .encode(
                x=alt.X("duration_hours:Q", title="Total BUSY hours"),
                y=alt.Y("city:N", sort="-x", title="City"),
                tooltip=[
                    alt.Tooltip("city:N", title="City"),
                    alt.Tooltip("duration_hours:Q", format=",.2f", title="hours"),
                    alt.Tooltip("duration_sec:Q", format=",.0f", title="seconds"),
                    alt.Tooltip("n_stations:Q", title="stations"),
                    alt.Tooltip("hours_per_station:Q", format=",.2f", title="h per station"),
                ],
            )
            .properties(height=800)
        )
        st.altair_chart(chart_city, width="stretch")
    else:
        st.info("No data after filters.")

    st.subheader("Полный рейтинг по городам")
    st.dataframe(
        agg_city[["city", "duration_hours", "duration_sec", "n_stations", "hours_per_station"]],
        width="stretch",
    )

    csv_city = agg_city.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Download city ranking (CSV)",
        data=csv_city,
        file_name="ranking_by_city.csv",
        mime="text/csv",
    )

    if not agg_city.empty:
        fig_city = px.treemap(
            agg_city.rename(columns={"city": "City"}),
            path=["City"],
            values="duration_hours",
            color="duration_hours",
            color_continuous_scale="Blues",
            title="Treemap по BUSY часам (Cities)",
        )
        st.plotly_chart(fig_city, width="stretch")

    agg_city_mps_top20 = (
        agg_city.sort_values("hours_per_station", ascending=False).head(20).copy()
    )
    st.subheader("By city: часов на одну станцию (top-20)")
    if not agg_city_mps_top20.empty:
        chart_city_mps = (
            alt.Chart(agg_city_mps_top20)
            .mark_bar()
            .encode(
                x=alt.X("hours_per_station:Q", title="Hours per station"),
                y=alt.Y("city:N", sort="-x", title="City"),
                tooltip=[
                    alt.Tooltip("city:N", title="City"),
                    alt.Tooltip("n_stations:Q", title="stations"),
                    alt.Tooltip("hours_per_station:Q", format=",.2f", title="h per station"),
                    alt.Tooltip("duration_hours:Q", format=",.2f", title="total hours"),
                ],
            )
            .properties(height=800)
        )
        st.altair_chart(chart_city_mps, width="stretch")
    else:
        st.info("No data after filters (minutes per station).")

    st.subheader("Полный рейтинг по городам (часов на одну станцию)")
    st.dataframe(
        agg_city.sort_values("hours_per_station", ascending=False)[
            ["city", "n_stations", "hours_per_station", "duration_hours", "duration_sec"]
        ],
        width="stretch",
    )


def render_group_rank(agg: pd.DataFrame, label: str) -> None:
    top20 = agg.head(20)
    st.subheader(f"By {label} (top-20 по BUSY часам)")
    if not top20.empty:
        chart = (
            alt.Chart(top20)
            .mark_bar()
            .encode(
                x=alt.X("duration_hours:Q", title="Total BUSY hours"),
                y=alt.Y("group:N", sort="-x", title=label),
                tooltip=[
                    alt.Tooltip("group:N", title=label),
                    alt.Tooltip("duration_hours:Q", format=",.2f", title="hours"),
                    alt.Tooltip("duration_sec:Q", format=",.0f", title="seconds"),
                    alt.Tooltip("n_stations:Q", title="stations"),
                    alt.Tooltip("hours_per_station:Q", format=",.2f", title="h per station"),
                ],
            )
            .properties(height=800)
        )
        st.altair_chart(chart, width="stretch")
    else:
        st.info("No data after filters.")

    st.subheader(f"Полный рейтинг по {label}")
    st.dataframe(
        agg[["group", "duration_hours", "duration_sec", "n_stations", "hours_per_station"]],
        width="stretch",
    )

    per_station_top20 = (
        agg.sort_values("hours_per_station", ascending=False).head(20).copy()
    )
    st.subheader(f"By {label}: часов на одну станцию (top-20)")
    if not per_station_top20.empty:
        chart_mps = (
            alt.Chart(per_station_top20)
            .mark_bar()
            .encode(
                x=alt.X("hours_per_station:Q", title="Hours per station"),
                y=alt.Y("group:N", sort="-x", title=label),
                tooltip=[
                    alt.Tooltip("group:N", title=label),
                    alt.Tooltip("n_stations:Q", title="stations"),
                    alt.Tooltip("hours_per_station:Q", format=",.2f", title="h per station"),
                    alt.Tooltip("duration_hours:Q", format=",.2f", title="total hours"),
                ],
            )
            .properties(height=800)
        )
        st.altair_chart(chart_mps, width="stretch")
    else:
        st.info("No data after filters (minutes per station).")

    st.subheader(f"Полный рейтинг по {label} (часов на одну станцию)")
    st.dataframe(
        agg.sort_values("hours_per_station", ascending=False)[
            ["group", "n_stations", "hours_per_station", "duration_hours", "duration_sec"]
        ],
        width="stretch",
    )


def render_minutes_map(map_data: pd.DataFrame) -> None:
    st.subheader("Minutes played heatmap")
    st.caption(
        "Непрерывная тепловая карта BUSY-активности по географии. "
        "Для лучшего контраста интенсивность ограничена на уровне P95."
    )
    if not map_data.empty:
        heat_data = map_data.copy()
        p95 = float(heat_data["duration_minutes"].quantile(0.95))
        if not pd.notna(p95) or p95 <= 0:
            p95 = float(heat_data["duration_minutes"].max())
        if p95 <= 0:
            st.info("Недостаточно данных для тепловой карты.")
            return

        heat_data["intensity_minutes"] = heat_data["duration_minutes"].clip(upper=p95)
        center = {
            "lat": float(heat_data["latitude"].mean()),
            "lon": float(heat_data["longitude"].mean()),
        }
        fig_map = px.density_mapbox(
            heat_data,
            lat="latitude",
            lon="longitude",
            z="intensity_minutes",
            radius=30,
            center=center,
            zoom=2,
            mapbox_style="open-street-map",
            color_continuous_scale="YlOrRd",
            hover_data={
                "duration_minutes": ":.2f",
                "intensity_minutes": ":.2f",
            },
            title="BUSY minutes heatmap (continuous)",
        )
        fig_map.update_layout(
            coloraxis_colorbar=dict(title="Minutes"),
            margin=dict(l=0, r=0, t=48, b=0),
        )
        st.plotly_chart(fig_map, width="stretch")
    else:
        st.info("Нет координат для отображения на карте.")


def render_extended_analytics(filtered: pd.DataFrame, agg_prod: pd.DataFrame) -> None:
    if agg_prod.empty:
        return

    agg_city = build_city_ranking(filtered)
    render_city_rankings(agg_city)

    processor_rank = build_group_ranking(filtered, "processor")
    graphics_rank = build_group_ranking(filtered, "graphic_names")
    render_group_rank(processor_rank, "processor")
    render_group_rank(graphics_rank, "graphic card")

    map_data = build_map_data(filtered)
    render_minutes_map(map_data)
