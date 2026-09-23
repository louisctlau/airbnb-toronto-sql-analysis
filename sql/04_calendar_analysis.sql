-- ============================================================================
-- 04_calendar_analysis.sql — Real occupancy from calendar data
-- ============================================================================
-- Run from the project root:
--     sqlite3 data/airbnb_toronto_2026_08.db < sql/04_calendar_analysis.sql
--
-- Dataset: Inside Airbnb calendar.csv.gz, Toronto, 2026-08-15 release
-- (scraped 2026-08-15 → 2026-08-27). 8,123,819 rows: 22,257 listings × 365
-- future days each (2026-08-15 → 2027-08-14, per-listing start may vary).
--
-- NOTE: this release has no price columns in calendar.csv, so all price
-- questions use the listings snapshot.
--
-- Caveat: unavailable ('f') days mix true bookings with host blocks /
-- seasonal unavailability — "occupancy" here is non-availability, the best
-- forward-looking proxy available.
-- ============================================================================
.mode column
.headers on

-- ----------------------------------------------------------------------------
-- C1. City-wide true occupancy: what share of the next 365 days is each
-- listing unavailable, averaged across listings?
-- ----------------------------------------------------------------------------
SELECT ROUND(AVG(1.0 * booked_days / total_days) * 100, 1) AS avg_true_occupancy_pct,
       COUNT(*) AS listings
FROM (
    SELECT listing_id,
           COUNT(*) AS total_days,
           SUM(1 - available) AS booked_days
    FROM calendar
    GROUP BY listing_id
);

-- ----------------------------------------------------------------------------
-- C2. True vs estimated occupancy by neighbourhood (top 10 by listing count).
-- Shows whether Inside Airbnb's `estimated_occupancy_l365d` is biased.
-- ----------------------------------------------------------------------------
WITH cal AS (
    SELECT listing_id,
           ROUND(100.0 * SUM(1 - available) / COUNT(*), 1) AS true_occ_pct
    FROM calendar
    GROUP BY listing_id
)
SELECT l.neighbourhood_cleansed AS neighbourhood,
       COUNT(*) AS listings,
       ROUND(AVG(cal.true_occ_pct), 1) AS true_occ_pct,
       ROUND(AVG(100.0 * l.estimated_occupancy_l365d / 365), 1) AS est_occ_pct,
       ROUND(AVG(cal.true_occ_pct) - AVG(100.0 * l.estimated_occupancy_l365d / 365), 1)
           AS bias_pts_true_minus_est
FROM listings l
JOIN cal ON cal.listing_id = l.id
WHERE l.estimated_occupancy_l365d IS NOT NULL
GROUP BY l.neighbourhood_cleansed
ORDER BY COUNT(*) DESC
LIMIT 10;

-- ----------------------------------------------------------------------------
-- C3. Seasonal availability curve: share of days bookable, by calendar month
-- (next 12 months). Peaks reveal high-demand season.
-- ----------------------------------------------------------------------------
SELECT STRFTIME('%Y-%m', date) AS cal_month,
       COUNT(*) AS listing_days,
       ROUND(100.0 * AVG(available), 1) AS pct_available
FROM calendar
GROUP BY cal_month
ORDER BY cal_month;

-- ----------------------------------------------------------------------------
-- C4. Booking lead-time proxy: how far ahead are listings currently booked?
-- For each listing, days from its first calendar date to its first
-- unavailable day; distribution of that lead time.
-- ----------------------------------------------------------------------------
WITH firsts AS (
    SELECT listing_id, MIN(date) AS start_date,
           MIN(CASE WHEN available = 0 THEN date END) AS first_booked
    FROM calendar
    GROUP BY listing_id
)
SELECT CASE
           WHEN first_booked IS NULL THEN 'No bookings in 365d'
           WHEN JULIANDAY(first_booked) - JULIANDAY(start_date) <= 7  THEN '0–7 days'
           WHEN JULIANDAY(first_booked) - JULIANDAY(start_date) <= 30 THEN '8–30 days'
           WHEN JULIANDAY(first_booked) - JULIANDAY(start_date) <= 90 THEN '31–90 days'
           ELSE '90+ days'
       END AS lead_time_band,
       COUNT(*) AS listings,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM firsts
GROUP BY lead_time_band
ORDER BY CASE lead_time_band
    WHEN '0–7 days' THEN 1 WHEN '8–30 days' THEN 2 WHEN '31–90 days' THEN 3
    WHEN '90+ days' THEN 4 ELSE 5 END;

-- ----------------------------------------------------------------------------
-- C5. minimum_nights distribution: how long must guests stay?
-- ----------------------------------------------------------------------------
SELECT CASE
           WHEN minimum_nights <= 1 THEN '1 night'
           WHEN minimum_nights <= 3 THEN '2–3 nights'
           WHEN minimum_nights <= 7 THEN '4–7 nights'
           WHEN minimum_nights <= 30 THEN '8–30 nights'
           ELSE '31+ nights'
       END AS min_nights_band,
       COUNT(*) AS listings,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM (
    SELECT listing_id, MIN(minimum_nights) AS minimum_nights
    FROM calendar
    GROUP BY listing_id
)
GROUP BY min_nights_band
ORDER BY MIN(minimum_nights);

-- ----------------------------------------------------------------------------
-- C6. min_nights by room type — do entire homes demand longer stays?
-- ----------------------------------------------------------------------------
SELECT l.room_type,
       COUNT(*) AS listings,
       ROUND(AVG(m.minimum_nights), 1) AS avg_min_nights,
       ROUND(AVG(100.0 * m.booked_days / m.total_days), 1) AS avg_true_occ_pct
FROM listings l
JOIN (
    SELECT listing_id, MIN(minimum_nights) AS minimum_nights,
           SUM(1 - available) AS booked_days, COUNT(*) AS total_days
    FROM calendar
    GROUP BY listing_id
) m ON m.listing_id = l.id
GROUP BY l.room_type;
