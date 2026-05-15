"""
transform.py
============
Transforms raw extracted data into records that match the DB schema:

  Brands, Websites, SocialMediaAccounts, Sources, Formats,
  Posts, Metrics, Traffic, Terms, ContentPillars, StrategyPillars

Also runs two ML models:
  1. SentenceTransformer  →  umap_x / umap_y embedding coordinates
  2. LLM classifier       →  format_id, content_pillar_id, strategy_pillar_id

Everything is returned as plain Python dicts ready for the Load layer.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import umap
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Embedding model  (SentenceTransformers + UMAP 2-D projection)
# ──────────────────────────────────────────────────────────────────────────────

class EmbeddingModel:
    """
    Encodes post texts with a SentenceTransformer, then projects the
    high-dimensional embeddings down to 2-D with UMAP so they can be
    stored as integer (umap_x, umap_y) coordinates in the Posts table.

    The UMAP reducer is fit once on the first batch and reused for
    subsequent calls so coordinates stay consistent within a run.  For
    production you should persist the fitted reducer to disk (pickle /
    joblib) so the coordinate space doesn't shift between pipeline runs.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        logger.info("Loading SentenceTransformer: %s", model_name)
        self.encoder = SentenceTransformer(model_name)
        self._reducer: umap.UMAP | None = None

    def encode(self, texts: list[str]) -> list[tuple[int, int]]:
        """
        Returns a list of (umap_x, umap_y) integer pairs, one per text.
        """
        if not texts:
            return []

        embeddings = self.encoder.encode(texts, show_progress_bar=False)

        if self._reducer is None:
            n = len(embeddings)
            n_neighbors = min(15, n - 1) if n > 1 else 1
            self._reducer = umap.UMAP(
                n_components=2,
                n_neighbors=n_neighbors,
                min_dist=0.1,
                random_state=42,
            )
            coords_2d = self._reducer.fit_transform(embeddings)
        else:
            coords_2d = self._reducer.transform(embeddings)

        # Scale to integer space  (multiply by 1000 to keep 3 decimal places)
        result = [
            (int(x * 1000), int(y * 1000))
            for x, y in coords_2d
        ]
        return result


# ──────────────────────────────────────────────────────────────────────────────
# LLM Classifier  (format + content pillar + strategy pillar)
# ──────────────────────────────────────────────────────────────────────────────

class PostClassifier:
    """
    Uses a locally-run LLM via llama-cpp-python to classify each post into:
      - format        (e.g. "Carousel", "Video", "Text", "Image", "Poll" …)
      - content_pillar (e.g. "Educational", "Inspirational", "Promotional" …)
      - strategy_pillar (e.g. "Brand Awareness", "Lead Gen", "Engagement" …)

    Falls back to keyword heuristics if the LLM is not available so the
    pipeline can run without a GPU.

    Model file path comes from the CLASSIFIER_MODEL_PATH env var or the
    constructor argument.  Download any GGUF model from HuggingFace, e.g.:
      https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF
    """

    SYSTEM_PROMPT = """You are a social-media content analyst.
Given a post text you must return ONLY a JSON object with exactly these keys:
  "format"          – one of: Carousel, Video, Text, Image, Poll, Story, Reel, Article, Other
  "content_pillar"  – one of: Educational, Inspirational, Promotional, Entertainment, Community, Behind-the-Scenes, User-Generated, News, Other
  "strategy_pillar" – one of: Brand Awareness, Lead Generation, Engagement, Retention, Conversion, Thought Leadership, Partnership, Other

No preamble. No explanation. Only the JSON object."""

    def __init__(
        self,
        model_path: str | None = None,
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
    ) -> None:
        self._llm = None
        if model_path:
            try:
                from llama_cpp import Llama  # type: ignore
                logger.info("Loading local LLM from %s", model_path)
                self._llm = Llama(
                    model_path=model_path,
                    n_ctx=n_ctx,
                    n_gpu_layers=n_gpu_layers,
                    verbose=False,
                )
            except Exception as exc:
                logger.warning("Could not load LLM (%s) – using heuristics.", exc)

    SYSTEM_PROMPT = """You are a social-media content analyst.
                    Given a post text you must return ONLY a JSON object with exactly these keys:
                    "format"          – one of: Carousel, Video, Text, Image, Poll, Story, Reel, Article, Other
                    "content_pillar"  – one of: Educational, Inspirational, Promotional, Entertainment, Community, Behind-the-Scenes, User-Generated, News, Other
                    "strategy_pillar" – one of: Brand Awareness, Lead Generation, Engagement, Retention, Conversion, Thought Leadership, Partnership, Other

                    No preamble. No explanation. Only the JSON object."""

    def classify(self, text: str) -> dict[str, str]:
        if self._llm is not None:
            return self._classify_with_llm(text)
        return self._classify_heuristic(text)

    def classify_batch(self, texts: list[str]) -> list[dict[str, str]]:
        return [self.classify(t) for t in texts]

    # ── LLM path ─────────────────────────────────────────────────────────────

    def _classify_with_llm(self, text: str) -> dict[str, str]:
        import json

        prompt = (
            f"<s>[INST] <<SYS>>\n{self.SYSTEM_PROMPT}\n<</SYS>>\n\n"
            f"Post text:\n{text[:1500]}\n[/INST]"
        )
        output = self._llm(  # type: ignore[operator]
            prompt,
            max_tokens=200,
            temperature=0.0,
            stop=["</s>", "[INST]"],
        )
        raw = output["choices"][0]["text"].strip()
        try:
            # Strip markdown fences if present
            clean = re.sub(r"```(?:json)?|```", "", raw).strip()
            return json.loads(clean)
        except Exception:
            logger.warning("LLM returned non-JSON: %s", raw[:200])
            return self._classify_heuristic(text)

    # ── Heuristic fallback ────────────────────────────────────────────────────

    def _classify_heuristic(self, text: str) -> dict[str, str]:
        lower = (text or "").lower()

        # Format
        if any(w in lower for w in ["watch", "video", "youtube", "reel"]):
            fmt = "Video"
        elif any(w in lower for w in ["swipe", "carousel", "slides"]):
            fmt = "Carousel"
        elif any(w in lower for w in ["poll", "vote", "survey"]):
            fmt = "Poll"
        elif any(w in lower for w in ["article", "blog", "read more"]):
            fmt = "Article"
        elif any(w in lower for w in ["story", "stories"]):
            fmt = "Story"
        else:
            fmt = "Text"

        # Content pillar
        if any(w in lower for w in ["learn", "tip", "how to", "guide", "tutorial"]):
            content = "Educational"
        elif any(w in lower for w in ["inspire", "motivat", "quote", "success"]):
            content = "Inspirational"
        elif any(w in lower for w in ["buy", "sale", "offer", "discount", "promo"]):
            content = "Promotional"
        elif any(w in lower for w in ["behind", "team", "office", "culture"]):
            content = "Behind-the-Scenes"
        elif any(w in lower for w in ["news", "update", "launch", "announce"]):
            content = "News"
        else:
            content = "Educational"

        # Strategy pillar
        if any(w in lower for w in ["brand", "awareness", "introduce"]):
            strategy = "Brand Awareness"
        elif any(w in lower for w in ["lead", "sign up", "register", "download"]):
            strategy = "Lead Generation"
        elif any(w in lower for w in ["comment", "share", "tag", "engage"]):
            strategy = "Engagement"
        elif any(w in lower for w in ["thought", "insight", "opinion", "expert"]):
            strategy = "Thought Leadership"
        else:
            strategy = "Engagement"

        return {
            "format": fmt,
            "content_pillar": content,
            "strategy_pillar": strategy,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────────────────────────────────────

def _row_hash(row: dict) -> str:
    """Deterministic SHA-256 hash of a record for deduplication."""
    key = str(sorted(row.items())).encode()
    return hashlib.sha256(key).hexdigest()[:16]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(val: Any) -> datetime | None:
    if pd.isna(val) if isinstance(val, float) else val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return pd.to_datetime(val, utc=True).to_pydatetime()
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Per-source post normalisation
# ──────────────────────────────────────────────────────────────────────────────

def _normalise_linkedin_posts(
    df: pd.DataFrame,
    account_id: int,
    brand_id: int,
) -> list[dict]:
    """Map LinkedIn content-tab columns to the Posts/Metrics schema."""
    records: list[dict] = []
    col = df.columns.str.lower().str.strip()
    df.columns = col  # normalise in-place

    for _, row in df.iterrows():
        text = str(row.get("update text", row.get("post text", row.get("message", ""))))
        url  = str(row.get("permalink", row.get("link", "")))
        created = _parse_date(row.get("date", row.get("published at", row.get("created at"))))

        post = {
            "postText": text,
            "postUrl": url,
            "created_at": created or _now_utc(),
            "account_id": account_id,
            "brand_id": brand_id,
            "source": "linkedin",
            # raw metrics – matched to Metrics table in Load
            "_impressions":      _safe_int(row.get("impressions", 0)),
            "_engagements":      _safe_int(row.get("engagements", 0)),
            "_clicks":           _safe_int(row.get("clicks", 0)),
            "_reactions":        _safe_int(row.get("reactions", row.get("likes", 0))),
            "_comments":         _safe_int(row.get("comments", 0)),
            "_shares":           _safe_int(row.get("shares", 0)),
            "_engagementRate":   _safe_float(row.get("engagement rate", 0)),
        }
        records.append(post)
    return records


def _normalise_x_posts(
    df: pd.DataFrame,
    account_id: int,
    brand_id: int,
) -> list[dict]:
    """Map X CSV columns to the Posts/Metrics schema."""
    records: list[dict] = []
    for _, row in df.iterrows():
        text = str(row.get("postText", row.get("Tweet text", "")))
        url  = str(row.get("postUrl", row.get("Tweet permalink", "")))
        created = _parse_date(row.get("created_at", row.get("time", "")))

        post = {
            "postText": text,
            "postUrl": url,
            "created_at": created or _now_utc(),
            "account_id": account_id,
            "brand_id": brand_id,
            "source": "x",
            "_impressions":     _safe_int(row.get("impressions", 0)),
            "_engagements":     _safe_int(row.get("engagements", 0)),
            "_clicks":          _safe_int(row.get("clicks", 0)),
            "_reactions":       _safe_int(row.get("reactions", 0)),
            "_comments":        _safe_int(row.get("comments", 0)),
            "_shares":          _safe_int(row.get("shares", 0)),
            "_engagementRate":  _safe_float(row.get("engagementRate", 0)),
            "_followersGained": _safe_int(row.get("followersGained", 0)),
        }
        records.append(post)
    return records


def _normalise_meta_posts(
    fb_posts: list[dict],
    ig_posts: list[dict],
    account_id: int,
    brand_id: int,
) -> list[dict]:
    """Map Meta API responses to the Posts/Metrics schema."""
    records: list[dict] = []

    for p in fb_posts:
        insights_map = _flatten_meta_insights(p.get("insights", {}).get("data", []))
        post = {
            "postText": p.get("message", p.get("story", "")),
            "postUrl": p.get("permalink_url", ""),
            "created_at": _parse_date(p.get("created_time")) or _now_utc(),
            "account_id": account_id,
            "brand_id": brand_id,
            "source": "facebook",
            "_impressions":    _safe_int(insights_map.get("post_impressions", 0)),
            "_engagements":    _safe_int(insights_map.get("post_engaged_users", 0)),
            "_clicks":         _safe_int(insights_map.get("post_clicks", 0)),
            "_reactions":      0,
            "_comments":       0,
            "_shares":         _safe_int(insights_map.get("post_shares", 0)),
            "_engagementRate": 0.0,
        }
        records.append(post)

    for m in ig_posts:
        insights_map = {i["name"]: i.get("values", [{}])[0].get("value", 0)
                        for i in m.get("insights", [])}
        post = {
            "postText": m.get("caption", ""),
            "postUrl": m.get("permalink", ""),
            "created_at": _parse_date(m.get("timestamp")) or _now_utc(),
            "account_id": account_id,
            "brand_id": brand_id,
            "source": "instagram",
            "_impressions":    _safe_int(insights_map.get("impressions", 0)),
            "_engagements":    _safe_int(insights_map.get("engagement", 0)),
            "_clicks":         0,
            "_reactions":      _safe_int(m.get("like_count", 0)),
            "_comments":       _safe_int(m.get("comments_count", 0)),
            "_shares":         0,
            "_engagementRate": 0.0,
        }
        records.append(post)

    return records


def _flatten_meta_insights(data: list[dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in data:
        name = item.get("name", "")
        values = item.get("values", [{}])
        out[name] = values[0].get("value", 0) if values else 0
    return out


def _safe_int(val: Any) -> int:
    try:
        return int(float(str(val).replace(",", "").replace("%", "")))
    except Exception:
        return 0


def _safe_float(val: Any) -> float:
    try:
        return float(str(val).replace(",", "").replace("%", ""))
    except Exception:
        return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# GA4 → Traffic rows
# ──────────────────────────────────────────────────────────────────────────────

def _normalise_ga4_traffic(df: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for _, row in df.iterrows():
        rows.append({
            "metric1": _safe_float(row.get("sessions", 0)),
            "metric2": _safe_float(row.get("screenPageViews", 0)),
            "metric3": _safe_float(row.get("activeUsers", 0)),
            # page_id / source_id resolved by Load layer after Websites upsert
            "_page_path":   str(row.get("pagePath", "")),
            "_source":      str(row.get("sessionSource", "")),
            "_medium":      str(row.get("sessionMedium", "")),
            "_date":        str(row.get("date", "")),
        })
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# Main Transformer
# ──────────────────────────────────────────────────────────────────────────────

class Transformer:
    """
    Orchestrates all transformation steps.

    Parameters
    ----------
    account_map : dict
        Maps channel name → SocialMediaAccounts.id
        e.g. {"linkedin": 1, "x": 2, "facebook": 3, "instagram": 4}
    brand_id : int
        The Brands.id for this run.
    classifier_model_path : str | None
        Path to a GGUF model file for the LLM classifier.
        If None, heuristic classification is used.
    embedding_model : str
        SentenceTransformer model name.
    formats : dict[str, int]
        Maps format label → Formats.id   (must be pre-loaded from DB)
    content_pillars : dict[str, int]
        Maps pillar label → ContentPillars.id
    strategy_pillars : dict[str, int]
        Maps pillar label → StrategyPillars.id
    """

    def __init__(
        self,
        account_map: dict[str, int],
        brand_id: int,
        formats: dict[str, int],
        content_pillars: dict[str, int],
        strategy_pillars: dict[str, int],
        classifier_model_path: str | None = None,
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        self.account_map = account_map
        self.brand_id = brand_id
        self.formats = formats
        self.content_pillars = content_pillars
        self.strategy_pillars = strategy_pillars

        self.embedder = EmbeddingModel(embedding_model)
        self.classifier = PostClassifier(model_path=classifier_model_path)

    # ── public API ────────────────────────────────────────────────────────────

    def run(self, raw: dict[str, Any]) -> dict[str, list[dict]]:
        """
        Entry point.  Accepts the bundle produced by Extractor.run() and
        returns a dict of record lists keyed by table name.
        """
        all_posts: list[dict] = []

        # LinkedIn
        for item in raw.get("linkedin", []):
            sheets = item["data"]
            df = sheets.get("posts", next(iter(sheets.values()), pd.DataFrame()))
            account_id = self.account_map.get("linkedin", 0)
            all_posts.extend(
                _normalise_linkedin_posts(df, account_id, self.brand_id)
            )

        # X
        for item in raw.get("x", []):
            account_id = self.account_map.get("x", 0)
            all_posts.extend(
                _normalise_x_posts(item["data"], account_id, self.brand_id)
            )

        # Meta
        meta = raw.get("meta", {})
        if meta:
            fb_posts = meta.get("fb_posts", [])
            ig_posts = meta.get("ig_posts", [])
            fb_account_id = self.account_map.get("facebook", 0)
            all_posts.extend(
                _normalise_meta_posts(fb_posts, ig_posts, fb_account_id, self.brand_id)
            )

        # ── ML enrichment ─────────────────────────────────────────────────────
        texts = [p["postText"] for p in all_posts]

        logger.info("Running embedding model on %d posts …", len(texts))
        coords = self.embedder.encode(texts)

        logger.info("Running classifier on %d posts …", len(texts))
        classifications = self.classifier.classify_batch(texts)

        for i, post in enumerate(all_posts):
            umap_x, umap_y = coords[i] if i < len(coords) else (0, 0)
            clf = classifications[i] if i < len(classifications) else {}

            post["umap_x"] = umap_x
            post["umap_y"] = umap_y
            post["format_id"] = self.formats.get(clf.get("format", "Other"), None)
            post["content_pillar_id"] = self.content_pillars.get(
                clf.get("content_pillar", "Other"), None
            )
            post["strategy_pillar_id"] = self.strategy_pillars.get(
                clf.get("strategy_pillar", "Other"), None
            )
            post["row_hash"] = _row_hash(
                {k: v for k, v in post.items() if not k.startswith("_")}
            )
            post["updated_at"] = _now_utc()

        # ── Split into table-specific lists ───────────────────────────────────
        posts_records   = self._build_posts_records(all_posts)
        metrics_records = self._build_metrics_records(all_posts)

        # GA4 traffic
        ga4_df = raw.get("ga4", pd.DataFrame())
        traffic_records = _normalise_ga4_traffic(ga4_df) if not ga4_df.empty else []

        # Terms  (top N by engagement per account)
        terms_records = self._build_terms(all_posts)

        return {
            "posts":    posts_records,
            "metrics":  metrics_records,
            "traffic":  traffic_records,
            "terms":    terms_records,
        }

    # ── helpers ───────────────────────────────────────────────────────────────

    def _build_posts_records(self, posts: list[dict]) -> list[dict]:
        keys = {
            "postText", "postUrl", "format_id", "content_pillar_id",
            "created_at", "strategy_pillar_id", "account_id",
            "umap_x", "umap_y", "row_hash", "updated_at",
        }
        return [{k: p[k] for k in keys if k in p} for p in posts]

    def _build_metrics_records(self, posts: list[dict]) -> list[dict]:
        records: list[dict] = []
        for p in posts:
            eng = p.get("_engagements", 0)
            imp = p.get("_impressions", 1) or 1
            records.append({
                "account_id":     p["account_id"],
                "date":           p["created_at"],
                "impressions":    p.get("_impressions", 0),
                "engagements":    eng,
                "engagementRate": p.get("_engagementRate") or round(eng / imp, 4),
                "clicks":         p.get("_clicks", 0),
                "reactions":      p.get("_reactions", 0),
                "comments":       p.get("_comments", 0),
                "shares":         p.get("_shares", 0),
                "bookmarks":      0,
                "followersGained":p.get("_followersGained", 0),
                "followersTotal": 0,
                "unfollows":      0,
                "row_hash":       p["row_hash"],
                "updated_at":     p["updated_at"],
            })
        return records

    def _build_terms(self, posts: list[dict]) -> list[dict]:
        """
        Simple frequency + engagement-weighted term extraction from post texts.
        """
        from collections import defaultdict
        import re as _re

        STOP = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "was", "are", "be",
            "this", "that", "it", "we", "i", "you", "he", "she", "they",
            "have", "has", "had", "will", "would", "can", "could", "should",
            "not", "no", "as", "up", "out", "our", "your", "my",
        }

        term_eng: dict[str, list[float]] = defaultdict(list)
        for p in posts:
            text = str(p.get("postText", ""))
            eng  = p.get("_engagements", 0)
            words = _re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
            for w in set(words):
                if w not in STOP:
                    term_eng[w].append(float(eng))

        records: list[dict] = []
        for term, engs in term_eng.items():
            records.append({
                "term": term,
                "engagement_score": round(sum(engs) / len(engs), 4),
                "updated_at": _now_utc(),
            })
        # Return top 1000 by engagement score
        records.sort(key=lambda r: r["engagement_score"], reverse=True)
        return records[:1000]
