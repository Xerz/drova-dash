from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st


@dataclass(frozen=True)
class TimeControls:
    threshold_hours: int
    selected_start: pd.Timestamp
    selected_end: pd.Timestamp
    rolling_window_days: int


@dataclass(frozen=True)
class SidebarFilters:
    enable_uuid: bool
    enable_prod: bool
    enable_city: bool
    enable_processor: bool
    enable_graphic: bool
    selected_uuids: list[Any]
    selected_products: list[Any]
    selected_cities: list[Any]
    selected_processors: list[Any]
    selected_graphics: list[Any]
    free_trial_only: bool
    product_number_range: tuple[int, int] | None
    ram_range: tuple[int, int] | None
    graphic_ram_range: tuple[int, int] | None


def ensure_legacy_session_state() -> None:
    # Legacy keys kept for backward-compatible session behavior.
    if "filters_enabled_station" not in st.session_state:
        st.session_state.filters_enabled_station = False
    if "filters_enabled_product" not in st.session_state:
        st.session_state.filters_enabled_product = False
    if "selected_uuids" not in st.session_state:
        st.session_state.selected_uuids = None
    if "selected_products" not in st.session_state:
        st.session_state.selected_products = None


def render_time_controls() -> TimeControls:
    st.sidebar.header("Controls")

    threshold_hours = st.sidebar.slider(
        "Max session length (hours)",
        min_value=4,
        max_value=30,
        value=30,
        step=1,
        help="Сессии длиннее значения будут отфильтрованы",
    )

    default_end = pd.Timestamp(datetime.today()).normalize()
    default_start = default_end - timedelta(days=30)
    selected_dates = st.sidebar.date_input(
        "Date range",
        value=(default_start.date(), default_end.date()),
        key="busy_date_range",
    )

    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
    else:
        start_date = end_date = selected_dates

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    date_range_days = max((end_date - start_date).days + 1, 1)
    max_window_days = 90
    rolling_window_days = st.sidebar.slider(
        "Sliding window (days)",
        min_value=1,
        max_value=max_window_days,
        value=min(7, date_range_days, max_window_days),
        step=1,
        help="Окно для скользящих метрик по датам",
    )

    selected_start = pd.Timestamp(start_date).normalize()
    selected_end = (
        pd.Timestamp(end_date).normalize()
        + pd.Timedelta(days=1)
        - pd.Timedelta(microseconds=1)
    )

    return TimeControls(
        threshold_hours=threshold_hours,
        selected_start=selected_start,
        selected_end=selected_end,
        rolling_window_days=rolling_window_days,
    )


def apply_time_filters(df: pd.DataFrame, controls: TimeControls) -> pd.DataFrame:
    max_seconds = controls.threshold_hours * 3600
    filtered = df[
        (df["duration_sec"].isna()) | (df["duration_sec"] <= max_seconds)
    ].copy()

    date_mask = (
        (filtered["started_at"] <= controls.selected_end)
        & (
            filtered["ended_at"].fillna(controls.selected_end)
            >= controls.selected_start
        )
    )
    return filtered[date_mask].copy()


def render_sidebar_filters(
    intervals_with_duration: pd.DataFrame,
    uuid_to_name: dict[Any, Any],
    pid_to_title: dict[Any, Any],
) -> SidebarFilters:
    st.sidebar.markdown("---")
    st.sidebar.header("Filters")

    all_uuids = sorted(intervals_with_duration["uuid"].dropna().unique().tolist())
    all_products = sorted(
        intervals_with_duration["product_id"].dropna().unique().tolist()
    )
    all_cities = sorted(
        intervals_with_duration["city_name"].dropna().unique().tolist()
    )
    all_processors = sorted(
        intervals_with_duration["processor"].dropna().unique().tolist()
    )
    all_graphics = sorted(
        intervals_with_duration["graphic_names"].dropna().unique().tolist()
    )

    def _fmt_uuid(u: Any) -> Any:
        name = uuid_to_name.get(u, u)
        return f"{name} ({u})" if name != u else u

    def _fmt_prod(p: Any) -> Any:
        title = pid_to_title.get(p, p)
        return f"{title} ({p})" if title != p else p

    ss = st.session_state

    if "enable_uuid" not in ss:
        ss.enable_uuid = False
    if "enable_prod" not in ss:
        ss.enable_prod = False
    if "enable_city" not in ss:
        ss.enable_city = False
    if "enable_processor" not in ss:
        ss.enable_processor = False
    if "enable_graphic" not in ss:
        ss.enable_graphic = False
    if "uuid_sel" not in ss:
        ss.uuid_sel = []
    if "prod_sel" not in ss:
        ss.prod_sel = []
    if "city_sel" not in ss:
        ss.city_sel = []
    if "processor_sel" not in ss:
        ss.processor_sel = []
    if "graphic_sel" not in ss:
        ss.graphic_sel = []

    ss.uuid_sel = [u for u in ss.uuid_sel if u in all_uuids]
    ss.prod_sel = [p for p in ss.prod_sel if p in all_products]
    ss.city_sel = [c for c in ss.city_sel if c in all_cities]
    ss.processor_sel = [p for p in ss.processor_sel if p in all_processors]
    ss.graphic_sel = [g for g in ss.graphic_sel if g in all_graphics]

    st.sidebar.checkbox("Filter by station", key="enable_uuid")
    if ss.enable_uuid:
        st.sidebar.multiselect(
            "Station",
            options=all_uuids,
            key="uuid_sel",
            format_func=_fmt_uuid,
        )

    st.sidebar.checkbox("Filter by product", key="enable_prod")
    if ss.enable_prod:
        st.sidebar.multiselect(
            "Product",
            options=all_products,
            key="prod_sel",
            format_func=_fmt_prod,
        )

    st.sidebar.checkbox("Filter by city", key="enable_city")
    if ss.enable_city:
        st.sidebar.multiselect(
            "City",
            options=all_cities,
            key="city_sel",
            help="Выбери один или несколько городов. Пусто — ничего не показывать.",
        )

    st.sidebar.checkbox("Filter by processor", key="enable_processor")
    if ss.enable_processor:
        st.sidebar.multiselect(
            "Processor",
            options=all_processors,
            key="processor_sel",
            help="Фильтр по названию CPU",
        )

    st.sidebar.checkbox("Filter by graphic card", key="enable_graphic")
    if ss.enable_graphic:
        st.sidebar.multiselect(
            "Graphic names",
            options=all_graphics,
            key="graphic_sel",
            help="Фильтр по GPU",
        )

    free_trial_only = st.sidebar.checkbox("Только Free trial станции")

    def _range_slider(
        df: pd.DataFrame,
        column: str,
        label: str,
        step: int = 1,
    ) -> tuple[int, int] | None:
        col_data = df[column].dropna()
        if col_data.empty:
            st.sidebar.info(f"Нет данных для {label}")
            return None
        min_val = int(col_data.min())
        max_val = int(col_data.max())
        return st.sidebar.slider(
            label,
            min_value=min_val,
            max_value=max_val,
            value=(min_val, max_val),
            step=max(step, 1),
        )

    product_number_range = _range_slider(
        intervals_with_duration,
        "product_number",
        "Количество продуктов (диапазон)",
    )
    ram_range = _range_slider(
        intervals_with_duration,
        "ram_bytes",
        "RAM bytes (диапазон)",
    )
    graphic_ram_range = _range_slider(
        intervals_with_duration,
        "graphic_ram_bytes",
        "Graphic RAM bytes (диапазон)",
    )

    selected_uuids = ss.uuid_sel if ss.enable_uuid else all_uuids
    selected_products = ss.prod_sel if ss.enable_prod else all_products
    selected_cities = ss.city_sel if ss.enable_city else all_cities
    selected_processors = ss.processor_sel if ss.enable_processor else all_processors
    selected_graphics = ss.graphic_sel if ss.enable_graphic else all_graphics

    return SidebarFilters(
        enable_uuid=ss.enable_uuid,
        enable_prod=ss.enable_prod,
        enable_city=ss.enable_city,
        enable_processor=ss.enable_processor,
        enable_graphic=ss.enable_graphic,
        selected_uuids=selected_uuids,
        selected_products=selected_products,
        selected_cities=selected_cities,
        selected_processors=selected_processors,
        selected_graphics=selected_graphics,
        free_trial_only=free_trial_only,
        product_number_range=product_number_range,
        ram_range=ram_range,
        graphic_ram_range=graphic_ram_range,
    )


def apply_sidebar_filters(
    intervals_with_duration: pd.DataFrame,
    filters: SidebarFilters,
) -> pd.DataFrame:
    mask = intervals_with_duration["duration_sec"].notna()
    if filters.enable_uuid:
        mask &= intervals_with_duration["uuid"].isin(filters.selected_uuids)
    if filters.enable_prod:
        mask &= intervals_with_duration["product_id"].isin(filters.selected_products)
    if filters.enable_city:
        mask &= intervals_with_duration["city_name"].isin(filters.selected_cities)
    if filters.enable_processor:
        mask &= intervals_with_duration["processor"].isin(filters.selected_processors)
    if filters.enable_graphic:
        mask &= intervals_with_duration["graphic_names"].isin(filters.selected_graphics)
    filtered = intervals_with_duration[mask].copy()

    if filters.free_trial_only:
        filtered = filtered[filtered["free_trial"] == 1]

    if filters.product_number_range:
        filtered = filtered[
            filtered["product_number"].between(
                filters.product_number_range[0], filters.product_number_range[1]
            )
        ]
    if filters.ram_range:
        filtered = filtered[
            filtered["ram_bytes"].between(filters.ram_range[0], filters.ram_range[1])
        ]
    if filters.graphic_ram_range:
        filtered = filtered[
            filtered["graphic_ram_bytes"].between(
                filters.graphic_ram_range[0], filters.graphic_ram_range[1]
            )
        ]

    return filtered


def apply_station_scope_filters(
    server_info_df: pd.DataFrame,
    filters: SidebarFilters,
) -> pd.DataFrame:
    if server_info_df.empty:
        return server_info_df.copy()

    scope = server_info_df.copy()
    scope["city_name"] = scope["city_name"].fillna("Unknown")
    scope["processor"] = scope["processor"].fillna("Unknown")
    scope["graphic_names"] = scope["graphic_names"].fillna("Unknown")
    scope["free_trial"] = pd.to_numeric(scope["free_trial"], errors="coerce").fillna(0)

    if filters.enable_uuid:
        scope = scope[scope["uuid"].isin(filters.selected_uuids)]
    if filters.enable_city:
        scope = scope[scope["city_name"].isin(filters.selected_cities)]
    if filters.enable_processor:
        scope = scope[scope["processor"].isin(filters.selected_processors)]
    if filters.enable_graphic:
        scope = scope[scope["graphic_names"].isin(filters.selected_graphics)]

    if filters.enable_prod and "product_id" in scope.columns:
        scope = scope[scope["product_id"].isin(filters.selected_products)]

    if filters.free_trial_only:
        scope = scope[scope["free_trial"] == 1]

    if filters.product_number_range:
        scope = scope[
            scope["product_number"].between(
                filters.product_number_range[0], filters.product_number_range[1]
            )
        ]
    if filters.ram_range:
        scope = scope[
            scope["ram_bytes"].between(filters.ram_range[0], filters.ram_range[1])
        ]
    if filters.graphic_ram_range:
        scope = scope[
            scope["graphic_ram_bytes"].between(
                filters.graphic_ram_range[0], filters.graphic_ram_range[1]
            )
        ]

    return scope.drop_duplicates("uuid").reset_index(drop=True)
