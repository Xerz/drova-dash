import io
import os
import sqlite3
from datetime import datetime
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

DB_PATH = "stations.db"
STATIONS_URL = "https://services.drova.io/server-manager/servers/public/web"
PRODUCTS_URL = "https://services.drova.io/product-manager/product/listfull2"


# -----------------------------
# Cached helpers
# -----------------------------
@st.cache_data(show_spinner=False, ttl=600)
def fetch_station_names(limit=1000, offset=0):
    payload = {
        "stationNameOrDescription": None,
        "stationStatus": None,
        "products": [],
        "geo": None,
        "requiredAccount": None,
        "freeToPlay": None,
        "license": None,
        "limit": limit,
        "offset": offset,
        "published": True,
    }
    try:
        r = requests.post(STATIONS_URL, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        return {item.get("uuid"): item.get("name") for item in data if isinstance(item, dict)}
    except Exception as e:
        st.warning(f"Не удалось получить список станций: {e}")
        return {}


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
    min_value=4, max_value=30, value=12, step=1,
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

    # (2) Фильтрация по максимальной длительности
    max_seconds = threshold_hours * 3600
    intervals_with_duration = intervals_with_duration[
        (intervals_with_duration["duration_sec"].isna()) |
        (intervals_with_duration["duration_sec"] <= max_seconds)
        ].copy()

    # Справочники имён
    uuid_to_name = fetch_station_names()
    pid_to_title = fetch_product_titles()

    # Человекочитаемые подписи
    intervals_with_duration["station_name"] = intervals_with_duration["uuid"].map(uuid_to_name)
    intervals_with_duration["product_title"] = intervals_with_duration["product_id"].map(pid_to_title)

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
    if "uuid_sel" not in ss: ss.uuid_sel = []
    if "prod_sel" not in ss: ss.prod_sel = []

    # Синхронизация с текущими опциями (БЕЗ фолбэка «всё», чтобы крестик работал)
    ss.uuid_sel = [u for u in ss.uuid_sel if u in all_uuids]
    ss.prod_sel = [p for p in ss.prod_sel if p in all_products]

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

    # Итоговые выборы
    selected_uuids = ss.uuid_sel if ss.enable_uuid else all_uuids
    selected_products = ss.prod_sel if ss.enable_prod else all_products

    # Применяем фильтрацию
    filtered = intervals_with_duration[
        intervals_with_duration["uuid"].isin(selected_uuids)
        & intervals_with_duration["product_id"].isin(selected_products)
        & intervals_with_duration["duration_sec"].notna()
        ].copy()

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
    st.markdown("### 📈 Rankings by total BUSY duration (filtered)")
    agg_uuid = (
        filtered.groupby("uuid", as_index=False)["duration_sec"].sum()
        .assign(duration_hours=lambda d: d["duration_sec"] / 3600)
        .sort_values("duration_hours", ascending=False)
    )
    agg_prod = (
        filtered.groupby("product_id", as_index=False)["duration_sec"].sum()
        .assign(duration_hours=lambda d: d["duration_sec"] / 3600)
        .sort_values("duration_hours", ascending=False)
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
                        alt.Tooltip("duration_hours:Q", format=",.2f", title="hours"),
                        alt.Tooltip("duration_sec:Q", format=",.0f", title="seconds"),
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
                        alt.Tooltip("duration_hours:Q", format=",.2f", title="hours"),
                        alt.Tooltip("duration_sec:Q", format=",.0f", title="seconds"),
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
        agg_uuid.assign(Station=agg_uuid["uuid_label"])[["Station", "uuid", "duration_hours", "duration_sec"]],
        use_container_width=True
    )

    st.subheader("Полный рейтинг по продуктам")
    st.dataframe(
        agg_prod.assign(Product=agg_prod["product_label"])[["Product", "product_id", "duration_hours", "duration_sec"]],
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

except Exception as e:
    st.error(f"Error: {e}")
