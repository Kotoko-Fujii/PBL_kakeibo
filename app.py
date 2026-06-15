import os
import random
import json
import gspread
import gspread.exceptions
import google.generativeai as genai
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request, abort
from datetime import datetime
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# --- 各種設定 ---
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# --- Gemini設定 ---
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def get_available_gemini_model():
    try:
        return genai.GenerativeModel("gemini-2.5-flash")
    except:
        return genai.GenerativeModel("gemini-1.5-flash")

gemini_model = get_available_gemini_model()
CATEGORIES = ["食費", "日用品", "交通費", "娯楽", "美容・衣服", "交際費", "その他"]

# --- スプレッドシート認証 ---
def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

# ★【新規追加】ユーザー専用のタブ（ワークシート）を取得または作成する関数
def get_or_create_user_sheet(sh, user_id):
    try:
        # すでにそのユーザーIDのタブがあれば、それを開く
        return sh.worksheet(user_id)
    except gspread.exceptions.WorksheetNotFound:
        # タブが見つからなければ、新しく作成する（初期設定：1000行、4列）
        ws = sh.add_worksheet(title=user_id, rows="1000", cols="4")
        # 1行目にヘッダーを書き込む
        ws.append_row(["日時", "品目", "金額", "カテゴリ"])
        return ws

def get_or_create_settings_sheet(sh):
    try:
        return sh.worksheet("設定")
    except:
        ws = sh.add_worksheet(title="設定", rows="10", cols="2")
        ws.update_acell('A1', '毎日の予算')
        ws.update_acell('B1', '2000')
        return ws
