"""
extract.py
==========
Handles all data extraction from:
  - LinkedIn (Excel .xlsx files)
  - X / Twitter (CSV files)
  - Meta Graph API (posts + page metrics)
  - Google Analytics 4 (website traffic)

Each extractor returns a plain dict / list of dicts so the Transform
layer can work source-agnostically.
"""

from __future__ import annotations

import os
import time
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from google.oauth2 import service_account

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# LinkedIn  (Excel → DataFrame)
# ──────────────────────────────────────────────────────────────────────────────

class LinkedInExcelExtractor:
    """
    Reads a LinkedIn analytics export (.xlsx).

    LinkedIn exports come in several tabs; we care about:
      - "Content" or "Updates" tab  →  individual post metrics
      - "Followers" tab             →  follower growth over time

    Adjust SHEET_NAMES if LinkedIn changes its export format.
    """

    CONTENT_SHEETS = ["Content", "Updates", "Post analytics"]
    FOLLOWER_SHEETS = ["Followers", "Follower analytics"]

    def __init__(self, filepath: str | Path) -> None:
        self.filepath = Path(filepath)
        if not self.filepath.exists():
            raise FileNotFoundError(self.filepath)

    def extract(self) -> dict[str, pd.DataFrame]:
        wb = pd.ExcelFile(self.filepath, engine="openpyxl")
        available = wb.sheet_names

        content_df = self._read_first_match(wb, self.CONTENT_SHEETS, available)
        follower_df = self._read_first_match(wb, self.FOLLOWER_SHEETS, available)

        result: dict[str, pd.DataFrame] = {}
        if content_df is not None:
            result["posts"] = content_df
        if follower_df is not None:
            result["followers"] = follower_df

        if not result:
            # Fall back: read all sheets
            logger.warning(
                "No recognised sheet found in %s – reading all sheets.", self.filepath
            )
            result = {name: wb.parse(name) for name in available}

        logger.info(
            "LinkedIn: extracted sheets %s from %s", list(result.keys()), self.filepath
        )
        return result

    @staticmethod
    def _read_first_match(
        wb: pd.ExcelFile, candidates: list[str], available: list[str]
    ) -> pd.DataFrame | None:
        for name in candidates:
            if name in available:
                return wb.parse(name)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# X / Twitter  (CSV → DataFrame)
# ──────────────────────────────────────────────────────────────────────────────

class XCsvExtractor:
    """
    Reads an X (Twitter) analytics CSV export.

    X exports one CSV per time period; columns vary slightly by export
    type (account overview vs. tweet activity).  We normalise column
    names so the Transform layer sees a consistent schema.
    """

    # Map from X raw column names → internal names
    COLUMN_MAP = {
        # tweet activity export
        "Tweet id": "post_id",
        "Tweet permalink": "postUrl",
        "Tweet text": "postText",
        "time": "created_at",
        "impressions": "impressions",
        "engagements": "engagements",
        "engagement rate": "engagementRate",
        "retweets": "shares",
        "replies": "comments",
        "likes": "reactions",
        "url clicks": "clicks",
        "user profile clicks": "clicks_profile",
        "hashtag clicks": "clicks_hashtag",
        "detail expands": "detail_expands",
        "follows": "followersGained",
        "app opens": "app_opens",
        "app installs": "app_installs",
        "media views": "media_views",
        "media engagements": "media_engagements",
    }

    def __init__(self, filepath: str | Path) -> None:
        self.filepath = Path(filepath)
        if not self.filepath.exists():
            raise FileNotFoundError(self.filepath)

    def extract(self) -> pd.DataFrame:
        df = pd.read_csv(self.filepath, low_memory=False)

        # Normalise column names: strip whitespace, lower-case lookup
        df.columns = df.columns.str.strip()
        rename = {
            col: self.COLUMN_MAP[col]
            for col in df.columns
            if col in self.COLUMN_MAP
        }
        df = df.rename(columns=rename)

        logger.info("X/Twitter: extracted %d rows from %s", len(df), self.filepath)
        return df


# ──────────────────────────────────────────────────────────────────────────────
# Meta Graph API
# ──────────────────────────────────────────────────────────────────────────────

class MetaAPIExtractor:
    """
    Pulls posts and page-level metrics from the Meta Graph API.

    Required env vars (or pass as constructor args):
      META_PAGE_ID        – numeric Facebook page / IG business account id
      META_ACCESS_TOKEN   – long-lived page access token

    Docs:
      https://developers.facebook.com/docs/graph-api/reference/page/feed/
      https://developers.facebook.com/docs/instagram-api/reference/ig-media/insights
    """

    BASE_URL = "https://graph.facebook.com/v19.0"

    # Fields we want per post (FB)
    FB_POST_FIELDS = (
        "id,message,story,full_picture,permalink_url,created_time,"
        "insights.metric(post_impressions,post_engaged_users,"
        "post_reactions_by_type_total,post_clicks,post_shares)"
    )

    # Fields we want per IG media
    IG_MEDIA_FIELDS = (
        "id,caption,media_type,permalink,timestamp,"
        "like_count,comments_count"
    )

    # IG media insights
    IG_INSIGHTS_METRICS = "impressions,reach,engagement,saved"

    def __init__(
        self,
        page_id: str | None = None,
        access_token: str | None = None,
        ig_user_id: str | None = None,
        since: str | None = None,   # ISO date e.g. "2024-01-01"
        until: str | None = None,
    ) -> None:
        self.page_id = page_id or os.environ["META_PAGE_ID"]
        self.access_token = access_token or os.environ["META_ACCESS_TOKEN"]
        self.ig_user_id = ig_user_id or os.environ.get("META_IG_USER_ID")
        self.since = since
        self.until = until

    # ── helpers ──────────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict:
        params.setdefault("access_token", self.access_token)
        url = f"{self.BASE_URL}/{endpoint}"
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, first_page: dict) -> list[dict]:
        """Follow 'next' cursors and collect all items."""
        items: list[dict] = list(first_page.get("data", []))
        paging = first_page.get("paging", {})
        while "next" in paging:
            resp = requests.get(paging["next"], timeout=30)
            resp.raise_for_status()
            page = resp.json()
            items.extend(page.get("data", []))
            paging = page.get("paging", {})
            time.sleep(0.25)  # be polite
        return items

    # ── Facebook posts ────────────────────────────────────────────────────────

    def extract_fb_posts(self) -> list[dict]:
        params: dict[str, Any] = {"fields": self.FB_POST_FIELDS, "limit": 100}
        if self.since:
            params["since"] = self.since
        if self.until:
            params["until"] = self.until

        first = self._get(f"{self.page_id}/feed", params)
        posts = self._paginate(first)
        logger.info("Meta FB: extracted %d posts", len(posts))
        return posts

    # ── Facebook page metrics ─────────────────────────────────────────────────

    def extract_fb_page_metrics(self) -> list[dict]:
        metrics = (
            "page_impressions,page_engaged_users,page_fans,"
            "page_fan_adds,page_fan_removes,page_views_total"
        )
        params: dict[str, Any] = {
            "metric": metrics,
            "period": "day",
        }
        if self.since:
            params["since"] = self.since
        if self.until:
            params["until"] = self.until

        data = self._get(f"{self.page_id}/insights", params)
        rows = self._paginate(data)
        logger.info("Meta FB: extracted %d page-metric rows", len(rows))
        return rows

    # ── Instagram media ───────────────────────────────────────────────────────

    def extract_ig_posts(self) -> list[dict]:
        if not self.ig_user_id:
            logger.warning("META_IG_USER_ID not set – skipping IG media extraction.")
            return []

        params: dict[str, Any] = {"fields": self.IG_MEDIA_FIELDS, "limit": 100}
        if self.since:
            params["since"] = self.since
        if self.until:
            params["until"] = self.until

        first = self._get(f"{self.ig_user_id}/media", params)
        media_items = self._paginate(first)

        # Fetch insights per media item
        enriched: list[dict] = []
        for item in media_items:
            try:
                insights = self._get(
                    f"{item['id']}/insights",
                    {"metric": self.IG_INSIGHTS_METRICS},
                )
                item["insights"] = insights.get("data", [])
            except requests.HTTPError as exc:
                logger.warning("IG insights failed for %s: %s", item["id"], exc)
                item["insights"] = []
            enriched.append(item)
            time.sleep(0.1)

        logger.info("Meta IG: extracted %d media items", len(enriched))
        return enriched

    def extract_all(self) -> dict[str, list]:
        return {
            "fb_posts": self.extract_fb_posts(),
            "fb_page_metrics": self.extract_fb_page_metrics(),
            "ig_posts": self.extract_ig_posts(),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Google Analytics 4
# ──────────────────────────────────────────────────────────────────────────────

class GA4Extractor:
    """
    Pulls page-level traffic metrics from GA4 using the Data API.

    Required:
      GA4_PROPERTY_ID     – e.g. "properties/123456789"
      GOOGLE_CREDENTIALS  – path to service-account JSON key file

    The extractor returns a DataFrame with one row per (date, page_path).
    """

    DEFAULT_DIMENSIONS = ["date", "pagePath", "sessionSource", "sessionMedium"]
    DEFAULT_METRICS = [
        "sessions",
        "screenPageViews",
        "activeUsers",
        "engagedSessions",
        "bounceRate",
        "averageSessionDuration",
    ]

    def __init__(
        self,
        property_id: str | None = None,
        credentials_path: str | None = None,
        start_date: str = "30daysAgo",
        end_date: str = "today",
        dimensions: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> None:
        self.property_id = property_id or os.environ["GA4_PROPERTY_ID"]
        creds_path = credentials_path or os.environ.get("GOOGLE_CREDENTIALS")

        if creds_path:
            creds = service_account.Credentials.from_service_account_file(
                creds_path,
                scopes=["https://www.googleapis.com/auth/analytics.readonly"],
            )
            self.client = BetaAnalyticsDataClient(credentials=creds)
        else:
            # ADC (Application Default Credentials) fallback
            self.client = BetaAnalyticsDataClient()

        self.start_date = start_date
        self.end_date = end_date
        self.dimensions = dimensions or self.DEFAULT_DIMENSIONS
        self.metrics = metrics or self.DEFAULT_METRICS

    def extract(self) -> pd.DataFrame:
        request = RunReportRequest(
            property=self.property_id,
            dimensions=[Dimension(name=d) for d in self.dimensions],
            metrics=[Metric(name=m) for m in self.metrics],
            date_ranges=[DateRange(start_date=self.start_date, end_date=self.end_date)],
        )

        response = self.client.run_report(request)

        rows: list[dict] = []
        for row in response.rows:
            record: dict[str, Any] = {}
            for i, dim in enumerate(self.dimensions):
                record[dim] = row.dimension_values[i].value
            for i, met in enumerate(self.metrics):
                record[met] = row.metric_values[i].value
            rows.append(record)

        df = pd.DataFrame(rows)
        logger.info("GA4: extracted %d rows (%s → %s)", len(df), self.start_date, self.end_date)
        return df


# ──────────────────────────────────────────────────────────────────────────────
# Convenience façade
# ──────────────────────────────────────────────────────────────────────────────

class Extractor:
    """
    High-level façade.  Collects raw data from all configured sources and
    returns a single bundle dict that is passed straight into Transform.

    Usage
    -----
    extractor = Extractor(
        linkedin_files=["path/to/linkedin.xlsx"],
        x_files=["path/to/x_export.csv"],
        meta_since="2024-01-01",
        ga4_start_date="2024-01-01",
    )
    raw = extractor.run()
    """

    def __init__(
        self,
        linkedin_files: list[str | Path] | None = None,
        x_files: list[str | Path] | None = None,
        extract_meta: bool = True,
        extract_ga4: bool = True,
        meta_since: str | None = None,
        meta_until: str | None = None,
        ga4_start_date: str = "30daysAgo",
        ga4_end_date: str = "today",
    ) -> None:
        self.linkedin_files = [Path(p) for p in (linkedin_files or [])]
        self.x_files = [Path(p) for p in (x_files or [])]
        self.extract_meta = extract_meta
        self.extract_ga4 = extract_ga4
        self.meta_since = meta_since
        self.meta_until = meta_until
        self.ga4_start_date = ga4_start_date
        self.ga4_end_date = ga4_end_date

    def run(self) -> dict[str, Any]:
        bundle: dict[str, Any] = {
            "linkedin": [],
            "x": [],
            "meta": {},
            "ga4": pd.DataFrame(),
        }

        # LinkedIn
        for fp in self.linkedin_files:
            ext = LinkedInExcelExtractor(fp)
            bundle["linkedin"].append({"file": str(fp), "data": ext.extract()})

        # X
        for fp in self.x_files:
            ext = XCsvExtractor(fp)
            bundle["x"].append({"file": str(fp), "data": ext.extract()})

        # Meta
        if self.extract_meta:
            meta_ext = MetaAPIExtractor(since=self.meta_since, until=self.meta_until)
            bundle["meta"] = meta_ext.extract_all()

        # GA4
        if self.extract_ga4:
            ga4_ext = GA4Extractor(
                start_date=self.ga4_start_date,
                end_date=self.ga4_end_date,
            )
            bundle["ga4"] = ga4_ext.extract()

        return bundle
