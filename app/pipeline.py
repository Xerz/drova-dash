import pandas as pd
import streamlit as st


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
                        records.append(
                            {
                                "uuid": uuid,
                                "product_id": current_product,
                                "started_at": start_ts,
                                "ended_at": ts,
                            }
                        )
                        current_product = new_prod
                        start_ts = ts
                else:
                    # leaving BUSY -> close interval
                    records.append(
                        {
                            "uuid": uuid,
                            "product_id": current_product,
                            "started_at": start_ts,
                            "ended_at": ts,
                        }
                    )
                    current_product = None
                    start_ts = None
        # if BUSY at end, leave open interval
        if current_product is not None:
            records.append(
                {
                    "uuid": uuid,
                    "product_id": current_product,
                    "started_at": start_ts,
                    "ended_at": pd.NaT,
                }
            )

    out = (
        pd.DataFrame.from_records(
            records, columns=["uuid", "product_id", "started_at", "ended_at"]
        )
        .sort_values(["uuid", "started_at"])
        .reset_index(drop=True)
    )
    return out
