import os
import time
import logging
import requests

import pandas as pd
import numpy as np

#from pathlib import path
from sqlalchemy import text
from typing import Any

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

def _get_acc_id(brand: str, channel: str, engine: Engine):
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

