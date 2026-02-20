import altair as alt
import pandas as pd
import plotly.express as px
import streamlit as st


def render_session_range_header(filtered: pd.DataFrame) -> None:
    min_date = filtered["started_at"].min()
    max_date = filtered["ended_at"].max()
    if pd.notna(min_date) and pd.notna(max_date):
        st.markdown(f"### Информация по сессиям с {min_date:%d.%m.%Y} по {max_date:%d.%m.%Y}")
    elif pd.notna(min_date):
        st.markdown(f"### Информация по сессиям начиная с {min_date:%d.%m.%Y}")
    else:
        st.markdown("### Информация по сессиям")


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
            st.altair_chart(chart_prod, use_container_width=True)
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
        use_container_width=True,
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
        use_container_width=True,
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
    st.plotly_chart(fig, use_container_width=True)


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
        st.altair_chart(chart_city, use_container_width=True)
    else:
        st.info("No data after filters.")

    st.subheader("Полный рейтинг по городам")
    st.dataframe(
        agg_city[["city", "duration_hours", "duration_sec", "n_stations", "hours_per_station"]],
        use_container_width=True,
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
        st.plotly_chart(fig_city, use_container_width=True)

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
        st.altair_chart(chart_city_mps, use_container_width=True)
    else:
        st.info("No data after filters (minutes per station).")

    st.subheader("Полный рейтинг по городам (часов на одну станцию)")
    st.dataframe(
        agg_city.sort_values("hours_per_station", ascending=False)[
            ["city", "n_stations", "hours_per_station", "duration_hours", "duration_sec"]
        ],
        use_container_width=True,
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
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("No data after filters.")

    st.subheader(f"Полный рейтинг по {label}")
    st.dataframe(
        agg[["group", "duration_hours", "duration_sec", "n_stations", "hours_per_station"]],
        use_container_width=True,
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


def render_minutes_map(map_data: pd.DataFrame) -> None:
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
