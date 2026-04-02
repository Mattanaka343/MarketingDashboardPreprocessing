import pandas as pd
import numpy as np
import hashlib 
import umap
from glob import glob
from sqlalchemy import create_engine, text, String
from sentence_transformers import SentenceTransformer
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
import re
import os

def add_row_hash(df):
    df = df.copy()
    df = df.sort_index(axis=1) 
    
    df["row_hash"] = df.apply(
        lambda row: hashlib.md5(
            "|".join([str(v) for v in row.values]).encode()
        ).hexdigest(),
        axis=1
    )
    return df


def pass_to_sql(
    df,
    engine,
    table_name,
    unique_cols=None,  
    timestamp_col="updated_at"
):

    df = df.copy()

    if unique_cols is None:
        df = add_row_hash(df)
        unique_cols = ["row_hash"]

    else:
        df["row_hash"] = add_row_hash(df[unique_cols])['row_hash']
        unique_cols = ["row_hash"]

    df[timestamp_col] = datetime.now()

    df.head(0).to_sql(
        table_name,
        con=engine,
        if_exists="append",
        index=False,
        dtype={
            "row_hash": String(32)
        }
    )

    constraint_name = f"unique_row_{table_name}"


    with engine.connect() as conn:

        col_exists = conn.execute(text(f"""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'mkt'
            AND table_name = '{table_name}'
            AND column_name = 'row_hash';
        """)).scalar()

        if not col_exists:
            conn.execute(text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN row_hash VARCHAR(32);
            """))

        ts_exists = conn.execute(text(f"""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'mkt'
            AND table_name = '{table_name}'
            AND column_name = '{timestamp_col}';
        """)).scalar()

        if not ts_exists:
            conn.execute(text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN {timestamp_col} DATETIME;
            """))

        exists = conn.execute(text(f"""
            SELECT COUNT(*)
            FROM information_schema.statistics
            WHERE table_schema = 'mkt'
            AND table_name = '{table_name}'
            AND index_name = '{constraint_name}';
        """)).scalar()

        if not exists:
            conn.execute(text(f"""
                ALTER TABLE {table_name}
                ADD CONSTRAINT {constraint_name}
                UNIQUE (`row_hash`);
            """))

    temp_table = f"{table_name}_temp"

    df.to_sql(
        temp_table,
        con=engine,
        if_exists="replace",
        index=False
    )


    with engine.connect() as conn:

        cols = ", ".join(df.columns)
        updates = ", ".join(
            [f"{col}=VALUES({col})" for col in df.columns]
        )

        conn.execute(text(f"""
            INSERT INTO {table_name} ({cols})
            SELECT {cols}
            FROM {temp_table}
            ON DUPLICATE KEY UPDATE
            {updates};
        """))

        conn.execute(text(f"DROP TABLE {temp_table}"))

XFiles = glob('Data//Raw/*.csv')
NLinFiles = glob('Data//Raw/nurvai*.xls')

WexFiles = glob('Data//Raw/wexpand-business*.xls')
TalFiles = glob('Data//Raw/wexpand-talent*.xls')


NLinData = []
WexData = []
TalData = []

for file in XFiles:
    if 'content' in file:
        XPostDF = pd.read_csv(file)
    else:
        XDF = pd.read_csv(file)
    
for file in NLinFiles:
    if 'content' in file:
        df = pd.read_excel(file,sheet_name=0,skiprows=1)
        NLinPostDF = pd.read_excel(file,sheet_name=1,skiprows=1)
    else:
        df = pd.read_excel(file)
    
    NLinData.append(df)
    
for file in WexFiles:
    if 'content' in file:
        df = pd.read_excel(file,sheet_name=0,skiprows=1)
        WexLinPostDF = pd.read_excel(file,sheet_name=1,skiprows=1)
    else:
        df = pd.read_excel(file)
    
    WexData.append(df)

for file in TalFiles:
    if 'content' in file:
        df = pd.read_excel(file,sheet_name=0,skiprows=1)
        TalLinPostDF = pd.read_excel(file,sheet_name=1,skiprows=1)
    else: 
        df = pd.read_excel(file)

    TalData.append(df)

NLinDF = NLinData[0]
WexDF = WexData[0]
TalDF = TalData[0]


for idx in range(1,len(NLinData)):
    NLinDF = pd.merge(NLinDF,NLinData[idx],on='Fecha', how='outer')

for idx in range(1,len(WexData)):
    WexDF = pd.merge(WexDF,WexData[idx],on='Fecha',how='outer')

for idx in range(1,len(TalData)):
    TalDF = pd.merge(TalDF,TalData[idx],on='Fecha',how='outer')

keepCols = [col for col in NLinDF.columns if 'total' in col.lower()]
keepCols.append('Fecha')

renameMap = {
    "Total de seguidores": "followersGained",
    "Visualizaciones de la página general (total)": "generalPageViews",
    "Visitantes únicos de la página general (total)": "generalPageUniqueVisitors",
    "Visualizaciones de la página de vida en la empresa (total)": "lifePageViews",
    "Visitantes únicos de la página de vida en la empresa (total)": "lifePageUniqueVisitors",
    "Visualizaciones de la página de empleo (total)": "jobsPageViews",
    "Visitantes únicos de la página de empleo (total)": "jobsPageUniqueVisitors",
    "Visualizaciones de la página en total (ordenador)": "pageViewsDesktop",
    "Visualizaciones de la página en total (móvil)": "pageViewsMobile",
    "Visualizaciones de la página en total (total)": "pageViews",
    "Visitantes únicos en total (ordenador)": "uniqueVisitorsDesktop",
    "Visitantes únicos en total (móvil)": "uniqueVisitorsMobile",
    "Visitantes únicos en total (total)": "uniqueVisitors",
    "Impresiones (totales)": "impressions",
    "Clics (totales)": "clicks",
    "Reacciones (total)": "reactions",
    "Comentarios (totales)": "comments",
    "Veces compartido (total)": "shares",
    "Tasa de interacción (total)": "engagementRate",
    "Fecha": "date"
}

NLinDF = NLinDF[keepCols]
WexDF = WexDF[keepCols]
TalDF = TalDF[keepCols]

NLinDF = NLinDF.rename(columns = renameMap)
WexDF = WexDF.rename(columns = renameMap)
TalDF = TalDF.rename(columns = renameMap)

WexDF['acc'] = ['buis' for i in range(len(WexDF))]
TalDF['acc'] = ['tal' for i in range(len(TalDF))]
NLinDF['acc'] = ['nvai' for i in range(len(NLinDF))]

WexDF['engagements'] = [val1*val2 for val1,val2 in zip(WexDF['impressions'],WexDF['engagementRate'])]
TalDF['engagements'] = [val1*val2 for val1,val2 in zip(TalDF['impressions'],TalDF['engagementRate'])]
NLinDF['engagements'] = [val1*val2 for val1,val2 in zip(NLinDF['impressions'],NLinDF['engagementRate'])]

WexDF['chan'] = ['lin' for i in range(len(WexDF))]
TalDF['chan'] = ['lin' for i in range(len(TalDF))]
NLinDF['chan'] = ['lin' for i in range(len(NLinDF))]

LinDF = pd.concat([WexDF,TalDF,NLinDF])
LinDF['date'] = pd.to_datetime(LinDF['date'],format='%m/%d/%Y')
LinDF['followersTotal'] = np.nan

renameMapX = {
    "Date": "date",
    "Impressions": "impressions",
    "Likes": "reactions",
    "Engagements": "engagements",
    "Bookmarks": "bookmarks",
    "Shares": "timesSent",
    "Reposts": "shares",
    "Replies": "comments",
    "New follows": "followersGained",
    "Unfollows": "unfollows",
    "Profile visits": "profileVisits",
    "Create Post": "postsCreated",
    "Video views": "videoViews",
    "Media views": "mediaViews",
    "Views": "views",
    "Watch Time (ms)": "watchTimeMs",
    "Average Watch Time (ms)": "avgWatchTimeMs",
    "Completion Rate": "completionRate",
    "Estimated Revenue": "estimatedRevenue"
}

XDF = XDF.rename(columns=renameMapX)
XDF['acc'] = ['nvai' for i in range(len(XDF))]
XDF['chan'] = ['x' for i in range(len(XDF))]
XDF['engagementRate'] = [val1/val2 if val2 != 0 else 0 for val1,val2 in zip(XDF['engagements'],XDF['impressions']) ]
XDF['date'] = pd.to_datetime(XDF['date'],format='%a, %b %d, %Y')

renameMapPosts = {
    'Post id':'postId', 
    'Date':'date', 
    'Post text':'postText',
    'Post Link': 'postUrl', 
    'Impressions': 'impressions', 
    'Likes': 'reactions',
    'Engagements': 'engagements', 
    'Bookmarks':'bookmarks', 
    'Shares': 'timesSent', 
    'New follows': 'followersGained',
    'Replies':'comments',
    'Reposts':'shares', 
    'Profile visits':'profileVisits',
    'Detail Expands':'detailExpands',
    'URL Clicks':'urlClicks',
    'Hashtag Clicks':'hashtagClicks',
    'Permalink Clicks': 'permalinkClicks'
}


XPostDF = XPostDF.rename(columns=renameMapPosts)
XPostDF['acc'] = ['nvai' for i in range(len(XPostDF))]
XPostDF['chan'] = ['x' for i in range(len(XPostDF))]
XPostDF['engagementRate'] = [val1/val2 if val2 != 0 else 0 for val1,val2 in zip(XPostDF['engagements'],XPostDF['impressions'])]
XPostDF['date'] = pd.to_datetime(XPostDF['date'],format='%a, %b %d, %Y')

renameMapLin = {
    'Título de la publicación': 'postText',
    'Enlace de la publicación': 'postUrl',
    'Tipo de publicación': 'postType',
    'Nombre de la campaña': 'campaignName',
    'Anunciado por': 'postedBy',
    'Fecha de creación': 'date',
    'Fecha de inicio de campaña': 'campaignStartDate',
    'Fecha de finalización de campaña': 'campaignEndDate',
    'Público': 'audience',
    'Impresiones': 'impressions',
    'Visualizaciones': 'views',
    'Visualizaciones fuera del sitio': 'offsiteViews',
    'Clics': 'clicks',
    'Porcentaje de clics': 'clickThroughRate',
    'Recomendaciones': 'reactions',
    'Comentarios': 'comments',
    'Veces compartido': 'shares',
    'Seguidores': 'followersGained',
    'Tasa de interacción': 'engagementRate',
    'Tipo de contenido': 'contentType'
}

NLinPostDF = NLinPostDF.rename(columns=renameMapLin)
WexLinPostDF = WexLinPostDF.rename(columns=renameMapLin)
TalLinPostDF =  TalLinPostDF.rename(columns=renameMapLin)

NLinPostDF['acc'] = ['nvai' for i in range(len(NLinPostDF))]
WexLinPostDF['acc'] = ['buis' for i in range(len(WexLinPostDF))]
TalLinPostDF['acc'] = ['tal' for i in range(len(TalLinPostDF))]

NLinPostDF['engagements'] = [np.round(val1*val2,1) for val1,val2 in zip(NLinPostDF['impressions'],NLinPostDF['engagementRate'])]
WexLinPostDF['engagements'] = [np.round(val1*val2,1) for val1,val2 in zip(WexLinPostDF['impressions'],WexLinPostDF['engagementRate'])]
TalLinPostDF['engagements'] = [np.round(val1*val2,1) for val1,val2 in zip(TalLinPostDF['impressions'],TalLinPostDF['engagementRate'])]

NLinPostDF['chan'] = ['lin' for i in range(len(NLinPostDF))]
WexLinPostDF['chan'] = ['lin' for i in range(len(WexLinPostDF))]
TalLinPostDF['chan'] = ['lin' for i in range(len(TalLinPostDF))]

LinPostDF = pd.concat([NLinPostDF,WexLinPostDF,TalLinPostDF])
LinPostDF['date'] = pd.to_datetime(LinPostDF['date'],format='%m/%d/%Y')
LinPostDF['contentType'] = LinPostDF['contentType'].str.replace('Vídeo','video')

MetricDF = pd.concat([LinDF,XDF])
PostDF = pd.concat([LinPostDF,XPostDF])

PostDF['type'] = 'Unspecified'

PostDF.loc[PostDF['postText'].str.startswith('@', na=False), 'type'] = 'Reply'
PostDF.loc[PostDF['postText'].str.contains('#NurvaiResearcherOfTheWeek', na=False), 'type'] = 'ROTW'
PostDF.loc[PostDF['postText'].str.contains('got us thinking:', na=False), 'type'] = 'Poll'
PostDF.loc[PostDF['postText'].str.contains('#NurvaiPaperOfTheWeek', na=False), 'type'] = 'POTW'

PostDF['pillar'] = 'Unspecified'
PostDF.loc[PostDF['acc'] == 'nvai', 'pillar'] = 'ExtAmp'

model = SentenceTransformer("all-MiniLM-L6-v2")

embeddings = model.encode(
    PostDF["postText"].tolist(),
    show_progress_bar=False
)

reducer = umap.UMAP(
    n_neighbors=15,
    min_dist=0.1,
    metric="cosine",
    random_state=42
)

embedding_2d = reducer.fit_transform(embeddings)

PostDF["umap_x"] = embedding_2d[:,0]
PostDF["umap_y"] = embedding_2d[:,1]

PostDF.to_csv('Data//Processed/PostDF.csv', index=False)
MetricDF.to_csv('Data//Processed/MetricDF.csv',index=False)

# ─────────────────────────────────────────────
# TERM COMPUTATION
#
# For each (acc, chan) combination we:
#   1. Build a TF-IDF matrix over all post texts
#   2. Multiply each term's TF-IDF score by the post's engagementRate
#   3. Sum across posts → engagement-weighted score per term
#   4. Normalise to 0-1 within each (acc, chan) group
#
# This gives us terms that are both frequent AND appear in
# high-engagement posts — not just the most common words.
# ─────────────────────────────────────────────



STOPWORDS = {
    # English
    'the','and','for','that','this','with','are','was','you','your',
    'have','has','from','not','but','they','our','their','been','more',
    'will','one','can','all','its','about','what','how','who','when',
    'which','also','into','than','some','out','just','we','it','is',
    'in','of','to','a','an','on','at','be','as','by','or','do',
    'if','up','so','he','she','my','his','her','we','us','me',
    # Spanish
    'que','los','las','una','para','con','por','del','como','una',
    'los','sus','más','pero','esta','esto','este','son','ha','se',
    'la','el','en','de','un','es','al','le','lo','si','ya','día',
    'nuestro', 'wexpandtalent', 'adayatwexpand', 'conocerás', 'muy',
    'pronto','siendo','desde', 'queremos', 'cada', 'no', 'teamlife', 
    'culturalaboral', 'peoplefirst', 'wexpand', 'cada', 'queremos',
    'nos', 'todos', 'solo', 'su', 'ser', 'buena', 'octubre',  
    # Common social noise
    'via','amp','rt','please','thank','thanks','new','get','use',
    'make','made','work','working','day','time','great','good',
    'need','want','know','see','look','say','said','next','last',
    'first','year','week','month','today','now','even','well', 'https',
    'great', 'really', 'like', 'important', 'interestring', 'co', 'way', 
    'interesting', 'see', 'seems', 'one'
}

def clean_text(text):
    text = str(text).lower()
    text = re.sub(r'http\S+', '', text)          # remove URLs
    text = re.sub(r'@\w+', '', text)             # remove mentions
    text = re.sub(r'#(\w+)', r'\1', text)        # keep hashtag words
    text = re.sub(r'[^a-záéíóúüñ\s]', ' ', text) # keep letters only
    return text

TermsRows = []

for (acc, chan), group in PostDF.groupby(['acc', 'chan']):
    group = group.dropna(subset=['postText', 'engagementRate'])
    group = group[group['postText'].str.strip() != '']

    if len(group) < 3:  # not enough posts to compute meaningful terms
        continue

    texts   = group['postText'].apply(clean_text).tolist()
    weights = group['engagementRate'].astype(float).values

    vectorizer = TfidfVectorizer(
        max_features=500,
        ngram_range=(1, 2),     # single words AND two-word phrases
        min_df=2,               # term must appear in at least 2 posts
        stop_words=list(STOPWORDS),
    )

    try:
        tfidf_matrix = vectorizer.fit_transform(texts)  # shape: (posts, terms)
    except ValueError:
        continue  # skip if not enough vocabulary

    terms = vectorizer.get_feature_names_out()

    # multiply each post's tfidf row by its engagement weight, then sum columns
    weighted_scores = tfidf_matrix.T.dot(weights)  # shape: (terms,)

    # normalise to 0-1
    max_score = weighted_scores.max()
    if max_score == 0:
        continue
    normalised = weighted_scores / max_score

    for term, score in zip(terms, normalised):
        if score > 0.05:  # drop near-zero terms
            TermsRows.append({
                'term':             term,
                'engagement_score': round(float(score), 4),
                'acc':              acc,
                'chan':             chan,
            })

TermsDF = pd.DataFrame(TermsRows)
TermsDF.to_csv('Data//Processed/TermsDF.csv', index=False)

# ─────────────────────────────────────────────

allFiles = XFiles + NLinFiles + WexFiles + TalFiles

engine = create_engine("mysql+pymysql://root:pword@localhost:3306/mkt")

pass_to_sql(MetricDF, engine, 'Metrics', unique_cols=['date'])
pass_to_sql(PostDF,   engine, 'Posts',   unique_cols=['postText'])
pass_to_sql(TermsDF,  engine, 'Terms',   unique_cols=['term', 'acc', 'chan'])

with engine.connect() as conn:
    query = text(
    """
    UPDATE Metrics m
    JOIN (
        SELECT
            acc,
            chan,
            date,
            SUM(
                COALESCE(followersGained, 0) 
                - COALESCE(unfollows, 0)
            ) OVER (
                PARTITION BY acc, chan
                ORDER BY date
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS followersTotal_calc
        FROM Metrics
    ) t
    ON m.acc = t.acc
    AND m.chan = t.chan
    AND m.date = t.date
    SET m.followersTotal = t.followersTotal_calc;
    """)
    conn.execute(query)
    conn.commit()


for file in allFiles:
    os.remove(file) 