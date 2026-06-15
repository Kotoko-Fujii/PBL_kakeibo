import os
import json
import gspread
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi
from linebot.models import TextSendMessage

# --- 1. LINEとスプレッドシートの設定 ---
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
user_id = os.getenv('USER_ID') # あなたのLINEユーザーID

def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

# --- 2. 消耗品のリマインド判定ロジック ---
# ここにアイテムと買い替え目安（日数）を自由に追加できます
WATCH_ITEMS = {
    "シャンプー": 60,
    "歯ブラシ": 30,    # ★追加しました！
    "洗剤": 30,
    "スポンジ": 21
}

def check_consumables(ws):
    records = ws.get_all_values()[1:]
    today = datetime.now()
    remind_alerts = []

    for item_name, limit_days in WATCH_ITEMS.items():
        last_bought_date = None
        
        # 下から（最新の記録から）順に探す
        for r in reversed(records):
            if len(r) >= 2 and item_name in r[1]:
                try:
                    last_bought_date = datetime.strptime(r[0], '%Y/%m/%d %H:%M')
                    break
                except:
                    continue
        
        if last_bought_date:
            days_passed = (today - last_bought_date).days
            if days_passed >= limit_days:
                remind_alerts.append(f"⚠️ {item_name}（前回購入から{days_passed}日経過）")
        else:
            remind_alerts.append(f"💡 {item_name}の購入記録がないよ。そろそろ必要かな？")
            
    return remind_alerts

# --- 3. メイン処理（毎日夜10時に動く部分） ---
def main():
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
        ws = sh.get_worksheet(0)
        
        today_str = datetime.now().strftime('%Y/%m/%d')
        records = ws.get_all_values()[1:]
        has_input_today = any(r[0].startswith(today_str) for r in records if len(r) > 0)
        
        alerts = check_consumables(ws)
        msg_lines = []
        
        # 毎日の入力確認
        if not has_input_today:
            msg_lines.append("🌙 夜10時だよ！今日の家計簿の入力は忘れてない？\n「品目 金額」で送ってね！")
        else:
            msg_lines.append("🌙 夜10時の定期連絡だよ！今日も家計簿の記録ありがとう！")
            
        # 消耗品リマインドの合体
        if alerts:
            msg_lines.append("\n【そろそろ買い替えかも？】")
            msg_lines.extend(alerts)
            
        # LINEへ直接送信 (Push API)
        full_message = "\n".join(msg_lines)
        line_bot_api.push_message(user_id, TextSendMessage(text=full_message))
        print("✅ リマインダーの送信に成功しました。")
        
    except Exception as e:
        print(f"❌ リマインダー実行エラー: {e}")

if __name__ == "__main__":
    main()
