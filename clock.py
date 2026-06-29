import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi
from linebot.models import TextSendMessage

# --- LINE API 設定 ---
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

# --- スプレッドシート認証 ---
def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

def send_morning_budget_reminders():
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
        
        # スプレッドシート内にあるすべてのタブ（ユーザーシート）を取得
        worksheets = sh.worksheets()
        
        for ws in worksheets:
            user_id = ws.title
            
            # LINEのユーザーIDは「U」から始まる33文字の英数字なので、それ以外（管理用など）はスキップ
            if not (user_id.startswith('U') and len(user_id) == 33):
                continue
                
            # 各ユーザーのシートから予算（G1セル）を取得
            try:
                val = ws.acell('G1').value
                budget = int(str(val).replace(',', '')) if val else 2000
            except:
                budget = 2000 # エラー時はデフォルト2000円
                
            # 対象のユーザーにプッシュメッセージを送信
            try:
                message = f"☀️ 朝のリマインド\n今日の予算は {budget:,}円 だよ！\n今日も無理せず節約がんばろうね💪"
                line_bot_api.push_message(user_id, TextSendMessage(text=message))
                print(f"Successfully sent to: {user_id}")
            except Exception as line_error:
                print(f"LINE send error for {user_id}: {line_error}")
                
    except Exception as e:
        print(f"Global Cron Error: {e}")

if __name__ == "__main__":
    send_morning_budget_reminders()
