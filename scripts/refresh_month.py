#!/usr/bin/env python3
"""Monthly refresh for the Toronto Airbnb SQL analysis project.

Runs the full pipeline for the newest available Inside Airbnb Toronto
snapshot: detect the latest release, download listings.csv.gz, build a
SQLite db, run the exploration + analysis queries, regenerate charts,
write a findings report skeleton (numbers only — prose gets a human
pass later), update the README, commit locally, and push to GitHub
through the API-based route (git-over-HTTPS does not work with the
stored credential).

Usage:
    python3 scripts/refresh_month.py            # process the newest available month
    python3 scripts/refresh_month.py --month 2026-10   # force a specific month (testing)
    python3 scripts/refresh_month.py --dry-run   # everything except GitHub push + README write

Stdlib only (plus sqlite3 + the repo's existing matplotlib dep for charts).
Idempotent: re-running for an already-processed month exits cleanly.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import logging
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SQL = ROOT / "sql"
DOCS = ROOT / "docs"
SCRIPTS = ROOT / "scripts"
LOGS = ROOT / "logs"

OWNER, REPO, GH_BRANCH = "louisctlau", "airbnb-toronto-sql-analysis", "main"
IA_BASE = "https://data.insideairbnb.com/canada/on/toronto"
CRED_HELPER = "/opt/hatch/skills/skill-creator/bin/dynamic_credentials.py"

# Probe this many days around the 15th when looking for a month's release.
PROBE_DAYS = [15, 16, 14, 13, 17, 12, 18]

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


# --------------------------------------------------------------------------
# logging
# --------------------------------------------------------------------------
def setup_logging(month: str) -> logging.Logger:
    LOGS.mkdir(exist_ok=True)
    log = logging.getLogger("refresh_month")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(LOGS / f"refresh-{month}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


# --------------------------------------------------------------------------
# 1. release detection + download
# --------------------------------------------------------------------------
def url_exists(url: str) -> bool:
    """True if the URL answers 2xx. Tries HEAD, falls back to a 1-byte range GET."""
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method)
            if method == "GET":
                req.add_header("Range", "bytes=0-0")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return False
        except Exception:
            pass
    return False


def detect_release(target: str | None, log: logging.Logger) -> str | None:
    """Return the release date 'YYYY-MM-DD' of the newest available snapshot.

    Without --month: probe the current month, then the two previous months.
    With --month: probe only that month.
    Returns None when no release is found (not an error — exit 0).
    """
    if target:
        y, m = map(int, target.split("-"))
        months = [(y, m)]
    else:
        today = date.today()
        months = []
        y, m = today.year, today.month
        for _ in range(3):
            months.append((y, m))
            m -= 1
            if m == 0:
                m, y = 12, y - 1
    for y, m in months:
        for day in PROBE_DAYS:
            rel = f"{y:04d}-{m:02d}-{day:02d}"
            url = f"{IA_BASE}/{rel}/data/listings.csv.gz"
            log.info("probing %s", url)
            if url_exists(url):
                log.info("found release %s", rel)
                return rel
        log.info("no release found for %04d-%02d", y, m)
    log.info("no new release published yet — nothing to do")
    return None


def month_paths(release: str) -> dict:
    y, m, _ = release.split("-")
    ym = f"{y}-{m}"
    return {
        "release": release,
        "month": ym,
        "label": f"{MONTH_NAMES[int(m) - 1]} {y}",
        "csv_gz": DATA / f"listings-{ym}.csv.gz",
        "csv": DATA / f"listings-{ym}.csv",
        "db": DATA / f"airbnb_toronto_{y}_{m}.db",
        "setup_sql": SQL / f"01_setup-{ym}.sql",
        "query_output": DOCS / f"query_output-{ym}.txt",
        "findings": DOCS / f"findings-{ym}.md",
        "metrics": DOCS / f"metrics-{ym}.json",
        "charts_dir": DOCS / "charts" / ym,
    }


def download_release(release: str, dest: Path, log: logging.Logger) -> None:
    """Download listings.csv.gz with one retry; validate gzip + header schema."""
    url = f"{IA_BASE}/{release}/data/listings.csv.gz"
    for attempt in (1, 2):
        try:
            log.info("downloading %s (attempt %d)", url, attempt)
            req = urllib.request.Request(url, headers={"User-Agent": "refresh_month.py/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
                shutil.copyfileobj(resp, f, length=1024 * 1024)
            break
        except Exception as e:
            log.warning("download attempt %d failed: %s", attempt, e)
            if attempt == 2:
                log.error("download failed twice — exiting 1")
                sys.exit(1)
            time.sleep(5)
    # validate: gzip integrity + 90-column header identical to a known snapshot
    try:
        with gzip.open(dest, "rt", encoding="utf-8") as f:
            header = f.readline().rstrip("\n")
    except Exception as e:
        log.error("gzip corrupt: %s — exiting 1", e)
        dest.unlink(missing_ok=True)
        sys.exit(1)
    canonical = DATA / "listings-2026-09.csv"
    ref_header = canonical.open(encoding="utf-8").readline().rstrip("\n") if canonical.exists() else None
    ncols = len(header.split(","))
    if ref_header is not None and header != ref_header:
        log.error("header mismatch vs 2026-09 snapshot (%d vs 90 expected cols) — exiting 1", ncols)
        sys.exit(1)
    log.info("download OK: %d bytes, header has %d columns", dest.stat().st_size, ncols)
    # keep the decompressed csv too (matches existing months)
    csv_path = dest.with_suffix("").with_suffix(".csv")  # listings-2026-10.csv
    with gzip.open(dest, "rb") as src, open(csv_path, "wb") as f:
        shutil.copyfileobj(src, f, length=1024 * 1024)
    log.info("decompressed to %s", csv_path.name)


# --------------------------------------------------------------------------
# 2. database build + query runs + charts
# --------------------------------------------------------------------------
def write_setup_sql(paths: dict, log: logging.Logger) -> None:
    """Generate sql/01_setup-<month>.sql from the September template."""
    template = (SQL / "01_setup-2026-09.sql").read_text(encoding="utf-8")
    month, release = paths["month"], paths["release"]
    csv_name = paths["csv"].name
    db_name = paths["db"].name
    new_sql_name = paths["setup_sql"].name

    subs = [
        ("Snapshot: 2026-09 release", f"Snapshot: {release} release"),
        ("listings-2026-09.csv", csv_name),
        ("sqlite3 data/airbnb_toronto.db < sql/01_setup.sql",
         f"sqlite3 data/{db_name} < sql/{new_sql_name}"),
        ("01_setup.sql — Toronto Airbnb Listings", f"{new_sql_name} — Toronto Airbnb Listings"),
    ]
    for old, new in subs:
        if old not in template:
            log.error("setup template substitution failed for %r — exiting 1", old[:60])
            sys.exit(1)
        template = template.replace(old, new)
    paths["setup_sql"].write_text(template, encoding="utf-8")
    log.info("wrote %s", paths["setup_sql"].name)


def run_sqlite(db: Path, sql_file: Path, log: logging.Logger, capture: Path | None = None) -> None:
    """Pipe a .sql file into the sqlite3 CLI (handles .mode/.import dot-commands)."""
    log.info("running %s -> %s", sql_file.name, db.name)
    with open(sql_file, "rb") as stdin:
        proc = subprocess.run(
            ["sqlite3", str(db)], stdin=stdin,
            capture_output=True, text=True, timeout=1800, cwd=ROOT,
        )
    if proc.returncode != 0:
        log.error("%s failed (rc=%d):\n%s", sql_file.name, proc.returncode, proc.stderr[-3000:])
        sys.exit(1)
    if capture:
        capture.write_text(proc.stdout, encoding="utf-8")
        log.info("saved %s (%d bytes)", capture.name, len(proc.stdout))
    elif proc.stdout.strip():
        log.info("output: %s", proc.stdout.strip()[-500:])


def run_charts(paths: dict, log: logging.Logger) -> None:
    cmd = [sys.executable, str(SCRIPTS / "make_charts_month.py"),
           "--db", str(paths["db"]),
           "--outdir", str(paths["charts_dir"]),
           "--label", paths["label"]]
    log.info("generating charts: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, cwd=ROOT)
    if proc.returncode != 0:
        log.error("chart generation failed:\n%s", proc.stderr[-3000:])
        sys.exit(1)
    pngs = sorted(paths["charts_dir"].glob("*.png"))
    if len(pngs) < 6:
        log.error("expected 6 charts, got %d — exiting 1", len(pngs))
        sys.exit(1)
    log.info("charts OK: %s", ", ".join(p.name for p in pngs))
    log.info("chart script printed:\n%s", proc.stdout.strip()[-2000:])


# --------------------------------------------------------------------------
# 3. metrics collection (window-function medians, same semantics as 03_analysis.sql)
# --------------------------------------------------------------------------
MEDIAN_CTE = """
WITH ranked AS (
    SELECT price,
           ROW_NUMBER() OVER (ORDER BY price) AS rn,
           COUNT(*)     OVER ()              AS cnt
    FROM listings
    WHERE price > 0 {extra}
),
m AS (
    SELECT AVG(price) AS med FROM ranked WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
)"""


def collect_metrics(db_path: Path, log: logging.Logger) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    q = lambda sql, *a: [dict(r) for r in cur.execute(sql, a)]

    m: dict = {}
    m["listings"] = cur.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    row = cur.execute("SELECT MIN(last_scraped), MAX(last_scraped) FROM listings").fetchone()
    m["earliest_scrape"], m["latest_scrape"] = row[0], row[1]
    r = cur.execute(
        "SELECT COUNT(*) t, SUM(price IS NULL) mp, SUM(first_review IS NULL) nr "
        "FROM listings").fetchone()
    m["missing_price"], m["pct_missing_price"] = r[1], round(100.0 * r[1] / r[0], 1)
    m["never_reviewed"] = r[2]
    m["room_mix"] = q(
        "SELECT room_type, COUNT(*) n, ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),1) pct "
        "FROM listings GROUP BY room_type ORDER BY n DESC")

    def median(extra=""):
        return cur.execute(
            MEDIAN_CTE.format(extra=extra) + " SELECT ROUND(med, 2) FROM m").fetchone()[0]

    m["entire_median"] = median("AND room_type = 'Entire home/apt'")
    m["private_median"] = median("AND room_type = 'Private room'")
    m["premium_ratio"] = round(m["entire_median"] / m["private_median"], 2)

    m["superhost"] = q(
        "SELECT CASE host_is_superhost WHEN 1 THEN 'Superhost' WHEN 0 THEN 'Regular host' "
        "ELSE 'Unknown' END AS host_type, COUNT(*) AS n, "
        "ROUND(AVG(price),2) AS avg_price, ROUND(AVG(review_scores_rating),2) AS avg_rating, "
        "ROUND(AVG(reviews_per_month),2) AS avg_reviews_per_month, "
        "ROUND(AVG(number_of_reviews),1) AS avg_total_reviews "
        "FROM listings WHERE price > 0 GROUP BY host_is_superhost")

    m["rating_bands"] = q(
        "SELECT CASE WHEN review_scores_rating IS NULL THEN 'No rating yet' "
        "WHEN review_scores_rating >= 4.8 THEN '4.80 - 5.00' "
        "WHEN review_scores_rating >= 4.5 THEN '4.50 - 4.79' ELSE 'Below 4.50' END AS band, "
        "COUNT(*) n, ROUND(AVG(price),2) avg_price, ROUND(AVG(number_of_reviews),1) avg_reviews "
        "FROM listings WHERE price > 0 GROUP BY band "
        "ORDER BY CASE band WHEN '4.80 - 5.00' THEN 1 WHEN 'No rating yet' THEN 2 "
        "WHEN '4.50 - 4.79' THEN 3 ELSE 4 END")

    m["availability"] = q(
        "SELECT CASE WHEN availability_365 <= 30 THEN '0-30 days' "
        "WHEN availability_365 <= 90 THEN '31-90 days' "
        "WHEN availability_365 <= 180 THEN '91-180 days' "
        "WHEN availability_365 <= 300 THEN '181-300 days' ELSE '301-365 days' END AS band, "
        "COUNT(*) n, ROUND(AVG(estimated_occupancy_l365d),1) avg_occ_days, "
        "ROUND(100.0*AVG(estimated_occupancy_l365d)/365,1) implied_pct "
        "FROM listings WHERE availability_365 IS NOT NULL AND price > 0 GROUP BY band "
        "ORDER BY CASE band WHEN '0-30 days' THEN 1 WHEN '31-90 days' THEN 2 "
        "WHEN '91-180 days' THEN 3 WHEN '181-300 days' THEN 4 ELSE 5 END")

    m["neighbourhoods"] = q(
        "SELECT neighbourhood_cleansed nb, COUNT(*) n, "
        "ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (),2) pct_supply, "
        "ROUND(AVG(price),2) avg_price FROM listings WHERE price > 0 "
        "GROUP BY nb ORDER BY n DESC LIMIT 15")
    # per-neighbourhood medians (window-function semantics)
    nb_med = {}
    for row_ in cur.execute(
            "SELECT nb, AVG(price) FROM ("
            " SELECT neighbourhood_cleansed nb, price,"
            " ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed ORDER BY price) rn,"
            " COUNT(*) OVER (PARTITION BY neighbourhood_cleansed) cnt"
            " FROM listings WHERE price > 0)"
            " WHERE rn IN ((cnt+1)/2,(cnt+2)/2) GROUP BY nb"):
        nb_med[row_[0]] = round(row_[1], 2)
    for n in m["neighbourhoods"]:
        n["median_price"] = nb_med.get(n["nb"])

    m["host_concentration"] = q(
        "WITH h AS (SELECT host_id, COUNT(*) n FROM listings WHERE price > 0 GROUP BY host_id) "
        "SELECT CASE WHEN n = 1 THEN '1 listing' WHEN n <= 5 THEN '2-5 listings' "
        "ELSE '6+ listings' END AS band, COUNT(*) hosts, SUM(n) listings, "
        "ROUND(100.0*SUM(n)/SUM(SUM(n)) OVER (),1) pct_supply "
        "FROM h GROUP BY band "
        "ORDER BY CASE band WHEN '1 listing' THEN 1 WHEN '2-5 listings' THEN 2 ELSE 3 END")
    host_avg = q(
        "WITH h AS (SELECT host_id, COUNT(*) n FROM listings WHERE price > 0 GROUP BY host_id) "
        "SELECT CASE WHEN n = 1 THEN '1 listing' WHEN n <= 5 THEN '2-5 listings' "
        "ELSE '6+ listings' END AS band, ROUND(AVG(l.price),2) avg_price "
        "FROM listings l JOIN h ON l.host_id = h.host_id WHERE l.price > 0 GROUP BY band")
    avg_map = {r["band"]: r["avg_price"] for r in host_avg}
    for r in m["host_concentration"]:
        r["avg_price"] = avg_map.get(r["band"])

    m["bedrooms"] = q(
        "WITH b AS (SELECT CAST(bedrooms AS INTEGER) bd, AVG(price) ap, COUNT(*) n "
        "FROM listings WHERE price > 0 AND room_type = 'Entire home/apt' "
        "AND bedrooms IS NOT NULL AND bedrooms BETWEEN 0 AND 5 GROUP BY bd) "
        "SELECT bd, n, ROUND(ap,2) avg_price, "
        "ROUND(ap - LAG(ap) OVER (ORDER BY bd), 2) marginal FROM b ORDER BY bd")

    m["revenue_leaders"] = q(
        "SELECT neighbourhood_cleansed nb, COUNT(*) n, "
        "ROUND(AVG(estimated_revenue_l365d),0) avg_rev, "
        "ROUND(AVG(estimated_occupancy_l365d),1) avg_occ_days "
        "FROM listings WHERE price > 0 AND estimated_revenue_l365d IS NOT NULL "
        "GROUP BY nb ORDER BY avg_rev DESC LIMIT 10")

    m["top_reviewed"] = q(
        "SELECT number_of_reviews, name, neighbourhood_cleansed nb, room_type, price, "
        "review_scores_rating rating FROM listings "
        "ORDER BY number_of_reviews DESC LIMIT 20")
    m["private_rooms_in_top20"] = sum(1 for r in m["top_reviewed"]
                                      if r["room_type"] == "Private room")

    m["seasonality"] = q(
        "SELECT SUBSTR(last_review,1,7) ym, COUNT(*) n FROM listings "
        "WHERE last_review IS NOT NULL GROUP BY ym ORDER BY ym DESC LIMIT 24")

    m["value_picks"] = q(
        "WITH nb_median AS (SELECT neighbourhood_cleansed nb, AVG(price) med FROM ("
        " SELECT neighbourhood_cleansed, price,"
        " ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed ORDER BY price) rn,"
        " COUNT(*) OVER (PARTITION BY neighbourhood_cleansed) cnt"
        " FROM listings WHERE price > 0 AND room_type = 'Entire home/apt')"
        " WHERE rn IN ((cnt+1)/2,(cnt+2)/2) GROUP BY neighbourhood_cleansed) "
        "SELECT l.name, l.neighbourhood_cleansed nb, l.price, ROUND(nm.med,2) nb_median, "
        "l.review_scores_rating rating, l.number_of_reviews reviews "
        "FROM listings l JOIN nb_median nm ON l.neighbourhood_cleansed = nm.nb "
        "WHERE l.room_type = 'Entire home/apt' AND l.price > 0 "
        "AND l.review_scores_rating >= 4.8 AND l.number_of_reviews >= 20 "
        "AND l.price < nm.med ORDER BY l.review_scores_rating DESC, l.number_of_reviews DESC LIMIT 8")

    con.close()
    log.info("collected metrics: %d listings, entire median $%s, private median $%s",
             m["listings"], m["entire_median"], m["private_median"])
    return m


# --------------------------------------------------------------------------
# 4. findings report skeleton (numbers auto-generated, prose skeleton)
# --------------------------------------------------------------------------
def _cad(x) -> str:
    return f"${x:,.2f}" if x is not None else "—"


def _md_table(headers: list, rows: list) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) if c is not None else "—" for c in r) + " |")
    return "\n".join(out)


def previous_metrics(month: str) -> dict | None:
    """Latest metrics-<month>.json older than the current month."""
    cands = sorted(DOCS.glob("metrics-2026-*.json"))
    older = [c for c in cands if c.stem < f"metrics-{month}"]
    if not older:
        return None
    return json.loads(older[-1].read_text(encoding="utf-8"))


def delta(new, old, suffix=""):
    if new is None or old is None:
        return ""
    d = round(new - old, 2)
    sign = "+" if d >= 0 else ""
    return f" ({sign}{d}{suffix} vs {old}{suffix})"


def write_report(paths: dict, metrics: dict, prev: dict | None, log: logging.Logger) -> None:
    month, release, label = paths["month"], paths["release"], paths["label"]
    y, m = month.split("-")
    m2 = metrics
    top5_nb = m2["neighbourhoods"][:5]
    superhost_row = next((r for r in m2["superhost"] if r["host_type"] == "Superhost"), {})
    regular_row = next((r for r in m2["superhost"] if r["host_type"] == "Regular host"), {})
    room_mix_str = ", ".join(f'{r["pct"]}% {r["room_type"].lower()}' for r in m2["room_mix"])
    leader = m2["top_reviewed"][0]
    rev_top5 = m2["revenue_leaders"][:5]

    L = []
    L.append(f"# Findings Report — Toronto Airbnb Listings ({label} snapshot)")
    L.append("")
    L.append("> **Auto-generated draft:** numbers below come from the actual query runs")
    L.append("> for this snapshot; prose is a skeleton awaiting a human pass. Every figure")
    L.append(f"> was verified against `data/{paths['db'].name}` on {date.today()}.")
    L.append("")
    L.append("## 1. Executive summary")
    L.append("")
    L.append(f"{m2['listings']:,} Toronto Airbnb listings (snapshot {release}; rows scraped")
    L.append(f"{m2['earliest_scrape']} → {m2['latest_scrape']}) were cleaned and analysed")
    L.append("with the same 20-query pipeline as the prior monthly reports.")
    L.append("")
    L.append("Headline numbers:")
    L.append("")
    L.append(f"- **Listings:** {m2['listings']:,}")
    L.append(f"- **Entire-home median:** {_cad(m2['entire_median'])}; "
             f"**private-room median:** {_cad(m2['private_median'])}; "
             f"premium **{m2['premium_ratio']}×**")
    L.append(f"- **Superhosts:** {superhost_row.get('avg_price', '—')} avg price, "
             f"{superhost_row.get('avg_rating', '—')} avg rating vs regulars "
             f"{regular_row.get('avg_price', '—')} / {regular_row.get('avg_rating', '—')}")
    L.append(f"- **No price quote:** {m2['pct_missing_price']}% of listings")
    L.append(f"- **Never reviewed:** {m2['never_reviewed']:,} listings")
    L.append("")

    if prev:
        pm = prev.get("_month", "prior")
        L.append(f"> ### vs {pm} snapshot — the biggest month-over-month changes")
        L.append(f"> - **Listings:** {prev['listings']:,} → {m2['listings']:,}"
                 f"{delta(m2['listings'], prev['listings'])}")
        L.append(f"> - **Entire-home median:** {_cad(prev['entire_median'])} → "
                 f"{_cad(m2['entire_median'])}"
                 f"{delta(m2['entire_median'], prev['entire_median'])}; "
                 f"private rooms {_cad(prev['private_median'])} → {_cad(m2['private_median'])}; "
                 f"premium {prev['premium_ratio']} → {m2['premium_ratio']}×")
        L.append(f"> - **No-quote share:** {prev['pct_missing_price']}% → {m2['pct_missing_price']}%")
        ps = next((r for r in prev["superhost"] if r["host_type"] == "Superhost"), {})
        pr = next((r for r in prev["superhost"] if r["host_type"] == "Regular host"), {})
        L.append(f"> - **Superhost pattern:** {ps.get('avg_price', '—')} vs {pr.get('avg_price', '—')} "
                 f"(prior) → {superhost_row.get('avg_price', '—')} vs "
                 f"{regular_row.get('avg_price', '—')} (this month)")
        L.append("")

    L.append("> Verified data profile:")
    L.append(f"> - Listings analysed: {m2['listings']:,}")
    L.append(f"> - Scrape window: {m2['earliest_scrape']} → {m2['latest_scrape']}")
    L.append(f"> - Room-type mix: {room_mix_str}")
    L.append(f"> - {m2['pct_missing_price']}% of listings have no active price quote; "
             f"{m2['never_reviewed']:,} were never reviewed")
    L.append("")
    L.append("## 2. Method")
    L.append("")
    L.append(f"- **Source:** Inside Airbnb detailed listings, Toronto, snapshot {release}")
    L.append(f"  (rows scraped {m2['earliest_scrape']} → {m2['latest_scrape']}). One row per listing; prices in CAD.")
    L.append(f"- **Pipeline:** `sql/{paths['setup_sql'].name}` loads the CSV into a raw staging table")
    L.append("  (all TEXT), then builds the same cleaned, typed `listings` table as prior months.")
    L.append("- **Quality gates:** `sql/02_exploration.sql` run unchanged against the new db.")
    L.append("- **Analysis:** `sql/03_analysis.sql` run unchanged (11 questions).")
    L.append("")
    L.append("## 3. Findings")
    L.append("")
    L.append("### 3.1 Where is the supply? (A1)")
    L.append("")
    L.append("Top 5 neighbourhoods by listing count:")
    L.append("")
    L.append(_md_table(["Neighbourhood", "Listings", "City share", "Avg price", "Median price"],
                       [[r["nb"], r["n"], f'{r["pct_supply"]}%', _cad(r["avg_price"]), _cad(r["median_price"])]
                        for r in top5_nb]))
    L.append("")
    L.append(f"![Listings by neighbourhood](charts/{month}/listings_by_neighbourhood.png)")
    L.append("")
    L.append("### 3.2 The entire-home premium (A2)")
    L.append("")
    L.append(f"Median entire home/apt: **{_cad(m2['entire_median'])}/night**. "
             f"Median private room: **{_cad(m2['private_median'])}**. "
             f"Premium ratio: **{m2['premium_ratio']}×**.")
    L.append("")
    L.append(f"![Median price by room type](charts/{month}/median_price_by_room_type.png)")
    L.append("")
    L.append("### 3.3 Superhost economics (A3)")
    L.append("")
    L.append(_md_table(["Host type", "Listings", "Avg price", "Avg rating", "Reviews/month", "Avg total reviews"],
                       [[r["host_type"], f"{r['n']:,}", _cad(r["avg_price"]), r["avg_rating"],
                         r["avg_reviews_per_month"], r["avg_total_reviews"]] for r in m2["superhost"]]))
    L.append("")
    L.append(f"![Superhost vs regular host](charts/{month}/superhost_vs_regular.png)")
    L.append("")
    L.append("### 3.4 Ratings and price (A4)")
    L.append("")
    L.append(_md_table(["Rating band", "Listings", "Avg price", "Avg reviews"],
                       [[r["band"], f"{r['n']:,}", _cad(r["avg_price"]), r["avg_reviews"]] for r in m2["rating_bands"]]))
    L.append("")
    L.append(f"![Price by rating band](charts/{month}/price_by_rating_band.png)")
    L.append("")
    L.append("### 3.5 Availability and occupancy (A5)")
    L.append("")
    L.append(_md_table(["Availability band", "Listings", "Avg est. occupied days/yr", "Implied occupancy"],
                       [[r["band"], f"{r['n']:,}", r["avg_occ_days"], f'{r["implied_pct"]}%'] for r in m2["availability"]]))
    L.append("")
    L.append("Note: `estimated_occupancy_l365d` is Inside Airbnb's estimate, not observed bookings.")
    L.append("")
    L.append(f"![Occupancy by availability](charts/{month}/occupancy_by_availability.png)")
    L.append("")
    L.append("### 3.6 Review magnets (A6)")
    L.append("")
    L.append(f"Top reviewed listing: \"{leader['name']}\" ({leader['nb']}, {leader['room_type']}, "
             f"{leader['number_of_reviews']:,} reviews, {_cad(leader['price'])}, {leader['rating']}★).")
    L.append(f"{m2['private_rooms_in_top20']} of the top 20 are private rooms.")
    L.append("")
    L.append("### 3.7 Seasonality signal (A7)")
    L.append("")
    L.append("Months with the most listings whose latest review falls in that month:")
    L.append("")
    L.append(_md_table(["Review month", "Listings with latest review"],
                       [[r["ym"], f"{r['n']:,}"] for r in m2["seasonality"][:8]]))
    L.append("")
    L.append("Caveat: this measures *recency of the latest review*, a rough activity proxy, not true demand.")
    L.append("")
    L.append("### 3.8 Who owns the supply? (A8)")
    L.append("")
    L.append(_md_table(["Host size band", "Hosts", "Listings", "% of supply", "Avg listing price"],
                       [[r["band"], f"{r['hosts']:,}", f"{r['listings']:,}", f'{r["pct_supply"]}%', _cad(r["avg_price"])]
                        for r in m2["host_concentration"]]))
    L.append("")
    L.append("### 3.9 Bedroom economics (A9)")
    L.append("")
    L.append("Entire homes only. Marginal cost computed with `LAG()`:")
    L.append("")
    L.append(_md_table(["Bedrooms", "Listings", "Avg price", "Marginal cost of extra bedroom"],
                       [[r["bd"], f"{r['n']:,}", _cad(r["avg_price"]),
                         f'+{_cad(r["marginal"])}' if r["marginal"] is not None else "—"] for r in m2["bedrooms"]]))
    L.append("")
    L.append(f"![Bedroom marginal cost](charts/{month}/bedroom_marginal_cost.png)")
    L.append("")
    L.append("### 3.10 Revenue leaders (A10)")
    L.append("")
    L.append("Top 5 neighbourhoods by avg estimated annual revenue per listing:")
    L.append("")
    L.append(_md_table(["Neighbourhood", "Listings", "Avg est. annual revenue", "Avg est. occupancy days"],
                       [[r["nb"], r["n"], f'${r["avg_rev"]:,.0f}', r["avg_occ_days"]] for r in rev_top5]))
    L.append("")
    L.append("### 3.11 Best-value picks (A11)")
    L.append("")
    L.append("Highly-rated (4.8★+, 20+ reviews) entire homes priced below their neighbourhood median:")
    L.append("")
    L.append(_md_table(["Name", "Neighbourhood", "Price", "NB median", "Rating", "Reviews"],
                       [[(r["name"] or "")[:60], r["nb"], _cad(r["price"]), _cad(r["nb_median"]),
                         r["rating"], r["reviews"]] for r in m2["value_picks"]]))
    L.append("")
    L.append("## 4. Limitations")
    L.append("")
    L.append("- **Single snapshot:** no true time series; occupancy/revenue are modelled")
    L.append("  estimates from one scrape, and `price` is a quoted nightly rate, not a transacted price.")
    L.append(f"- **Missing prices ({m2['pct_missing_price']}%):** listings without an active quote are excluded")
    L.append("  from price math.")
    L.append("- **Review proxy:** review counts understate stays (not every guest reviews)")
    L.append("  and `last_review` month is an activity proxy, not demand.")
    L.append("- **Geography:** neighbourhood boundaries are Inside Airbnb's, not the city's official wards.")
    L.append(f"- **Scope:** Toronto only, {label} — findings don't generalise to other cities or months.")
    L.append("")
    L.append("## 5. Next steps")
    L.append("")
    L.append(f"- [x] Re-run on the {label} snapshot (this report).")
    L.append("- [ ] Re-run monthly (this script automates it).")
    L.append("- [ ] Add `calendar.csv` / `reviews.csv` if not already present.")
    L.append("- [ ] Polish the prose in this auto-generated report.")
    L.append("")
    L.append("## Appendix: reproducibility")
    L.append("")
    L.append("```bash")
    L.append(f"sqlite3 data/{paths['db'].name} < sql/{paths['setup_sql'].name}")
    L.append(f"sqlite3 data/{paths['db'].name} < sql/02_exploration.sql")
    L.append(f"sqlite3 data/{paths['db'].name} < sql/03_analysis.sql")
    L.append("```")
    L.append("")
    L.append(f"Query outputs are saved at `docs/{paths['query_output'].name}`. Regenerate with:")
    L.append("")
    L.append("```bash")
    L.append(f"sqlite3 data/{paths['db'].name} < sql/03_analysis.sql > docs/{paths['query_output'].name}")
    L.append("```")
    L.append("")
    L.append("Charts were regenerated for this snapshot (same 6 figures):")
    L.append("")
    L.append("```bash")
    L.append(f"python3 scripts/make_charts_month.py --db data/{paths['db'].name} \\")
    L.append(f"    --outdir docs/charts/{month} --label \"{label}\"")
    L.append("```")
    L.append("")

    paths["findings"].write_text("\n".join(L), encoding="utf-8")
    log.info("wrote %s (%d bytes)", paths["findings"].name, paths["findings"].stat().st_size)


# --------------------------------------------------------------------------
# 5. README update (skipped in dry-run)
# --------------------------------------------------------------------------
def update_readme(paths: dict, metrics: dict, log: logging.Logger) -> None:
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    month, release, label = paths["month"], paths["release"], paths["label"]
    y, m = month.split("-")

    if month in text:
        log.info("README already mentions %s — skipping", month)
        return

    # 5a. snapshots table row (insert after the newest existing row)
    row = (f"| {label} | {release} | {metrics['earliest_scrape']} → {metrics['latest_scrape']} "
           f"| {metrics['listings']:,} | [findings-{month}.md](docs/findings-{month}.md) |\n")
    lines = text.splitlines(keepends=True)
    insert_at = None
    for i, ln in enumerate(lines):
        if ln.startswith("| September 2026 |") or ln.startswith("| August 2026 |"):
            insert_at = i + 1  # keep updating to the LAST month row seen
    if insert_at is not None:
        lines.insert(insert_at, row)
    text = "".join(lines)

    # 5b. project structure additions
    struct_adds = {
        f"│   ├── listings-{month}.csv": f"│   ├── listings-{month}.csv       # {label} source data (downloaded, gitignored)",
        f"│   └── airbnb_toronto_{y}_{m}.db": f"│   └── airbnb_toronto_{y}_{m}.db  # {label} SQLite database (build artifact)",
    }
    for anchor, newline in struct_adds.items():
        key = anchor.split("│   ├── ")[-1].split("│   └── ")[-1]
        if key in text:
            continue  # already present
        # append after the matching anchor line's sibling group
        out, done = [], False
        for ln in text.splitlines(keepends=True):
            out.append(ln)
            if not done and ln.rstrip().startswith(anchor.rstrip()):
                out.append(newline + "\n")
                done = True
        text = "".join(out)
    for old, new in [
        (f"│   ├── 01_setup-{y}-{m}.sql", None),  # guard handled below
    ]:
        pass
    if f"01_setup-{month}.sql" not in text:
        text = text.replace(
            "│   ├── 01_setup-2026-09.sql # same pipeline, September CSV (June script untouched)\n",
            "│   ├── 01_setup-2026-09.sql # same pipeline, September CSV (June script untouched)\n"
            f"│   ├── 01_setup-{month}.sql # same pipeline, {label} CSV (June script untouched)\n")
    if f"findings-{month}.md" not in text or f"query_output-{month}.txt" not in text:
        text = text.replace(
            "│   ├── findings-2026-09.md     # September findings report (filled)\n",
            "│   ├── findings-2026-09.md     # September findings report (filled)\n"
            f"│   ├── findings-{month}.md     # {label} findings report (auto-generated)\n")
        text = text.replace(
            "│   ├── query_output-2026-09.txt # September: actual analysis output\n",
            "│   ├── query_output-2026-09.txt # September: actual analysis output\n"
            f"│   ├── query_output-{month}.txt # {label}: actual analysis output\n")

    readme.write_text(text, encoding="utf-8")
    log.info("README updated with %s snapshot", month)


# --------------------------------------------------------------------------
# 6. local git commit
# --------------------------------------------------------------------------
def git_commit(paths: dict, log: logging.Logger) -> None:
    tracked = [
        str(paths["setup_sql"]), str(paths["query_output"]), str(paths["findings"]),
        str(paths["metrics"]), "README.md",
        *[str(p) for p in sorted(paths["charts_dir"].glob("*.png"))],
        "scripts/refresh_month.py", "scripts/refresh_month.md",
    ]
    rel = [str(Path(p).relative_to(ROOT)) if Path(p).is_absolute() else p for p in tracked]
    existing = [p for p in rel if (ROOT / p).exists()]
    subprocess.run(["git", "add", *existing], cwd=ROOT, check=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    if not status:
        log.info("nothing new to commit locally")
        return
    subprocess.run(["git", "commit", "-m",
                    f"Add {paths['label']} snapshot analysis (automated refresh)"],
                   cwd=ROOT, check=True, capture_output=True, text=True)
    log.info("local git commit created")


# --------------------------------------------------------------------------
# 7. GitHub push via the REST API (git-database API, one commit)
#    git push over HTTPS does NOT work with this credential — see the
#    known quirk in scripts/refresh_month.md.
# --------------------------------------------------------------------------
def _load_cred_helper():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dynamic_credentials", CRED_HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GitHub:
    def __init__(self, log: logging.Logger):
        self.log = log
        self.cred = _load_cred_helper()
        self.api = "https://api.github.com"

    def req(self, method: str, path: str, body: dict | None = None) -> dict:
        url = self.api + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        if data:
            req.add_header("Content-Type", "application/json")
        self.cred.add_surrogate_to_request(
            req, credential_name="custom.github", allowed_hosts=("api.github.com",))
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return self.cred.read_json_response(resp)
        except urllib.error.HTTPError as e:
            try:
                payload = e.read().decode()[:500]
            except Exception:
                payload = ""
            raise RuntimeError(f"GitHub API {method} {path} -> {e.code}: {payload}")

    def push_files(self, files: dict[str, Path], message: str, log: logging.Logger) -> str:
        """Create blobs -> tree -> commit -> update main ref. Returns new commit SHA."""
        ref = self.req("GET", f"/repos/{OWNER}/{REPO}/git/refs/heads/{GH_BRANCH}")
        ref_sha = ref["object"]["sha"]
        base_tree = self.req("GET", f"/repos/{OWNER}/{REPO}/git/commits/{ref_sha}")["tree"]["sha"]

        entries = []
        for repo_path, local in files.items():
            blob = self.req("POST", f"/repos/{OWNER}/{REPO}/git/blobs",
                            {"content": base64.b64encode(local.read_bytes()).decode(),
                             "encoding": "base64"})
            entries.append({"path": repo_path, "mode": "100644",
                            "type": "blob", "sha": blob["sha"]})
            log.info("blob created for %s", repo_path)
        tree = self.req("POST", f"/repos/{OWNER}/{REPO}/git/trees",
                        {"base_tree": base_tree, "tree": entries})
        commit = self.req("POST", f"/repos/{OWNER}/{REPO}/git/commits",
                          {"message": message, "tree": tree["sha"], "parents": [ref_sha]})
        self.req("PATCH", f"/repos/{OWNER}/{REPO}/git/refs/heads/{GH_BRANCH}",
                 {"sha": commit["sha"]})
        log.info("pushed commit %s to %s", commit["sha"], GH_BRANCH)

        # verify the remote tree contains everything we pushed
        tree_now = self.req("GET",
                            f"/repos/{OWNER}/{REPO}/git/trees/{GH_BRANCH}?recursive=1")
        names = {t["path"] for t in tree_now["tree"]}
        missing = [p for p in files if p not in names]
        if missing:
            raise RuntimeError(f"remote tree missing after push: {missing}")
        log.info("verified %d pushed files present in remote tree", len(files))
        return commit["sha"]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Monthly refresh for the Airbnb SQL project.")
    ap.add_argument("--month", help="force a specific month (YYYY-MM) instead of detecting")
    ap.add_argument("--dry-run", action="store_true",
                    help="do everything except the GitHub push and README write")
    args = ap.parse_args()

    # provisional log name until we know the month
    log = setup_logging(args.month or "detect")

    t0 = time.time()
    release = detect_release(args.month, log)
    if release is None:
        log.info("no release available — exiting 0")
        return
    paths = month_paths(release)
    if paths["month"] != (args.month or "detect"):
        # re-open the log file under the real month name
        for h in log.handlers:
            h.close()
        log = setup_logging(paths["month"])
    log.info("detected release %s (%s)", release, paths["label"])

    # idempotency: already processed
    if paths["csv_gz"].exists() or paths["findings"].exists():
        log.info("%s already processed (csv_gz=%s, findings=%s) — skipping cleanly",
                 paths["month"], paths["csv_gz"].exists(), paths["findings"].exists())
        return

    # 1. download
    t = time.time()
    download_release(release, paths["csv_gz"], log)
    log.info("download step took %.1fs", time.time() - t)

    # 2. build db + run queries + charts
    t = time.time()
    write_setup_sql(paths, log)
    if paths["db"].exists():
        paths["db"].unlink()
    run_sqlite(paths["db"], paths["setup_sql"], log)
    run_sqlite(paths["db"], SQL / "02_exploration.sql", log)
    run_sqlite(paths["db"], SQL / "03_analysis.sql", log, capture=paths["query_output"])
    run_charts(paths, log)
    log.info("build+queries+charts took %.1fs", time.time() - t)

    # 3. metrics + report
    t = time.time()
    metrics = collect_metrics(paths["db"], log)
    metrics["_month"] = paths["month"]
    metrics["_release"] = release
    paths["metrics"].write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    prev = previous_metrics(paths["month"])
    write_report(paths, metrics, prev, log)
    log.info("metrics+report took %.1fs", time.time() - t)

    # 4. README + git (README skipped in dry-run)
    if not args.dry_run:
        update_readme(paths, metrics, log)
    else:
        log.info("dry-run: skipping README write")
    git_commit(paths, log)

    # 5. GitHub push (skipped in dry-run)
    if args.dry_run:
        log.info("dry-run: skipping GitHub push")
    else:
        t = time.time()
        gh = GitHub(log)
        files = {
            f"sql/{paths['setup_sql'].name}": paths["setup_sql"],
            f"docs/{paths['query_output'].name}": paths["query_output"],
            f"docs/{paths['findings'].name}": paths["findings"],
            f"docs/{paths['metrics'].name}": paths["metrics"],
            "README.md": ROOT / "README.md",
            "scripts/refresh_month.py": SCRIPTS / "refresh_month.py",
            "scripts/refresh_month.md": SCRIPTS / "refresh_month.md",
            **{f"docs/charts/{paths['month']}/{p.name}": p
               for p in sorted(paths["charts_dir"].glob("*.png"))},
        }
        sha = gh.push_files(files, f"Add {paths['label']} snapshot analysis (automated refresh)", log)
        log.info("GitHub push took %.1fs, commit %s", time.time() - t, sha)

    log.info("refresh for %s complete in %.1fs", paths["month"], time.time() - t0)


if __name__ == "__main__":
    main()
