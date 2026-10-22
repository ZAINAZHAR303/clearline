-- =============================================================================
-- Clearline -- Unified Semantic Layer: the Counterparty model.
--
-- This is the heart of the Track 1 claim. Two sources that share no key and
-- disagree about names -- an internal vendor book and the OFAC SDN list --
-- become one governed business model with declared relationships, so the agent
-- asks ONE semantic question and Zetaris federates it.
--
-- Pattern taken from the reference build in the Zetaris getting-started repo
-- (open_data/usl/sql/02_sic_edgar_usl_create.sql).
--
-- Statements in this file are separated by `-- @@`, not by semicolons: a
-- COMPILE USL ... DDL statement contains several CREATE TABLE blocks that each
-- end in a semicolon, so splitting on `;` would break it apart.
--
--   python scripts/apply_sql.py sql/03_usl_counterparty.sql
-- =============================================================================

CREATE NAMESPACE IF NOT EXISTS lightning.metastore;

-- @@

CREATE NAMESPACE IF NOT EXISTS lightning.metastore.clearline;

-- @@

-- The model. watchlist_alias is a separate table with a foreign key because
-- the alias is what actually identifies a counterparty -- "Metaalkunde BV" is
-- an alias of an entity whose caption looks nothing like it. Modelling aliases
-- as first-class rows is what lets a single join find that.
COMPILE USL IF NOT EXISTS counterparty_usl DEPLOY NAMESPACE lightning.metastore.clearline DDL
CREATE TABLE counterparty (
    vendor_id varchar(10) NOT NULL PRIMARY KEY,
    legal_name varchar(200) NOT NULL,
    trading_name varchar(200),
    tax_id varchar(40),
    country varchar(2),
    bank_country varchar(2),
    onboarded_date varchar(10),
    annual_spend_usd bigint,
    category varchar(60)
);
CREATE TABLE watchlist_entity (
    entity_id varchar(40) NOT NULL PRIMARY KEY,
    caption varchar(300) NOT NULL,
    country varchar(2),
    dataset varchar(40),
    programme varchar(200)
);
CREATE TABLE watchlist_alias (
    alias_key varchar(340) NOT NULL PRIMARY KEY,
    entity_id varchar(40) NOT NULL FOREIGN KEY REFERENCES watchlist_entity(entity_id),
    alias varchar(300) NOT NULL
);

-- @@

UPDATE USL lightning.metastore.clearline.counterparty_usl SET DESCRIPTION 'Clearline counterparty model. Joins an internal vendor book to the OFAC SDN watchlist, which share no key and disagree on names. Aliases are first-class rows because the alias, not the caption, is what identifies a counterparty.';

-- @@

UPDATE USL lightning.metastore.clearline.counterparty_usl.counterparty SET TABLE DESCRIPTION 'One row per vendor in the internal procurement book. tax_id is ~16 percent null, which the agent reads at runtime and raises its evidence bar for.';

-- @@

UPDATE USL lightning.metastore.clearline.counterparty_usl.watchlist_entity SET TABLE DESCRIPTION 'One row per sanctioned organisation. country is where the entity is registered, never the jurisdiction of the list it appears on.';

-- @@

UPDATE USL lightning.metastore.clearline.counterparty_usl.watchlist_alias SET TABLE DESCRIPTION 'One row per alias. An exact match here against a vendor legal name is the identification a screening decision rests on.';

-- @@

-- NOT NULL columns must be fed by expressions the planner can prove are not
-- nullable, or ACTIVATE fails with "Schema mismatch ... nullable -> NOT NULL".
-- COALESCE is what the reference build uses for exactly this.
ACTIVATE USL TABLE lightning.metastore.clearline.counterparty_usl.counterparty AS
SELECT
    COALESCE(vendor_id, '') AS vendor_id,
    COALESCE(legal_name, '') AS legal_name,
    trading_name,
    tax_id,
    country,
    bank_country,
    onboarded_date,
    CAST(annual_spend_usd AS bigint) AS annual_spend_usd,
    category
FROM clearline.vendor_master_table;

-- @@

ACTIVATE USL TABLE lightning.metastore.clearline.counterparty_usl.watchlist_entity AS
SELECT DISTINCT
    COALESCE(entity_id, '') AS entity_id,
    COALESCE(caption, '') AS caption,
    country,
    dataset,
    CAST(NULL AS string) AS programme
FROM clearline.sanctions_table;

-- @@

ACTIVATE USL TABLE lightning.metastore.clearline.counterparty_usl.watchlist_alias AS
SELECT
    COALESCE(CONCAT(entity_id, '|', alias), '') AS alias_key,
    COALESCE(entity_id, '') AS entity_id,
    COALESCE(alias, '') AS alias
FROM clearline.sanctions_table
WHERE alias IS NOT NULL;

-- @@

-- Data quality, run by Zetaris rather than computed in the agent. The result
-- is what the agent reads at runtime to decide how much weight a column can
-- carry -- see clearline/zetaris.py::dq_report.
RUN DQ TABLE lightning.metastore.clearline.counterparty_usl.counterparty;

-- @@

RUN DQ TABLE lightning.metastore.clearline.counterparty_usl.watchlist_alias;
