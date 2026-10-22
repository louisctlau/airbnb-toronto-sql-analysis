"""Toronto Airbnb — SQL portfolio dashboard.

Run locally from this directory:  streamlit run app.py
Requires the project SQLite databases in ../data/.

Deploying? The app is self-contained when dashboard/data/market_summary.db
exists (built by scripts/build_dashboard_bundle.py): in that "bundle mode"
every tab works identically off the small committed bundle, no full
databases or secrets needed. See dashboard/README.md.
"""
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
BASE = Path(__file__).resolve().parent
BUNDLE_DB = BASE / "data" / "market_summary.db"
BUNDLE = BUNDLE_DB.exists()

if BUNDLE:
    # Bundle mode: one self-contained db for every month.
    MONTHS = {
        "June 2026": str(BUNDLE_DB),
        "July 2026": str(BUNDLE_DB),
        "August 2026": str(BUNDLE_DB),
        "September 2026": str(BUNDLE_DB),
    }
    MONTH_CODES = {
        "June 2026": "2026-06",
        "July 2026": "2026-07",
        "August 2026": "2026-08",
        "September 2026": "2026-09",
    }
else:
    # Local dev: the full per-month databases.
    DATA_DIR = BASE.parent / "data"
    MONTHS = {
        "June 2026": str(DATA_DIR / "airbnb_toronto.db"),
        "July 2026": str(DATA_DIR / "airbnb_toronto_2026_07.db"),
        "August 2026": str(DATA_DIR / "airbnb_toronto_2026_08.db"),
        "September 2026": str(DATA_DIR / "airbnb_toronto_2026_09.db"),
    }
    MONTH_CODES = {}

st.set_page_config(
    page_title="Toronto Airbnb — SQL Analysis Dashboard",
    page_icon="🏙️",
    layout="wide",
)


def src_for(view: str) -> str:
    """SQL FROM-source for the listings table of one month's view.

    Bundle mode reads a per-month view (listings_2026_06, …) over the shared
    listings_slim table; local mode uses that month's own `listings` table.
    Every query keeps `FROM listings ...` semantics verbatim in both modes.
    """
    if BUNDLE:
        return "listings_" + MONTH_CODES[view].replace("-", "_")
    return "listings"


def median_sql(src: str, rt: str) -> str:
    return f"""
SELECT AVG(price) FROM (
  SELECT price,
         ROW_NUMBER() OVER (ORDER BY price) AS rn,
         COUNT(*) OVER () AS cnt
  FROM {src}
  WHERE price > 0 AND room_type = '{rt}'
) WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
"""


def kpi_sql(src: str) -> str:
    return f"""
SELECT
  (SELECT COUNT(*) FROM {src}) AS listings,
  ({median_sql(src, 'Entire home/apt')}) AS entire_med,
  ({median_sql(src, 'Private room')}) AS private_med,
  (SELECT 100.0 * SUM(CASE WHEN price IS NULL OR price <= 0 THEN 1 ELSE 0 END)
           / COUNT(*) FROM {src}) AS no_quote_pct,
  (SELECT 100.0 * SUM(CASE WHEN host_is_superhost = 1 THEN 1 ELSE 0 END)
           / COUNT(*) FROM {src} WHERE price > 0) AS superhost_share,
  (SELECT 100.0 * SUM(CASE WHEN number_of_reviews = 0 OR number_of_reviews IS NULL
                      THEN 1 ELSE 0 END) / COUNT(*) FROM {src}) AS never_reviewed_pct
"""


# ----------------------------------------------------------------------------
# Data layer (all cached; heavy calendar queries aggregate in SQL)
# ----------------------------------------------------------------------------
def connect(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data
def query(db: str, sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = connect(db)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def kpi_query(view: str):
    """(sql, params) producing one month's KPI row (bundle table or live SQL)."""
    if BUNDLE:
        return ("SELECT * FROM monthly_kpis WHERE month = ?",
                (MONTH_CODES[view],))
    return kpi_sql(src_for(view)), ()


@st.cache_data
def kpis(view: str) -> dict:
    db = MONTHS[view]
    sql, params = kpi_query(view)
    row = query(db, sql, params).iloc[0]
    return {
        "listings": int(row["listings"]),
        "entire_med": round(float(row["entire_med"]), 2),
        "private_med": round(float(row["private_med"]), 2),
        "no_quote_pct": round(float(row["no_quote_pct"]), 1),
        "superhost_share": round(float(row["superhost_share"]), 1),
        "never_reviewed_pct": round(float(row["never_reviewed_pct"]), 1),
    }


@st.cache_data
def all_kpis() -> pd.DataFrame:
    rows = []
    for label in MONTHS:
        k = kpis(label)
        k["month"] = label
        rows.append(k)
    df = pd.DataFrame(rows)
    df["premium"] = (df["entire_med"] / df["private_med"]).round(2)
    return df


def neighbourhoods_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    WITH med AS (
      SELECT nb, AVG(price) AS median_price FROM (
        SELECT neighbourhood_cleansed AS nb, price,
               ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed ORDER BY price) AS rn,
               COUNT(*) OVER (PARTITION BY neighbourhood_cleansed) AS cnt
        FROM {src} WHERE price > 0)
      WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
      GROUP BY nb)
    SELECT l.neighbourhood_cleansed AS nb,
           COUNT(*) AS listings,
           ROUND(AVG(l.price), 2) AS avg_price,
           ROUND(m.median_price, 2) AS median_price,
           ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_supply
    FROM {src} l JOIN med m ON m.nb = l.neighbourhood_cleansed
    WHERE l.price > 0
    GROUP BY l.neighbourhood_cleansed
    ORDER BY listings DESC
    """


@st.cache_data
def neighbourhoods(view: str) -> pd.DataFrame:
    return query(MONTHS[view], neighbourhoods_sql(view))


def superhost_stats_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT CASE WHEN host_is_superhost = 1 THEN 'Superhost'
                WHEN host_is_superhost = 0 THEN 'Regular host'
                ELSE 'Unknown' END AS host_type,
           COUNT(*) AS listings,
           ROUND(AVG(price), 2) AS avg_price,
           ROUND(AVG(review_scores_rating), 2) AS avg_rating,
           ROUND(AVG(reviews_per_month), 2) AS avg_reviews_pm
    FROM {src} WHERE price > 0 GROUP BY host_is_superhost
    """


@st.cache_data
def superhost_stats(view: str) -> pd.DataFrame:
    return query(MONTHS[view], superhost_stats_sql(view))


def host_concentration_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    WITH hs AS (
      SELECT host_id, COUNT(*) AS n
      FROM {src} WHERE host_id IS NOT NULL AND price > 0 GROUP BY host_id)
    SELECT CASE WHEN h.n = 1 THEN '1 listing'
                WHEN h.n <= 5 THEN '2–5 listings'
                ELSE '6+ listings' END AS band,
           COUNT(DISTINCT h.host_id) AS hosts,
           COUNT(*) AS listings,
           ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_supply,
           ROUND(AVG(l.price), 2) AS avg_price
    FROM {src} l JOIN hs h ON h.host_id = l.host_id
    WHERE l.price > 0
    GROUP BY band ORDER BY MIN(h.n)
    """


@st.cache_data
def host_concentration(view: str) -> pd.DataFrame:
    return query(MONTHS[view], host_concentration_sql(view))


def room_medians_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT room_type, AVG(price) AS median_price FROM (
      SELECT room_type, price,
             ROW_NUMBER() OVER (PARTITION BY room_type ORDER BY price) AS rn,
             COUNT(*) OVER (PARTITION BY room_type) AS cnt
      FROM {src} WHERE price > 0)
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY room_type ORDER BY median_price DESC
    """


@st.cache_data
def room_medians(view: str) -> pd.DataFrame:
    return query(MONTHS[view], room_medians_sql(view))


def bedroom_curve_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT CAST(bedrooms AS INTEGER) AS bedrooms,
           COUNT(*) AS listings,
           ROUND(AVG(price), 2) AS avg_price,
           ROUND(AVG(price) - LAG(AVG(price)) OVER (ORDER BY CAST(bedrooms AS INTEGER)), 2)
             AS marginal
    FROM {src}
    WHERE room_type = 'Entire home/apt' AND price > 0 AND bedrooms BETWEEN 1 AND 5
    GROUP BY bedrooms ORDER BY bedrooms
    """


@st.cache_data
def bedroom_curve(view: str) -> pd.DataFrame:
    return query(MONTHS[view], bedroom_curve_sql(view))


def rating_bands_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT CASE WHEN review_scores_rating IS NULL THEN 'No rating yet'
                WHEN review_scores_rating < 4.5 THEN 'Below 4.50'
                WHEN review_scores_rating < 4.8 THEN '4.50 – 4.79'
                ELSE '4.80 – 5.00' END AS band,
           COUNT(*) AS listings,
           ROUND(AVG(price), 2) AS avg_price
    FROM {src} WHERE price > 0
    GROUP BY band
    ORDER BY CASE band WHEN 'No rating yet' THEN 0 WHEN 'Below 4.50' THEN 1
                       WHEN '4.50 – 4.79' THEN 2 ELSE 3 END
    """


@st.cache_data
def rating_bands(view: str) -> pd.DataFrame:
    return query(MONTHS[view], rating_bands_sql(view))


def true_occupancy_by_nb_sql(view: str) -> str:
    if BUNDLE:
        return """
        SELECT nb, listings,
               true_occ_pct, est_occ_pct
        FROM calendar_occupancy_neighbourhood
        """
    src = src_for(view)
    return f"""
    WITH occ AS (
      SELECT l.id, l.neighbourhood_cleansed AS nb, l.estimated_occupancy_l365d,
             SUM(1 - c.available) * 100.0 / COUNT(*) AS true_occ
      FROM calendar c JOIN {src} l ON l.id = c.listing_id
      GROUP BY l.id)
    SELECT nb, COUNT(*) AS listings,
           ROUND(AVG(true_occ), 1) AS true_occ_pct,
           ROUND(AVG(estimated_occupancy_l365d) * 100.0 / 365, 1) AS est_occ_pct
    FROM occ GROUP BY nb HAVING listings >= 20
    ORDER BY true_occ_pct DESC LIMIT 10
    """


@st.cache_data
def true_occupancy_by_nb(view: str) -> pd.DataFrame:
    return query(MONTHS[view], true_occupancy_by_nb_sql(view))


def availability_curve_sql(view: str) -> str:
    if BUNDLE:
        return """
        SELECT cal_month, pct_available FROM calendar_monthly
        """
    return """
    SELECT strftime('%Y-%m', date) AS cal_month,
           ROUND(SUM(available) * 100.0 / COUNT(*), 1) AS pct_available
    FROM calendar GROUP BY cal_month ORDER BY cal_month
    """


@st.cache_data
def availability_curve(view: str) -> pd.DataFrame:
    return query(MONTHS[view], availability_curve_sql(view))


def city_true_occupancy_sql(view: str) -> str:
    if BUNDLE:
        return "SELECT city_true_occ_pct AS occ FROM calendar_summary"
    return """
    SELECT SUM(1 - available) * 100.0 / COUNT(*) AS occ FROM calendar
    """


@st.cache_data
def city_true_occupancy(view: str) -> float:
    df = query(MONTHS[view], city_true_occupancy_sql(view))
    return round(float(df.iloc[0]["occ"]), 1)


def review_volume_sql(view: str) -> str:
    if BUNDLE:
        return """
        SELECT review_month, reviews FROM review_volume
        """
    return """
    SELECT strftime('%Y-%m', date) AS review_month, COUNT(*) AS reviews
    FROM reviews GROUP BY review_month ORDER BY review_month
    """


@st.cache_data
def review_volume(view: str) -> pd.DataFrame:
    return query(MONTHS[view], review_volume_sql(view))


def review_velocity_sql(view: str) -> str:
    if BUNDLE:
        return """
        SELECT name, nb, room_type, price, reviews_pm, reviews
        FROM velocity_top
        """
    src = src_for(view)
    return f"""
    SELECT name, neighbourhood_cleansed AS nb, room_type,
           ROUND(price, 2) AS price,
           ROUND(reviews_per_month, 2) AS reviews_pm,
           number_of_reviews AS reviews
    FROM {src}
    WHERE number_of_reviews >= 20 AND reviews_per_month IS NOT NULL
    ORDER BY reviews_per_month DESC LIMIT 15
    """


@st.cache_data
def review_velocity(view: str) -> pd.DataFrame:
    return query(MONTHS[view], review_velocity_sql(view))


@st.cache_data
def neighbourhood_list(view: str) -> list:
    src = src_for(view)
    df = query(MONTHS[view], f"""
    SELECT neighbourhood_cleansed AS nb, COUNT(*) AS n
    FROM {src} WHERE neighbourhood_cleansed IS NOT NULL
    GROUP BY nb ORDER BY n DESC LIMIT 60
    """)
    return df["nb"].tolist()


# ----------------------------------------------------------------------------
# Added Oct 2026: what-changed panel, estimated upper-bound revenue,
# professionalization trend, forward availability, neighbourhood comparator.
# ----------------------------------------------------------------------------
MONTH_ORDER = ["June 2026", "July 2026", "August 2026", "September 2026"]
LATEST, PRIOR = MONTH_ORDER[-1], MONTH_ORDER[-2]


def view_sql(sql: str, note: str = None):
    """Collapsed expander showing the exact SQL behind a section."""
    with st.expander("View SQL"):
        st.code(sql.strip(), language="sql")
        if note:
            st.caption(note)


def id_delta_sql(view: str) -> str:
    return f"SELECT id FROM {src_for(view)}"


@st.cache_data
def listing_id_delta(new_view: str, old_view: str) -> tuple:
    """(added, removed) listing-id counts between two snapshots."""
    new_ids = set(query(MONTHS[new_view], id_delta_sql(new_view))["id"])
    old_ids = set(query(MONTHS[old_view], id_delta_sql(old_view))["id"])
    return len(new_ids - old_ids), len(old_ids - new_ids)


def overall_median_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT AVG(price) AS median_price FROM (
      SELECT price,
             ROW_NUMBER() OVER (ORDER BY price) AS rn,
             COUNT(*) OVER () AS cnt
      FROM {src} WHERE price > 0)
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    """


@st.cache_data
def overall_median(view: str) -> float:
    df = query(MONTHS[view], overall_median_sql(view))
    return float(df.iloc[0]["median_price"])


def nb_median_pair_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT nb, AVG(price) AS median_price, MAX(cnt) AS priced_listings FROM (
      SELECT neighbourhood_cleansed AS nb, price,
             ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed
                                ORDER BY price) AS rn,
             COUNT(*) OVER (PARTITION BY neighbourhood_cleansed) AS cnt
      FROM {src} WHERE price > 0 AND neighbourhood_cleansed IS NOT NULL)
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY nb
    """


@st.cache_data
def nb_price_movers(new_view: str, old_view: str,
                    min_listings: int = 50) -> pd.DataFrame:
    """Top-3 neighbourhood median-price movers between two snapshots."""
    new = query(MONTHS[new_view], nb_median_pair_sql(new_view)).rename(
        columns={"median_price": "med_new", "priced_listings": "n_new"})
    old = query(MONTHS[old_view], nb_median_pair_sql(old_view)).rename(
        columns={"median_price": "med_old", "priced_listings": "n_old"})
    m = new.merge(old, on="nb", how="inner")
    m = m[(m["n_new"] >= min_listings) & (m["n_old"] >= min_listings)].copy()
    m["change_pct"] = (m["med_new"] / m["med_old"] - 1) * 100
    m["abs_change"] = m["change_pct"].abs()
    return m.sort_values("abs_change", ascending=False).head(3)


def host_size_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT
      ROUND(100.0 * SUM(CASE WHEN calculated_host_listings_count >= 2
                             THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_multi,
      ROUND(100.0 * SUM(CASE WHEN calculated_host_listings_count >= 5
                             THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_5plus,
      ROUND(100.0 * SUM(CASE WHEN calculated_host_listings_count = 1
                             THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_single,
      ROUND(100.0 * SUM(CASE WHEN room_type = 'Entire home/apt'
                             THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_entire
    FROM {src}
    WHERE calculated_host_listings_count IS NOT NULL
    """


@st.cache_data
def host_size_trend() -> pd.DataFrame:
    """Professionalization trend across every snapshot in the warehouse."""
    rows = []
    for label in MONTH_ORDER:
        r = query(MONTHS[label], host_size_sql(label)).iloc[0]
        rows.append({"month": label,
                     "pct_multi": float(r["pct_multi"]),
                     "pct_5plus": float(r["pct_5plus"]),
                     "pct_single": float(r["pct_single"]),
                     "pct_entire": float(r["pct_entire"])})
    df = pd.DataFrame(rows)
    df["month"] = pd.Categorical(df["month"], categories=MONTH_ORDER,
                                 ordered=True)
    return df.sort_values("month")


def revenue_room_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT room_type, ROUND(AVG(rev), 2) AS median_est_revenue,
           MAX(cnt) AS listings FROM (
      SELECT room_type, price * (30 - availability_30) AS rev,
             ROW_NUMBER() OVER (PARTITION BY room_type
                                ORDER BY price * (30 - availability_30)) AS rn,
             COUNT(*) OVER (PARTITION BY room_type) AS cnt
      FROM {src}
      WHERE price > 0 AND availability_30 IS NOT NULL)
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY room_type ORDER BY median_est_revenue DESC
    """


def revenue_nb_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT nb, ROUND(AVG(rev), 2) AS median_est_revenue,
           MAX(cnt) AS listings FROM (
      SELECT neighbourhood_cleansed AS nb,
             price * (30 - availability_30) AS rev,
             ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed
                                ORDER BY price * (30 - availability_30)) AS rn,
             COUNT(*) OVER (PARTITION BY neighbourhood_cleansed) AS cnt
      FROM {src}
      WHERE price > 0 AND availability_30 IS NOT NULL
        AND neighbourhood_cleansed IS NOT NULL)
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY nb ORDER BY listings DESC LIMIT 15
    """


def revenue_exclusions_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT SUM(CASE WHEN price IS NULL OR price <= 0 THEN 1 ELSE 0 END) AS no_price,
           SUM(CASE WHEN price > 0 AND availability_30 IS NULL
                    THEN 1 ELSE 0 END) AS no_avail
    FROM {src}
    """


@st.cache_data
def revenue_by_room(view: str) -> pd.DataFrame:
    return query(MONTHS[view], revenue_room_sql(view))


@st.cache_data
def revenue_by_nb(view: str) -> pd.DataFrame:
    return query(MONTHS[view], revenue_nb_sql(view))


@st.cache_data
def revenue_exclusions(view: str) -> tuple:
    r = query(MONTHS[view], revenue_exclusions_sql(view)).iloc[0]
    return int(r["no_price"]), int(r["no_avail"] or 0)


def fwd_avail_city_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT
      ROUND(AVG(CASE WHEN rn30 IN ((cnt + 1) / 2, (cnt + 2) / 2)
                     THEN a30 END) * 100.0 / 30, 1) AS med_avail_30,
      ROUND(AVG(CASE WHEN rn60 IN ((cnt + 1) / 2, (cnt + 2) / 2)
                     THEN a60 END) * 100.0 / 60, 1) AS med_avail_60,
      ROUND(AVG(CASE WHEN rn90 IN ((cnt + 1) / 2, (cnt + 2) / 2)
                     THEN a90 END) * 100.0 / 90, 1) AS med_avail_90
    FROM (
      SELECT availability_30 AS a30, availability_60 AS a60,
             availability_90 AS a90,
             ROW_NUMBER() OVER (ORDER BY availability_30) AS rn30,
             ROW_NUMBER() OVER (ORDER BY availability_60) AS rn60,
             ROW_NUMBER() OVER (ORDER BY availability_90) AS rn90,
             COUNT(*) OVER () AS cnt
      FROM {src}
      WHERE availability_30 IS NOT NULL AND availability_60 IS NOT NULL
        AND availability_90 IS NOT NULL)
    """


def fwd_avail_nb_sql(view: str) -> str:
    src = src_for(view)
    return f"""
    SELECT nb, MAX(cnt) AS listings,
      ROUND(AVG(CASE WHEN rn30 IN ((cnt + 1) / 2, (cnt + 2) / 2)
                     THEN a30 END) * 100.0 / 30, 1) AS med_avail_30,
      ROUND(AVG(CASE WHEN rn60 IN ((cnt + 1) / 2, (cnt + 2) / 2)
                     THEN a60 END) * 100.0 / 60, 1) AS med_avail_60,
      ROUND(AVG(CASE WHEN rn90 IN ((cnt + 1) / 2, (cnt + 2) / 2)
                     THEN a90 END) * 100.0 / 90, 1) AS med_avail_90
    FROM (
      SELECT neighbourhood_cleansed AS nb,
             availability_30 AS a30, availability_60 AS a60,
             availability_90 AS a90,
             ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed
                                ORDER BY availability_30) AS rn30,
             ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed
                                ORDER BY availability_60) AS rn60,
             ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed
                                ORDER BY availability_90) AS rn90,
             COUNT(*) OVER (PARTITION BY neighbourhood_cleansed) AS cnt
      FROM {src}
      WHERE neighbourhood_cleansed IS NOT NULL
        AND availability_30 IS NOT NULL AND availability_60 IS NOT NULL
        AND availability_90 IS NOT NULL)
    GROUP BY nb HAVING listings >= 30
    ORDER BY listings DESC LIMIT 15
    """


@st.cache_data
def fwd_avail_city(view: str) -> pd.Series:
    return query(MONTHS[view], fwd_avail_city_sql(view)).iloc[0]


@st.cache_data
def fwd_avail_nb(view: str) -> pd.DataFrame:
    return query(MONTHS[view], fwd_avail_nb_sql(view))


def comparator_stats_sql(view: str, nbs: list) -> str:
    src = src_for(view)
    ph = ", ".join("?" for _ in nbs)
    return f"""
    SELECT neighbourhood_cleansed AS nb,
           COUNT(*) AS listings,
           ROUND(100.0 * SUM(CASE WHEN price > 0 AND host_is_superhost = 1
                                  THEN 1 ELSE 0 END)
                 / NULLIF(SUM(CASE WHEN price > 0 THEN 1 ELSE 0 END), 0),
                 1) AS superhost_pct,
           ROUND(AVG(100.0 * (1 - availability_365 / 365.0)), 1)
             AS occ_upper_pct,
           ROUND(AVG(reviews_per_month), 2) AS reviews_pm
    FROM {src}
    WHERE neighbourhood_cleansed IN ({ph})
    GROUP BY neighbourhood_cleansed
    """


def comparator_medians_sql(view: str, nbs: list) -> str:
    src = src_for(view)
    ph = ", ".join("?" for _ in nbs)
    return f"""
    SELECT nb, room_type, ROUND(AVG(price), 2) AS median_price FROM (
      SELECT neighbourhood_cleansed AS nb, room_type, price,
             ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed, room_type
                                ORDER BY price) AS rn,
             COUNT(*) OVER (PARTITION BY neighbourhood_cleansed, room_type)
               AS cnt
      FROM {src}
      WHERE price > 0 AND neighbourhood_cleansed IN ({ph})
        AND room_type IN ('Entire home/apt', 'Private room'))
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY nb, room_type
    """


@st.cache_data
def comparator(view: str, nbs: tuple) -> tuple:
    """(stats table with medians joined, long-form medians) for chosen nbs."""
    stats = query(MONTHS[view], comparator_stats_sql(view, list(nbs)),
                  tuple(nbs))
    meds = query(MONTHS[view], comparator_medians_sql(view, list(nbs)),
                 tuple(nbs))
    piv = meds.pivot(index="nb", columns="room_type", values="median_price")
    out = stats.set_index("nb").join(piv).reset_index()
    return out, meds

# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------
st.sidebar.title("🏙️ Toronto Airbnb")
st.sidebar.caption("SQL portfolio dashboard · Inside Airbnb data")
view = st.sidebar.selectbox(
    "Snapshot",
    ["June 2026", "July 2026", "August 2026", "September 2026", "Trends (all months)"],
    index=3,
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "Source: [Inside Airbnb](https://insideairbnb.com/get-the-data/) "
    "detailed listings, Toronto. CC BY 4.0. Prices in CAD. "
    "Calendar + reviews data exist for the **August 2026** snapshot only."
)

TABS = ["Overview", "Neighbourhoods", "Hosts", "Pricing",
        "Occupancy", "Reviews", "Value finder"]
tab_over, tab_nb, tab_hosts, tab_price, tab_occ, tab_rev, tab_val = st.tabs(TABS)

if view == "Trends (all months)":
    st.title("📈 Month-over-month trends")
    df = all_kpis()
    order = ["June 2026", "July 2026", "August 2026", "September 2026"]
    df["month"] = pd.Categorical(df["month"], categories=order, ordered=True)
    df = df.sort_values("month")

    metrics = {
        "entire_med": "Entire-home median ($/night)",
        "private_med": "Private-room median ($/night)",
        "premium": "Entire-home premium ratio",
        "no_quote_pct": "No price quote (%)",
        "superhost_share": "Superhost share of listings (%)",
        "never_reviewed_pct": "Never reviewed (%)",
        "listings": "Total listings",
    }
    cols = st.columns(2)
    for i, (col, label) in enumerate(metrics.items()):
        fig = px.line(df, x="month", y=col, markers=True, title=label)
        fig.update_layout(margin=dict(l=20, r=20, t=40, b=20), height=280)
        cols[i % 2].plotly_chart(fig, use_container_width=True)

    st.dataframe(df.set_index("month"), use_container_width=True)
    st.caption("Each value is recomputed live from that month's SQLite database "
               "with the same window-function median semantics as sql/03_analysis.sql.")
    view_sql(kpi_sql("listings"),
             "Run once per snapshot month against that month's listings "
             "table (bundle mode reads the precomputed monthly_kpis table "
             "instead); the trend charts are assembled from those KPI rows "
             "in pandas.")
    st.stop()

# ----------------------------------------------------------------------------
# Overview tab
# ----------------------------------------------------------------------------
with tab_over:
    st.header(f"Overview — {view}")
    k = kpis(view)
    c1, c2, c3 = st.columns(3)
    c1.metric("Listings", f"{k['listings']:,}")
    c2.metric("Entire-home median", f"${k['entire_med']:,.2f}")
    c3.metric("Private-room median", f"${k['private_med']:,.2f}")
    c4, c5, c6 = st.columns(3)
    c4.metric("Entire-home premium", f"{k['entire_med'] / k['private_med']:.2f}×")
    c5.metric("Superhost share", f"{k['superhost_share']}%")
    c6.metric("No price quote", f"{k['no_quote_pct']}%")
    _ksql, _kparams = kpi_query(view)
    view_sql(_ksql + (f"\n-- bound parameter: {_kparams[0]}" if _kparams else ""))

    st.subheader(f"What changed — {LATEST} vs {PRIOR}")
    added, removed = listing_id_delta(LATEST, PRIOR)
    k_new, k_old = kpis(LATEST), kpis(PRIOR)
    med_new, med_old = overall_median(LATEST), overall_median(PRIOR)
    w1, w2, w3 = st.columns(3)
    w1.metric("Listings (net)", f"{k_new['listings'] - k_old['listings']:+,}",
              help=f"{added:,} listing IDs appear in {LATEST} that were not "
                   f"in {PRIOR}; {removed:,} disappeared.")
    w2.metric("Added / removed listings", f"+{added:,} / −{removed:,}")
    w3.metric("Overall median price",
              f"${med_new:,.2f}",
              delta=f"{(med_new / med_old - 1) * 100:+.1f}% vs {PRIOR}")
    s_delta = k_new["superhost_share"] - k_old["superhost_share"]
    st.write(f"Superhost share: **{k_new['superhost_share']}%** "
             f"({s_delta:+.1f} pts vs {PRIOR}).")
    movers = nb_price_movers(LATEST, PRIOR)
    st.markdown("**Biggest neighbourhood median-price movers** "
                "(neighbourhoods with ≥50 priced listings in both months):")
    mv = movers.rename(columns={
        "nb": "Neighbourhood", "med_old": f"Median {PRIOR} ($)",
        "med_new": f"Median {LATEST} ($)", "change_pct": "Change %",
        "n_old": f"Listings {PRIOR}", "n_new": f"Listings {LATEST}"})
    mv[f"Median {PRIOR} ($)"] = mv[f"Median {PRIOR} ($)"].round(2)
    mv[f"Median {LATEST} ($)"] = mv[f"Median {LATEST} ($)"].round(2)
    mv["Change %"] = mv["Change %"].round(1)
    st.dataframe(mv[["Neighbourhood", f"Median {PRIOR} ($)",
                     f"Median {LATEST} ($)", "Change %",
                     f"Listings {PRIOR}", f"Listings {LATEST}"]],
                 use_container_width=True, hide_index=True)
    view_sql(id_delta_sql(LATEST) + "\n-- and the same SELECT for "
             + PRIOR + ",\n-- run once per snapshot:\n"
             + nb_median_pair_sql(LATEST),
             "Listing-ID membership and the overall median are compared "
             "across the two snapshots in pandas; neighbourhood medians use "
             "the window-function query above (bound table = the snapshot's "
             "listings view).")

    st.subheader("Month-over-month headline metrics")
    df = all_kpis()
    order = ["June 2026", "July 2026", "August 2026", "September 2026"]
    df["month"] = pd.Categorical(df["month"], categories=order, ordered=True)
    df = df.sort_values("month")
    melted = df.melt(id_vars="month", value_vars=["entire_med", "private_med"])
    melted["variable"] = melted["variable"].map(
        {"entire_med": "Entire home/apt", "private_med": "Private room"})
    fig = px.line(melted,
                  x="month", y="value", color="variable", markers=True,
                  labels={"value": "$/night", "variable": "Room type"},
                  title="Median nightly price over time")
    st.plotly_chart(fig, use_container_width=True)
    _ksql, _kparams = kpi_query(view)
    view_sql(_ksql + (f"\n-- bound parameter: {_kparams[0]}" if _kparams else ""),
             "The same KPI query runs for every snapshot month; the two "
             "median series are reshaped for the chart in pandas.")

with tab_nb:
    st.header(f"Neighbourhoods — {view}")
    nb = neighbourhoods(view)
    top15 = nb.head(15)

    fig = px.bar(top15.sort_values("listings"), x="listings", y="nb",
                 orientation="h", color="median_price",
                 color_continuous_scale="Viridis",
                 labels={"nb": "", "listings": "Listings", "median_price": "Median $"},
                 title="Top 15 neighbourhoods by listing count (colour = median price)")
    st.plotly_chart(fig, use_container_width=True)

    fig2 = px.bar(top15.sort_values("median_price"), x="median_price", y="nb",
                  orientation="h",
                  labels={"nb": "", "median_price": "Median $/night"},
                  title="Top 15 neighbourhoods by median nightly price")
    st.plotly_chart(fig2, use_container_width=True)
    view_sql(neighbourhoods_sql(view),
             "One query feeds both charts above (top-15 cut taken in pandas).")

    st.subheader("Mean vs median — where averages lie")
    skew = nb[nb["listings"] >= 50].copy()
    skew["skew_ratio"] = (skew["avg_price"] - skew["median_price"]) / skew["median_price"]
    skew = skew.sort_values("skew_ratio", ascending=False).head(10)
    fig3 = go.Figure()
    fig3.add_trace(go.Bar(name="Mean", x=skew["nb"], y=skew["avg_price"]))
    fig3.add_trace(go.Bar(name="Median", x=skew["nb"], y=skew["median_price"]))
    fig3.update_layout(barmode="group", title="Mean vs median price (most skewed neighbourhoods)",
                       xaxis_tickangle=-30)
    st.plotly_chart(fig3, use_container_width=True)
    tb = nb[nb["nb"] == "Trinity-Bellwoods"]
    if not tb.empty:
        st.info(f"Example: Trinity-Bellwoods averages ${tb.iloc[0]['avg_price']:,.2f} "
                f"but its median is only ${tb.iloc[0]['median_price']:,.2f} — "
                "a few luxury listings drag the mean up. That's why this dashboard "
                "reports medians (window-function) instead of averages.")
    view_sql(neighbourhoods_sql(view),
             "Same neighbourhood query as above; the skew ratio "
             "(mean − median) / median is computed in pandas.")

    st.subheader("Neighbourhood comparator")
    st.caption("Pick 2–4 neighbourhoods for a side-by-side view. Occupancy "
               "upper bound = calendar unavailability over the next 365 days "
               "(booked + host-blocked days) — an upper bound on occupancy, "
               "not booked occupancy.")
    all_nb = neighbourhood_list(view)
    picks = st.multiselect("Compare neighbourhoods", all_nb,
                           default=all_nb[:2], max_selections=4)
    if len(picks) < 2:
        st.info("Pick at least two neighbourhoods to compare.")
    else:
        comp, comp_meds = comparator(view, tuple(picks))
        comp = comp.set_index("nb").reindex(picks).reset_index()
        table = pd.DataFrame({
            "Neighbourhood": comp["nb"],
            "Listings": comp["listings"],
            "Entire-home median ($)": comp.get("Entire home/apt"),
            "Private-room median ($)": comp.get("Private room"),
            "Superhost %": comp["superhost_pct"],
            "Occupancy upper bound %": comp["occ_upper_pct"],
            "Reviews / listing / month": comp["reviews_pm"],
        })
        st.dataframe(table, use_container_width=True, hide_index=True)
        fig = px.bar(comp_meds, x="nb", y="median_price", color="room_type",
                     barmode="group",
                     labels={"nb": "", "median_price": "Median $/night",
                             "room_type": "Room type"},
                     title="Median nightly price by room type")
        st.plotly_chart(fig, use_container_width=True)
        view_sql(comparator_stats_sql(view, picks) + "\n\n"
                 + comparator_medians_sql(view, picks),
                 "The ? placeholders are bound to the selected neighbourhood "
                 "names; the stats table and the medians are joined in pandas.")

with tab_hosts:
    st.header(f"Hosts — {view}")
    sh = superhost_stats(view)
    sh = sh[sh["host_type"] != "Unknown"]
    c1, c2, c3 = st.columns(3)
    m1 = sh.set_index("host_type")
    for i, (metric, title, fmt) in enumerate(
            [("avg_price", "Avg price $/night", "${:,.2f}"),
             ("avg_rating", "Avg rating", "{:.2f}"),
             ("avg_reviews_pm", "Reviews / month", "{:.2f}")]):
        fig = go.Figure(go.Bar(x=m1.index, y=m1[metric], text=m1[metric].round(2),
                               textposition="auto"))
        fig.update_layout(title=title, height=280, margin=dict(l=20, r=20, t=40, b=20))
        [c1, c2, c3][i].plotly_chart(fig, use_container_width=True)
    view_sql(superhost_stats_sql(view))

    hc = host_concentration(view)
    col1, col2 = st.columns(2)
    fig = px.pie(hc, values="pct_supply", names="band", hole=0.45,
                 title="Share of priced supply by host portfolio size")
    col1.plotly_chart(fig, use_container_width=True)
    fig = px.bar(hc, x="band", y="avg_price", color="band",
                 labels={"band": "", "avg_price": "Avg $/night"},
                 title="Avg nightly price by host portfolio size")
    col2.plotly_chart(fig, use_container_width=True)
    st.caption("Single-listing hosts price highest; multi-listing professionals "
               "compete on volume — the self-join behind this is query A8.")
    view_sql(host_concentration_sql(view))

    st.subheader("Professionalization trend — all snapshots")
    st.caption("Share of listings run by multi-listing hosts (the "
               "\"hotel-ization\" lens), trended across every snapshot in "
               "the warehouse, independent of the snapshot selector.")
    trend = host_size_trend()
    cur = trend.iloc[-1]
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Listings with multi-listing hosts (≥2)",
              f"{cur['pct_multi']:.1f}%")
    t2.metric("Listings with hosts running ≥5", f"{cur['pct_5plus']:.1f}%")
    t3.metric("Single-listing hosts", f"{cur['pct_single']:.1f}%")
    t4.metric("Entire-home share", f"{cur['pct_entire']:.1f}%")
    melt = trend.melt(id_vars="month",
                      value_vars=["pct_multi", "pct_5plus", "pct_single",
                                  "pct_entire"])
    melt["variable"] = melt["variable"].map({
        "pct_multi": "Host has ≥2 listings",
        "pct_5plus": "Host has ≥5 listings",
        "pct_single": "Single-listing host",
        "pct_entire": "Entire home/apt"})
    fig = px.line(melt, x="month", y="value", color="variable", markers=True,
                  labels={"value": "% of listings", "variable": ""},
                  title="Share of listings by host portfolio size — Jun → Sep 2026")
    st.plotly_chart(fig, use_container_width=True)
    view_sql(host_size_sql(LATEST),
             "Run once per snapshot month (the bound table changes per "
             "month); monthly rows are stacked for the chart in pandas. Host "
             "portfolio size is each listing's calculated_host_listings_count.")

with tab_price:
    st.header(f"Pricing — {view}")

    st.subheader("Estimated upper-bound revenue")
    st.caption("Estimated monthly revenue per listing = nightly price × "
               "unavailable nights in the next 30 days. Unavailable days mix "
               "bookings with host blocks, so every figure here is an "
               "**estimated upper bound**, not actual earnings.")
    rev_room = revenue_by_room(view)
    rr = rev_room.set_index("room_type")
    r1, r2 = st.columns(2)
    if "Entire home/apt" in rr.index:
        r1.metric("Entire-home median estimated monthly revenue (upper bound)",
                  f"${rr.loc['Entire home/apt', 'median_est_revenue']:,.2f}")
    if "Private room" in rr.index:
        r2.metric("Private-room median estimated monthly revenue (upper bound)",
                  f"${rr.loc['Private room', 'median_est_revenue']:,.2f}")
    rev_nb = revenue_by_nb(view)
    st.markdown("**Median estimated monthly revenue (upper bound) by "
                "neighbourhood — top 15 by priced listings**")
    st.dataframe(rev_nb.rename(columns={
        "nb": "Neighbourhood",
        "median_est_revenue": "Median estimated monthly revenue — upper bound ($)",
        "listings": "Priced listings"}),
        use_container_width=True, hide_index=True)
    no_price, no_avail = revenue_exclusions(view)
    st.caption(f"Excludes {no_price:,} listings with no price quote"
               + (f" and {no_avail:,} with no availability data"
                  if no_avail else "")
               + ". Revenue uses availability_30 from the listing's calendar "
                 "summary (scrape date + 30 days).")
    view_sql(revenue_room_sql(view) + "\n\n" + revenue_nb_sql(view))

    rm = room_medians(view)
    fig = px.bar(rm, x="room_type", y="median_price", color="room_type",
                 labels={"room_type": "", "median_price": "Median $/night"},
                 title="Median nightly price by room type")
    st.plotly_chart(fig, use_container_width=True)
    view_sql(room_medians_sql(view))

    bc = bedroom_curve(view)
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Avg price", x=bc["bedrooms"], y=bc["avg_price"],
                         text=bc["avg_price"], textposition="outside"))
    fig.add_trace(go.Scatter(name="Marginal cost of extra bedroom", x=bc["bedrooms"],
                             y=bc["marginal"], mode="lines+markers",
                             yaxis="y2", line=dict(color="orange", width=3)))
    fig.update_layout(title="Bedroom economics — avg price & marginal cost per extra bedroom",
                      yaxis=dict(title="$/night"), yaxis2=dict(title="Marginal $",
                      overlaying="y", side="right"), legend=dict(x=0.05, y=0.95))
    st.plotly_chart(fig, use_container_width=True)
    view_sql(bedroom_curve_sql(view),
             "Average price is grouped in SQL; the marginal-cost line is the "
             "SQL LAG() difference between adjacent bedroom counts.")

    rb = rating_bands(view)
    fig = px.bar(rb, x="band", y="avg_price", color="band",
                 labels={"band": "Rating band", "avg_price": "Avg $/night"},
                 title="Average price by rating band")
    st.plotly_chart(fig, use_container_width=True)
    view_sql(rating_bands_sql(view))

with tab_occ:
    st.header(f"Occupancy — {view}")

    st.subheader(f"Forward availability — {view} snapshot")
    st.caption("Median share of days still bookable over the next 30 / 60 / "
               "90 days from the snapshot's scrape date, from each listing's "
               "calendar summary fields (availability_30 / 60 / 90). The raw "
               "day-by-day calendar exists only for the August snapshot, so "
               "this panel uses the per-listing availability windows the "
               "warehouse stores for every month. Low forward availability "
               "means calendars are filling — booked or host-blocked.")
    fc = fwd_avail_city(view)
    f1, f2, f3 = st.columns(3)
    f1.metric("Median available — next 30 days", f"{fc['med_avail_30']}%")
    f2.metric("Median available — next 60 days", f"{fc['med_avail_60']}%")
    f3.metric("Median available — next 90 days", f"{fc['med_avail_90']}%")
    fnb = fwd_avail_nb(view)
    fm = fnb.melt(id_vars=["nb", "listings"],
                  value_vars=["med_avail_30", "med_avail_60", "med_avail_90"])
    fm["variable"] = fm["variable"].map({
        "med_avail_30": "Next 30 days", "med_avail_60": "Next 60 days",
        "med_avail_90": "Next 90 days"})
    fig = px.bar(fm, x="nb", y="value", color="variable", barmode="group",
                 labels={"nb": "", "value": "Median % of days available",
                         "variable": "Window"},
                 title="Forward availability by neighbourhood (top 15, ≥30 listings)")
    fig.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)
    view_sql(fwd_avail_city_sql(view) + "\n\n" + fwd_avail_nb_sql(view),
             "Medians use the window-function pattern: each window's "
             "ROW_NUMBER ordering picks the middle listing(s) per group.")

    if view != "August 2026":
        st.warning("📅 Calendar data exists for the **August 2026** snapshot only. "
                   "Switch the snapshot selector to August 2026 to see "
                   "calendar-derived unavailability analysis.")
    else:
        true_occ = city_true_occupancy(view)
        st.metric("City-wide calendar unavailability (upper bound on occupancy, next 365 days)",
                  f"{true_occ}%")
        st.caption("Inside Airbnb's `estimated_occupancy_l365d` field puts this at "
                   "~20% — the calendar shows roughly **2.4×** more unavailable "
                   "days. Unavailable days mix bookings with host blocks (seasonal "
                   "closures, owner use), so this is an upper bound on true "
                   "occupancy, not booked occupancy.")
        view_sql(city_true_occupancy_sql(view))
        occ = true_occupancy_by_nb(view)
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Unavailable %", x=occ["nb"], y=occ["true_occ_pct"]))
        fig.add_trace(go.Bar(name="Inside Airbnb estimate %", x=occ["nb"],
                             y=occ["est_occ_pct"]))
        fig.update_layout(barmode="group", xaxis_tickangle=-30,
                          title="Calendar unavailability vs estimated occupancy — top 10 neighbourhoods",
                          yaxis_title="%")
        st.plotly_chart(fig, use_container_width=True)
        view_sql(true_occupancy_by_nb_sql(view),
                 "Bundle mode reads the precomputed "
                 "calendar_occupancy_neighbourhood table, built from this "
                 "query at bundle time.")
        av = availability_curve(view)
        fig = px.line(av, x="cal_month", y="pct_available", markers=True,
                      labels={"cal_month": "", "pct_available": "% available"},
                      title="Share of calendar days still bookable, by month")
        st.plotly_chart(fig, use_container_width=True)
        view_sql(availability_curve_sql(view),
                 "Bundle mode reads the precomputed calendar_monthly table, "
                 "built from this query at bundle time.")

with tab_rev:
    st.header(f"Reviews — {view}")
    if view != "August 2026":
        st.warning("💬 Review-level data exists for the **August 2026** snapshot only. "
                   "Switch the snapshot selector to August 2026 to explore review trends.")
    else:
        rv = review_volume(view)
        fig = px.line(rv, x="review_month", y="reviews", markers=True,
                      labels={"review_month": "", "reviews": "Reviews"},
                      title="Review volume by month (Jan 2023 → Aug 2026)")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Clear summer seasonality every year; 2026 volume is far above "
                   "prior years — review activity is accelerating.")
        view_sql(review_volume_sql(view),
                 "Bundle mode reads the precomputed review_volume table, "
                 "built from this query at bundle time.")

        st.subheader("What do guests talk about? 2023 vs 2026")
        tw = pd.read_csv(BASE / "data" / "top_words.csv")
        t23 = tw[tw["year"] == 2023].head(20).sort_values("count")
        t26 = tw[tw["year"] == 2026].head(20).sort_values("count")
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(t23, x="count", y="word", orientation="h",
                               title="Top review words — 2023"), use_container_width=True)
        c2.plotly_chart(px.bar(t26, x="count", y="word", orientation="h",
                               title="Top review words — 2026"), use_container_width=True)
        st.caption("Vocabulary is remarkably stable: hospitality words "
                   "(helpful, friendly, hosts) and place words (space, house, area) "
                   "dominate both years. Precomputed once into "
                   "`dashboard/data/top_words.csv` — the 447k-comment scan never "
                   "runs at page load.")
        with st.expander("View SQL"):
            st.caption("No query runs at page load for this section: the word "
                       "counts were precomputed once from the August "
                       "snapshot's reviews table into "
                       "`dashboard/data/top_words.csv`. There is no live SQL "
                       "to show.")

        st.subheader("Fastest review velocity")
        st.dataframe(review_velocity(view), use_container_width=True)
        view_sql(review_velocity_sql(view),
                 "Bundle mode reads the precomputed velocity_top table, built "
                 "from this query at bundle time.")

with tab_val:
    st.header(f"Value finder — {view}")
    st.caption("The A11 query, interactive: highly-rated entire homes priced "
               "below their neighbourhood median.")
    col1, col2, col3 = st.columns(3)
    nb_choice = col1.selectbox("Neighbourhood", neighbourhood_list(view))
    max_price = col2.number_input("Max price ($/night)", min_value=20,
                                  max_value=5000, value=300, step=10)
    min_rating = col3.slider("Min rating", 4.0, 5.0, 4.8, 0.05)
    src = src_for(view)
    value_sql = f"""
        WITH nb_median AS (
          SELECT neighbourhood_cleansed AS nb, AVG(price) AS median_price FROM (
            SELECT neighbourhood_cleansed, price,
                   ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed ORDER BY price) AS rn,
                   COUNT(*) OVER (PARTITION BY neighbourhood_cleansed) AS cnt
            FROM {src} WHERE price > 0 AND room_type = 'Entire home/apt')
          WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2) GROUP BY neighbourhood_cleansed)
        SELECT l.name, ROUND(l.price, 2) AS price,
               ROUND(m.median_price, 2) AS nb_median_price,
               l.review_scores_rating AS rating,
               l.number_of_reviews AS reviews
        FROM {src} l JOIN nb_median m ON m.nb = l.neighbourhood_cleansed
        WHERE l.room_type = 'Entire home/apt' AND l.price > 0
          AND l.neighbourhood_cleansed = ?
          AND l.price <= ?
          AND l.review_scores_rating >= ?
          AND l.number_of_reviews >= 10
          AND l.price < m.median_price
        ORDER BY l.review_scores_rating DESC, l.number_of_reviews DESC
        LIMIT 25
        """
    view_sql(value_sql,
             "The three ? placeholders are bound, in order, to the "
             "neighbourhood, max price and minimum rating chosen above.")
    if st.button("Find value picks"):
        vals = query(MONTHS[view], value_sql,
                     params=(nb_choice, float(max_price), float(min_rating)))
        if vals.empty:
            st.info("No listings match — try a higher max price or lower min rating.")
        else:
            st.success(f"Found {len(vals)} value picks in {nb_choice}.")
            st.dataframe(vals, use_container_width=True)
