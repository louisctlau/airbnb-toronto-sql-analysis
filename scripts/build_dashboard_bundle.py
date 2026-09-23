#!/usr/bin/env python3
"""Build dashboard/data/market_summary.db — a small, self-contained SQLite
bundle for deploying the Streamlit dashboard on Streamlit Community Cloud.

The full project databases (incl. the 1.2GB August db with 8.1M calendar
rows) are gitignored and far too big to ship. This script extracts only what
the dashboard needs:

  * listings_slim — one row per listing for the 4 monthly snapshots
    (~88k rows), with a `month` discriminator ('2026-06' … '2026-09').
  * Precomputed August-only aggregates (calendar_*, review_volume,
    velocity_top) so the dashboard never touches the raw calendar/reviews
    tables at page load.
  * monthly_kpis — 4 rows of full-precision headline metrics.

Run from the project root:  python3 scripts/build_dashboard_bundle.py
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "dashboard" / "data" / "market_summary.db"

SNAPSHOTS = [
    ("2026-06", "airbnb_toronto.db"),
    ("2026-07", "airbnb_toronto_2026_07.db"),
    ("2026-08", "airbnb_toronto_2026_08.db"),
    ("2026-09", "airbnb_toronto_2026_09.db"),
]

LISTING_COLS = [
    "id", "name", "neighbourhood_cleansed", "room_type", "property_type",
    "price", "bedrooms", "beds", "accommodates", "bathrooms",
    "review_scores_rating", "number_of_reviews", "reviews_per_month",
    "host_id", "host_is_superhost", "host_listings_count",
    "calculated_host_listings_count", "minimum_nights",
    "availability_30", "availability_60", "availability_90", "availability_365",
    "estimated_occupancy_l365d", "estimated_revenue_l365d",
    "last_review", "first_review",
]

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


def main() -> int:
    if OUT.exists():
        OUT.unlink()
    out = sqlite3.connect(OUT)
    cur = out.cursor()

    # --- listings_slim -------------------------------------------------------
    cols_def = "month TEXT, " + ", ".join(LISTING_COLS)
    cur.execute(f"CREATE TABLE listings_slim ({cols_def})")
    total = 0
    for code, fname in SNAPSHOTS:
        src = DATA / fname
        if not src.exists():
            print(f"ERROR: missing source db {src}", file=sys.stderr)
            return 1
        # schema check on a separate connection (avoids locking `src` for DETACH)
        chk = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        have = [r[1] for r in chk.execute("PRAGMA table_info(listings)")]
        chk.close()
        missing = [c for c in LISTING_COLS if c not in have]
        if missing:
            print(f"ERROR: {fname} listings table missing columns: {missing}",
                  file=sys.stderr)
            return 1
        cur.execute("ATTACH DATABASE ? AS src", (str(src),))
        cols = ", ".join(LISTING_COLS)
        before = out.total_changes
        cur.execute(
            f"INSERT INTO listings_slim (month, {cols}) "
            f"SELECT '{code}', {cols} FROM src.listings"
        )
        out.commit()
        n = out.total_changes - before
        total += n
        print(f"  {code}: {n:,} listings rows")
        cur.execute("DETACH DATABASE src")
    out.commit()

    cur.execute("CREATE INDEX idx_slim_month_nb ON listings_slim (month, neighbourhood_cleansed)")
    cur.execute("CREATE INDEX idx_slim_month_rt ON listings_slim (month, room_type)")
    cur.execute("CREATE INDEX idx_slim_month_host ON listings_slim (month, host_id)")
    # Per-month views: let dashboard queries address a plain table name in
    # both modes (bundle view vs. local per-month `listings` table).
    for code, _ in SNAPSHOTS:
        v = "listings_" + code.replace("-", "_")
        cur.execute(f"CREATE VIEW {v} AS SELECT * FROM listings_slim WHERE month = '{code}'")
    print(f"listings_slim: {total:,} rows total")

    # --- monthly_kpis (full precision; rounding happens at display) ----------
    cur.execute("""
    CREATE TABLE monthly_kpis (
      month TEXT PRIMARY KEY, listings INT,
      entire_med REAL, private_med REAL,
      no_quote_pct REAL, superhost_share REAL, never_reviewed_pct REAL)
    """)
    aug_src = None
    for code, fname in SNAPSHOTS:
        src = DATA / fname
        c = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        row = c.execute(KPI_SQL).fetchone()
        c.close()
        cur.execute(
            "INSERT INTO monthly_kpis VALUES (?,?,?,?,?,?,?)",
            (code, int(row[0]), float(row[1]), float(row[2]),
             float(row[3]), float(row[4]), float(row[5])))
        print(f"  {code}: listings={row[0]}, entire_med={row[1]:.2f}, "
              f"private_med={row[2]:.2f}, no_quote={row[3]:.1f}%")
        if code == "2026-08":
            aug_src = str(src)

    # --- August-only precomputed aggregates ----------------------------------
    aug = sqlite3.connect(f"file:{aug_src}?mode=ro", uri=True)

    cur.execute("""
    CREATE TABLE calendar_monthly (cal_month TEXT, pct_available REAL)
    """)
    cur.executemany(
        "INSERT INTO calendar_monthly VALUES (?,?)",
        aug.execute("""
        SELECT strftime('%Y-%m', date) AS cal_month,
               ROUND(SUM(available) * 100.0 / COUNT(*), 1) AS pct_available
        FROM calendar GROUP BY cal_month ORDER BY cal_month"""))

    cur.execute("""
    CREATE TABLE calendar_occupancy_neighbourhood (
      nb TEXT, listings INT, true_occ_pct REAL, est_occ_pct REAL)
    """)
    cur.executemany(
        "INSERT INTO calendar_occupancy_neighbourhood VALUES (?,?,?,?)",
        aug.execute("""
        WITH occ AS (
          SELECT l.id, l.neighbourhood_cleansed AS nb, l.estimated_occupancy_l365d,
                 SUM(1 - c.available) * 100.0 / COUNT(*) AS true_occ
          FROM calendar c JOIN listings l ON l.id = c.listing_id
          GROUP BY l.id)
        SELECT nb, COUNT(*) AS listings,
               ROUND(AVG(true_occ), 1) AS true_occ_pct,
               ROUND(AVG(estimated_occupancy_l365d) * 100.0 / 365, 1) AS est_occ_pct
        FROM occ GROUP BY nb HAVING listings >= 20
        ORDER BY true_occ_pct DESC LIMIT 10"""))

    true_occ = aug.execute(
        "SELECT SUM(1 - available) * 100.0 / COUNT(*) FROM calendar").fetchone()[0]
    min_nights = aug.execute("""
        SELECT CASE WHEN minimum_nights <= 1 THEN '1 night'
                    WHEN minimum_nights <= 7 THEN '2–7 nights'
                    WHEN minimum_nights <= 30 THEN '8–30 nights'
                    ELSE '31+ nights' END AS band,
               ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM listings), 1) AS pct
        FROM listings GROUP BY band""").fetchall()
    cur.execute("""
    CREATE TABLE calendar_summary (
      city_true_occ_pct REAL,
      min_nights_1 REAL, min_nights_2_7 REAL,
      min_nights_8_30 REAL, min_nights_31plus REAL)
    """)
    bands = {b: p for b, p in min_nights}
    cur.execute("INSERT INTO calendar_summary VALUES (?,?,?,?,?)", (
        round(true_occ, 1),
        bands.get("1 night", 0.0), bands.get("2–7 nights", 0.0),
        bands.get("8–30 nights", 0.0), bands.get("31+ nights", 0.0)))
    print(f"  calendar: city true occupancy = {true_occ:.1f}%")

    cur.execute("""
    CREATE TABLE review_volume (review_month TEXT, reviews INT)
    """)
    cur.executemany(
        "INSERT INTO review_volume VALUES (?,?)",
        aug.execute("""
        SELECT strftime('%Y-%m', date) AS review_month, COUNT(*) AS reviews
        FROM reviews GROUP BY review_month ORDER BY review_month"""))

    cur.execute("""
    CREATE TABLE velocity_top AS
    SELECT name, neighbourhood_cleansed AS nb, room_type,
           ROUND(price, 2) AS price,
           ROUND(reviews_per_month, 2) AS reviews_pm,
           number_of_reviews AS reviews
    FROM listings_slim
    WHERE month = '2026-08'
      AND number_of_reviews >= 20 AND reviews_per_month IS NOT NULL
    ORDER BY reviews_per_month DESC LIMIT 15
    """)
    aug.close()

    out.commit()
    out.execute("VACUUM")
    out.close()

    size_mb = OUT.stat().st_size / 1e6
    print(f"\nBundle written: {OUT}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
