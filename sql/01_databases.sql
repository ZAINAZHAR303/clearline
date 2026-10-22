-- =============================================================================
-- Clearline -- Lightning database and schemastore container.
-- Run ONE statement at a time in the SQL Editor (http://localhost:3000) or via
-- scripts/run_sql.py. Lightning SQL does not accept a batch.
--
-- NOTE: the DESCRIBE BY text accepts alphanumerics, spaces and _ . - , only.
-- A colon returns 400 "Description is invalid", and every dependent CREATE
-- then fails with "Lightning Database doesn't exist", which looks unrelated.
--
-- "Object already exists" on a re-run is fine: check the existing object
-- matches and move on to the next statement.
-- =============================================================================

CREATE LIGHTNING DATABASE CLEARLINE_REST DESCRIBE BY "Clearline internal vendor master plus external registries";

CREATE SCHEMASTORE CONTAINER clearline;
