import sqlite3

import pandas as pd
import requests
import streamlit as st

from app.config import CACHE_TTL_SECONDS, DB_PATH, PRODUCTS_URL


@st.cache_data(show_spinner=False, ttl=CACHE_TTL_SECONDS)
def fetch_stations_dict(limit=1000, offset=0):
    """Возвращает мапы uuid->name и uuid->city_name из таблицы server_info."""

    _ = (limit, offset)
    try:
        server_info = fetch_server_info(DB_PATH)
        uuid_to_name = dict(zip(server_info["uuid"], server_info["name"]))
        uuid_to_city = dict(zip(server_info["uuid"], server_info["city_name"]))
        return uuid_to_name, uuid_to_city
    except Exception as e:
        st.warning(f"Не удалось получить список станций: {e}")
        return {}, {}


@st.cache_data(show_spinner=False, ttl=CACHE_TTL_SECONDS)
def fetch_product_titles():
    try:
        r = requests.get(PRODUCTS_URL, timeout=15)
        r.raise_for_status()
        data = r.json()
        return {
            item.get("productId"): item.get("title")
            for item in data
            if isinstance(item, dict)
        }
    except Exception as e:
        st.warning(f"Не удалось получить список продуктов: {e}")
        return {}


@st.cache_data(show_spinner=False, ttl=CACHE_TTL_SECONDS)
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


def load_station_changes(path: str) -> pd.DataFrame:
    with sqlite3.connect(path) as conn:
        df = pd.read_sql_query(
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
    return df
