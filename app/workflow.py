from typing import Any

import pandas as pd
import streamlit as st

from app.data_access import (
    fetch_product_titles,
    fetch_server_info,
    fetch_stations_dict,
    load_station_changes,
)
from app.filters import TimeControls, apply_time_filters
from app.pipeline import build_busy_intervals, clean_df
from app.preparation import (
    enrich_intervals_with_metadata,
    prepare_intervals_with_duration,
)


def load_prepared_intervals(
    db_path: str,
    time_controls: TimeControls,
) -> tuple[pd.DataFrame, dict[Any, Any], dict[Any, Any], pd.DataFrame]:
    with st.spinner("Loading station_changes from SQLite…"):
        raw_df = load_station_changes(db_path)

    with st.spinner("Cleaning…"):
        df_clean = clean_df(raw_df)

    with st.spinner("Building BUSY intervals…"):
        intervals = build_busy_intervals(df_clean)

    intervals_with_duration = prepare_intervals_with_duration(intervals)
    intervals_with_duration = apply_time_filters(intervals_with_duration, time_controls)

    server_info_df = fetch_server_info(db_path)
    uuid_to_name, uuid_to_city = fetch_stations_dict()
    pid_to_title = fetch_product_titles()

    intervals_with_duration = enrich_intervals_with_metadata(
        intervals_with_duration=intervals_with_duration,
        server_info_df=server_info_df,
        uuid_to_name=uuid_to_name,
        uuid_to_city=uuid_to_city,
        pid_to_title=pid_to_title,
    )
    return intervals_with_duration, uuid_to_name, pid_to_title, server_info_df
