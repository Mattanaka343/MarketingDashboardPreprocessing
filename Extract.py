import os
import time
import logging
import requests

import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()

#from pathlib import path
from sqlalchemy import text
from typing import Any

from datetime import datetime

from sqlalchemy.engine import Engine
#from google.analytics.data_v1beta import BetaAnalyticsDataClient
#from google.oauth2 import service_account
#from google.analytics.data_v1beta.types import (
#   DateRange,
#   Dimension,
#   Metric,
#   RunReportRequest,
#)

RENAME_MAP_LINKEDIN_METRICS = {
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

RENAME_MAP_X_METRICS = {
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

RENAME_MAP_X_POSTS = {
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


RENAME_MAP_LINKEDIN_POSTS = {
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

META_BASE_URL = "https://graph.facebook.com/v25.0"

INSTA_ACCOUNTS = {
    "Wexpand Talent": {
        "user_id":   os.getenv("IG_USER_ID"),
        "token":     os.getenv("IG_ACCESS_TOKEN"),
    },
}

_INSTA_ACCOUNT_METRICS_TS = ["follower_count", "reach"]
_INSTA_ACCOUNT_METRICS_TV = ["accounts_engaged", "total_interactions", "views"]

RENAME_MAP_INSTA_METRICS = {
    "follower_count": "followersGained",
    "accounts_engaged": "accountsEngaged",
    "total_interactions": "engagements",
    "views": "impressions"  
}

_INSTA_POST_METRICS = [
    "reach", 
    "total_interactions", 
    "saved",
    "views"  
]

_INSTA_POST_METRICS_REELS = [
    "reach", 
    "saved", 
    "shares", 
    "total_interactions",
    "views",
    "ig_reels_avg_watch_time", 
    "ig_reels_video_view_total_time"
]

RENAME_MAP_INSTA_POSTS = {
    "id": "postId",
    "timestamp": "date",                      
    "caption": "postText",                    
    "permalink": "postUrl",
    "media_type": "postType",
    "likes_count": "reactions",                
    "comments_count": "comments",             
    
    "total_interactions": "engagements",       
    "saved": "saves",
    "shares": "shares",
    "views": "impressions",                  
    "ig_reels_avg_watch_time": "avgWatchTimeMs",
    "ig_reels_video_view_total_time": "watchTimeMs"
}

def _meta_get(url: str, params: dict, retries: int = 3) -> dict:
    """
    Thin wrapper around the meta praph api. It allows for safe retrie

    parameters:
        url:        the url pertaining to the request
        params:     the parameters the request should take
        retries:    the amoount of times it is allowed to try to obtain a response again

    output:
        response:   returns a json of the response the api sends back  
    """
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                logging.error("Meta API error %s: %s", url, exc)
                raise


def instaExtraction(brand: tuple, engine: Engine) -> tuple:
    """
    This function extracts both account level and post level metrics for the instagram account of a brand.
    
    parameters:
        brand:  a tuple containing the name of the brand as it is to be found on files and as it is found on the database
        engine: a mysql connection

    output:
        MetricsDF:  A pandas dataframe containing the account level metrics
        PostDF:     A pandas dataframe containing the post level metrics 
    """
    brand_name = brand[1]

    if brand_name not in INSTA_ACCOUNTS:
        logging.info("instaExtraction: no Instagram account configured for '%s', skipping.", brand_name)
        return None, None

    cfg = INSTA_ACCOUNTS[brand_name]
    ig_user_id = cfg["user_id"]
    token      = cfg["token"]

    if not ig_user_id or not token:
        logging.error("instaExtraction: missing env vars for '%s'. Check INSTA_ACCOUNTS.", brand_name)
        return None, None

    account_id = _get_acc_id(brand_name, "Instagram", engine)
    params     = {"access_token": token}

    # -- Account-level daily metrics --
    MetricsDF = None
    try:
        ts_resp = _meta_get(
            f"{META_BASE_URL}/{ig_user_id}/insights",
            {**params, "metric": ",".join(_INSTA_ACCOUNT_METRICS_TS), "period": "day"},
        )
        tv_resp = _meta_get(
            f"{META_BASE_URL}/{ig_user_id}/insights",
            {**params, "metric": ",".join(_INSTA_ACCOUNT_METRICS_TV), "period": "day", "metric_type": "total_value"},
        )
        
        combined_data = ts_resp.get("data", []) + tv_resp.get("data", [])
        date_rows: dict[str, dict] = {}
        for m in combined_data:
            if "total_value" in m:
                val_block = m["total_value"]
                day = val_block.get("end_time", "")[:10] if "end_time" in val_block else datetime.utcnow().strftime('%Y-%m-%d')
                date_rows.setdefault(day, {"date": day})
                date_rows[day][m["name"]] = val_block.get("value", 0)
            else:
                for point in m.get("values", []):
                    day = point["end_time"][:10]
                    date_rows.setdefault(day, {"date": day})
                    val = point["value"]
                    date_rows[day][m["name"]] = sum(val.values()) if isinstance(val, dict) else val

        if date_rows:
            MetricsDF = pd.DataFrame(date_rows.values()).rename(columns=RENAME_MAP_INSTA_METRICS)
            MetricsDF["date"]           = pd.to_datetime(MetricsDF["date"])
            MetricsDF["account_id"]     = account_id
            
            MetricsDF["engagementRate"] = MetricsDF.apply(
                lambda r: r["engagements"] / r["impressions"] if r.get("impressions") else 0, axis=1
            )
            MetricsDF["followersGained"] = MetricsDF.get("followersGained", np.nan)
            
            if "reach" in MetricsDF.columns:
                MetricsDF = MetricsDF.drop(columns=["reach"])

    except Exception as exc:
        logging.error("instaExtraction metrics failed for '%s': %s", brand_name, exc)

    # -- Per-post insights --
    PostsDF = None
    try:
        # Added media_product_type into the initial fields mapping payload
        media_resp = _meta_get(
            f"{META_BASE_URL}/{ig_user_id}/media",
            {**params, "fields": "id,timestamp,caption,permalink,media_type,media_product_type,like_count,comments_count"},
        )
        posts = media_resp.get("data", [])
        while "next" in media_resp.get("paging", {}):
            media_resp = _meta_get(media_resp["paging"]["next"], {})
            posts.extend(media_resp.get("data", []))

        post_rows = []
        for post in posts:
            post_id            = post["id"]
            media_type         = post.get("media_type", "IMAGE")
            media_product_type = post.get("media_product_type", "") # Fetch the exact sub-type structure
            
            # Strict validation to ensure retention metrics are only asked for explicit Reels tab items
            if media_product_type == "REELS":
                metrics = _INSTA_POST_METRICS_REELS
            else:
                metrics = _INSTA_POST_METRICS
                
            try:
                ins = _meta_get(f"{META_BASE_URL}/{post_id}/insights", {**params, "metric": ",".join(metrics)})
                insight_data = {
                    item["name"]: item["values"][0]["value"] if item.get("values") else item.get("value", 0)
                    for item in ins.get("data", [])
                }
            except Exception:
                insight_data = {}

            post_rows.append({
                "id": post_id, "timestamp": post.get("timestamp"),
                "caption": post.get("caption", ""), "permalink": post.get("permalink", ""),
                "media_type": media_type, "likes_count": post.get("like_count", 0),
                "comments_count": post.get("comments_count", 0), **insight_data,
            })

        if post_rows:
            PostsDF = pd.DataFrame(post_rows).rename(columns=RENAME_MAP_INSTA_POSTS)
            PostsDF["account_id"]     = account_id
            PostsDF["date"]           = pd.to_datetime(PostsDF["date"])
            
            PostsDF["engagementRate"] = PostsDF.apply(
                lambda r: r.get("engagements", 0) / r["impressions"] if r.get("impressions") else 0, axis=1
            )
            
            PostsDF["views"] = PostsDF.get("impressions", 0)
            
            if "reach" in PostsDF.columns:
                PostsDF = PostsDF.drop(columns=["reach"])

    except Exception as exc:
        logging.error("instaExtraction posts failed for '%s': %s", brand_name, exc)

    return MetricsDF, PostsDF

def _get_acc_id(brand: str, channel: str, engine: Engine) -> int:
    """
    Obtains the id for a social media account from the database/

    parameters:
        brand:      The name of the brand whose ID you'd like to receive
        channel:    The name of the channel for the brand whose ID you'd like to receive
        engine:     A sqlalchemy connection to the database

    output:
        id:         An integer that represents the brand and social media account combination in the database

    """
    with engine.connect() as conn:
        idx = conn.execute(
            text(f"""
                  SELECT sma.id 
                  FROM SocialMediaAccounts sma
                  JOIN Brands b
                      ON sma.brand_id = b.id
                  WHERE b.name = '{brand}'
                  AND sma.channel = '{channel}'""")).scalar()
        
        return idx 

def linkedInExtraction(paths: list, brand: tuple, engine:Engine) -> tuple:
    """
    Extracts the data from the excel files produced by the different brands linkedin accounts

    parameters:
        paths:      A list of paths to different data files
        brand:      A tuple containing the in path signifier for a certain brand and it's in database name
        engine:     A sqlalchemy connection to the database

    output:
        MetricsData: A pandas dataframe containing all of the account level metrics for a certain brand's linkedin account
        PostsDF:   A pandas  dataframe containing all posts and post level metrics for a certain brand's linkedin account

    """
    total_data = []
    posts = False
    PostsDF = None
    MetricsData = None

    for path in paths:
        if brand[0] in path and '.xls' in path:
            if 'content' in path:
                PostsDF = pd.read_excel(path,sheet_name=1,skiprows=1)
                df = pd.read_excel(path,sheet_name=0,skiprows=1)
                posts = True
            else:
                df = pd.read_excel(path)

            total_data.append(df)
    
    account_id = _get_acc_id(brand[1],'LinkedIn',engine)
    if total_data != []:
        MetricsData = total_data[0]
        if len(total_data) > 1:
            for idx in range(1,len(total_data)):
                MetricsData = pd.merge(MetricsData,total_data[idx],on='Fecha', how='outer')
        keep_cols = [col for col in MetricsData.columns if 'total' in col.lower()]
        keep_cols.append('Fecha')

        MetricsData = MetricsData[keep_cols]
        MetricsData = MetricsData.rename(columns = RENAME_MAP_LINKEDIN_METRICS)
        MetricsData['account_id'] = account_id
        MetricsData['engagements'] = [val1*val2 for val1,val2 in zip(MetricsData['impressions'],MetricsData['engagementRate'])]
        MetricsData['date'] = pd.to_datetime(MetricsData['date'],format='%m/%d/%Y')
        MetricsData['followersTotal'] = np.nan

    if posts:
        PostsDF = PostsDF.rename(columns= RENAME_MAP_LINKEDIN_POSTS)
        PostsDF['account_id'] = account_id
        PostsDF['engagements'] = [np.round(val1*val2,1) for val1,val2 in zip(PostsDF['impressions'],PostsDF['engagementRate'])]
        PostsDF['date'] = pd.to_datetime(PostsDF['date'],format='%m/%d/%Y')
    
    return MetricsData, PostsDF


def xExtraction(paths: list, brand:tuple, engine:Engine) -> tuple:
    """
    Extracts all possible information from the .csv files produced by linkedIn

    parameters: 
        paths:  A list of paths for diffferent data files
        brand:  A tuple containing the in file signifier for a brand and their in database name 
        engine: A sqlalchemy connection to the database

    output:
        MetricsDF:  A pandas dataframe with the account level metrics
        PostsDF:    A pandas dataframe with the per post metrics
    """
    metrics = False
    posts = False

    MetricsDF = None
    PostsDF = None

    for path in paths:
        if brand[0] in path and '.csv' in path:
            if 'overview' in path:
                MetricsDF = pd.read_csv(path)
                metrics = True
            
            else:
                PostsDF = pd.read_csv(path)
                posts = True

    account_id  = _get_acc_id(brand[1],'X',engine)

    if metrics:
        MetricsDF = MetricsDF.rename(columns=RENAME_MAP_X_METRICS)
        MetricsDF['account_id'] = account_id
        MetricsDF['engagementRate'] = [val1/val2 if val2 != 0 else 0 for val1,val2 in zip(MetricsDF['engagements'],MetricsDF['impressions'])]
        MetricsDF['date'] = pd.to_datetime(MetricsDF['date'],format='%a, %b %d, %Y')
    
    if posts:
        PostsDF = PostsDF.rename(columns = RENAME_MAP_X_POSTS)
        PostsDF['account_id'] = account_id
        PostsDF['engagement_rate'] = [val1/val2 if val2 != 0 else 0 for val1,val2 in zip(PostsDF['engagements'], PostsDF['impressions'])]
        PostsDF['date'] = pd.to_datetime(PostsDF['date'],format='%a, %b %d, %Y')

    return MetricsDF, PostsDF


