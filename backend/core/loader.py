"""
core/loader.py — Data loading and cleaning for ParkIQ.

Provides:
    load_and_clean(filepath)   — reads a CSV, cleans it, and adds derived columns
    generate_synthetic_data()  — creates 500 realistic synthetic records for demo
"""

import random
import string
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Peak hours definition (used in both load_and_clean and generate_synthetic_data)
# ---------------------------------------------------------------------------
PEAK_HOURS = {7, 8, 9, 17, 18, 19, 20}

VIOLATION_TYPES = [
    "No Parking",
    "Wrong Side Parking",
    "Blocking Driveway",
    "Double Parking",
    "Expired Meter",
    "Handicap Zone Violation",
]

VEHICLE_TYPES = ["Car", "Motorcycle", "Truck", "Auto", "Bus", "Van"]

OFFENCE_CODES = ["OFF001", "OFF002", "OFF003", "OFF004", "OFF005", "OFF006"]

JUNCTION_NAMES = [
    "Silk Board Junction",
    "KR Circle",
    "MG Road Junction",
    "Hebbal Flyover",
    "Electronic City Junction",
    "Koramangala 5th Block",
    "Whitefield Main Road",
    "Bannerghatta Road Junction",
    "Jayanagar 4th Block",
    "HSR Layout Sector 1",
]

POLICE_STATIONS = [
    "Koramangala PS",
    "Indiranagar PS",
    "MG Road PS",
    "Whitefield PS",
    "HSR Layout PS",
]

# Bangalore city centre coordinates
BASE_LAT = 12.9716
BASE_LON = 77.5946


# ---------------------------------------------------------------------------
# Internal helper: normalise violation_type values
# ---------------------------------------------------------------------------

def _normalize_violation_type(val) -> str:
    """
    The real dataset stores violation_type as a JSON-ish array string,
    e.g. '["WRONG PARKING","PARKING NEAR ROAD CROSSING"]'.
    Extract the first element and title-case it for display.
    Falls back to returning the raw value (or 'Unknown') if parsing fails.
    """
    if val is None or (isinstance(val, float) and val != val):
        return "Unknown"
    s = str(val).strip()
    if s.startswith("["):
        try:
            import json
            parsed = json.loads(s)
            if isinstance(parsed, list) and parsed:
                return str(parsed[0]).title()
        except Exception:
            # Strip brackets/quotes manually as fallback
            s = s.strip("[]").split(",")[0].strip().strip('"').strip("'")
    return s.title() if s else "Unknown"


# ---------------------------------------------------------------------------
# Internal helper: parse a datetime column robustly, handling tz-aware strings
# ---------------------------------------------------------------------------

def _parse_datetime_col(series: pd.Series) -> pd.Series:
    """
    Parse a Series of datetime strings into a tz-naive datetime64 Series.

    Handles timezone-aware strings (e.g. '2023-11-20 00:28:46+00') by
    element-wise parsing (bypasses pandas' internal cache which has known
    incompatibilities with numpy ≥ 2 / Python 3.14 builds).  Non-parseable
    values are coerced to NaT.
    """
    from dateutil import parser as dateutil_parser

    def _safe_parse(val):
        if val is None or (isinstance(val, float) and val != val):  # NaN check
            return pd.NaT
        if isinstance(val, (pd.Timestamp, datetime)):
            # Already a datetime — just strip tz if present
            ts = pd.Timestamp(val)
            return ts.tz_localize(None) if ts.tzinfo is not None else ts
        try:
            ts = dateutil_parser.parse(str(val))
            # Return as tz-naive (strip offset, keep the wall-clock time)
            return pd.Timestamp(ts.replace(tzinfo=None))
        except Exception:
            return pd.NaT

    return pd.Series(
        [_safe_parse(v) for v in series],
        index=series.index,
        dtype="datetime64[ns]",
    )


# ---------------------------------------------------------------------------
# Internal helper: compute and attach derived columns to an existing DataFrame
# ---------------------------------------------------------------------------

def _add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute derived columns and return an enriched copy of the DataFrame.

    Guards every access with ``if col in df.columns`` or safe defaults so
    DataFrames missing optional columns never raise KeyError/AttributeError.
    Uses ``assign`` for all new columns to avoid pandas Copy-on-Write warnings.
    """
    df = df.copy()

    # -- Ensure datetime columns are proper dtype --
    if "created_datetime" in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df["created_datetime"]):
            df = df.assign(
                created_datetime=_parse_datetime_col(df["created_datetime"])
            )

    if "closed_datetime" in df.columns:
        if not pd.api.types.is_datetime64_any_dtype(df["closed_datetime"]):
            df = df.assign(
                closed_datetime=_parse_datetime_col(df["closed_datetime"])
            )

    # hour_of_day
    if "created_datetime" in df.columns:
        df = df.assign(hour_of_day=df["created_datetime"].dt.hour)
    else:
        df = df.assign(hour_of_day=np.nan)

    # day_of_week
    if "created_datetime" in df.columns:
        df = df.assign(day_of_week=df["created_datetime"].dt.day_name())
    else:
        df = df.assign(day_of_week=np.nan)

    # resolution_minutes
    if "closed_datetime" in df.columns and "created_datetime" in df.columns:
        df = df.assign(
            resolution_minutes=(
                df["closed_datetime"] - df["created_datetime"]
            ).dt.total_seconds() / 60
        )
    else:
        df = df.assign(resolution_minutes=np.nan)

    # is_peak_hour  (computed after hour_of_day is already assigned above)
    df = df.assign(is_peak_hour=df["hour_of_day"].isin(PEAK_HOURS))

    # week_number (ISO week; cast from UInt32 to Int64 for JSON-friendliness)
    if "created_datetime" in df.columns:
        df = df.assign(
            week_number=df["created_datetime"]
            .dt.isocalendar()
            .week.astype("Int64")
        )
    else:
        df = df.assign(week_number=np.nan)

    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_and_clean(filepath: str) -> pd.DataFrame:
    """
    Read a CSV of parking violations, clean it, and enrich with derived columns.

    Steps:
        1. Read CSV (pandas infers dtypes).
        2. Parse created_datetime / closed_datetime with errors='coerce'.
        3. Drop rows where latitude or longitude is null or zero.
        4. Filter out rows where validation_status == 'INVALID' (if column present).
        5. Compute derived columns (hour_of_day, day_of_week, resolution_minutes,
           is_peak_hour, week_number).
        6. Print a data summary to stdout.

    Parameters
    ----------
    filepath : str
        Path to the CSV file.

    Returns
    -------
    pd.DataFrame
        Cleaned and enriched DataFrame.
    """
    # 1. Read CSV — read all columns as strings first to avoid C-level
    #    type-inference errors on mixed/malformed datetime columns
    df = pd.read_csv(filepath, dtype=str, keep_default_na=False)

    # Replace empty strings with NaN so downstream numeric ops work
    df = df.replace("", np.nan)

    # Cast lat/lon to float (they were read as str)
    for col in ("latitude", "longitude"):
        if col in df.columns:
            df = df.assign(**{col: pd.to_numeric(df[col], errors="coerce")})

    # 2. Parse datetime columns
    if "created_datetime" in df.columns:
        df = df.assign(
            created_datetime=_parse_datetime_col(df["created_datetime"])
        )
    if "closed_datetime" in df.columns:
        df = df.assign(
            closed_datetime=_parse_datetime_col(df["closed_datetime"])
        )

    # 3. Drop rows with null or zero lat/lon
    if "latitude" in df.columns:
        df = df[df["latitude"].notna() & (df["latitude"] != 0)]
    if "longitude" in df.columns:
        df = df[df["longitude"].notna() & (df["longitude"] != 0)]

    # 4. Filter out INVALID rows
    if "validation_status" in df.columns:
        df = df[df["validation_status"] != "INVALID"]

    # 5. Compute derived columns
    df = _add_derived_columns(df)

    # 6. Normalize violation_type — real CSV stores JSON arrays like
    #    '["WRONG PARKING","PARKING NEAR ROAD CROSSING"]'; extract first value
    if "violation_type" in df.columns:
        df = df.assign(violation_type=df["violation_type"].apply(_normalize_violation_type))

    # 7. Print summary
    _print_summary(df, label="Loaded Data")

    return df.reset_index(drop=True)


def generate_synthetic_data() -> pd.DataFrame:
    """
    Generate 500 realistic synthetic parking violation records around Bangalore.

    Returns
    -------
    pd.DataFrame
        DataFrame with the same schema as load_and_clean output, including
        all derived columns.
    """
    rng = random.Random()   # independent Random instance (no global state side-effects)

    now = datetime.utcnow()
    ninety_days_ago = now - timedelta(days=90)
    total_seconds_window = int((now - ninety_days_ago).total_seconds())

    records = []
    for i in range(1, 501):
        # Timestamps
        offset_seconds = rng.randint(0, total_seconds_window)
        created_dt = ninety_days_ago + timedelta(seconds=offset_seconds)
        resolution_secs = rng.randint(15, 360) * 60
        closed_dt = created_dt + timedelta(seconds=resolution_secs)

        junction = rng.choice(JUNCTION_NAMES)

        # Random KA-XX-XX-XXXX vehicle number
        district_num = rng.randint(1, 99)
        series = "".join(rng.choices(string.ascii_uppercase, k=2))
        number = rng.randint(1000, 9999)
        vehicle_number = f"KA-{district_num:02d}-{series}-{number}"

        records.append(
            {
                "id": i,
                "latitude": BASE_LAT + rng.uniform(-0.05, 0.05),
                "longitude": BASE_LON + rng.uniform(-0.05, 0.05),
                "location": junction,
                "vehicle_number": vehicle_number,
                "vehicle_type": rng.choice(VEHICLE_TYPES),
                "description": "",
                "violation_type": rng.choice(VIOLATION_TYPES),
                "offence_code": rng.choice(OFFENCE_CODES),
                "created_datetime": created_dt,
                "closed_datetime": closed_dt,
                "modified_datetime": closed_dt,
                "device_id": None,
                "created_by_id": None,
                "center_code": None,
                "police_station": rng.choice(POLICE_STATIONS),
                "data_sent_to_scita": None,
                "junction_name": junction,
                "action_taken_timestamp": None,
                "data_sent_to_scita_timestamp": None,
                "updated_vehicle_number": None,
                "updated_vehicle_type": None,
                "validation_status": "VALID",
                "validation_timestamp": None,
            }
        )

    df = pd.DataFrame(records)

    # Run the same derived-column pipeline as load_and_clean
    df = _add_derived_columns(df)

    # Print synthetic data summary
    _print_summary(df, label="Synthetic Data (500 records generated)")

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Internal helper: pretty-print a data summary
# ---------------------------------------------------------------------------

def _print_summary(df: pd.DataFrame, label: str = "Data Summary") -> None:
    """Print a concise summary of the cleaned DataFrame."""
    print("=" * 60)
    print(f"ParkIQ — {label}")
    print("=" * 60)
    print(f"  Total records      : {len(df):,}")

    if "created_datetime" in df.columns:
        date_min = df["created_datetime"].min()
        date_max = df["created_datetime"].max()
        print(f"  Date range         : {date_min} → {date_max}")
    else:
        print("  Date range         : N/A (no created_datetime column)")

    if "junction_name" in df.columns:
        print(f"  Unique junctions   : {df['junction_name'].nunique()}")
    else:
        print("  Unique junctions   : N/A")

    if "violation_type" in df.columns:
        top5 = df["violation_type"].value_counts().head(5)
        print("  Top 5 violation types:")
        for vtype, cnt in top5.items():
            print(f"    {vtype:<35} {cnt:>5}")
    else:
        print("  Top 5 violation types: N/A")

    print("=" * 60)
