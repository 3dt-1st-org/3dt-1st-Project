-- Purpose: build Google search queries for events with missing city.
-- Replace table/column names if your schema differs.

SELECT
    id,
    title,
    trim(title) || ' 장소' AS google_query
FROM locallink.gyeonggi_events
WHERE coalesce(nullif(trim(city), ''), '기타') = '기타'
ORDER BY id;
