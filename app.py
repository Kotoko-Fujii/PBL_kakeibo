import os
import random
import json
import gspread
import google.generativeai as genai
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request, abort
from datetime import datetime
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)

app = Flask(__name__)

# --- 各種設定 ---
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# --- Gemini設定 (安定版モデル gemini-pro を指定) ---
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel("gemini-pro")

# カテゴリ定義
CATEGORIES = ["食費", "日用品", "交通費", "娯楽", "美容・衣服", "交際費", "その他"]

def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

def ask_gemini_category(item_name):
    options = "、".join(CATEGORIES)
    # プロンプトで数字無視を徹底
    prompt = f"「{item_name}」を【{options}】のどれか1つに分類して。数字や『円』が含まれていても無視して名称だけで判断し、カテゴリ名のみ答えて。"
    
    try:
        response = gemini_model.generate_content(prompt)
        result = response.text.strip()
        
        # 回答の中にカテゴリ名が含まれているかチェック
        for cat in CATEGORIES:
            if cat in result:
                return cat
                
        return "その他"
        
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return "その他"

DAILY_BUDGET = 2000 

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['x-line-signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    now = datetime.now()
    date_str = now.strftime('%Y/%m/%d %H:%M')

    if user_message == "節約":
        reply_text = f"💡 アドバイス：\n{random.choice(['自炊は最強！', 'マイボトルで節約！', 'コンビニ買いを我慢！'])}"
    elif user_message == "合計":
        try:
            gc = get_gspread_client()
            sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
            ws = sh.get_worksheet(0)
            prices = ws.col_values(3)[1:] # 3列目（金額）
            total = sum([int(str(p).replace(',', '')) for p in prices if str(p).replace(',', '').isdigit()])
            reply_text = f"💰 今月の合計：{total:,}円"
        except Exception as e:
            reply_text = f"❌ 集計エラー: {e}"
    elif " " in user_message or "　" in user_message:
        items = user_message.replace("　", " ").split(" ")
        if len(items) >= 2:
            # 品目名から余計なスペースを除去
            item_name = items[0].strip()
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "").strip()
            
            if raw_price.isdigit():
                item_price = int(raw_price)
                category = ask_gemini_category(item_name) # AI判定
                
                remaining = DAILY_BUDGET - item_price
                budget_msg = f"\n💰 残予算：{remaining:,}円" if remaining >= 0 else f"\n⚠️ オーバー：{abs(remaining):,}円"
                
                try:
                    gc = get_gspread_client()
                    sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
                    ws = sh.get_worksheet(0)
                    ws.append_row([date_str, item_name, item_price, category])
                    save_status = f"\n✅ 「{category}」で記録！"
                except Exception as e:
                    save_status = f"\n❌ 保存失敗: {e}"
                
                reply_text = f"【完了】\n品目：{item_name}\n金額：{item_price:,}円\n判定：{category}{budget_msg}{save_status}"
            else:
                reply_text = "金額は数字で送ってね！"
    else:
        reply_text = "「スタバ 600」のように送ってね！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
