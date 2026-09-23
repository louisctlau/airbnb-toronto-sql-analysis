"""Toronto Airbnb — SQL portfolio dashboard.

Run from this directory:  streamlit run app.py
Requires the project SQLite databases in ../data/.
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
DATA_DIR = BASE.parent / "data"
MONTHS = {
    "June 2026": DATA_DIR / "airbnb_toronto.db",
    "July 2026": DATA_DIR / "airbnb_toronto_2026_07.db",
    "August 2026": DATA_DIR / "airbnb_toronto_2026_08.db",
    "September 2026": DATA_DIR / "airbnb_toronto_2026_09.db",
}

st.set_page_config(
    page_title="Toronto Airbnb — SQL Analysis Dashboard",
    page_icon="🏙️",
    layout="wide",
)

MEDIAN_SQL = """
SELECT AVG(price) FROM (
  SELECT price,
         ROW_NUMBER() OVER (ORDER BY price) AS rn,
         COUNT(*) OVER () AS cnt
  FROM listings
  WHERE price > 0 AND room_type = '{rt}'
) WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
"""

KPI_SQL = """
SELECT
  (SELECT COUNT(*) FROM listings) AS listings,
  ({ent}) AS entire_med,
  ({priv}) AS private_med,
  (SELECT 100.0 * SUM(CASE WHEN price IS NULL OR price <= 0 THEN 1 ELSE 0 END)
           / COUNT(*) FROM listings) AS no_quote_pct,
  (SELECT 100.0 * SUM(CASE WHEN host_is_superhost = 1 THEN 1 ELSE 0 END)
           / COUNT(*) FROM listings WHERE price > 0) AS superhost_share,
  (SELECT 100.0 * SUM(CASE WHEN number_of_reviews = 0 OR number_of_reviews IS NULL
                      THEN 1 ELSE 0 END) / COUNT(*) FROM listings) AS never_reviewed_pct
""".format(ent=MEDIAN_SQL.format(rt="Entire home/apt"),
           priv=MEDIAN_SQL.format(rt="Private room"))


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


@st.cache_data
def kpis(db: str) -> dict:
    row = query(db, KPI_SQL).iloc[0]
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
    for label, db in MONTHS.items():
        k = kpis(str(db))
        k["month"] = label
        rows.append(k)
    df = pd.DataFrame(rows)
    df["premium"] = (df["entire_med"] / df["private_med"]).round(2)
    return df


@st.cache_data
def neighbourhoods(db: str) -> pd.DataFrame:
    return query(db, """
    WITH med AS (
      SELECT nb, AVG(price) AS median_price FROM (
        SELECT neighbourhood_cleansed AS nb, price,
               ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed ORDER BY price) AS rn,
               COUNT(*) OVER (PARTITION BY neighbourhood_cleansed) AS cnt
        FROM listings WHERE price > 0)
      WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
      GROUP BY nb)
    SELECT l.neighbourhood_cleansed AS nb,
           COUNT(*) AS listings,
           ROUND(AVG(l.price), 2) AS avg_price,
           ROUND(m.median_price, 2) AS median_price,
           ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_supply
    FROM listings l JOIN med m ON m.nb = l.neighbourhood_cleansed
    WHERE l.price > 0
    GROUP BY l.neighbourhood_cleansed
    ORDER BY listings DESC
    """)


@st.cache_data
def superhost_stats(db: str) -> pd.DataFrame:
    return query(db, """
    SELECT CASE WHEN host_is_superhost = 1 THEN 'Superhost'
                WHEN host_is_superhost = 0 THEN 'Regular host'
                ELSE 'Unknown' END AS host_type,
           COUNT(*) AS listings,
           ROUND(AVG(price), 2) AS avg_price,
           ROUND(AVG(review_scores_rating), 2) AS avg_rating,
           ROUND(AVG(reviews_per_month), 2) AS avg_reviews_pm
    FROM listings WHERE price > 0 GROUP BY host_is_superhost
    """)


@st.cache_data
def host_concentration(db: str) -> pd.DataFrame:
    return query(db, """
    WITH hs AS (
      SELECT host_id, COUNT(*) AS n
      FROM listings WHERE host_id IS NOT NULL AND price > 0 GROUP BY host_id)
    SELECT CASE WHEN h.n = 1 THEN '1 listing'
                WHEN h.n <= 5 THEN '2–5 listings'
                ELSE '6+ listings' END AS band,
           COUNT(DISTINCT h.host_id) AS hosts,
           COUNT(*) AS listings,
           ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_supply,
           ROUND(AVG(l.price), 2) AS avg_price
    FROM listings l JOIN hs h ON h.host_id = l.host_id
    WHERE l.price > 0
    GROUP BY band ORDER BY MIN(h.n)
    """)


@st.cache_data
def room_medians(db: str) -> pd.DataFrame:
    return query(db, """
    SELECT room_type, AVG(price) AS median_price FROM (
      SELECT room_type, price,
             ROW_NUMBER() OVER (PARTITION BY room_type ORDER BY price) AS rn,
             COUNT(*) OVER (PARTITION BY room_type) AS cnt
      FROM listings WHERE price > 0)
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY room_type ORDER BY median_price DESC
    """)


@st.cache_data
def bedroom_curve(db: str) -> pd.DataFrame:
    return query(db, """
    SELECT CAST(bedrooms AS INTEGER) AS bedrooms,
           COUNT(*) AS listings,
           ROUND(AVG(price), 2) AS avg_price,
           ROUND(AVG(price) - LAG(AVG(price)) OVER (ORDER BY CAST(bedrooms AS INTEGER)), 2)
             AS marginal
    FROM listings
    WHERE room_type = 'Entire home/apt' AND price > 0 AND bedrooms BETWEEN 1 AND 5
    GROUP BY bedrooms ORDER BY bedrooms
    """)


@st.cache_data
def rating_bands(db: str) -> pd.DataFrame:
    return query(db, """
    SELECT CASE WHEN review_scores_rating IS NULL THEN 'No rating yet'
                WHEN review_scores_rating < 4.5 THEN 'Below 4.50'
                WHEN review_scores_rating < 4.8 THEN '4.50 – 4.79'
                ELSE '4.80 – 5.00' END AS band,
           COUNT(*) AS listings,
           ROUND(AVG(price), 2) AS avg_price
    FROM listings WHERE price > 0
    GROUP BY band
    ORDER BY CASE band WHEN 'No rating yet' THEN 0 WHEN 'Below 4.50' THEN 1
                       WHEN '4.50 – 4.79' THEN 2 ELSE 3 END
    """)


@st.cache_data
def true_occupancy_by_nb(db: str) -> pd.DataFrame:
    return query(db, """
    WITH occ AS (
      SELECT l.id, l.neighbourhood_cleansed AS nb, l.estimated_occupancy_l365d,
             SUM(1 - c.available) * 100.0 / COUNT(*) AS true_occ
      FROM calendar c JOIN listings l ON l.id = c.listing_id
      GROUP BY l.id)
    SELECT nb, COUNT(*) AS listings,
           ROUND(AVG(true_occ), 1) AS true_occ_pct,
           ROUND(AVG(estimated_occupancy_l365d) * 100.0 / 365, 1) AS est_occ_pct
    FROM occ GROUP BY nb HAVING listings >= 20
    ORDER BY true_occ_pct DESC LIMIT 10
    """)


@st.cache_data
def availability_curve(db: str) -> pd.DataFrame:
    return query(db, """
    SELECT strftime('%Y-%m', date) AS cal_month,
           ROUND(SUM(available) * 100.0 / COUNT(*), 1) AS pct_available
    FROM calendar GROUP BY cal_month ORDER BY cal_month
    """)


@st.cache_data
def city_true_occupancy(db: str) -> float:
    df = query(db, """
    SELECT SUM(1 - available) * 100.0 / COUNT(*) AS occ FROM calendar
    """)
    return round(float(df.iloc[0]["occ"]), 1)


@st.cache_data
def review_volume(db: str) -> pd.DataFrame:
    return query(db, """
    SELECT strftime('%Y-%m', date) AS review_month, COUNT(*) AS reviews
    FROM reviews GROUP BY review_month ORDER BY review_month
    """)


@st.cache_data
def review_velocity(db: str) -> pd.DataFrame:
    return query(db, """
    SELECT name, neighbourhood_cleansed AS nb, room_type,
           ROUND(price, 2) AS price,
           ROUND(reviews_per_month, 2) AS reviews_pm,
           number_of_reviews AS reviews
    FROM listings
    WHERE number_of_reviews >= 20 AND reviews_per_month IS NOT NULL
    ORDER BY reviews_per_month DESC LIMIT 15
    """)


@st.cache_data
def neighbourhood_list(db: str) -> list:
    df = query(db, """
    SELECT neighbourhood_cleansed AS nb, COUNT(*) AS n
    FROM listings WHERE neighbourhood_cleansed IS NOT NULL
    GROUP BY nb ORDER BY n DESC LIMIT 60
    """)
    return df["nb"].tolist()

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
if view != "Trends (all months)":
    DB = str(MONTHS[view])

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
    st.stop()

# ----------------------------------------------------------------------------
# Overview tab
# ----------------------------------------------------------------------------
with tab_over:
    st.header(f"Overview — {view}")
    k = kpis(DB)
    c1, c2, c3 = st.columns(3)
    c1.metric("Listings", f"{k['listings']:,}")
    c2.metric("Entire-home median", f"${k['entire_med']:,.2f}")
    c3.metric("Private-room median", f"${k['private_med']:,.2f}")
    c4, c5, c6 = st.columns(3)
    c4.metric("Entire-home premium", f"{k['entire_med'] / k['private_med']:.2f}×")
    c5.metric("Superhost share", f"{k['superhost_share']}%")
    c6.metric("No price quote", f"{k['no_quote_pct']}%")

    st.subheader("Month-over-month headline metrics")
    df = all_kpis()
    order = ["June 2026", "July 2026", "August 2026", "September 2026"]
    df["month"] = pd.Categorical(df["month"], categories=order, ordered=True)
    df = df.sort_values("month")
    fig = px.line(df.melt(id_vars="month", value_vars=["entire_med", "private_med"]),
                  x="month", y="value", color="variable", markers=True,
                  labels={"value": "$/night", "variable": "Room type"},
                  title="Median nightly price over time")
    st.plotly_chart(fig, use_container_width=True)

with tab_nb:
    st.header(f"Neighbourhoods — {view}")
    nb = neighbourhoods(DB)
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

with tab_hosts:
    st.header(f"Hosts — {view}")
    sh = superhost_stats(DB)
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

    hc = host_concentration(DB)
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

with tab_price:
    st.header(f"Pricing — {view}")
    rm = room_medians(DB)
    fig = px.bar(rm, x="room_type", y="median_price", color="room_type",
                 labels={"room_type": "", "median_price": "Median $/night"},
                 title="Median nightly price by room type")
    st.plotly_chart(fig, use_container_width=True)

    bc = bedroom_curve(DB)
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

    rb = rating_bands(DB)
    fig = px.bar(rb, x="band", y="avg_price", color="band",
                 labels={"band": "Rating band", "avg_price": "Avg $/night"},
                 title="Average price by rating band")
    st.plotly_chart(fig, use_container_width=True)

with tab_occ:
    st.header(f"Occupancy — {view}")
    if view != "August 2026":
        st.warning("📅 Calendar data exists for the **August 2026** snapshot only. "
                   "Switch the snapshot selector to August 2026 to see true "
                   "(calendar-derived) occupancy analysis.")
    else:
        true_occ = city_true_occupancy(DB)
        st.metric("City-wide true occupancy (calendar-derived, next 365 days)",
                  f"{true_occ}%")
        st.caption("Inside Airbnb's `estimated_occupancy_l365d` field puts this at "
                   "~20% — the calendar shows roughly **2.4×** more actual booked "
                   "days. Estimates understate real activity.")
        occ = true_occupancy_by_nb(DB)
        fig = go.Figure()
        fig.add_trace(go.Bar(name="True occupancy %", x=occ["nb"], y=occ["true_occ_pct"]))
        fig.add_trace(go.Bar(name="Inside Airbnb estimate %", x=occ["nb"],
                             y=occ["est_occ_pct"]))
        fig.update_layout(barmode="group", xaxis_tickangle=-30,
                          title="True vs estimated occupancy — top 10 neighbourhoods",
                          yaxis_title="%")
        st.plotly_chart(fig, use_container_width=True)
        av = availability_curve(DB)
        fig = px.line(av, x="cal_month", y="pct_available", markers=True,
                      labels={"cal_month": "", "pct_available": "% available"},
                      title="Share of calendar days still bookable, by month")
        st.plotly_chart(fig, use_container_width=True)

with tab_rev:
    st.header(f"Reviews — {view}")
    if view != "August 2026":
        st.warning("💬 Review-level data exists for the **August 2026** snapshot only. "
                   "Switch the snapshot selector to August 2026 to explore review trends.")
    else:
        rv = review_volume(DB)
        fig = px.line(rv, x="review_month", y="reviews", markers=True,
                      labels={"review_month": "", "reviews": "Reviews"},
                      title="Review volume by month (Jan 2023 → Aug 2026)")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Clear summer seasonality every year; 2026 volume is far above "
                   "prior years — review activity is accelerating.")

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

        st.subheader("Fastest review velocity")
        st.dataframe(review_velocity(DB), use_container_width=True)

with tab_val:
    st.header(f"Value finder — {view}")
    st.caption("The A11 query, interactive: highly-rated entire homes priced "
               "below their neighbourhood median.")
    col1, col2, col3 = st.columns(3)
    nb_choice = col1.selectbox("Neighbourhood", neighbourhood_list(DB))
    max_price = col2.number_input("Max price ($/night)", min_value=20,
                                  max_value=5000, value=300, step=10)
    min_rating = col3.slider("Min rating", 4.0, 5.0, 4.8, 0.05)
    if st.button("Find value picks"):
        vals = query(DB, """
        WITH nb_median AS (
          SELECT neighbourhood_cleansed AS nb, AVG(price) AS median_price FROM (
            SELECT neighbourhood_cleansed, price,
                   ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed ORDER BY price) AS rn,
                   COUNT(*) OVER (PARTITION BY neighbourhood_cleansed) AS cnt
            FROM listings WHERE price > 0 AND room_type = 'Entire home/apt')
          WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2) GROUP BY neighbourhood_cleansed)
        SELECT l.name, ROUND(l.price, 2) AS price,
               ROUND(m.median_price, 2) AS nb_median_price,
               l.review_scores_rating AS rating,
               l.number_of_reviews AS reviews
        FROM listings l JOIN nb_median m ON m.nb = l.neighbourhood_cleansed
        WHERE l.room_type = 'Entire home/apt' AND l.price > 0
          AND l.neighbourhood_cleansed = ?
          AND l.price <= ?
          AND l.review_scores_rating >= ?
          AND l.number_of_reviews >= 10
          AND l.price < m.median_price
        ORDER BY l.review_scores_rating DESC, l.number_of_reviews DESC
        LIMIT 25
        """, params=(nb_choice, float(max_price), float(min_rating)))
        if vals.empty:
            st.info("No listings match — try a higher max price or lower min rating.")
        else:
            st.success(f"Found {len(vals)} value picks in {nb_choice}.")
            st.dataframe(vals, use_container_width=True)
