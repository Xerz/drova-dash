import os

import streamlit as st

from app.aggregations import (
    build_city_ranking,
    build_group_ranking,
    build_map_data,
    build_station_product_rankings,
)
from app.config import DB_PATH
from app.filters import (
    apply_sidebar_filters,
    ensure_legacy_session_state,
    render_sidebar_filters,
    render_time_controls,
)
from app.views import (
    render_city_rankings,
    render_group_rank,
    render_minutes_map,
    render_product_treemap,
    render_session_range_header,
    render_station_product_rankings,
)
from app.workflow import load_prepared_intervals

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(page_title="Station Changes Dashboard", layout="wide")
# st.title("📊 Station Changes → BUSY Intervals")

ensure_legacy_session_state()
time_controls = render_time_controls()

# -----------------------------
# Pipeline (без вывода «сырых» таблиц)
# -----------------------------
try:
    if not os.path.exists(DB_PATH):
        st.error(f"Не найден файл БД: {DB_PATH}. Помести stations.db рядом с приложением.")
        st.stop()
    intervals_with_duration, uuid_to_name, pid_to_title = load_prepared_intervals(
        DB_PATH, time_controls
    )

    sidebar_filters = render_sidebar_filters(
        intervals_with_duration,
        uuid_to_name=uuid_to_name,
        pid_to_title=pid_to_title,
    )
    filtered = apply_sidebar_filters(intervals_with_duration, sidebar_filters)

    render_session_range_header(filtered)

    agg_uuid, agg_prod = build_station_product_rankings(
        filtered=filtered,
        intervals_with_duration=intervals_with_duration,
        uuid_to_name=uuid_to_name,
        pid_to_title=pid_to_title,
    )
    render_station_product_rankings(agg_uuid, agg_prod)
    render_product_treemap(agg_prod)

    if not agg_prod.empty:
        agg_city = build_city_ranking(filtered)
        render_city_rankings(agg_city)

        processor_rank = build_group_ranking(filtered, "processor")
        graphics_rank = build_group_ranking(filtered, "graphic_names")
        render_group_rank(processor_rank, "processor")
        render_group_rank(graphics_rank, "graphic card")

        map_data = build_map_data(filtered)
        render_minutes_map(map_data)



except Exception as e:
    st.error(f"Error: {e}")
