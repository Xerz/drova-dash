import io
import os
import sqlite3
from datetime import datetime, timedelta
import tempfile
import requests
import pandas as pd
import streamlit as st
import altair as alt
import plotly.express as px

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(page_title="Station Changes Dashboard", layout="wide")
# st.title("📊 Station Changes → BUSY Intervals")

DB_PATH = "stations20251221.db"
STATIONS_URL = "https://services.drova.io/server-manager/servers/public/web"
PRODUCTS_URL = "https://services.drova.io/product-manager/product/listfull2"


# -----------------------------
# Cached helpers
# -----------------------------
@st.cache_data(show_spinner=False, ttl=600)
def fetch_stations_dict(limit=1000, offset=0):
    """Возвращает мапы uuid->name и uuid->city_name из таблицы server_info."""

    try:
        server_info = fetch_server_info(DB_PATH)
        uuid_to_name = dict(zip(server_info["uuid"], server_info["name"]))
        uuid_to_city = dict(zip(server_info["uuid"], server_info["city_name"]))
        return uuid_to_name, uuid_to_city
    except Exception as e:
        st.warning(f"Не удалось получить список станций: {e}")
        return {}, {}



@st.cache_data(show_spinner=False, ttl=600)
def fetch_product_titles():
    try:
        r = requests.get(PRODUCTS_URL, timeout=15)
        r.raise_for_status()
        data = r.json()
        return {item.get("productId"): item.get("title") for item in data if isinstance(item, dict)}
    except Exception as e:
        st.warning(f"Не удалось получить список продуктов: {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=600)
def fetch_server_info(db_path: str) -> pd.DataFrame:
    """Загружает таблицу server_info из SQLite."""

    try:
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(
                """
                SELECT
                    uuid,
                    name,
                    city_name,
                    processor,
                    graphic_names,
                    free_trial,
                    product_number,
                    ram_bytes,
                    graphic_ram_bytes,
                    longitude,
                    latitude
                FROM server_info
                """,
                conn,
            )
        return df
    except Exception as e:
        st.warning(f"Не удалось загрузить server_info: {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def load_station_changes(path: str) -> pd.DataFrame:
    with sqlite3.connect(path) as conn:
        df = pd.read_sql_query(
            "SELECT id, uuid, old_state, new_state, old_product_id, new_product_id, changed_at FROM station_changes",
            conn
        )
    return df


@st.cache_data(show_spinner=False)
def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "changed_at" in df.columns:
        df["changed_at"] = pd.to_datetime(df["changed_at"], errors="coerce")
    # Drop rows with any NA (per requirement #2)
    df = df.dropna(how="any").reset_index(drop=True)
    # Sort chronologically within each uuid, then by id for stability
    df = df.sort_values(["uuid", "changed_at", "id"]).reset_index(drop=True)
    return df


@st.cache_data(show_spinner=False)
def build_busy_intervals(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for uuid, g in df.groupby("uuid", sort=False):
        current_product = None
        start_ts = None
        for _, row in g.iterrows():
            new_state = str(row["new_state"]).upper()
            new_prod = row["new_product_id"]
            ts = row["changed_at"]

            if current_product is None:
                # looking for a BUSY start
                if new_state == "BUSY" and pd.notna(new_prod):
                    current_product = new_prod
                    start_ts = ts
                # else remain idle until a BUSY appears
            else:
                # currently in BUSY
                if new_state == "BUSY":
                    if new_prod != current_product:
                        # product changed while BUSY -> close and reopen
                        records.append({
                            "uuid": uuid,
                            "product_id": current_product,
                            "started_at": start_ts,
                            "ended_at": ts,
                        })
                        current_product = new_prod
                        start_ts = ts
                else:
                    # leaving BUSY -> close interval
                    records.append({
                        "uuid": uuid,
                        "product_id": current_product,
                        "started_at": start_ts,
                        "ended_at": ts,
                    })
                    current_product = None
                    start_ts = None
        # if BUSY at end, leave open interval
        if current_product is not None:
            records.append({
                "uuid": uuid,
                "product_id": current_product,
                "started_at": start_ts,
                "ended_at": pd.NaT,
            })

    out = (
        pd.DataFrame.from_records(records, columns=["uuid", "product_id", "started_at", "ended_at"])
        .sort_values(["uuid", "started_at"])
        .reset_index(drop=True)
    )
    return out


# -----------------------------
# Sidebar controls
# -----------------------------
st.sidebar.header("Controls")

# (2) Слайдер для «длинных» сессий: 4–30 часов (по умолчанию 12)
threshold_hours = st.sidebar.slider(
    "Max session length (hours)",
    min_value=4, max_value=30, value=30, step=1,
    help="Сессии длиннее значения будут отфильтрованы"
)

# Session state для стабильных фильтров
if "filters_enabled_station" not in st.session_state:
    st.session_state.filters_enabled_station = False
if "filters_enabled_product" not in st.session_state:
    st.session_state.filters_enabled_product = False
if "selected_uuids" not in st.session_state:
    st.session_state.selected_uuids = None  # позже инициализируем списком всех
if "selected_products" not in st.session_state:
    st.session_state.selected_products = None

# -----------------------------
# Pipeline (без вывода «сырых» таблиц)
# -----------------------------
try:
    if not os.path.exists(DB_PATH):
        st.error(f"Не найден файл БД: {DB_PATH}. Помести stations.db рядом с приложением.")
        st.stop()

    with st.spinner("Loading station_changes from SQLite…"):
        raw_df = load_station_changes(DB_PATH)

    with st.spinner("Cleaning…"):
        df_clean = clean_df(raw_df)

    with st.spinner("Building BUSY intervals…"):
        intervals = build_busy_intervals(df_clean)

    # st.markdown("### ⏱️ Durations (where ended_at present)")
    # if intervals.empty:
    #     st.info("No intervals constructed.")
    #     st.stop()

    # расчёт длительности
    intervals_with_duration = intervals.copy()
    intervals_with_duration["duration_sec"] = (
        (intervals_with_duration["ended_at"] - intervals_with_duration["started_at"]).dt.total_seconds()
    )
    intervals_with_duration["duration_minutes"] = intervals_with_duration["duration_sec"] / 60

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

    selected_start = pd.Timestamp(start_date).normalize()
    selected_end = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    # (2) Фильтрация по максимальной длительности
    max_seconds = threshold_hours * 3600
    intervals_with_duration = intervals_with_duration[
        (intervals_with_duration["duration_sec"].isna()) |
        (intervals_with_duration["duration_sec"] <= max_seconds)
        ].copy()

    date_mask = (
        (intervals_with_duration["started_at"] <= selected_end)
        & (intervals_with_duration["ended_at"].fillna(selected_end) >= selected_start)
    )
    intervals_with_duration = intervals_with_duration[date_mask].copy()

    server_info_df = fetch_server_info(DB_PATH)

    # Справочники имён
    uuid_to_name, uuid_to_city = fetch_stations_dict()
    pid_to_title = fetch_product_titles()

    intervals_with_duration = intervals_with_duration.merge(
        server_info_df,
        on="uuid",
        how="left",
    )

    # Человекочитаемые подписи
    intervals_with_duration["station_name"] = intervals_with_duration["uuid"].map(uuid_to_name)
    intervals_with_duration["product_title"] = intervals_with_duration["product_id"].map(pid_to_title)
    intervals_with_duration["city_name"] = intervals_with_duration["city_name"].fillna(intervals_with_duration["uuid"].map(uuid_to_city))
    intervals_with_duration["city_name"] = intervals_with_duration["city_name"].fillna("Unknown")
    intervals_with_duration["processor"] = intervals_with_duration["processor"].fillna("Unknown")
    intervals_with_duration["graphic_names"] = intervals_with_duration["graphic_names"].fillna("Unknown")
    intervals_with_duration["free_trial"] = intervals_with_duration["free_trial"].fillna(0)

    # Таблица длительностей (видимая)
    # st.dataframe(
    #     intervals_with_duration.dropna(subset=["duration_sec"]).sort_values("duration_sec", ascending=False).head(200),
    #     use_container_width=True
    # )

    # -----------------------------
    # Фильтры (3 — стабильные, с именами)
    # -----------------------------
    st.sidebar.markdown("---")
    st.sidebar.header("Filters")

    # Опции
    all_uuids = sorted(intervals_with_duration["uuid"].dropna().unique().tolist())
    all_products = sorted(intervals_with_duration["product_id"].dropna().unique().tolist())
    all_cities = sorted(intervals_with_duration["city_name"].dropna().unique().tolist())
    all_processors = sorted(intervals_with_duration["processor"].dropna().unique().tolist())
    all_graphics = sorted(intervals_with_duration["graphic_names"].dropna().unique().tolist())


    # Функции форматирования "человеческих" подписей
    def _fmt_uuid(u):
        name = uuid_to_name.get(u, u)
        return f"{name} ({u})" if name != u else u


    def _fmt_prod(p):
        title = pid_to_title.get(p, p)
        return f"{title} ({p})" if title != p else p


    ss = st.session_state

    # Инициализация: один раз — всё выбрано
    if "enable_uuid" not in ss: ss.enable_uuid = False
    if "enable_prod" not in ss: ss.enable_prod = False
    if "enable_city" not in ss: ss.enable_city = False
    if "enable_processor" not in ss: ss.enable_processor = False
    if "enable_graphic" not in ss: ss.enable_graphic = False
    if "uuid_sel" not in ss: ss.uuid_sel = []
    if "prod_sel" not in ss: ss.prod_sel = []
    if "city_sel" not in ss: ss.city_sel = []  # стартуем пустым
    if "processor_sel" not in ss: ss.processor_sel = []
    if "graphic_sel" not in ss: ss.graphic_sel = []

    # Синхронизация с текущими опциями (БЕЗ фолбэка «всё», чтобы крестик работал)
    ss.uuid_sel = [u for u in ss.uuid_sel if u in all_uuids]
    ss.prod_sel = [p for p in ss.prod_sel if p in all_products]
    ss.city_sel = [c for c in ss.city_sel if c in all_cities]
    ss.processor_sel = [p for p in ss.processor_sel if p in all_processors]
    ss.graphic_sel = [g for g in ss.graphic_sel if g in all_graphics]

    # Чекбоксы (без value=) и мультиселекты (без default=), состояние хранится в key
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
            help="Выбери один или несколько городов. Пусто — ничего не показывать."
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

    # Диапазоны
    def _range_slider(column, label, step=1):
        col_data = intervals_with_duration[column].dropna()
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

    product_number_range = _range_slider("product_number", "Количество продуктов (диапазон)")
    ram_range = _range_slider("ram_bytes", "RAM bytes (диапазон)")
    graphic_ram_range = _range_slider("graphic_ram_bytes", "Graphic RAM bytes (диапазон)")

    # Итоговые выборы
    selected_uuids = ss.uuid_sel if ss.enable_uuid else all_uuids
    selected_products = ss.prod_sel if ss.enable_prod else all_products
    selected_city = ss.city_sel if ss.enable_city else all_cities
    selected_processors = ss.processor_sel if ss.enable_processor else all_processors
    selected_graphics = ss.graphic_sel if ss.enable_graphic else all_graphics

    # Применяем фильтрацию
    filtered = intervals_with_duration[
        intervals_with_duration["uuid"].isin(selected_uuids)
        & intervals_with_duration["product_id"].isin(selected_products)
        & intervals_with_duration["city_name"].isin(selected_city)
        & intervals_with_duration["processor"].isin(selected_processors)
        & intervals_with_duration["graphic_names"].isin(selected_graphics)
        & intervals_with_duration["duration_sec"].notna()
        ].copy()

    if free_trial_only:
        filtered = filtered[filtered["free_trial"] == 1]

    if product_number_range:
        filtered = filtered[
            filtered["product_number"].between(product_number_range[0], product_number_range[1])
        ]
    if ram_range:
        filtered = filtered[
            filtered["ram_bytes"].between(ram_range[0], ram_range[1])
        ]
    if graphic_ram_range:
        filtered = filtered[
            filtered["graphic_ram_bytes"].between(graphic_ram_range[0], graphic_ram_range[1])
        ]

    min_date = filtered["started_at"].min()
    max_date = filtered["ended_at"].max()
    if pd.notna(min_date) and pd.notna(max_date):
        st.markdown(f"### Информация по сессиям с {min_date:%d.%m.%Y} по {max_date:%d.%m.%Y}")
    elif pd.notna(min_date):
        st.markdown(f"### Информация по сессиям начиная с {min_date:%d.%m.%Y}")
    else:
        st.markdown("### Информация по сессиям")

    # -----------------------------
    # Рейтинги и графики
    # -----------------------------

    # --- сессионные статистики по станциям/продуктам
    stats_uuid = (
        filtered.groupby("uuid")["duration_sec"]
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

    stats_prod = (
        filtered.groupby("product_id")["duration_sec"]
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

    st.markdown("### 📈 Rankings by total BUSY duration (filtered)")
    agg_uuid = (
        filtered.groupby("uuid", as_index=False)["duration_sec"].sum()
        .assign(duration_hours=lambda d: d["duration_sec"] / 3600)
        .sort_values("duration_hours", ascending=False)
        .merge(stats_uuid, on="uuid", how="left")
    )

    agg_prod = (
        filtered.groupby("product_id", as_index=False)["duration_sec"].sum()
        .assign(duration_hours=lambda d: d["duration_sec"] / 3600)
        .sort_values("duration_hours", ascending=False)
        .merge(stats_prod, on="product_id", how="left")
    )

    # Подписи
    agg_uuid["uuid_label"] = agg_uuid["uuid"].map(uuid_to_name).fillna(agg_uuid["uuid"])
    agg_prod["product_label"] = agg_prod["product_id"].map(pid_to_title).fillna(agg_prod["product_id"])

    # Топ-20 для графиков
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
                    y=alt.Y("uuid_label:N", sort='-x', title="Station"),
                    tooltip=[
                        alt.Tooltip("uuid_label:N", title="Station"),
                        alt.Tooltip("uuid:N", title="uuid"),
                        alt.Tooltip("duration_hours:Q", format=",.2f", title="Total (h)"),
                        alt.Tooltip("duration_sec:Q", format=",.0f", title="Total (sec)"),
                        # новые поля по сессиям
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
            st.altair_chart(chart_uuid, use_container_width=True)
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
                    y=alt.Y("product_label:N", sort='-x', title="Product"),
                    tooltip=[
                        alt.Tooltip("product_label:N", title="Product"),
                        alt.Tooltip("product_id:N", title="product_id"),
                        alt.Tooltip("duration_hours:Q", format=",.2f", title="Total (h)"),
                        alt.Tooltip("duration_sec:Q", format=",.0f", title="Total (sec)"),
                        # новые поля по сессиям
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
            st.altair_chart(chart_prod, use_container_width=True)
        else:
            st.info("No data after filters.")

    # Полные таблицы рейтингов
    st.subheader("Полный рейтинг по станциям")
    st.dataframe(
        agg_uuid.assign(Station=agg_uuid["uuid_label"])[["Station", "uuid", "duration_hours", "duration_sec", "session_mean_hours", "session_p25_hours", "session_p75_hours"]],
        use_container_width=True
    )

    st.subheader("Полный рейтинг по продуктам")
    st.dataframe(
        agg_prod.assign(Product=agg_prod["product_label"])[["Product", "product_id", "duration_hours", "duration_sec", "session_mean_hours", "session_p25_hours", "session_p75_hours"]],
        use_container_width=True
    )

    # Treemap по продуктам (опционально — красиво как WinDirStat/GrandPerspective)
    if not agg_prod.empty:
        fig = px.treemap(
            agg_prod,
            path=["product_label"],
            values="duration_hours",
            color="duration_hours",
            color_continuous_scale="Blues",
            title="Treemap по BUSY часам (Products)"
        )
        st.plotly_chart(fig, use_container_width=True)

        # -----------------------------
        # Рейтинг по городам
        # -----------------------------
        # city_name может быть NaN — подменим меткой
        agg_city = (
            filtered.assign(city=lambda d: d["city_name"].fillna("Unknown"))
            .groupby("city", as_index=False)
            .agg(
                duration_sec=("duration_sec", "sum"),
                n_stations=("uuid", "nunique"),
            )
            .assign(
                duration_hours=lambda d: d["duration_sec"] / 3600,
                hours_per_station=lambda d: (d["duration_sec"] / 3600) / d["n_stations"]
            )
            .sort_values("duration_hours", ascending=False)
        )

        # Топ-20 по суммарным BUSY часам для графика
        agg_city_top20 = agg_city.head(20).copy()

        st.subheader("By city (top-20 по BUSY часам)")
        if not agg_city_top20.empty:
            chart_city = (
                alt.Chart(agg_city_top20)
                .mark_bar()
                .encode(
                    x=alt.X("duration_hours:Q", title="Total BUSY hours"),
                    y=alt.Y("city:N", sort='-x', title="City"),
                    tooltip=[
                        alt.Tooltip("city:N", title="City"),
                        alt.Tooltip("duration_hours:Q", format=",.2f", title="hours"),
                        alt.Tooltip("duration_sec:Q", format=",.0f", title="seconds"),
                        alt.Tooltip("n_stations:Q", title="stations"),
                        alt.Tooltip("hours_per_station:Q", format=",.2f", title="h per station"),
                    ],
                )
                .properties(height=800)  # чтобы было как на других графиках
            )
            st.altair_chart(chart_city, use_container_width=True)
        else:
            st.info("No data after filters.")

        # Полная таблица рейтинга по городам
        st.subheader("Полный рейтинг по городам")
        st.dataframe(
            agg_city[["city", "duration_hours", "duration_sec", "n_stations", "hours_per_station"]],
            use_container_width=True
        )

        # (необязательно) Скачать CSV с рейтингом по городам
        csv_city = agg_city.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download city ranking (CSV)",
            data=csv_city,
            file_name="ranking_by_city.csv",
            mime="text/csv"
        )

        # Treemap по городам (опционально, требует plotly)
        if not agg_city.empty:
            fig_city = px.treemap(
                agg_city.rename(columns={"city": "City"}),
                path=["City"],
                values="duration_hours",
                color="duration_hours",
                color_continuous_scale="Blues",
                title="Treemap по BUSY часам (Cities)"
            )
            st.plotly_chart(fig_city, use_container_width=True)

        # -------------------------------------
        # Новый рейтинг: часов на одну станцию
        # -------------------------------------
        agg_city_mps_top20 = (
            agg_city.sort_values("hours_per_station", ascending=False)
            .head(20)
            .copy()
        )

        st.subheader("By city: часов на одну станцию (top-20)")
        if not agg_city_mps_top20.empty:
            chart_city_mps = (
                alt.Chart(agg_city_mps_top20)
                .mark_bar()
                .encode(
                    x=alt.X("hours_per_station:Q", title="Hours per station"),
                    y=alt.Y("city:N", sort='-x', title="City"),
                    tooltip=[
                        alt.Tooltip("city:N", title="City"),
                        alt.Tooltip("n_stations:Q", title="stations"),
                        alt.Tooltip("hours_per_station:Q", format=",.2f", title="h per station"),
                        alt.Tooltip("duration_hours:Q", format=",.2f", title="total hours"),
                    ],
                )
                .properties(height=800)
            )
            st.altair_chart(chart_city_mps, use_container_width=True)
        else:
            st.info("No data after filters (minutes per station).")

        st.subheader("Полный рейтинг по городам (часов на одну станцию)")
        st.dataframe(
            agg_city.sort_values("hours_per_station", ascending=False)[
                ["city", "n_stations", "hours_per_station", "duration_hours", "duration_sec"]
            ],
            use_container_width=True
        )

        def render_group_rank(df: pd.DataFrame, column: str, label: str):
            agg = (
                df.assign(group=lambda d: d[column].fillna("Unknown"))
                .groupby("group", as_index=False)
                .agg(
                    duration_sec=("duration_sec", "sum"),
                    n_stations=("uuid", "nunique"),
                )
                .assign(
                    duration_hours=lambda d: d["duration_sec"] / 3600,
                    hours_per_station=lambda d: (d["duration_sec"] / 3600) / d["n_stations"]
                )
                .sort_values("duration_hours", ascending=False)
            )

            top20 = agg.head(20)
            st.subheader(f"By {label} (top-20 по BUSY часам)")
            if not top20.empty:
                chart = (
                    alt.Chart(top20)
                    .mark_bar()
                    .encode(
                        x=alt.X("duration_hours:Q", title="Total BUSY hours"),
                        y=alt.Y("group:N", sort='-x', title=label),
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
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("No data after filters.")

            st.subheader(f"Полный рейтинг по {label}")
            st.dataframe(
                agg[["group", "duration_hours", "duration_sec", "n_stations", "hours_per_station"]],
                use_container_width=True,
            )

            per_station_top20 = (
                agg.sort_values("hours_per_station", ascending=False)
                .head(20)
                .copy()
            )
            st.subheader(f"By {label}: часов на одну станцию (top-20)")
            if not per_station_top20.empty:
                chart_mps = (
                    alt.Chart(per_station_top20)
                    .mark_bar()
                    .encode(
                        x=alt.X("hours_per_station:Q", title="Hours per station"),
                        y=alt.Y("group:N", sort='-x', title=label),
                        tooltip=[
                            alt.Tooltip("group:N", title=label),
                            alt.Tooltip("n_stations:Q", title="stations"),
                            alt.Tooltip("hours_per_station:Q", format=",.2f", title="h per station"),
                            alt.Tooltip("duration_hours:Q", format=",.2f", title="total hours"),
                        ],
                    )
                    .properties(height=800)
                )
                st.altair_chart(chart_mps, use_container_width=True)
            else:
                st.info("No data after filters (minutes per station).")

            st.subheader(f"Полный рейтинг по {label} (часов на одну станцию)")
            st.dataframe(
                agg.sort_values("hours_per_station", ascending=False)[
                    ["group", "n_stations", "hours_per_station", "duration_hours", "duration_sec"]
                ],
                use_container_width=True,
            )

        render_group_rank(filtered, "processor", "processor")
        render_group_rank(filtered, "graphic_names", "graphic card")

        map_data = (
            filtered.dropna(subset=["latitude", "longitude"])
            .groupby(["latitude", "longitude"], as_index=False)
            .agg(duration_minutes=("duration_minutes", "sum"))
        )

        st.subheader("Minutes played on map")
        if not map_data.empty:
            fig_map = px.scatter_mapbox(
                map_data,
                lat="latitude",
                lon="longitude",
                size="duration_minutes",
                color="duration_minutes",
                color_continuous_scale="Blues",
                size_max=30,
                zoom=2,
                hover_data={"duration_minutes": ":.2f"},
                title="BUSY minutes by station location",
            )
            fig_map.update_layout(mapbox_style="open-street-map")
            st.plotly_chart(fig_map, use_container_width=True)
        else:
            st.info("Нет координат для отображения на карте.")



except Exception as e:
    st.error(f"Error: {e}")
