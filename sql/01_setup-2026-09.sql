-- ============================================================================
-- 01_setup.sql — Toronto Airbnb Listings: database setup & data load
-- ============================================================================
-- Dataset : Inside Airbnb — Toronto, Ontario, Canada (detailed listings)
-- Snapshot: 2026-09 release
-- Engine  : SQLite 3.45+
--
-- Run from the project root:
--     sqlite3 data/airbnb_toronto.db < sql/01_setup.sql
--
-- Strategy: import the CSV into a raw staging table (everything TEXT, so the
-- load never fails on messy values), then build a clean, typed `listings`
-- table with derived/cleaned columns for analysis.
-- ============================================================================

-- --- 1. Raw staging table (schema matches listings.csv exactly) --------------
DROP TABLE IF EXISTS listings_raw;
CREATE TABLE listings_raw (
    "id" TEXT,
    "listing_url" TEXT,
    "scrape_id" TEXT,
    "last_scraped" TEXT,
    "source" TEXT,
    "name" TEXT,
    "description" TEXT,
    "neighborhood_overview" TEXT,
    "picture_url" TEXT,
    "host_id" TEXT,
    "host_url" TEXT,
    "host_profile_id" TEXT,
    "host_profile_url" TEXT,
    "host_name" TEXT,
    "host_since" TEXT,
    "hosts_time_as_user_years" TEXT,
    "hosts_time_as_user_months" TEXT,
    "hosts_time_as_host_years" TEXT,
    "hosts_time_as_host_months" TEXT,
    "host_location" TEXT,
    "host_about" TEXT,
    "host_response_time" TEXT,
    "host_response_rate" TEXT,
    "host_acceptance_rate" TEXT,
    "host_is_superhost" TEXT,
    "host_thumbnail_url" TEXT,
    "host_picture_url" TEXT,
    "host_neighbourhood" TEXT,
    "host_listings_count" TEXT,
    "host_total_listings_count" TEXT,
    "host_verifications" TEXT,
    "host_has_profile_pic" TEXT,
    "host_identity_verified" TEXT,
    "neighbourhood" TEXT,
    "neighbourhood_cleansed" TEXT,
    "neighbourhood_group_cleansed" TEXT,
    "latitude" TEXT,
    "longitude" TEXT,
    "property_type" TEXT,
    "room_type" TEXT,
    "accommodates" TEXT,
    "bathrooms" TEXT,
    "bathrooms_text" TEXT,
    "bedrooms" TEXT,
    "beds" TEXT,
    "amenities" TEXT,
    "price" TEXT,
    "price_quote_checkin_date" TEXT,
    "price_quote_checkout_date" TEXT,
    "price_quote_total_price" TEXT,
    "price_quote_price_per_night" TEXT,
    "price_quote_raw" TEXT,
    "minimum_nights" TEXT,
    "maximum_nights" TEXT,
    "minimum_minimum_nights" TEXT,
    "maximum_minimum_nights" TEXT,
    "minimum_maximum_nights" TEXT,
    "maximum_maximum_nights" TEXT,
    "minimum_nights_avg_ntm" TEXT,
    "maximum_nights_avg_ntm" TEXT,
    "calendar_updated" TEXT,
    "has_availability" TEXT,
    "availability_30" TEXT,
    "availability_60" TEXT,
    "availability_90" TEXT,
    "availability_365" TEXT,
    "calendar_last_scraped" TEXT,
    "number_of_reviews" TEXT,
    "number_of_reviews_ltm" TEXT,
    "number_of_reviews_l30d" TEXT,
    "availability_eoy" TEXT,
    "number_of_reviews_ly" TEXT,
    "estimated_occupancy_l365d" TEXT,
    "estimated_revenue_l365d" TEXT,
    "first_review" TEXT,
    "last_review" TEXT,
    "review_scores_rating" TEXT,
    "review_scores_accuracy" TEXT,
    "review_scores_cleanliness" TEXT,
    "review_scores_checkin" TEXT,
    "review_scores_communication" TEXT,
    "review_scores_location" TEXT,
    "review_scores_value" TEXT,
    "license" TEXT,
    "instant_bookable" TEXT,
    "calculated_host_listings_count" TEXT,
    "calculated_host_listings_count_entire_homes" TEXT,
    "calculated_host_listings_count_private_rooms" TEXT,
    "calculated_host_listings_count_shared_rooms" TEXT,
    "reviews_per_month" TEXT
);

-- --- 2. Load the CSV ---------------------------------------------------------
-- csv mode handles quoted fields, embedded commas and multi-line text.
.mode csv
.import --skip 1 'data/listings-2026-09.csv' listings_raw

-- --- 3. Clean, typed analysis table ------------------------------------------
DROP TABLE IF EXISTS listings;
CREATE TABLE listings AS
SELECT
    CAST(id AS INTEGER)                                        AS id,
    NULLIF(name, '')                                           AS name,
    DATE(last_scraped)                                        AS last_scraped,
    CAST(NULLIF(host_id, '') AS INTEGER)                       AS host_id,
    NULLIF(host_name, '')                                     AS host_name,
    DATE(NULLIF(host_since, ''))                               AS host_since,
    CASE host_is_superhost WHEN 't' THEN 1 WHEN 'f' THEN 0 END AS host_is_superhost,
    CAST(NULLIF(host_listings_count, '') AS INTEGER)           AS host_listings_count,
    NULLIF(neighbourhood, '')                                 AS neighbourhood,
    NULLIF(neighbourhood_cleansed, '')                         AS neighbourhood_cleansed,
    CAST(NULLIF(latitude, '') AS REAL)                         AS latitude,
    CAST(NULLIF(longitude, '') AS REAL)                        AS longitude,
    NULLIF(property_type, '')                                 AS property_type,
    NULLIF(room_type, '')                                     AS room_type,
    CAST(NULLIF(accommodates, '') AS INTEGER)                  AS accommodates,
    -- bathrooms_text looks like '1 bath' / '2.5 baths' -> numeric baths
    CAST(
        CASE
            WHEN bathrooms_text = '' THEN NULL
            ELSE SUBSTR(bathrooms_text, 1, INSTR(bathrooms_text, ' ') - 1)
        END AS REAL
    )                                                          AS bathrooms,
    CAST(NULLIF(bedrooms, '') AS REAL)                         AS bedrooms,
    CAST(NULLIF(beds, '') AS REAL)                             AS beds,
    -- price looks like '$1,449.89' -> strip '$' and ',' -> REAL (CAD)
    CAST(
        NULLIF(REPLACE(REPLACE(price, '$', ''), ',', ''), '') AS REAL
    )                                                          AS price,
    CAST(NULLIF(minimum_nights, '') AS INTEGER)                AS minimum_nights,
    CAST(NULLIF(availability_30, '') AS INTEGER)              AS availability_30,
    CAST(NULLIF(availability_60, '') AS INTEGER)              AS availability_60,
    CAST(NULLIF(availability_90, '') AS INTEGER)              AS availability_90,
    CAST(NULLIF(availability_365, '') AS INTEGER)             AS availability_365,
    CAST(NULLIF(number_of_reviews, '') AS INTEGER)            AS number_of_reviews,
    CAST(NULLIF(reviews_per_month, '') AS REAL)               AS reviews_per_month,
    DATE(NULLIF(first_review, ''))                            AS first_review,
    DATE(NULLIF(last_review, ''))                             AS last_review,
    CAST(NULLIF(review_scores_rating, '') AS REAL)            AS review_scores_rating,
    CAST(NULLIF(estimated_occupancy_l365d, '') AS INTEGER)    AS estimated_occupancy_l365d,
    CAST(NULLIF(estimated_revenue_l365d, '') AS REAL)         AS estimated_revenue_l365d,
    CAST(NULLIF(calculated_host_listings_count, '') AS INTEGER)
                                                              AS calculated_host_listings_count
FROM listings_raw;

-- Primary key on the cleaned table (ids were verified unique in staging).
CREATE UNIQUE INDEX idx_listings_id ON listings (id);

-- --- 4. Helpful indexes for the analysis workload -----------------------------
CREATE INDEX idx_listings_neighbourhood  ON listings (neighbourhood_cleansed);
CREATE INDEX idx_listings_room_type      ON listings (room_type);
CREATE INDEX idx_listings_price          ON listings (price);
CREATE INDEX idx_listings_host_id        ON listings (host_id);
CREATE INDEX idx_listings_superhost      ON listings (host_is_superhost);

-- --- 5. Smoke tests -----------------------------------------------------------
SELECT 'raw rows'      AS check_name, COUNT(*) AS value FROM listings_raw
UNION ALL
SELECT 'clean rows',   COUNT(*)                FROM listings
UNION ALL
SELECT 'distinct ids', COUNT(DISTINCT id)      FROM listings
UNION ALL
SELECT 'min scrape',   MIN(last_scraped)       FROM listings
UNION ALL
SELECT 'max scrape',   MAX(last_scraped)       FROM listings;
