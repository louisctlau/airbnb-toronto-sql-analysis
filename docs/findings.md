# Findings Report — Toronto Airbnb Listings (June 2026 snapshot)

> Figures verified from `sql/02_exploration.sql` and `sql/03_analysis.sql`
> output, 2026-09-22. No fabricated numbers.

## 1. Executive summary

22,198 Toronto Airbnb listings (scraped 2026-06-16 → 2026-06-28; snapshot
2026-06-15) were cleaned and analysed with 20 SQL queries. Three takeaways
stand out:

1. **Quality is rewarded, but cheaply:** superhosts charge *less* per night
   than regular hosts ($274 vs $286) while rating 4.88 vs 4.73 and earning
   ~3× the reviews — suggesting the superhost badge is won on
   value-for-money, not premium pricing.
2. **Supply is hyper-concentrated:** Waterfront Communities-The Island holds
   17.4% of all listings, and single-listing hosts (53% of priced supply)
   price ~64% above multi-listing professionals — the market's "casual" and
   "pro" segments behave very differently.
3. **Bedroom count has accelerating returns for hosts:** the marginal nightly
   cost of an extra bedroom climbs from ~$103 (1→2 beds) to ~$337 (4→5 beds),
   while the top revenue neighbourhood (Black Creek, ~$66.5k avg est.
   annual revenue per listing) shows luxury outliers can distort averages.

> Verified data profile:
> - Listings analysed: 22,198 (all ids unique — 0 duplicates)
> - Scrape window: 2026-06-16 → 2026-06-28
> - Room-type mix: 68.6% entire home/apt, 31.1% private room, 0.3% hotel room, 0.1% shared room
> - 17.7% of listings have no active price quote; 22.8% (5,053) were never reviewed

## 2. Method

- **Source:** Inside Airbnb detailed listings, Toronto, snapshot 2026-06-15
  (rows scraped 2026-06-16 → 2026-06-28). One row per listing; prices in CAD.
- **Pipeline:** `sql/01_setup.sql` loads the CSV into a raw staging table
  (all TEXT), then builds a cleaned, typed `listings` table:
  `$1,234.56` → numeric price, `'t'/'f'` → 1/0 flags, date casts,
  `bathrooms_text` ("2.5 baths") → numeric baths. Fully blank
  `instant_bookable` column dropped and documented in `02_exploration.sql`.
- **Quality gates:** `sql/02_exploration.sql` checks duplicates (Q4), missing
  key fields (Q1), numeric range sanity (Q5) and review-date integrity (Q6)
  before any analysis runs. Result: 0 duplicate ids; 17.7% of listings have
  no price quote (excluded from price math); 22.8% never reviewed; no
  negative prices, bad ratings, or impossible dates found.
- **Analysis:** `sql/03_analysis.sql` answers 11 business questions with
  CTEs, window functions (medians, `LAG()`, running shares) and a self-join
  for host-concentration analysis.

## 3. Findings

### 3.1 Where is the supply? (A1)

Top 5 neighbourhoods by listing count: Waterfront Communities-The Island
(3,184 listings, 17.4% of city supply, median $320), Niagara (749, 4.1%,
$320), Church-Yonge Corridor (579, 3.2%, $249), Annex (575, 3.1%, $269),
Moss Park (549, 3.0%, $270). At the bargain end, Kensington-Chinatown's
median is just $145 — less than half the Waterfront median. Note the mean
can mislead: Trinity-Bellwoods averages $319 but its median is only $193,
evidence of luxury listings skewing the average — one reason the query
computes medians with window functions instead of `AVG`.

_Chart placeholder: horizontal bar — listings per neighbourhood (top 15)._

### 3.2 The entire-home premium (A2)

Median entire home/apt: **$265/night**. Median private room: **$85.50**.
Premium ratio: **3.1×**. The `CASE`-inside-aggregate pivot keeps both
medians in one row for a clean headline comparison.

_Chart placeholder: grouped bars — median price by room type._

### 3.3 Superhost economics (A3)

| Host type    | Listings | Avg price | Avg rating | Reviews/month | Avg total reviews |
|--------------|----------|-----------|------------|---------------|-------------------|
| Superhost    | 7,021    | $273.80   | 4.88       | 1.95          | 56.5              |
| Regular host | 11,255   | $286.37   | 4.73       | 1.30          | 18.1              |
| Unknown      | 1        | $368.10   | —          | —             | 0.0               |

The headline surprise: superhosts charge **less** on average while rating
higher and earning ~3× the reviews. Analytical caveat: correlation, not
causation — superhosts may self-select into better-managed properties, and
their lower prices may be a deliberate volume strategy. (One row has a
blank superhost flag, grouped as "Unknown".)

### 3.4 Ratings and price (A4)

| Rating band   | Listings | Avg price | Avg reviews |
|---------------|----------|-----------|-------------|
| No rating yet | 4,081    | $319.49   | 0.0         |
| 4.80 – 5.00   | 10,055   | $284.47   | 43.9        |
| 4.50 – 4.79   | 2,974    | $250.25   | 48.6        |
| Below 4.50    | 1,167    | $203.38   | 12.7        |

Among rated listings, price rises with rating — quality pays. The "No
rating yet" band is the priciest at $319.49, likely new hosts pricing
ambitiously before reviews land. Keeping unrated listings as their own
group (rather than dropping them) avoids survivorship bias.

### 3.5 Availability and occupancy (A5)

| Availability band | Listings | Avg est. occupied days/yr | Implied occupancy |
|-------------------|----------|---------------------------|-------------------|
| 0–30 days         | 4,210    | 36.6                      | 10.0%             |
| 31–90 days        | 3,148    | 85.7                      | 23.5%             |
| 91–180 days       | 3,558    | 92.5                      | 25.3%             |
| 181–300 days      | 5,165    | 88.3                      | 24.2%             |
| 301–365 days      | 6,117    | 50.2                      | 13.8%             |

Listings available 91–180 days/yr show the highest estimated occupancy
(~25%) — the sweet spot between casual and dormant. Listings bookable
301+ days have just 13.8% implied occupancy, suggesting a long tail of
stale or rarely-booked supply. Note: `estimated_occupancy_l365d` is Inside
Airbnb's estimate, not observed bookings.

### 3.6 Review magnets (A6)

The city's most-reviewed listing is a private room in Danforth East York
("Private suite all to yourself", 1,388 reviews, $154, 4.87★). The top-20
list is dominated by **private rooms** (17 of 20) priced $49–$329 — i.e.
review volume comes from high-turnover budget stays, not luxury. Cliffcrest
appears three times, all private rooms from what looks like one operator.

### 3.7 Seasonality signal (A7)

`last_review` months climb steeply into the scrape: June 2026 (4,767
listings with their latest review that month) vs ~340–430/month in
fall 2025 and ~70–150/month in early 2024. Activity rises through spring
into summer — the expected warm-season pattern — though part of the June
spike is mechanical (reviews can only be "latest" in the scrape month for
actively reviewed listings). Caveat: this measures *recency of the latest
review*, a rough activity proxy, not true demand.

### 3.8 Who owns the supply? (A8)

| Host size band | Hosts | Listings | % of supply | Avg listing price |
|----------------|-------|----------|-------------|-------------------|
| 1 listing      | 9,700 | 9,700    | 53.1%       | $344.96           |
| 2–5 listings   | 2,102 | 5,513    | 30.2%       | $208.95           |
| 6+ listings    | 245   | 3,064    | 16.8%       | $211.42           |

Computed via self-join: each listing joined to its host's portfolio stats.
Single-listing hosts are the majority of supply (53.1%) and price ~64%
above multi-listing hosts — casual hosts price high, professionals compete
on volume. 245 large operators (6+ listings) control 16.8% of priced supply,
so the market is partially professionalised but far from dominated.

### 3.9 Bedroom economics (A9)

| Bedrooms | Listings | Avg price | Marginal cost of extra bedroom |
|----------|----------|-----------|-------------------------------|
| 0        | 1        | $214.67   | — (n=1, ignore)               |
| 1        | 5,720    | $256.57   | —                             |
| 2        | 3,865    | $359.07   | +$102.50                      |
| 3        | 1,499    | $521.57   | +$162.49                      |
| 4        | 450      | $738.11   | +$216.54                      |
| 5        | 167      | $1,074.63 | +$336.52                      |

Entire homes only, compared like-for-like. Each extra bedroom costs more
than the last — from +$103 (1→2) to +$337 (4→5) per night — computed with
`LAG()` over grouped averages. The 0-bedroom row (n=1) is too thin to trust.

### 3.10 Revenue leaders (A10)

Top 5 neighbourhoods by avg estimated annual revenue per listing: Black
Creek ($66,499, n=39), Broadview North ($37,668, n=26), Waterfront
Communities-The Island ($35,414, n=3,184), Playter Estates-Danforth
($30,335, n=37), Wychwood ($27,868, n=88). Small-n warning: Black Creek's
lead rests on just 39 listings — likely a few luxury outliers, the same
skew seen in 3.1. Waterfront's #3 spot on 3,184 listings is the robust
signal.

### 3.11 Best-value picks (A11)

20 highly-rated (4.8★+, 20+ reviews) entire homes priced below their
neighbourhood median, found by comparing each listing against a
window-function median per neighbourhood. Standouts: a 5.0★ studio in
Bloorcourt at $91 vs a $185 local median (176 reviews); a 5.0★ 1BR with
CN Tower view downtown at $304 vs a $331 Waterfront median (56 reviews).
This query doubles as a realistic "consumer tool" — the kind of feature a
booking site would ship.

## 4. Limitations

- **Single snapshot:** no true time series; occupancy/revenue are modelled
  estimates from one scrape, and `price` is a quoted nightly rate, not a
  transacted price.
- **Missing prices (17.7%):** listings without an active quote are excluded
  from price math — if missingness correlates with price tier, averages are
  biased.
- **Review proxy:** review counts understate stays (not every guest reviews)
  and `last_review` month is an activity proxy, not demand.
- **Geography:** neighbourhood boundaries are Inside Airbnb's, not the
  city's official wards.
- **Scope:** Toronto only, June 2026 — findings don't generalise to other
  cities or seasons.

## 5. Next steps

- [ ] Add `calendar.csv` (365-day availability per listing) for real
      occupancy analysis instead of estimates.
- [ ] Add `reviews.csv` for review-velocity and sentiment trends over time.
- [ ] Pull 2–3 quarterly snapshots to measure supply growth and price trends.
- [ ] Build a dashboard (Metabase / Streamlit) on top of these queries.
- [ ] Re-run quarterly; automate with a scheduled `sqlite3` + script job.

## Appendix: reproducibility

```bash
sqlite3 data/airbnb_toronto.db < sql/01_setup.sql
sqlite3 data/airbnb_toronto.db < sql/02_exploration.sql
sqlite3 data/airbnb_toronto.db < sql/03_analysis.sql
```

Query outputs for every figure above are the actual run results saved at
`docs/query_output.txt`. Regenerate with:

```bash
sqlite3 data/airbnb_toronto.db < sql/03_analysis.sql > docs/query_output.txt
```
