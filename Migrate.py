import os 
import ollama
import json

import pandas as pd
import numpy as np

from sqlalchemy import create_engine
from sklearn.metrics.pairwise import cosine_similarity
from dotenv import load_dotenv
from utils import add_row_hash
from datetime import datetime
from warnings import simplefilter

simplefilter('ignore')

load_dotenv()

DATABASE_USER = os.getenv("DATABASE_USER")
DATABASE_PASSWORD = os.getenv("MYSQL_PASSWORD")

EMBED_MODEL = os.getenv("EMBED_MODEL")
LLM_MODEL = os.getenv("LLM_MODEL")

TOP_K = 5

def get_embedding(text):
    response = ollama.embeddings(
        model=EMBED_MODEL,
        prompt=text
    )
    return response["embedding"]

def retrieve_similar_posts(post_text, source, df, top_k=TOP_K):

    target_embedding = np.array(
        get_embedding(post_text)
    ).reshape(1, -1)

    source_df = df[df["account_id"] == source].copy()

    embeddings_matrix = np.vstack(source_df["embedding"].values)

    similarities = cosine_similarity(
        target_embedding,
        embeddings_matrix
    )[0]

    source_df["similarity"] = similarities

    source_df = source_df.sort_values(
        "similarity",
        ascending=False
    )

    # remove identical post
    source_df = source_df[
        source_df["text"] != post_text
    ]

    return source_df.head(top_k)

def dict_to_prompt(title, d):
    rows = [f"{k} -> {v}" for k, v in d.items()]
    return f"{title}:\n" + "\n".join(rows)


def classify_post(
    post_text,
    source,
    df,
    formats,
    content_pillars,
    strategy_pillars
):

    similar_posts = retrieve_similar_posts(
        post_text,
        source,
        df
    )

    context_posts = "\n".join([
        f"- {t[:300]}"
        for t in similar_posts["text"].tolist()
    ])

    prompt = f"""
You are a social media classifier.

Choose EXACTLY ONE ID from each category.

{dict_to_prompt("FORMATS", formats)}

{dict_to_prompt("CONTENT PILLARS", content_pillars)}

{dict_to_prompt("STRATEGY PILLARS", strategy_pillars)}

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

    except Exception:
        print(content)
        raise ValueError("Model returned invalid JSON")


engine_old = create_engine(f'mysql+pymysql://{DATABASE_USER}:{DATABASE_PASSWORD}@localhost:3306/mkt')
engine_new = create_engine(f'mysql+pymysql://{DATABASE_USER}:{DATABASE_PASSWORD}@localhost:3306/Marketing')

Accounts = pd.read_sql('SELECT * FROM SocialMediaAccounts',engine_new)

Metrics_old = pd.read_sql('SELECT * FROM Metrics', engine_old)

map = {
        ('x','nvai'):Accounts.loc[Accounts['channel']=='X','id'].values[0], 
        ('lin','buis'):Accounts.loc[(Accounts['channel']=='LinkedIn') & (Accounts['brand_id'] == 2),'id'].values[0],
        ('lin','tal'):Accounts.loc[(Accounts['channel']=='LinkedIn') & (Accounts['brand_id'] == 3),'id'].values[0],
        ('lin','nvai'):Accounts.loc[(Accounts['channel']=='LinkedIn') & (Accounts['brand_id'] == 1),'id'].values[0],
        }

Metrics_old['account_id'] = [map[(chan,acc)] for chan, acc in zip(Metrics_old['chan'],Metrics_old['acc'])] 

metrics_new_columns = list(pd.read_sql('SELECT * FROM Metrics',engine_new).drop(columns = ['row_hash','updated_at']).columns)

Metrics_new = Metrics_old[metrics_new_columns]

int_cols = ["bookmarks","clicks","comments","engagements","followersGained","followersTotal","impressions",
            "reactions", "shares", "unfollows", "account_id"]

for col in int_cols:
    Metrics_new[col] = (Metrics_new[col]//1).astype("Int64")

Metrics_new["row_hash"] = add_row_hash(Metrics_new[['date','account_id']])['row_hash']
Metrics_new['updated_at'] = datetime.now()

Metrics_new.to_sql('Metrics',engine_new,if_exists='append',index=False)

Posts_old = pd.read_sql("SELECT * FROM Posts",engine_old)

Posts_old['account_id'] = [map[(chan,acc)] for chan, acc in zip(Posts_old['chan'],Posts_old['acc'])] 

FORMATS = pd.read_sql("SELECT * FROM Formats", engine_new, index_col='id').to_dict()["format"]
CONTENT_PILLARS = pd.read_sql("SELECT * FROM ContentPillars", engine_new, index_col='id').to_dict()["pillar"]

all_strat_pillars = pd.read_sql("SELECT * FROM StrategyPillars", engine_new, index_col='id')

STRAT_PILLARS_NVAI = all_strat_pillars[all_strat_pillars['brand_id'] == 1].to_dict()['pillar']
STRAT_PILLARS_BUIS = all_strat_pillars[all_strat_pillars['brand_id'] == 2].to_dict()['pillar']
STRAT_PILLARS_TAL = all_strat_pillars[all_strat_pillars['brand_id'] == 3].to_dict()['pillar']

Posts_old["embedding"] = Posts_old["postText"].fillna("").apply(get_embedding)

strategy_map = {
    Accounts.loc[
        (Accounts["channel"] == "LinkedIn") &
        (Accounts["brand_id"] == 1),
        "id"
    ].values[0]: STRAT_PILLARS_NVAI,

    Accounts.loc[
        (Accounts["channel"] == "LinkedIn") &
        (Accounts["brand_id"] == 2),
        "id"
    ].values[0]: STRAT_PILLARS_BUIS,

    Accounts.loc[
        (Accounts["channel"] == "LinkedIn") &
        (Accounts["brand_id"] == 3),
        "id"
    ].values[0]: STRAT_PILLARS_TAL,

    Accounts.loc[
        Accounts["channel"] == "X",
        "id"
    ].values[0]: STRAT_PILLARS_NVAI
}

results = []

for idx, row in Posts_old.iterrows():

    print(f"Classifying row {idx}")

    try:

        strategy_pillars = strategy_map[row["account_id"]]

        classification = classify_post(
            post_text=row["postText"],
            source=row["account_id"],
            df=Posts_old,
            formats=FORMATS,
            content_pillars=CONTENT_PILLARS,
            strategy_pillars=strategy_pillars
        )

        results.append(classification)

    except Exception as e:

        print(f"Failed on row {idx}: {e}")

        results.append({
            "format_id": pd.NA,
            "content_pillar_id": pd.NA,
            "strategy_pillar_id": pd.NA
        })

classification_df = pd.DataFrame(results)

Posts_old["format_id"] = classification_df["format_id"]
Posts_old["content_pillar_id"] = classification_df["content_pillar_id"]
Posts_old["strategy_pillar_id"] = classification_df["strategy_pillar_id"]

posts_new_columns = list(pd.read_sql('SELECT * FROM Posts',engine_new).drop(columns = ['row_hash','updated_at']).columns)

Posts_new = Posts_old[posts_new_columns]

Posts_new.to_sql("Posts",engine_new,if_exists="append",index=False)

for col in int_cols:
    Posts_new[col] = (Posts_new[col]//1).astype("Int64")

Posts_new["row_hash"] = add_row_hash(Metrics_new[['postText','account_id']])['row_hash']
Posts_new['updated_at'] = datetime.now()

Terms_old = pd.read_sql('SELECT * FROM Terms',engine_old)

Terms_old['account_id'] = [map[(chan,acc)] for chan,acc in zip(Terms_old['chan'],Terms_old['acc'])]

terms_new_columns = list(pd.read_sql('SELECT * FROM Terms').drop(columns=['row_hash','updated_at']).columns())

Terms_new = Terms_old[terms_new_columns]

Terms_new["row_hash"] = add_row_hash(Terms_new[['term','account_id']])['row_hash']
Terms_new['updated_at'] = datetime.now()

Terms_new.to_sql('Terms',engine_new,if_exists="append",index=False)