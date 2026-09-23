# Toronto Airbnb Listings — SQL Analysis

An end-to-end SQL data analysis of Toronto's short-term rental market: ingest a
real public dataset, profile its quality, then answer business questions with
clean, portfolio-ready SQL.

## Dataset

- **Source:** [Inside Airbnb](https://insideairbnb.com/get-the-data/) — detailed
  listings file, Toronto, Ontario, Canada
- **Snapshot:** 15 June 2026 release (rows scraped 2026-06-16 → 2026-06-28)
- **File:** `data/listings.csv` (22,198 listings × 90 columns, decompressed from
  `listings.csv.gz`)
- **License:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- **Grain:** one row per Airbnb listing at scrape time (prices in CAD)

## Project structure

```
airbnb-toronto-sql-analysis/
├── data/
│   ├── listings.csv        # source data (downloaded, gitignored in real use)
│   └── airbnb_toronto.db   # SQLite database created by the setup script
├── sql/
│   ├── 01_setup.sql        # staging import → cleaned, typed `listings` table
│   ├── 02_exploration.sql  # data-quality & exploratory checks (Q0–Q8)
│   └── 03_analysis.sql     # 11 business questions (A1–A11)
├── scripts/
│   └── make_charts.py      # generates docs/charts from the SQLite db (matplotlib)
├── docs/
│   ├── findings.md         # written findings report (all sections filled)
│   ├── query_output.txt    # actual output of sql/03_analysis.sql
│   └── charts/             # generated figures (see Key findings below)
└── README.md
```

## How to run

Requires `sqlite3` (3.35+). Run from the project root:

```bash
# 1. Build the database (imports CSV, creates cleaned `listings` table)
sqlite3 data/airbnb_toronto.db < sql/01_setup.sql

# 2. Run data-quality checks
sqlite3 data/airbnb_toronto.db < sql/02_exploration.sql

# 3. Run the business-question analysis
sqlite3 data/airbnb_toronto.db < sql/03_analysis.sql
```

To re-download the data:

```bash
curl -sSL -o data/listings.csv.gz \
  "https://data.insideairbnb.com/canada/on/toronto/2026-06-15/data/listings.csv.gz"
gunzip -c data/listings.csv.gz > data/listings.csv
```

## Data-quality summary (verified)

| Check | Result |
|---|---|
| Listings loaded | 22,198 |
| Duplicate listing ids | 0 |
| Missing nightly price | 3,921 (17.7% — no active quote at scrape) |
| Missing room type / neighbourhood / coordinates | 0 |
| Listings never reviewed | 5,053 (22.8%) |
| Review dates after scrape / last < first review | 0 |
| Fully blank `instant_bookable` column (dropped from clean table) | 22,198 / 22,198 |

## Business questions

| # | Question | Techniques |
|---|---|---|
| A1 | Top 15 neighbourhoods by supply, price, market share | CTE, window `SUM() OVER ()` |
| A2 | Entire-home premium over private rooms | Median via `ROW_NUMBER()` |
| A3 | Superhost vs regular-host price/rating/review gaps | `GROUP BY`, conditional agg |
| A4 | Rating bands vs average price | `CASE` bucketing |
| A5 | Availability bands vs estimated occupancy | Bucketing, derived metrics |
| A6 | 20 most-reviewed listings | `ORDER BY … LIMIT` |
| A7 | Seasonality of latest reviews (last 24 months) | `STRFTIME`, time series |
| A8 | Host concentration: share of supply by portfolio size | CTE + self-join |
| A9 | Marginal price of each extra bedroom | `LAG()` window function |
| A10 | Top 10 neighbourhoods by estimated annual revenue | Aggregation, `HAVING` |
| A11 | Best-value picks: 4.8★+ entire homes below neighbourhood median | CTE, windowed median, join |

## Key findings

- **Entire-home premium: 3.1×** — median $265/night for an entire home vs
  $85.50 for a private room. Waterfront Communities-The Island dominates
  supply with 3,184 listings (17.4% of the city); Kensington-Chinatown is
  the bargain corner at a $145 median.

  ![Listings by neighbourhood](docs/charts/listings_by_neighbourhood.png)
  ![Median price by room type](docs/charts/median_price_by_room_type.png)

- **Superhosts win on value, not price** — superhosts charge *less* than
  regular hosts on average ($273.80 vs $286.37) while rating 4.88 vs 4.73
  and earning ~3× the reviews (1.95 vs 1.30 reviews/month).

  ![Superhost vs regular host](docs/charts/superhost_vs_regular.png)

- **Ratings pay** — average price rises with rating band ($203 below 4.50 →
  $284 at 4.80–5.00). Unrated listings price highest ($319), likely new
  hosts pricing ambitiously before reviews arrive.

  ![Price by rating band](docs/charts/price_by_rating_band.png)

- **Availability sweet spot** — estimated occupancy peaks (~25%) for
  listings available 91–180 days/yr; listings bookable 301+ days sit at
  13.8%, suggesting a long tail of stale supply.

  ![Occupancy by availability](docs/charts/occupancy_by_availability.png)

- **Bedroom economics** — the marginal nightly cost of an extra bedroom
  climbs from +$103 (1→2 beds) to +$337 (4→5 beds), via `LAG()` over
  grouped averages.

  ![Bedroom marginal cost](docs/charts/bedroom_marginal_cost.png)

- **Host concentration** — 53.1% of priced supply sits with single-listing
  hosts (avg $344.96/night) vs 16.8% with 6+ listing operators (avg
  $211.42): casual hosts price high, professionals compete on volume.

Full analysis: [`docs/findings.md`](docs/findings.md).

## Sample query output

A9 — marginal cost per bedroom (entire homes):

```
bedrooms  listings  avg_price  marginal_cost_of_extra_bedroom
--------  --------  ---------  ------------------------------
1         5720      256.57
2         3865      359.07     102.5
3         1499      521.57     162.49
4         450       738.11     216.54
5         167       1074.63    336.52
```

Complete output of all 11 analysis queries:
[`docs/query_output.txt`](docs/query_output.txt).

## Limitations & next steps

See [`docs/findings.md`](docs/findings.md) for the full write-up, including
limitations (single snapshot, estimated occupancy/revenue fields are Inside
Airbnb's models, not Airbnb's books) and ideas for extension
(multi-snapshot trends, calendar.csv occupancy analysis, reviews.csv sentiment).

> **Note:** `data/` (CSV + built SQLite db, ~158 MB) is gitignored. Clone,
> then re-download the data and run `sql/01_setup.sql` to rebuild the database.
