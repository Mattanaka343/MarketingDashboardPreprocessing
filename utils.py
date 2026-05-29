import os
import smtplib
import hashlib 

from glob import glob
from dotenv import load_dotenv

from email.mime.text import MIMEText

load_dotenv()

DATA_PATH = os.getenv('DATA_PATH')
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT = os.getenv("NOTIFY_TO")

def find_files() -> list:
    paths = glob(DATA_PATH+'*.*')
    if paths == []:
        return None
    else:
        return paths
    

def send_mail(subject:str,body:str):
    """
    Sends an automated e-mail with body and subject
    """
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["FROM"] = GMAIL_USER
    msg["To"] = RECIPIENT

    with smtplib.SMTP_SSL("smtp.gmail.com", 465,) as smtp:
        smtp.login(GMAIL_USER,GMAIL_PASS)
        smtp.sendmail(GMAIL_USER,RECIPIENT,msg.as_string())

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

def clear_temp_files(allFiles:list):
    for file in allFiles:
        os.remove(file) 

