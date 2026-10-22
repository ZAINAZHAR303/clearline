-- =============================================================================
-- Clearline -- register the sources as Lightning REST tables.
--
-- Pattern copied from the proven recipe in the Zetaris getting-started repo:
--   open_data/rest_apis/sql/non_rate_limited/02_pokeapi_create.sql
-- A REST table expects a JSON OBJECT at the root; arrays inside it are flattened
-- with LATERAL VIEW explode(). That is why the sample files wrap their records
-- under a single key rather than being a bare array.
--
-- PREREQUISITE: the data sidecar must be running, so that Zetaris itself (not
-- just your laptop) can reach the files. Zetaris cannot read a file sitting on
-- your host filesystem. Start it with:
--
--     bash scripts/sidecar.sh
--
-- Then these endpoints resolve from inside the Zetaris network:
--     http://clearline-data/vendor_master.json
--     http://clearline-data/sanctions_sample.json
--
-- Run ONE statement at a time.
-- =============================================================================

-- --- Source 1: internal vendor master ---------------------------------------
-- This is the "internal data an organisation runs on" that Zetaris exists to
-- serve, and it is what makes this a fragmented-intelligence problem rather
-- than a public-data mashup.

CREATE LIGHTNING REST TABLE vendor_master_raw FROM CLEARLINE_REST REQUEST(
    endpoint "http://clearline-data/vendor_master.json",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
) BODY ();

CREATE SCHEMASTORE VIEW vendor_master_table WITH CONTAINER clearline AS
SELECT
    v.vendor_id,
    v.legal_name,
    v.trading_name,
    v.tax_id,
    v.country,
    v.address,
    v.bank_country,
    v.onboarded_date,
    v.annual_spend_usd,
    v.category
FROM clearline_rest.vendor_master_raw
LATERAL VIEW explode(vendors) AS v;


-- --- Source 2: sanctions extract --------------------------------------------
-- Day 1 registers the synthetic placeholder. Day 2 replaces the file served by
-- the sidecar with the real OpenSanctions bulk extract; these statements do not
-- change, only the file behind the endpoint does.

CREATE LIGHTNING REST TABLE sanctions_raw FROM CLEARLINE_REST REQUEST(
    endpoint "http://clearline-data/sanctions_sample.json",
    method "get",
    response_type "json",
    http_encoding "URLENCODED"
) HEADER (
) BODY ();

CREATE SCHEMASTORE VIEW sanctions_table WITH CONTAINER clearline AS
SELECT
    e.id          AS entity_id,
    e.caption     AS caption,
    e.country     AS country,
    e.dataset     AS dataset,
    alias         AS alias
FROM clearline_rest.sanctions_raw
LATERAL VIEW explode(entities) AS e
LATERAL VIEW explode(e.aliases) AS alias;


-- --- Day 2: GLEIF and EDGAR --------------------------------------------------
-- GLEIF needs no key. EDGAR 403s without a descriptive User-Agent, which goes
-- in the HEADER() block -- that is what it is for:
--
-- CREATE LIGHTNING REST TABLE edgar_company FROM CLEARLINE_REST REQUEST(
--     endpoint "https://data.sec.gov/submissions/CIK0000320193.json",
--     method "get",
--     response_type "json",
--     http_encoding "URLENCODED"
-- ) HEADER (
--     "User-Agent" "Clearline Hackathon your.email@example.com"
-- ) BODY ();


-- --- Verify ------------------------------------------------------------------
-- SELECT vendor_id, legal_name, country FROM clearline.vendor_master_table LIMIT 5;
-- SELECT entity_id, caption, alias FROM clearline.sanctions_table LIMIT 10;
