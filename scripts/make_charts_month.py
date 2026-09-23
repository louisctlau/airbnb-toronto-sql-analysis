#!/usr/bin/env python3
"""Generate portfolio-quality charts for the Toronto Airbnb SQL analysis.

Queries the SQLite db with SQL matching sql/03_analysis.sql semantics
(price > 0 filters, window-function medians) and renders 6 PNGs to
docs/charts/ (150 dpi). Prints underlying numbers to stdout for verification.

Usage: python3 scripts/make_charts_month.py --db <db> --outdir <dir> --label "<label>"
"""
import sqlite3
from pathlib import Path

import argparse

import matplotlib
matplotlib.use("Agg")
_p = argparse.ArgumentParser()
_p.add_argument("--db", required=True, help="path to sqlite db")
_p.add_argument("--outdir", required=True, help="chart output dir")
_p.add_argument("--label", required=True, help='e.g. "July 2026"')
args = _p.parse_args()
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent.parent
DB = Path(args.db)
OUT = Path(args.outdir)
OUT.mkdir(parents=True, exist_ok=True)
label = args.label

# --- clean, consistent style ------------------------------------------------
plt.rcParams.update({
    "figure.dpi": 150,
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linestyle": "--",
})
BLUE = "#2b6cb0"
TEAL = "#2c7a7b"
ORANGE = "#dd6b20"
GREEN = "#38a169"
PURPLE = "#6b46c1"
GRAY = "#718096"

def cad(x, pos=None):
    return f"${x:,.0f}"

def cad0(x):
    return f"${x:,.0f}"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

MEDIAN_CTE = """
WITH ranked AS (
    SELECT {part_col} AS grp, price,
           ROW_NUMBER() OVER (PARTITION BY {part_col} ORDER BY price) AS rn,
           COUNT(*)     OVER (PARTITION BY {part_col})                 AS cnt
    FROM listings
    WHERE price > 0 {extra}
),
med AS (
    SELECT grp, AVG(price) AS median_price
    FROM ranked
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY grp
)
"""

def save(fig, name):
    path = OUT / name
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    try:
        print(f"saved {path.relative_to(ROOT)}")
    except ValueError:
        print(f"saved {path}")

# ---------------------------------------------------------------------------
# 1. listings_by_neighbourhood.png — top 15 by listing count (A1 semantics)
# ---------------------------------------------------------------------------
rows = cur.execute("""
WITH nb AS (
    SELECT neighbourhood_cleansed AS nb,
           COUNT(*)               AS listings,
           AVG(price)             AS avg_price
    FROM listings
    WHERE price > 0
    GROUP BY neighbourhood_cleansed
),
med AS (
    SELECT nb, AVG(price) AS median_price
    FROM (
        SELECT neighbourhood_cleansed AS nb, price,
               ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed ORDER BY price) AS rn,
               COUNT(*)     OVER (PARTITION BY neighbourhood_cleansed)                 AS cnt
        FROM listings
        WHERE price > 0
    )
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY nb
)
SELECT nb.nb AS neighbourhood,
       nb.listings,
       ROUND(100.0 * nb.listings / SUM(nb.listings) OVER (), 1) AS pct,
       ROUND(nb.avg_price, 2)     AS avg_price,
       ROUND(med.median_price, 2) AS median_price
FROM nb JOIN med ON med.nb = nb.nb
ORDER BY nb.listings DESC
LIMIT 15
""").fetchall()

names = [r["neighbourhood"] for r in rows]
counts = [r["listings"] for r in rows]
pcts = [r["pct"] for r in rows]
print("\n[1] Top-15 neighbourhoods by listing count:")
for r in rows:
    print(f"    {r['neighbourhood']}: {r['listings']} listings ({r['pct']}%), median ${r['median_price']}")

fig, ax = plt.subplots(figsize=(9, 6))
y = range(len(names))
ax.barh(list(y), counts, color=BLUE, height=0.6)
ax.set_yticks(list(y))
ax.set_yticklabels(names)
ax.invert_yaxis()
ax.set_xlabel("Listings")
ax.set_title(f"Toronto Airbnb supply — top 15 neighbourhoods\n(Inside Airbnb snapshot, {label})")
ax.xaxis.grid(True, alpha=0.25)
# annotate Waterfront's share
i = names.index("Waterfront Communities-The Island")
ax.annotate(f"{counts[i]:,} listings — {pcts[i]:.1f}% of city supply",
            xy=(counts[i], i), xytext=(counts[i] + 90, i - 0.35),
            fontsize=9, color="#1a202c",
            arrowprops=dict(arrowstyle="->", color="#1a202c", lw=1.2))
ax.set_xlim(0, max(counts) * 1.45)
save(fig, "listings_by_neighbourhood.png")

# ---------------------------------------------------------------------------
# 2. median_price_by_room_type.png — window-function medians (Q3 semantics)
# ---------------------------------------------------------------------------
rows = cur.execute(MEDIAN_CTE.format(part_col="room_type", extra="") + """
SELECT grp AS room_type, ROUND(median_price, 2) AS median_price
FROM med
ORDER BY median_price DESC
""").fetchall()
ns = cur.execute("SELECT room_type, COUNT(*) n FROM listings WHERE price > 0 GROUP BY room_type").fetchall()
nmap = {r["room_type"]: r["n"] for r in ns}
print("\n[2] Median nightly price by room type (price > 0):")
for r in rows:
    print(f"    {r['room_type']}: ${r['median_price']} (n={nmap[r['room_type']]})")

labels = [r["room_type"] for r in rows]
vals = [r["median_price"] for r in rows]
fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.bar(labels, vals, color=[BLUE, TEAL, ORANGE, GRAY], width=0.55)
ax.set_ylabel("Median nightly price (CAD)")
ax.set_title(f"Median nightly price by room type\n(Inside Airbnb snapshot, {label})")
ax.yaxis.set_major_formatter(FuncFormatter(cad))
for b, v, lab in zip(bars, vals, labels):
    ax.text(b.get_x() + b.get_width() / 2, v + 6, cad0(v),
            ha="center", fontsize=10, fontweight="bold")
ax.set_ylim(0, max(vals) * 1.18)
plt.xticks(rotation=12, ha="right")
save(fig, "median_price_by_room_type.png")

# ---------------------------------------------------------------------------
# 3. superhost_vs_regular.png — grouped bars (A3 semantics)
# ---------------------------------------------------------------------------
rows = cur.execute("""
SELECT CASE WHEN host_is_superhost = 1 THEN 'Superhost'
            WHEN host_is_superhost = 0 THEN 'Regular host'
            ELSE 'Unknown' END AS host_type,
       COUNT(*) AS listings,
       AVG(price) AS avg_price,
       AVG(review_scores_rating) AS avg_rating,
       AVG(reviews_per_month) AS avg_rpm
FROM listings
WHERE price > 0 AND host_is_superhost IS NOT NULL
GROUP BY host_is_superhost
""").fetchall()
print("\n[3] Superhost vs regular host:")
for r in rows:
    print(f"    {r['host_type']}: n={r['listings']}, avg price ${r['avg_price']:.2f}, "
          f"avg rating {r['avg_rating']:.2f}, reviews/mo {r['avg_rpm']:.2f}")

# normalise each metric to % of the max so all fit one axis; annotate values
metrics = [
    ("Avg nightly price (CAD)", [r["avg_price"] for r in rows], [BLUE, GRAY], cad0),
    ("Avg rating (★)", [r["avg_rating"] for r in rows], [BLUE, GRAY], lambda v: f"{v:.2f}"),
    ("Reviews / month", [r["avg_rpm"] for r in rows], [BLUE, GRAY], lambda v: f"{v:.2f}"),
]
labels = [r["host_type"] for r in rows]
fig, axes = plt.subplots(1, 3, figsize=(10, 4), sharey=False)
fig.suptitle(f"Superhost vs regular host ({label} snapshot)", fontweight="bold", fontsize=13)
for ax, (title, vals, cols, fmt) in zip(axes, metrics):
    bars = ax.bar(labels, vals, color=cols, width=0.55)
    ax.set_title(title, fontsize=10)
    ax.set_ylim(0, max(vals) * 1.25)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + max(vals) * 0.03, fmt(v),
                ha="center", fontsize=10, fontweight="bold")
save(fig, "superhost_vs_regular.png")

# ---------------------------------------------------------------------------
# 4. price_by_rating_band.png — (A4 semantics)
# ---------------------------------------------------------------------------
rows = cur.execute("""
SELECT CASE
         WHEN review_scores_rating IS NULL THEN 'No rating yet'
         WHEN review_scores_rating < 4.5  THEN 'Below 4.50'
         WHEN review_scores_rating < 4.8  THEN '4.50 – 4.79'
         ELSE '4.80 – 5.00'
       END AS rating_band,
       COUNT(*) AS listings,
       AVG(price) AS avg_price
FROM listings
WHERE price > 0
GROUP BY rating_band
""").fetchall()
order = {"No rating yet": 0, "Below 4.50": 1, "4.50 – 4.79": 2, "4.80 – 5.00": 3}
rows = sorted(rows, key=lambda r: order[r["rating_band"]])
print("\n[4] Avg nightly price by rating band:")
for r in rows:
    print(f"    {r['rating_band']}: n={r['listings']}, avg ${r['avg_price']:.2f}")

labels = [r["rating_band"] for r in rows]
vals = [r["avg_price"] for r in rows]
fig, ax = plt.subplots(figsize=(8.5, 5))
colors = [GRAY, "#e53e3e", ORANGE, GREEN]
bars = ax.bar(labels, vals, color=colors, width=0.6)
ax.set_ylabel("Average nightly price (CAD)")
ax.set_title(f"Higher ratings command higher prices\n(Toronto Airbnb, {label})")
ax.yaxis.set_major_formatter(FuncFormatter(cad))
ax.set_ylim(0, max(vals) * 1.18)
for b, v, r in zip(bars, vals, rows):
    ax.text(b.get_x() + b.get_width() / 2, v + 5, f"{cad0(v)}\nn={r['listings']:,}",
            ha="center", fontsize=9, fontweight="bold")
save(fig, "price_by_rating_band.png")

# ---------------------------------------------------------------------------
# 5. occupancy_by_availability.png — (A5 semantics)
# ---------------------------------------------------------------------------
rows = cur.execute("""
SELECT CASE
         WHEN availability_365 <= 30  THEN '0–30 days'
         WHEN availability_365 <= 90  THEN '31–90 days'
         WHEN availability_365 <= 180 THEN '91–180 days'
         WHEN availability_365 <= 300 THEN '181–300 days'
         ELSE '301–365 days'
       END AS band,
       COUNT(*) AS listings,
       AVG(estimated_occupancy_l365d) AS avg_occ_days,
       AVG(100.0 * estimated_occupancy_l365d / 365) AS occ_pct
FROM listings
WHERE availability_365 IS NOT NULL
GROUP BY band
ORDER BY MIN(availability_365)
""").fetchall()
print("\n[5] Occupancy by availability band (Inside Airbnb estimates):")
for r in rows:
    print(f"    {r['band']}: n={r['listings']}, avg occupied {r['avg_occ_days']:.1f} days/yr "
          f"({r['occ_pct']:.1f}% implied)")

bands = [r["band"] for r in rows]
occ = [r["occ_pct"] for r in rows]
days = [r["avg_occ_days"] for r in rows]
fig, ax = plt.subplots(figsize=(9, 5))
bars = ax.bar(bands, occ, color=TEAL, width=0.55)
ax.set_ylabel("Implied occupancy (%)")
ax.set_xlabel("Days available in next 365 days")
ax.set_title(f"Occupancy is highest in the mid-availability sweet spot\n(Inside Airbnb estimates, {label})")
ax.set_ylim(0, max(occ) * 1.35)
for b, p, d, r in zip(bars, occ, days, rows):
    ax.text(b.get_x() + b.get_width() / 2, p + 0.4,
            f"{p:.1f}%\n({d:.0f} days)\nn={r['listings']:,}",
            ha="center", fontsize=9, fontweight="bold")
save(fig, "occupancy_by_availability.png")

# ---------------------------------------------------------------------------
# 6. bedroom_marginal_cost.png — bars + LAG() line (A9 semantics)
# ---------------------------------------------------------------------------
rows = cur.execute("""
SELECT CAST(bedrooms AS INTEGER) AS bedrooms,
       COUNT(*) AS listings,
       AVG(price) AS avg_price,
       AVG(price) - LAG(AVG(price)) OVER (ORDER BY CAST(bedrooms AS INTEGER)) AS marginal
FROM listings
WHERE room_type = 'Entire home/apt'
  AND price > 0
  AND bedrooms BETWEEN 0 AND 5
GROUP BY bedrooms
ORDER BY bedrooms
""").fetchall()
rows = [r for r in rows if r["bedrooms"] >= 1]  # drop n=1 zero-bedroom row
print("\n[6] Bedroom economics (entire homes/apts only):")
for r in rows:
    m = f"+${r['marginal']:.2f}" if r["marginal"] is not None else "—"
    print(f"    {r['bedrooms']} bd: n={r['listings']}, avg ${r['avg_price']:.2f}, marginal {m}")

beds = [r["bedrooms"] for r in rows]
avgs = [r["avg_price"] for r in rows]
margs = [r["marginal"] if r["marginal"] is not None else 0 for r in rows]

fig, ax1 = plt.subplots(figsize=(9, 5))
bars = ax1.bar(beds, avgs, color=BLUE, width=0.55, label="Avg nightly price")
ax1.set_xlabel("Bedrooms")
ax1.set_ylabel("Average nightly price (CAD)")
ax1.yaxis.set_major_formatter(FuncFormatter(cad))
ax1.set_xticks(beds)

ax2 = ax1.twinx()
line = ax2.plot(beds, margs, color=ORANGE, marker="o", linewidth=2.5,
                markersize=7, label="Marginal cost of extra bedroom")
ax2.set_ylabel("Marginal cost of extra bedroom (CAD)")
ax2.yaxis.set_major_formatter(FuncFormatter(cad))
ax2.spines["top"].set_visible(False)
for x, m in zip(beds[1:], margs[1:]):
    ax2.annotate(f"+{cad0(m)}", xy=(x, m), xytext=(4, 12),
                 textcoords="offset points", fontsize=9, fontweight="bold", color="#9c4221")

ax1.set_title(f"Each extra bedroom costs more than the last\n(entire homes/apts, Toronto, {label})")
ax1.set_ylim(0, max(avgs) * 1.12)
ax1.legend([bars, line[0]], ["Avg nightly price", "Marginal cost of extra bedroom"],
           loc="upper left", frameon=False, fontsize=9)
save(fig, "bedroom_marginal_cost.png")

print("\nDone — 6 charts written to", OUT)
