"""
load.py
=======
Loads the transformed records into a relational database that matches
the schema in the ERD:

  Brands · Websites · SocialMediaAccounts · Sources · Formats
  ContentPillars · StrategyPillars · Posts · Metrics · Traffic · Terms

Uses SQLAlchemy Core (no ORM) so the same code works with PostgreSQL,
MySQL, and SQLite.  Pass the connection string via the DB_URL env var
or the Loader constructor.

Upsert strategy
---------------
Every table that receives recurring data uses INSERT … ON CONFLICT DO
UPDATE (Postgres) or REPLACE INTO (SQLite/MySQL) based on a row_hash or
natural-key column so re-running the pipeline is idempotent.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    create_engine, text,
)
from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Schema definition  (mirrors the ERD exactly)
# ──────────────────────────────────────────────────────────────────────────────

metadata = MetaData()

brands_table = Table(
    "Brands", metadata,
    Column("id",   Integer, primary_key=True, autoincrement=True),
    Column("name", String(255), nullable=False, unique=True),
)

websites_table = Table(
    "Websites", metadata,
    Column("id",          Integer, primary_key=True, autoincrement=True),
    Column("brand_id",    Integer, ForeignKey("Brands.id"), nullable=False),
    Column("url",         String(512)),
    Column("page_name",   String(255)),
    Column("propperty_id", String(255)),   # GA4 property id string
    Index("ix_websites_brand", "brand_id"),
)

social_media_accounts_table = Table(
    "SocialMediaAccounts", metadata,
    Column("id",       Integer, primary_key=True, autoincrement=True),
    Column("brand_id", Integer, ForeignKey("Brands.id"), nullable=False),
    Column("channel",  String(100), nullable=False),
    Index("ix_sma_brand_channel", "brand_id", "channel", unique=True),
)

sources_table = Table(
    "Sources", metadata,
    Column("id",       Integer, primary_key=True, autoincrement=True),
    Column("source",   String(255)),
    Column("medium",   String(255)),
    Column("campaign", String(255)),
    Column("brand_id", Integer, ForeignKey("Brands.id")),
)

formats_table = Table(
    "Formats", metadata,
    Column("id",     Integer, primary_key=True, autoincrement=True),
    Column("format", String(100), nullable=False, unique=True),
)

content_pillars_table = Table(
    "ContentPillars", metadata,
    Column("id",     Integer, primary_key=True, autoincrement=True),
    Column("pillar", String(255), nullable=False, unique=True),
)

strategy_pillars_table = Table(
    "StrategyPillars", metadata,
    Column("id",       Integer, primary_key=True, autoincrement=True),
    Column("pillar",   String(255), nullable=False),
    Column("brand_id", Integer, ForeignKey("Brands.id")),
)

posts_table = Table(
    "Posts", metadata,
    Column("id",               Integer, primary_key=True, autoincrement=True),
    Column("postText",         Text),
    Column("postUrl",          String(1024)),
    Column("format_id",        Integer, ForeignKey("Formats.id")),
    Column("content_pillar_id",Integer, ForeignKey("ContentPillars.id")),
    Column("created_at",       DateTime(timezone=True)),
    Column("strategy_pillar_id", Integer, ForeignKey("StrategyPillars.id")),
    Column("metrics",          Integer),          # FK resolved after insert
    Column("account_id",       Integer, ForeignKey("SocialMediaAccounts.id")),
    Column("umap_x",           Integer),
    Column("umap_y",           Integer),
    Column("row_hash",         String(64), unique=True),
    Column("updated_at",       DateTime(timezone=True)),
    Index("ix_posts_account",  "account_id"),
    Index("ix_posts_hash",     "row_hash"),
)

metrics_table = Table(
    "Metrics", metadata,
    Column("id",             Integer, primary_key=True, autoincrement=True),
    Column("account_id",     Integer, ForeignKey("SocialMediaAccounts.id")),
    Column("bookmarks",      Integer, default=0),
    Column("clicks",         Integer, default=0),
    Column("comments",       Integer, default=0),
    Column("date",           DateTime(timezone=True)),
    Column("engagementRate", Float,   default=0.0),
    Column("engagements",    Integer, default=0),
    Column("followersGained",Integer, default=0),
    Column("followersTotal", Integer, default=0),
    Column("impressions",    Integer, default=0),
    Column("reactions",      Integer, default=0),
    Column("shares",         Integer, default=0),
    Column("unfollows",      Integer, default=0),
    Column("row_hash",       String(64), unique=True),
    Column("updated_at",     DateTime(timezone=True)),
)

traffic_table = Table(
    "Traffic", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("metric1",   Float),
    Column("metric2",   Float),
    Column("metric3",   Float),
    Column("page_id",   Integer, ForeignKey("Websites.id")),
    Column("source_id", Integer, ForeignKey("Sources.id")),
)

terms_table = Table(
    "Terms", metadata,
    Column("id",               Integer, primary_key=True, autoincrement=True),
    Column("term",             String(255), nullable=False),
    Column("engagement_score", Float),
    Column("account_id",       Integer, ForeignKey("SocialMediaAccounts.id")),
    Column("updated_at",       DateTime(timezone=True)),
    Index("ix_terms_term",    "term"),
)


# ──────────────────────────────────────────────────────────────────────────────
# Upsert helpers  (dialect-aware)
# ──────────────────────────────────────────────────────────────────────────────

def _upsert(engine: Engine, table: Table, rows: list[dict], conflict_cols: list[str]) -> None:
    """
    Insert rows; on conflict on `conflict_cols`, update all other columns.
    Works with PostgreSQL and SQLite.  For MySQL swap to
    sqlalchemy.dialects.mysql.insert.
    """
    if not rows:
        return

    dialect = engine.dialect.name

    with engine.begin() as conn:
        for chunk in _chunks(rows, 500):
            if dialect == "postgresql":
                stmt = pg_insert(table).values(chunk)
                update_cols = {
                    c.name: stmt.excluded[c.name]
                    for c in table.columns
                    if c.name not in conflict_cols and not c.primary_key
                }
                stmt = stmt.on_conflict_do_update(
                    index_elements=conflict_cols,
                    set_=update_cols,
                )
            else:
                # SQLite / fallback: replace
                stmt = sqlite_insert(table).values(chunk)
                update_cols = {
                    c.name: stmt.excluded[c.name]
                    for c in table.columns
                    if c.name not in conflict_cols and not c.primary_key
                }
                stmt = stmt.on_conflict_do_update(
                    index_elements=conflict_cols,
                    set_=update_cols,
                )

            conn.execute(stmt)


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


# ──────────────────────────────────────────────────────────────────────────────
# Reference-data helpers
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_FORMATS = [
    "Carousel", "Video", "Text", "Image", "Poll",
    "Story", "Reel", "Article", "Other",
]

DEFAULT_CONTENT_PILLARS = [
    "Educational", "Inspirational", "Promotional", "Entertainment",
    "Community", "Behind-the-Scenes", "User-Generated", "News", "Other",
]

DEFAULT_STRATEGY_PILLARS = [
    "Brand Awareness", "Lead Generation", "Engagement", "Retention",
    "Conversion", "Thought Leadership", "Partnership", "Other",
]


def _seed_reference_tables(engine: Engine, brand_id: int) -> dict[str, dict[str, int]]:
    """
    Ensure Formats, ContentPillars, and StrategyPillars are populated.
    Returns three lookup dicts: {label → id}.
    """
    with engine.begin() as conn:
        # Formats
        for fmt in DEFAULT_FORMATS:
            conn.execute(
                text(
                    "INSERT INTO \"Formats\" (format) VALUES (:f) "
                    "ON CONFLICT (format) DO NOTHING"
                ),
                {"f": fmt},
            )

        # ContentPillars
        for p in DEFAULT_CONTENT_PILLARS:
            conn.execute(
                text(
                    "INSERT INTO \"ContentPillars\" (pillar) VALUES (:p) "
                    "ON CONFLICT (pillar) DO NOTHING"
                ),
                {"p": p},
            )

        # StrategyPillars
        for p in DEFAULT_STRATEGY_PILLARS:
            conn.execute(
                text(
                    "INSERT INTO \"StrategyPillars\" (pillar, brand_id) "
                    "VALUES (:p, :b) ON CONFLICT DO NOTHING"
                ),
                {"p": p, "b": brand_id},
            )

        formats = {
            r.format: r.id
            for r in conn.execute(text('SELECT id, format FROM "Formats"'))
        }
        content_pillars = {
            r.pillar: r.id
            for r in conn.execute(text('SELECT id, pillar FROM "ContentPillars"'))
        }
        strategy_pillars = {
            r.pillar: r.id
            for r in conn.execute(
                text('SELECT id, pillar FROM "StrategyPillars" WHERE brand_id = :b'),
                {"b": brand_id},
            )
        }

    return {
        "formats": formats,
        "content_pillars": content_pillars,
        "strategy_pillars": strategy_pillars,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main Loader
# ──────────────────────────────────────────────────────────────────────────────

class Loader:
    """
    Loads transformed records into the database.

    Parameters
    ----------
    db_url : str
        SQLAlchemy connection string, e.g.:
          "postgresql+psycopg2://user:pass@host:5432/dbname"
          "sqlite:///./social.db"
    brand_name : str
        Human-readable brand name.  The brand is upserted on first run.
    channels : list[str]
        Social channels to register as SocialMediaAccounts,
        e.g. ["linkedin", "x", "facebook", "instagram"]
    website_url : str | None
        Primary website URL to register in Websites.
    ga4_property_id : str | None
        GA4 property id string to store alongside the website.
    """

    def __init__(
        self,
        db_url: str | None = None,
        brand_name: str = "My Brand",
        channels: list[str] | None = None,
        website_url: str | None = None,
        ga4_property_id: str | None = None,
    ) -> None:
        self.db_url = db_url or os.environ["DB_URL"]
        self.brand_name = brand_name
        self.channels = channels or ["linkedin", "x", "facebook", "instagram"]
        self.website_url = website_url
        self.ga4_property_id = ga4_property_id

        self.engine = create_engine(self.db_url, echo=False, future=True)
        metadata.create_all(self.engine)

        self.brand_id: int = self._upsert_brand()
        self.account_map: dict[str, int] = self._upsert_accounts()
        self.website_id: int | None = self._upsert_website()
        self.ref = _seed_reference_tables(self.engine, self.brand_id)

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, transformed: dict[str, list[dict]]) -> None:
        """
        Accepts the dict produced by Transformer.run() and persists
        every table in dependency order.
        """
        self._load_posts(transformed.get("posts", []))
        self._load_metrics(transformed.get("metrics", []))
        self._load_traffic(transformed.get("traffic", []))
        self._load_terms(transformed.get("terms", []))
        logger.info("Load complete.")

    # ── Reference / lookup properties exposed for Transform ──────────────────

    @property
    def formats(self) -> dict[str, int]:
        return self.ref["formats"]

    @property
    def content_pillars(self) -> dict[str, int]:
        return self.ref["content_pillars"]

    @property
    def strategy_pillars(self) -> dict[str, int]:
        return self.ref["strategy_pillars"]

    # ── Setup helpers ─────────────────────────────────────────────────────────

    def _upsert_brand(self) -> int:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO "Brands" (name) VALUES (:n) '
                    "ON CONFLICT (name) DO NOTHING"
                ),
                {"n": self.brand_name},
            )
            row = conn.execute(
                text('SELECT id FROM "Brands" WHERE name = :n'),
                {"n": self.brand_name},
            ).fetchone()
        return row.id

    def _upsert_accounts(self) -> dict[str, int]:
        account_map: dict[str, int] = {}
        with self.engine.begin() as conn:
            for channel in self.channels:
                conn.execute(
                    text(
                        'INSERT INTO "SocialMediaAccounts" (brand_id, channel) '
                        "VALUES (:b, :c) ON CONFLICT (brand_id, channel) DO NOTHING"
                    ),
                    {"b": self.brand_id, "c": channel},
                )
                row = conn.execute(
                    text(
                        'SELECT id FROM "SocialMediaAccounts" '
                        "WHERE brand_id = :b AND channel = :c"
                    ),
                    {"b": self.brand_id, "c": channel},
                ).fetchone()
                if row:
                    account_map[channel] = row.id
        return account_map

    def _upsert_website(self) -> int | None:
        if not self.website_url:
            return None
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO "Websites" (brand_id, url, propperty_id) '
                    "VALUES (:b, :u, :p) ON CONFLICT DO NOTHING"
                ),
                {"b": self.brand_id, "u": self.website_url, "p": self.ga4_property_id},
            )
            row = conn.execute(
                text('SELECT id FROM "Websites" WHERE brand_id = :b AND url = :u'),
                {"b": self.brand_id, "u": self.website_url},
            ).fetchone()
        return row.id if row else None

    # ── Table loaders ─────────────────────────────────────────────────────────

    def _load_posts(self, records: list[dict]) -> None:
        if not records:
            return
        logger.info("Loading %d posts …", len(records))
        _upsert(self.engine, posts_table, records, ["row_hash"])

    def _load_metrics(self, records: list[dict]) -> None:
        if not records:
            return
        logger.info("Loading %d metric rows …", len(records))
        _upsert(self.engine, metrics_table, records, ["row_hash"])

    def _load_traffic(self, records: list[dict]) -> None:
        if not records:
            return
        logger.info("Resolving page/source IDs for %d traffic rows …", len(records))

        with self.engine.connect() as conn:
            pages = {
                r.url: r.id
                for r in conn.execute(
                    text('SELECT id, url FROM "Websites" WHERE brand_id = :b'),
                    {"b": self.brand_id},
                )
            }
            sources = {}
            for r in conn.execute(
                text('SELECT id, source, medium FROM "Sources" WHERE brand_id = :b'),
                {"b": self.brand_id},
            ):
                sources[(r.source, r.medium)] = r.id

        cleaned: list[dict] = []
        for row in records:
            page_path = row.pop("_page_path", "")
            source    = row.pop("_source", "")
            medium    = row.pop("_medium", "")
            row.pop("_date", None)

            # Resolve or insert Source
            src_key = (source, medium)
            if src_key not in sources:
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            'INSERT INTO "Sources" (source, medium, brand_id) '
                            "VALUES (:s, :m, :b) ON CONFLICT DO NOTHING"
                        ),
                        {"s": source, "m": medium, "b": self.brand_id},
                    )
                    r = conn.execute(
                        text(
                            'SELECT id FROM "Sources" '
                            "WHERE source = :s AND medium = :m AND brand_id = :b"
                        ),
                        {"s": source, "m": medium, "b": self.brand_id},
                    ).fetchone()
                    if r:
                        sources[src_key] = r.id

            row["page_id"]   = pages.get(page_path) or self.website_id
            row["source_id"] = sources.get(src_key)
            cleaned.append(row)

        with self.engine.begin() as conn:
            for chunk in _chunks(cleaned, 500):
                conn.execute(traffic_table.insert(), chunk)

    def _load_terms(self, records: list[dict]) -> None:
        if not records:
            return
        logger.info("Loading %d terms …", len(records))
        # Attach default account_id (first in map)
        default_account = next(iter(self.account_map.values()), None)
        for r in records:
            r.setdefault("account_id", default_account)
        _upsert(self.engine, terms_table, records, ["term"])


# ──────────────────────────────────────────────────────────────────────────────
# Convenience façade
# ──────────────────────────────────────────────────────────────────────────────

class ETLPipeline:
    """
    Wires together Extract → Transform → Load.

    Quick-start
    -----------
    from extract import Extractor
    from transform import Transformer
    from load import ETLPipeline

    pipeline = ETLPipeline(
        brand_name="Acme Corp",
        linkedin_files=["data/linkedin_export.xlsx"],
        x_files=["data/x_export.csv"],
        channels=["linkedin", "x", "facebook", "instagram"],
        website_url="https://acme.com",
        ga4_property_id="properties/123456789",
        # Optional – omit to use heuristic classifier:
        classifier_model_path="/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        db_url="postgresql+psycopg2://user:pass@localhost/social",
    )
    pipeline.run()
    """

    def __init__(
        self,
        brand_name: str = "My Brand",
        linkedin_files: list[str] | None = None,
        x_files: list[str] | None = None,
        channels: list[str] | None = None,
        website_url: str | None = None,
        ga4_property_id: str | None = None,
        meta_since: str | None = None,
        meta_until: str | None = None,
        ga4_start_date: str = "30daysAgo",
        ga4_end_date: str = "today",
        classifier_model_path: str | None = None,
        embedding_model: str = "all-MiniLM-L6-v2",
        db_url: str | None = None,
        extract_meta: bool = True,
        extract_ga4: bool = True,
    ) -> None:
        from extract import Extractor
        from transform import Transformer

        self.loader = Loader(
            db_url=db_url,
            brand_name=brand_name,
            channels=channels or ["linkedin", "x", "facebook", "instagram"],
            website_url=website_url,
            ga4_property_id=ga4_property_id,
        )

        self.extractor = Extractor(
            linkedin_files=linkedin_files,
            x_files=x_files,
            extract_meta=extract_meta,
            extract_ga4=extract_ga4,
            meta_since=meta_since,
            meta_until=meta_until,
            ga4_start_date=ga4_start_date,
            ga4_end_date=ga4_end_date,
        )

        self.transformer = Transformer(
            account_map=self.loader.account_map,
            brand_id=self.loader.brand_id,
            formats=self.loader.formats,
            content_pillars=self.loader.content_pillars,
            strategy_pillars=self.loader.strategy_pillars,
            classifier_model_path=classifier_model_path,
            embedding_model=embedding_model,
        )

    def run(self) -> None:
        logger.info("── EXTRACT ────────────────────────────────")
        raw = self.extractor.run()

        logger.info("── TRANSFORM ──────────────────────────────")
        transformed = self.transformer.run(raw)

        logger.info("── LOAD ────────────────────────────────────")
        self.loader.run(transformed)


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Run the social-media ETL pipeline.")
    parser.add_argument("--brand",         default="My Brand")
    parser.add_argument("--linkedin",      nargs="*", default=[])
    parser.add_argument("--x",             nargs="*", default=[])
    parser.add_argument("--website",       default=None)
    parser.add_argument("--ga4-property",  default=None)
    parser.add_argument("--meta-since",    default=None)
    parser.add_argument("--meta-until",    default=None)
    parser.add_argument("--ga4-start",     default="30daysAgo")
    parser.add_argument("--ga4-end",       default="today")
    parser.add_argument("--classifier",    default=None, help="Path to GGUF model file")
    parser.add_argument("--no-meta",       action="store_true")
    parser.add_argument("--no-ga4",        action="store_true")
    args = parser.parse_args()

    ETLPipeline(
        brand_name=args.brand,
        linkedin_files=args.linkedin,
        x_files=args.x,
        website_url=args.website,
        ga4_property_id=args.ga4_property,
        meta_since=args.meta_since,
        meta_until=args.meta_until,
        ga4_start_date=args.ga4_start,
        ga4_end_date=args.ga4_end,
        classifier_model_path=args.classifier,
        extract_meta=not args.no_meta,
        extract_ga4=not args.no_ga4,
    ).run()
