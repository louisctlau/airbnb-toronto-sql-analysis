-- ============================================================================
-- 02_exploration.sql — Data quality & exploratory checks
-- ============================================================================
-- Run from the project root:
--     sqlite3 data/airbnb_toronto.db < sql/02_exploration.sql
--
-- Each section starts with a comment describing what it checks and why.
-- Expected outputs are left as TODOs in README/docs for the analyst to fill in.
-- ============================================================================
.mode column
.headers on

-- ----------------------------------------------------------------------------
-- Q0. Overall size and scrape window.
-- A snapshot scraped over several days is normal for Inside Airbnb data.
-- ----------------------------------------------------------------------------
SELECT COUNT(*) AS listings,
       MIN(last_scraped) AS earliest_scrape,
       MAX(last_scraped) AS latest_scrape
FROM listings;

-- ----------------------------------------------------------------------------
-- Q1. Null / empty checks on the columns every downstream query relies on.
-- Missing prices, room types, neighbourhoods or coordinates must be known
-- before they can silently bias the analysis.
-- ----------------------------------------------------------------------------
SELECT
    COUNT(*)                                                     AS total_listings,
    SUM(price IS NULL)                                           AS missing_price,
    SUM(room_type IS NULL)                                       AS missing_room_type,
    SUM(neighbourhood_cleansed IS NULL)                          AS missing_neighbourhood,
    SUM(latitude IS NULL OR longitude IS NULL)                   AS missing_coordinates,
    SUM(number_of_reviews IS NULL)                               AS missing_review_count,
    SUM(review_scores_rating IS NULL)                            AS missing_rating,
    SUM(first_review IS NULL)                                    AS listings_never_reviewed,
    ROUND(100.0 * SUM(price IS NULL) / COUNT(*), 1)               AS pct_missing_price
FROM listings;

-- ----------------------------------------------------------------------------
-- Q2. Categorical coverage: room types, property types, host response values.
-- Flags unexpected categories and shows the market mix at a glance.
-- ----------------------------------------------------------------------------
SELECT room_type, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM listings
GROUP BY room_type
ORDER BY n DESC;

SELECT property_type, COUNT(*) AS n
FROM listings
GROUP BY property_type
ORDER BY n DESC
LIMIT 15;

-- ----------------------------------------------------------------------------
-- Q3. Price distribution by room type (min / max / avg / median).
-- Median is computed with a window function; the mean alone hides the skew.
-- Prices of 0 or NULL are excluded as data-entry noise / missing quotes.
-- ----------------------------------------------------------------------------
WITH ranked AS (
    SELECT room_type, price,
           ROW_NUMBER() OVER (PARTITION BY room_type ORDER BY price) AS rn,
           COUNT(*)     OVER (PARTITION BY room_type)                 AS cnt
    FROM listings
    WHERE price > 0
)
SELECT room_type,
       COUNT(*)                                   AS n,
       ROUND(MIN(price), 2)                       AS min_price,
       ROUND(AVG(price), 2)                       AS avg_price,
       ROUND(AVG(CASE WHEN rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
                      THEN price END), 2)        AS median_price,
       ROUND(MAX(price), 2)                       AS max_price
FROM ranked
GROUP BY room_type
ORDER BY median_price DESC;

-- ----------------------------------------------------------------------------
-- Q4. Duplicate listing ids — there should be none (id is the natural key).
-- ----------------------------------------------------------------------------
SELECT id, COUNT(*) AS occurrences
FROM listings
GROUP BY id
HAVING COUNT(*) > 1;

-- ----------------------------------------------------------------------------
-- Q5. Numeric range sanity: impossible values in capacity/availability fields.
-- ----------------------------------------------------------------------------
SELECT
    SUM(accommodates <= 0 OR accommodates > 16)            AS odd_accommodates,
    SUM(bedrooms < 0 OR bedrooms > 10)                     AS odd_bedrooms,
    SUM(availability_365 < 0 OR availability_365 > 365)    AS bad_availability_365,
    SUM(availability_30 < 0 OR availability_30 > 30)       AS bad_availability_30,
    SUM(review_scores_rating < 1 OR review_scores_rating > 5) AS bad_rating,
    SUM(minimum_nights < 0)                                AS negative_min_nights,
    SUM(price < 0)                                        AS negative_price
FROM listings;

-- ----------------------------------------------------------------------------
-- Q6. Review-date integrity: last_review before first_review, or reviews
-- dated after the scrape itself, would signal bad source data.
-- ----------------------------------------------------------------------------
SELECT
    SUM(last_review < first_review)                        AS last_before_first,
    SUM(last_review > last_scraped)                        AS review_after_scrape,
    SUM(first_review IS NOT NULL AND number_of_reviews = 0) AS has_first_review_but_zero_reviews
FROM listings;

-- ----------------------------------------------------------------------------
-- Q7. Completely empty "dead" columns — e.g. instant_bookable is blank for
-- every row in this snapshot, so it is dropped from the cleaned table.
-- (Checked against listings_raw; kept here as a documented decision.)
-- ----------------------------------------------------------------------------
SELECT COUNT(*) AS rows_where_instant_bookable_is_blank
FROM listings_raw
WHERE instant_bookable IS NULL OR instant_bookable = '';

-- ----------------------------------------------------------------------------
-- Q8. Spot-check: 5 random listings to eyeball the cleaned values.
-- ----------------------------------------------------------------------------
SELECT id, name, neighbourhood_cleansed, room_type, price,
       accommodates, bathrooms, bedrooms, number_of_reviews, last_scraped
FROM listings
ORDER BY RANDOM()
LIMIT 5;
