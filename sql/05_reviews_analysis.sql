-- ============================================================================
-- 05_reviews_analysis.sql — Review trends from reviews data
-- ============================================================================
-- Run from the project root:
--     sqlite3 data/airbnb_toronto_2026_08.db < sql/05_reviews_analysis.sql
--
-- Dataset: Inside Airbnb reviews.csv.gz, Toronto, 2026-08-15 release.
-- The `reviews` table keeps only reviews dated >= 2023-01-01 (447,129 of
-- 709,449 rows — documented cut to bound db size; full raw file kept in
-- data/reviews-2026-08.csv.gz).
--
-- Note: no rating is attached to individual reviews in this file; velocity,
-- volume and text signals only.
-- ============================================================================
.mode column
.headers on

-- ----------------------------------------------------------------------------
-- R1. Review volume by month, last 36 months: is review activity growing?
-- ----------------------------------------------------------------------------
SELECT STRFTIME('%Y-%m', date) AS review_month,
       COUNT(*) AS reviews,
       COUNT(DISTINCT listing_id) AS active_listings
FROM reviews
GROUP BY review_month
ORDER BY review_month;

-- ----------------------------------------------------------------------------
-- R2. Average review length (words) by month: are guests writing more/less?
-- ----------------------------------------------------------------------------
SELECT STRFTIME('%Y-%m', date) AS review_month,
       ROUND(AVG(LENGTH(comments) - LENGTH(REPLACE(comments, ' ', '')) + 1), 1)
           AS avg_words
FROM reviews
WHERE comments IS NOT NULL AND LENGTH(TRIM(comments)) > 0
GROUP BY review_month
ORDER BY review_month;

-- ----------------------------------------------------------------------------
-- R3. Fastest-growing review velocity: listings with the most reviews in
-- the last 90 days vs their lifetime average (listings with 20+ reviews).
-- ----------------------------------------------------------------------------
WITH lifetime AS (
    SELECT listing_id, COUNT(*) AS total_reviews
    FROM reviews
    GROUP BY listing_id
),
recent AS (
    SELECT listing_id, COUNT(*) AS reviews_90d
    FROM reviews
    WHERE date >= DATE('2026-08-15', '-90 days')
    GROUP BY listing_id
)
SELECT l.name,
       l.neighbourhood_cleansed AS neighbourhood,
       l.room_type,
       r.reviews_90d,
       lf.total_reviews,
       ROUND(1.0 * r.reviews_90d / lf.total_reviews * 100, 1) AS pct_of_total_in_90d
FROM recent r
JOIN lifetime lf ON lf.listing_id = r.listing_id
JOIN listings l ON l.id = r.listing_id
WHERE lf.total_reviews >= 20
ORDER BY r.reviews_90d DESC
LIMIT 20;

-- ----------------------------------------------------------------------------
-- R4. Review-velocity percentiles: how reviews concentrate across listings.
-- ----------------------------------------------------------------------------
SELECT CASE
           WHEN n_reviews = 0 THEN '0'
           WHEN n_reviews <= 5 THEN '1–5'
           WHEN n_reviews <= 20 THEN '6–20'
           WHEN n_reviews <= 50 THEN '21–50'
           ELSE '51+'
       END AS review_count_band,
       COUNT(*) AS listings,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct_of_listings
FROM (
    SELECT l.id, COUNT(r.id) AS n_reviews
    FROM listings l
    LEFT JOIN reviews r ON r.listing_id = l.id
    GROUP BY l.id
)
GROUP BY review_count_band
ORDER BY MIN(n_reviews);

-- ----------------------------------------------------------------------------
-- R5. Most reviews per month: listings with the densest recent review
-- stream (reviews in last 12 months).
-- ----------------------------------------------------------------------------
SELECT l.name,
       l.neighbourhood_cleansed AS neighbourhood,
       l.room_type,
       ROUND(l.price, 2) AS price,
       l.review_scores_rating AS rating,
       COUNT(*) AS reviews_12mo
FROM reviews r
JOIN listings l ON l.id = r.listing_id
WHERE r.date >= DATE('2026-08-15', '-365 days')
GROUP BY l.id
ORDER BY reviews_12mo DESC
LIMIT 15;

-- ----------------------------------------------------------------------------
-- R6. Seasonality of reviews: average monthly volume across 2024–2026
-- (August 2026 is partial — scrape month).
-- ----------------------------------------------------------------------------
WITH monthly AS (
    SELECT DATE(STRFTIME('%Y-%m-01', date)) AS ym_start, COUNT(*) AS cnt
    FROM reviews
    WHERE date >= '2024-01-01' AND date < '2026-08-01'
    GROUP BY ym_start
)
SELECT STRFTIME('%m', ym_start) AS month_num,
       ROUND(AVG(cnt), 0) AS avg_reviews_per_month
FROM monthly
GROUP BY month_num
ORDER BY month_num;
