-- ============================================================================
-- 03_analysis.sql — Business questions on Toronto Airbnb listings
-- ============================================================================
-- Run from the project root:
--     sqlite3 data/airbnb_toronto.db < sql/03_analysis.sql
--
-- Snapshot: Inside Airbnb, Toronto, scraped 2026-06-16 → 2026-06-28.
-- Prices are nightly quotes in CAD. Listings with NULL price are excluded
-- from price math (they had no active price quote at scrape time).
-- ============================================================================
.mode column
.headers on

-- ----------------------------------------------------------------------------
-- A1. Where is the supply? Top 15 neighbourhoods by listing count, with
-- average & median price and each neighbourhood's share of city supply.
-- ----------------------------------------------------------------------------
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
       ROUND(100.0 * nb.listings / SUM(nb.listings) OVER (), 1) AS pct_of_city_supply,
       ROUND(nb.avg_price, 2)     AS avg_price,
       ROUND(med.median_price, 2) AS median_price
FROM nb
JOIN med ON med.nb = nb.nb
ORDER BY nb.listings DESC
LIMIT 15;

-- ----------------------------------------------------------------------------
-- A2. The entire-home premium: how much more does a whole place cost than
-- a private room, in median nightly price terms?
-- ----------------------------------------------------------------------------
WITH medians AS (
    SELECT room_type, AVG(price) AS median_price
    FROM (
        SELECT room_type, price,
               ROW_NUMBER() OVER (PARTITION BY room_type ORDER BY price) AS rn,
               COUNT(*)     OVER (PARTITION BY room_type)                 AS cnt
        FROM listings
        WHERE price > 0 AND room_type IN ('Entire home/apt', 'Private room')
    )
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY room_type
)
SELECT
    MAX(CASE WHEN room_type = 'Entire home/apt' THEN ROUND(median_price, 2) END) AS entire_home_median,
    MAX(CASE WHEN room_type = 'Private room'    THEN ROUND(median_price, 2) END) AS private_room_median,
    ROUND(
        MAX(CASE WHEN room_type = 'Entire home/apt' THEN median_price END) /
        MAX(CASE WHEN room_type = 'Private room'    THEN median_price END), 2
    ) AS entire_home_premium_ratio
FROM medians;

-- ----------------------------------------------------------------------------
-- A3. Superhost vs regular host: price, rating and review-velocity gaps.
-- ----------------------------------------------------------------------------
SELECT
    CASE
        WHEN host_is_superhost = 1 THEN 'Superhost'
        WHEN host_is_superhost = 0 THEN 'Regular host'
        ELSE 'Unknown'
    END AS host_type,
    COUNT(*)                                   AS listings,
    ROUND(AVG(price), 2)                       AS avg_price,
    ROUND(AVG(review_scores_rating), 2)        AS avg_rating,
    ROUND(AVG(reviews_per_month), 2)           AS avg_reviews_per_month,
    ROUND(AVG(number_of_reviews), 1)           AS avg_total_reviews
FROM listings
WHERE price > 0
GROUP BY host_is_superhost;

-- ----------------------------------------------------------------------------
-- A4. Do higher-rated listings charge more? Average nightly price across
-- rating bands (listings without ratings are shown separately, not dropped).
-- ----------------------------------------------------------------------------
SELECT
    CASE
        WHEN review_scores_rating IS NULL THEN 'No rating yet'
        WHEN review_scores_rating < 4.5  THEN 'Below 4.50'
        WHEN review_scores_rating < 4.8  THEN '4.50 – 4.79'
        ELSE '4.80 – 5.00'
    END AS rating_band,
    COUNT(*)              AS listings,
    ROUND(AVG(price), 2)  AS avg_price,
    ROUND(AVG(number_of_reviews), 1) AS avg_reviews
FROM listings
WHERE price > 0
GROUP BY rating_band
ORDER BY avg_price DESC;

-- ----------------------------------------------------------------------------
-- A5. Availability & occupancy: how much of the next year is bookable, and
-- how does Inside Airbnb's estimated occupancy vary with availability?
-- ----------------------------------------------------------------------------
SELECT
    CASE
        WHEN availability_365 <= 30  THEN '0–30 days'
        WHEN availability_365 <= 90  THEN '31–90 days'
        WHEN availability_365 <= 180 THEN '91–180 days'
        WHEN availability_365 <= 300 THEN '181–300 days'
        ELSE '301–365 days'
    END AS availability_band,
    COUNT(*)                                            AS listings,
    ROUND(AVG(estimated_occupancy_l365d), 1)             AS avg_est_occupancy_days,
    ROUND(AVG(100.0 * estimated_occupancy_l365d / 365), 1) AS implied_occupancy_pct
FROM listings
WHERE availability_365 IS NOT NULL
GROUP BY availability_band
ORDER BY MIN(availability_365);

-- ----------------------------------------------------------------------------
-- A6. The city's review magnets: 20 most-reviewed listings.
-- ----------------------------------------------------------------------------
SELECT number_of_reviews,
       name,
       neighbourhood_cleansed AS neighbourhood,
       room_type,
       ROUND(price, 2) AS price,
       review_scores_rating AS rating
FROM listings
ORDER BY number_of_reviews DESC
LIMIT 20;

-- ----------------------------------------------------------------------------
-- A7. Seasonality proxy: in which months do listings get their latest review?
-- (last_review month distribution — a rough demand-activity signal.)
-- ----------------------------------------------------------------------------
SELECT STRFTIME('%Y-%m', last_review) AS review_month,
       COUNT(*) AS listings_with_latest_review
FROM listings
WHERE last_review IS NOT NULL
GROUP BY review_month
ORDER BY review_month DESC
LIMIT 24;

-- ----------------------------------------------------------------------------
-- A8. Host concentration: what share of supply sits with multi-listing hosts?
-- Self-join: each listing is compared against its host's portfolio stats.
-- ----------------------------------------------------------------------------
WITH host_stats AS (
    SELECT host_id,
           COUNT(*)        AS portfolio_size,
           AVG(price)      AS host_avg_price
    FROM listings
    WHERE host_id IS NOT NULL AND price > 0
    GROUP BY host_id
)
SELECT
    CASE
        WHEN h.portfolio_size = 1 THEN '1 listing'
        WHEN h.portfolio_size <= 5 THEN '2–5 listings'
        ELSE '6+ listings'
    END AS host_size_band,
    COUNT(DISTINCT h.host_id) AS hosts,
    COUNT(*)                 AS listings,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_supply,
    ROUND(AVG(l.price), 2)    AS avg_listing_price
FROM listings l
JOIN host_stats h ON h.host_id = l.host_id
WHERE l.price > 0
GROUP BY host_size_band
ORDER BY MIN(h.portfolio_size);

-- ----------------------------------------------------------------------------
-- A9. Price by bedroom count: the marginal cost of extra bedrooms
-- (entire homes/apts only, to compare like with like).
-- ----------------------------------------------------------------------------
SELECT
    CAST(bedrooms AS INTEGER) AS bedrooms,
    COUNT(*)                 AS listings,
    ROUND(AVG(price), 2)     AS avg_price,
    ROUND(
        AVG(price) - LAG(AVG(price)) OVER (ORDER BY CAST(bedrooms AS INTEGER)), 2
    )                        AS marginal_cost_of_extra_bedroom
FROM listings
WHERE room_type = 'Entire home/apt'
  AND price > 0
  AND bedrooms BETWEEN 0 AND 5
GROUP BY bedrooms
ORDER BY bedrooms;

-- ----------------------------------------------------------------------------
-- A10. Estimated revenue leaders: top 10 neighbourhoods by average estimated
-- annual revenue per listing (Inside Airbnb's estimate from calendar data).
-- ----------------------------------------------------------------------------
SELECT neighbourhood_cleansed AS neighbourhood,
       COUNT(*) AS listings,
       ROUND(AVG(estimated_revenue_l365d), 0) AS avg_est_annual_revenue,
       ROUND(AVG(estimated_occupancy_l365d), 1) AS avg_est_occupancy_days
FROM listings
WHERE estimated_revenue_l365d IS NOT NULL
GROUP BY neighbourhood_cleansed
HAVING COUNT(*) >= 20
ORDER BY avg_est_annual_revenue DESC
LIMIT 10;

-- ----------------------------------------------------------------------------
-- A11. Best value picks: highly-rated entire homes priced below the
-- neighbourhood median (window function ranks value within each market).
-- ----------------------------------------------------------------------------
WITH nb_median AS (
    SELECT neighbourhood_cleansed AS nb, AVG(price) AS median_price
    FROM (
        SELECT neighbourhood_cleansed, price,
               ROW_NUMBER() OVER (PARTITION BY neighbourhood_cleansed ORDER BY price) AS rn,
               COUNT(*)     OVER (PARTITION BY neighbourhood_cleansed)                 AS cnt
        FROM listings
        WHERE price > 0 AND room_type = 'Entire home/apt'
    )
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY neighbourhood_cleansed
)
SELECT name,
       neighbourhood_cleansed AS neighbourhood,
       ROUND(price, 2) AS price,
       ROUND(nb_median.median_price, 2) AS nb_median_price,
       review_scores_rating AS rating,
       number_of_reviews AS reviews
FROM listings
JOIN nb_median ON nb_median.nb = listings.neighbourhood_cleansed
WHERE room_type = 'Entire home/apt'
  AND price > 0
  AND review_scores_rating >= 4.8
  AND number_of_reviews >= 20
  AND price < nb_median.median_price
ORDER BY review_scores_rating DESC, number_of_reviews DESC
LIMIT 20;
