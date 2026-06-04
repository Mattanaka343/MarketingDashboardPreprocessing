import os
import json
import ollama
import umap
import re

import numpy as np
import pandas as pd

from dotenv import load_dotenv
from sqlalchemy import text
from utils import add_row_hash

from sqlalchemy.engine import Engine
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer 
from datetime import datetime

load_dotenv()

DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("MYSQL_PASSWORD")

EMBED_MODEL = os.getenv("EMBED_MODEL")
LLM_MODEL = os.getenv("LLM_MODEL")

TOP_K = 5

INT_COLS = ["bookmarks","clicks","comments","engagements","followersGained","followersTotal","impressions",
            "reactions", "shares", "unfollows", "account_id",'timesSent','profileVisits','detailExpands','urlClicks',
            'hashtagClicks','permalinkClicks']




def _get_embedding(text:str) -> np.array:

    response = ollama.embeddings(
        model=EMBED_MODEL,
        prompt=text
    )

    return np.array(response["embedding"])


def _prepare_retrieval_data(df: pd.DataFrame):
    """
    Precompute things we reuse often.

    Call this ONCE after loading the dataframe.
    """

    retrieval_data = {}

    grouped = df.groupby("account_id")

    for account_id, group in grouped:

        retrieval_data[account_id] = {
            "df": group,
            "embeddings_matrix": np.vstack(
                group["embedding"].values
            )
        }

    return retrieval_data


def _retrieve_similar_posts(
    post_text,
    source,
    retrieval_data,
    top_k=TOP_K
):

    if source not in retrieval_data:
        return pd.DataFrame()

    target_embedding = _get_embedding(post_text)

    source_data = retrieval_data[source]

    source_df = source_data["df"]
    embeddings_matrix = source_data["embeddings_matrix"]

    similarities = cosine_similarity(
        target_embedding.reshape(1, -1),
        embeddings_matrix
    )[0]

    results = source_df.copy()

    results["similarity"] = similarities

    # remove identical post
    results = results[
        results["postText"] != post_text
    ]

    results = results.sort_values(
        "similarity",
        ascending=False
    )

    return results.head(top_k)


def _dict_to_prompt(title, d):

    rows = [
        f"{k} -> {v}"
        for k, v in d.items()
    ]

    return f"{title}:\n" + "\n".join(rows)


def _classify_post(
    post_text,
    source,
    retrieval_data,
    formats,
    content_pillars,
    strategy_pillars
):

    similar_posts = _retrieve_similar_posts(
        post_text,
        source,
        retrieval_data
    )

    context_posts = "\n".join([
        f"- {t[:300]}"
        for t in similar_posts["postText"].tolist()
    ])

    prompt = f"""
You are a social media classifier.

Choose EXACTLY ONE ID from each category.

{_dict_to_prompt("FORMATS", formats)}

{_dict_to_prompt("CONTENT PILLARS", content_pillars)}

{_dict_to_prompt("STRATEGY PILLARS", strategy_pillars)}

POST:
{post_text}

SIMILAR POSTS FROM SAME SOURCE:
{context_posts}

RULES:
- Return ONLY valid JSON
- Use ONLY integer IDs
- Do NOT explain
- Do NOT output markdown

OUTPUT FORMAT:
{{
    "format_id": 1,
    "content_pillar_id": 1,
    "strategy_pillar_id": 1
}}
"""

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        options={
            "temperature": 0
        }
    )

    content = response["message"]["content"]

    try:
        return json.loads(content)

    except json.JSONDecodeError:
        print(content)
        raise ValueError(
            "Model returned invalid JSON"
        )


def _get_embedding_space(df):

    reducer = umap.UMAP(
        n_neighbors=15,
        min_dist=0.1,
        metric="cosine",
        random_state=42
    )

    embeddings = np.vstack(
        df["embedding"].values
    )

    embedding_2d = reducer.fit_transform(
        embeddings
    )

    result = df.drop(columns='embedding').copy()

    result["umap_x"] = embedding_2d[:, 0]
    result["umap_y"] = embedding_2d[:, 1]

    return result

def _add_embeddings_to_df(df):
    
    df = df.copy()

    df["embedding"] = df["postText"].apply(
            _get_embedding
        )
    
    return df

def _bend_to_sql_shape(df:pd.DataFrame,table:str,engine: Engine) -> pd.DataFrame:
    query = text(f"SHOW COLUMNS FROM {table}")
    
    sql_cols = []

    with engine.connect() as conn:
        result = conn.execute(query)
        
        for row in result:
            map = row._mapping
            sql_cols.append(map["Field"])
    
    return df[sql_cols]

def _clean_text(text):
    text = str(text).lower()
    text = re.sub(r'http\S+', '', text)          # remove URLs
    text = re.sub(r'@\w+', '', text)             # remove mentions
    text = re.sub(r'#(\w+)', r'\1', text)        # keep hashtag words
    text = re.sub(r'[^a-záéíóúüñ\s]', ' ', text) # keep letters only
    return text

def _get_top_terms(df):

    STOPWORDS = {
        # English
        'the','and','for','that','this','with','are','was','you','your',
        'have','has','from','not','but','they','our','their','been','more',
        'will','one','can','all','its','about','what','how','who','when',
        'which','also','into','than','some','out','just','we','it','is',
        'in','of','to','a','an','on','at','be','as','by','or','do',
        'if','up','so','he','she','my','his','her','us','me',

        # Spanish
        'que','los','las','una','para','con','por','del','como',
        'sus','más','pero','esta','esto','este','son','ha','se',
        'la','el','en','de','un','es','al','le','lo','si','ya',
        'día','nuestro','muy','pronto','siendo','desde',
        'queremos','cada','nos','todos','solo','su','ser',
        'buena','octubre',

        # Brand / noise
        'wexpandtalent','adayatwexpand','conocerás',
        'teamlife','culturalaboral','peoplefirst','wexpand',

        # Social noise
        'via','amp','rt','please','thank','thanks','new','get',
        'use','make','made','work','working','day','time',
        'great','good','need','want','know','see','look',
        'say','said','next','last','first','year','week',
        'month','today','now','even','well','https',
        'really','like','important','interestring',
        'co','way','interesting','seems'
    }

    term_rows = []

    grouped = df.groupby(["account_id"])

    for account_id, group in grouped:

        group = group.dropna(
            subset=["postText", "engagementRate"]
        )

        group = group[
            group["postText"].astype(str).str.strip() != ""
        ]

        if len(group) < 3:
            continue

        texts = (
            group["postText"]
            .astype(str)
            .apply(_clean_text)
            .tolist()
        )

        try:
            weights = (
                group["engagementRate"]
                .astype(float)
                .values
            )

        except ValueError:
            continue

        vectorizer = TfidfVectorizer(
            max_features=500,
            ngram_range=(1, 2),
            min_df=2,
            stop_words=list(STOPWORDS),
        )

        try:
            tfidf_matrix = vectorizer.fit_transform(texts)

        except ValueError:
            continue

        terms = vectorizer.get_feature_names_out()

        # weight tfidf by engagement
        weighted_scores = (
            tfidf_matrix.T.dot(weights)
        )

        weighted_scores = np.asarray(
            weighted_scores
        ).flatten()

        max_score = weighted_scores.max()

        if max_score <= 0:
            continue

        normalized_scores = (
            weighted_scores / max_score
        )

        for term, score in zip(
            terms,
            normalized_scores
        ):

            if score <= 0.05:
                continue

            term_rows.append({
                "term": term,
                "engagement_score": round(
                    float(score),
                    4
                ),
                "account_id": account_id
            })

    return pd.DataFrame(term_rows)

def transform_posts(dfs:list, engine: Engine) -> tuple:
    """
    """

    FORMATS = pd.read_sql("SELECT * FROM Formats", engine, index_col='id').to_dict()["format"]
    CONTENT_PILLARS = pd.read_sql("SELECT * FROM ContentPillars", engine, index_col='id').to_dict()["pillar"]
    
    STRAT_PILLAR_MAP = pd.read_sql(
        """
        SELECT sma.id AS account_id,
            strp.pillar AS pillar,
            strp.id AS id

        FROM StrategyPillars strp
        JOIN Brands b
            ON strp.brand_id = b.id
        JOIN SocialMediaAccounts sma
            ON b.id = sma.brand_id
        """, engine, index_col='id'
    )
    
    exceptions = []

    df = pd.concat(dfs)

    df = _add_embeddings_to_df(df)

    
    retrieval_data = _prepare_retrieval_data(df)

    results = []

    for idx, row in df.iterrows():

        try:

            strategy_pillars = STRAT_PILLAR_MAP.loc[STRAT_PILLAR_MAP['account_id '] == row['account_id']].to_dict()['pillar']

            classification = _classify_post(
                post_text=row["postText"],
                source=row["account_id"],
                retrieval_data= retrieval_data,
                formats=FORMATS,
                content_pillars=CONTENT_PILLARS,
                strategy_pillars=strategy_pillars
            )

            results.append(classification)
        except Exception as e:

            text = f"{type(e).__name__}: {e}. Failed on row {idx}"
            exceptions.append(text)

            results.append({
                "format_id": pd.NA,
                "content_pillar_id": pd.NA,
                "strategy_pillar_id": pd.NA
            })
    
    classification_df = pd.DataFrame(results)

    df["format_id"] = classification_df["format_id"]
    df["content_pillar_id"] = classification_df["content_pillar_id"]
    df["strategy_pillar_id"] = classification_df["strategy_pillar_id"]

    df = _get_embedding_space(df)
    
    df['row_hash'] = add_row_hash(df[['postText','account_id']])['row_hash']
    df['updated_at'] = datetime.now()

    for col in INT_COLS:
        if col in df.columns:
            df[col] = (df[col]//1).astype("Int64")

    PostDF = _bend_to_sql_shape(df,'Posts',engine)

    terms = _get_top_terms(df)

    terms['row_hash'] = add_row_hash(terms[['term','account_id']])['row_hash']
    terms['updated_at'] = datetime.now()

    TermsDF = _bend_to_sql_shape(terms,'Terms',engine)
    
    return PostDF, TermsDF, exceptions

def transform_metrics(dfs:list, engine: Engine) -> pd.DataFrame:
    """
    """

    df = pd.concat(dfs)

    df['row_hash'] = add_row_hash(df[['date','account_id']])['row_hash']
    df['updated_at'] = datetime.now()

    for col in INT_COLS:
        if col in df.columns:
            df[col] = (df[col]//1).astype("Int64")

    
    MetricsDF = _bend_to_sql_shape(df,'Metrics',engine)

    return MetricsDF
    
    










