# Dashboard — Toronto Airbnb SQL Analysis

Interactive Streamlit dashboard over the four monthly Toronto Airbnb snapshots
(June → September 2026) in `../data/`.

## Run

```bash
cd dashboard
# option A: use the prepared venv (streamlit/plotly/pandas pre-installed)
./.venv/bin/streamlit run app.py
# option B: your own environment
pip install -r requirements.txt
streamlit run app.py
```

The app opens at http://localhost:8501.

## Tabs

- **Overview** — KPI cards (listings, entire-home / private-room medians,
  premium ratio, superhost share, no-price-quote %) recomputed live from the
  selected month's database, plus a month-over-month median-price sparkline.
- **Neighbourhoods** — top-15 supply bars (coloured by median price), median
  price ranking, and a mean-vs-median skew chart with the Trinity-Bellwoods
  example.
- **Hosts** — superhost vs regular-host price/rating/review-velocity
  comparison, host-concentration donut (1 / 2–5 / 6+ listings), avg price by
  host-size band.
- **Pricing** — median price by room type, bedroom marginal-cost curve
  (bar + `LAG()` line), price by rating band.
- **Occupancy** — August 2026 only: calendar-derived **true** occupancy vs
  Inside Airbnb's estimate by neighbourhood (top 10), and the availability
  curve by month. Other months show a clear "August only" message.
- **Reviews** — August 2026 only: review volume by month (44 months), top
  review words 2023 vs 2026 (precomputed in `data/top_words.csv`), fastest
  review-velocity listings.
- **Value finder** — interactive A11 query: pick a neighbourhood, max price
  and min rating → 4.8★+ entire homes priced below their neighbourhood median.

The sidebar snapshot selector also offers **Trends (all months)** — live
month-over-month line charts for every headline KPI, each recomputed from its
month's database.

## Data provenance

All figures are computed in SQL against the project's SQLite databases
(`../data/airbnb_toronto*.db`), snapshots of Inside Airbnb's Toronto detailed
listings (CC BY 4.0), with the same median semantics (window functions) as
`../sql/03_analysis.sql`. The `calendar` (8.1M rows) and `reviews` (447k rows)
tables exist in the August database only.

## Performance

- Every query is wrapped in `@st.cache_data`; heavy calendar aggregations
  (8.1M rows) run once in SQL with index support and are then cached.
- The top-words comparison is precomputed once into `data/top_words.csv` —
  the 447k-comment scan never runs at page load.

## Screenshots

> TODO — add screenshots after running locally:
> - `screenshots/overview.png`
> - `screenshots/trends.png`
> - `screenshots/value-finder.png`
