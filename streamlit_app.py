import io
import os
import sqlite3
from datetime import datetime
import requests
import plotly.express as px

import pandas as pd
import tempfile
import streamlit as st
import altair as alt

st.set_page_config(page_title="Station Changes Dashboard", layout="wide")
st.title("📊 Station Changes → BUSY Intervals")

st.markdown(
    """
This mini‑dashboard does three things:

1) Loads the `station_changes` table from an uploaded SQLite database into a pandas DataFrame.
2) Drops any rows containing **any** missing values.
3) Builds a new DataFrame of **BUSY intervals** with columns: `uuid, product_id, started_at, ended_at` by scanning changes in chronological order.

**Assumptions** (edit as needed):
- We construct intervals only for periods where a station is in the `BUSY` state.
- `started_at` is the timestamp of a transition **into** `BUSY` (i.e., when `new_state == 'BUSY'`). The `product_id` is taken from `new_product_id` at that moment.
- If the station switches product while still `BUSY` (i.e., `new_state == 'BUSY'` and `new_product_id` changes), we end the previous interval at that change and start a new one.
- `ended_at` is the timestamp when the station leaves `BUSY` (any `new_state != 'BUSY'`) **or** when it remains `BUSY` but switches to a different `product_id`.
- If an interval is still open at the end of the data, `ended_at` is left empty (NaT).
- We do not attempt to back‑fill intervals that started before the first observed change.
"""
)

# -------------------------
# Sidebar: DB input options
# -------------------------
st.sidebar.header("Data Source")
opt = st.sidebar.radio("Choose input method", ["Upload .sqlite/.db file", "Enter path on server"], index=0)

db_path = None
if opt == "Upload .sqlite/.db file":
    up = st.sidebar.file_uploader("Upload SQLite DB", type=["sqlite", "db", "sqlite3"])
    if up is not None:
        # Persist to a temporary file so sqlite3 can open it
        tmp_path = os.path.join(tempfile.gettempdir(), f"_uploaded_{int(datetime.now().timestamp())}.db")
        with open(tmp_path, "wb") as f:
            f.write(up.read())
        db_path = tmp_path
else:
    db_path = st.sidebar.text_input("Server filesystem path to SQLite DB", value="")

run = st.sidebar.button("Load table")
STATIONS_URL = "https://services.drova.io/server-manager/servers/public/web"
PRODUCTS_URL = "https://services.drova.io/product-manager/product/listfull2"

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
        # ожидаем массив объектов, каждый с uuid и name
        mapping = {item.get("uuid"): item.get("name") for item in data if isinstance(item, dict)}
        return mapping
    except Exception as e:
        st.warning(f"Не удалось получить список станций: {e}")
        return {}

@st.cache_data(show_spinner=False, ttl=600)
def fetch_product_titles():
    try:
        r = requests.get(PRODUCTS_URL, timeout=15)
        r.raise_for_status()
        data = r.json()
        # массив объектов с productId и title
        mapping = {item.get("productId"): item.get("title") for item in data if isinstance(item, dict)}
        return mapping
    except Exception as e:
        st.warning(f"Не удалось получить список продуктов: {e}")
        return {}

@st.cache_data(show_spinner=False)
def load_station_changes(path: str) -> pd.DataFrame:
    with sqlite3.connect(path) as conn:
        df = pd.read_sql_query("SELECT id, uuid, old_state, new_state, old_product_id, new_product_id, changed_at FROM station_changes", conn)
    return df

@st.cache_data(show_spinner=False)
def clean_df(df: pd.DataFrame) -> pd.DataFrame:
    # Ensure datetime type and sort
    if "changed_at" in df.columns:
        df = df.copy()
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
                        # still BUSY on same product -> do nothing
                        pass
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

    out = pd.DataFrame.from_records(records, columns=["uuid", "product_id", "started_at", "ended_at"]).sort_values(["uuid", "started_at"]).reset_index(drop=True)
    return out

if run and db_path:
    try:
        with st.spinner("Loading station_changes from SQLite…"):
            raw_df = load_station_changes(db_path)
        st.success(f"Loaded {len(raw_df):,} rows from station_changes")

        st.subheader("1) Raw table (first 200 rows)")
        st.dataframe(raw_df.head(200), use_container_width=True)

        with st.spinner("Cleaning… (drop any NA, parse timestamps, sort)"):
            df_clean = clean_df(raw_df)
        st.subheader("2) Cleaned table (no NA)")
        st.caption("All rows containing any missing values were dropped. Timestamps parsed to datetime, rows sorted by uuid + changed_at.")
        st.dataframe(df_clean.head(200), use_container_width=True)

        with st.spinner("Building BUSY intervals…"):
            intervals = build_busy_intervals(df_clean)
        st.subheader("3) BUSY intervals: uuid, product_id, started_at, ended_at")
        st.dataframe(intervals, use_container_width=True)

        # Optional: simple summary and download
        st.markdown("### ⏱️ Durations (where ended_at present)")
        if not intervals.empty:
            intervals_with_duration = intervals.copy()
            intervals_with_duration["duration_sec"] = (
                (intervals_with_duration["ended_at"] - intervals_with_duration["started_at"]) \
                .dt.total_seconds()
            )
            intervals_with_duration = intervals_with_duration[
                (intervals_with_duration["duration_sec"].isna()) |
                (intervals_with_duration["duration_sec"] <= 43200)
                ].copy()
            st.dataframe(intervals_with_duration.dropna(subset=["duration_sec"]).sort_values("duration_sec", ascending=False).head(200), use_container_width=True)

            csv = intervals.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Download intervals as CSV", data=csv, file_name="busy_intervals.csv", mime="text/csv")

            # Получаем справочники имен
            uuid_to_name = fetch_station_names()
            pid_to_title = fetch_product_titles()

            # Добавляем человеко-читаемые названия (если нет — оставляем NA)
            intervals_with_duration["station_name"] = intervals_with_duration["uuid"].map(uuid_to_name)
            intervals_with_duration["product_title"] = intervals_with_duration["product_id"].map(pid_to_title)

            # -------------------------
            # 🔎 Filters (UUID / Product)
            # -------------------------
            st.sidebar.header("Filters")
            uuids_all = sorted(intervals_with_duration["uuid"].dropna().unique().tolist())
            prods_all = sorted(intervals_with_duration["product_id"].dropna().unique().tolist())

            enable_uuid = st.sidebar.checkbox("Filter by uuid", value=False)
            selected_uuids = uuids_all
            if enable_uuid:
                selected_uuids = st.sidebar.multiselect("uuid", options=uuids_all, default=uuids_all)

            enable_prod = st.sidebar.checkbox("Filter by product_id", value=False)
            selected_prods = prods_all
            if enable_prod:
                selected_prods = st.sidebar.multiselect("product_id", options=prods_all, default=prods_all)

            filtered = intervals_with_duration[
                intervals_with_duration["uuid"].isin(selected_uuids)
                & intervals_with_duration["product_id"].isin(selected_prods)
                & intervals_with_duration["duration_sec"].notna()
                ].copy()

            st.markdown("### 📈 Rankings by total BUSY duration (filtered)")
            # агрегируем в часы для наглядности
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

            # Подписи для осей/tooltip: имя, если есть; иначе исходный id
            agg_uuid["uuid_label"] = agg_uuid["uuid"].map(uuid_to_name).fillna(agg_uuid["uuid"])
            agg_prod["product_label"] = agg_prod["product_id"].map(pid_to_title).fillna(agg_prod["product_id"])

            # Топ-20 для графиков
            agg_uuid_top20 = agg_uuid.head(20).copy()
            agg_prod_top20 = agg_prod.head(20).copy()
            agg_uuid_top20["uuid_label"] = agg_uuid_top20["uuid"].map(uuid_to_name).fillna(agg_uuid_top20["uuid"])
            agg_prod_top20["product_label"] = agg_prod_top20["product_id"].map(pid_to_title).fillna(
                agg_prod_top20["product_id"])

            left, right = st.columns(2)
            with left:
                st.subheader("By uuid (top-20)")
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
                st.subheader("By product_id (top-20)")
                if not agg_prod_top20.empty:
                    chart_prod = (
                        alt.Chart(agg_prod_top20 if 'agg_prod_top20' in locals() else agg_prod)
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
            st.subheader("Полный рейтинг по uuid")
            st.dataframe(
                agg_uuid.assign(Station=agg_uuid["uuid_label"])[["Station","uuid","duration_hours","duration_sec"]],
                use_container_width=True
            )

            st.subheader("Полный рейтинг по product_id")
            st.dataframe(
                agg_prod.assign(Product=agg_prod["product_label"])[["Product","product_id","duration_hours","duration_sec"]],
                use_container_width=True
            )

            # допустим, у нас agg_prod с колонками: product_label, duration_hours
            fig = px.treemap(
                agg_prod,
                path=["product_label"],  # путь иерархии (можно добавить 'uuid_label' как вложенный уровень)
                values="duration_hours",
                color="duration_hours",
                color_continuous_scale="Blues",
                title="Treemap по BUSY часам (Products)"
            )

            st.plotly_chart(fig, use_container_width=True)

            # Кнопки скачивания рейтингов
            csv_uuid = agg_uuid.to_csv(index=False).encode("utf-8")
            csv_prod = agg_prod.to_csv(index=False).encode("utf-8")
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("⬇️ Download uuid ranking (CSV)", data=csv_uuid, file_name="ranking_by_uuid.csv",
                                   mime="text/csv")
            with c2:
                st.download_button("⬇️ Download product ranking (CSV)", data=csv_prod,
                                   file_name="ranking_by_product.csv", mime="text/csv")

        else:
            st.info("No intervals constructed.")

    except Exception as e:
        st.error(f"Error: {e}")
elif run and not db_path:
    st.warning("Please upload a database or enter a valid path.")
else:
    st.info("👈 Upload a SQLite DB or provide a path, then click *Load table*.")
