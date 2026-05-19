import os
import smtplib

from dotenv import load_dotenv
from email.mime.text import MIMEText

load_dotenv()

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_PASS = os.getenv("GMAIL_APP_PASSWORD")
RECIPIENT = os.getenv("NOTIFY_TO")

def send_mail():
    