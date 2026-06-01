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

# --- Gemini設定 (404エラー対策済み) ---
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel("models/gemini-1.5-flash-latest")

# カテゴリ定義
CATEGORIES = ["食費", "日用品", "交通費", "娯楽", "美容・衣服", "交際費", "その他"]

def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

def ask_gemini_category(item_name):
    options = "、".join(CATEGORIES)
    # 【改良】AIに数字を無視するよう強く指示
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
        print(f"Gemini Error: {e}")
        return "その他"

DAILY_BUDGET = 2000 
#予算挿入
def get_daily_budget():
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
        ws = sh.get_worksheet(0)
        val = ws.acell('G1').value
        if val and str(val).isdigit():
            return int(val)
        else:
            ws.update_acell('G1', 2000)
            return 2000
    except Exception as e:
        print(f"予算取得エラー: {e}")
        return 2000

def update_daily_budget(new_budget):
    gc = get_gspread_client()
    sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
    ws = sh.get_worksheet(0)
    ws.update_acell('G1', new_budget)

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
    # 【手順②】スプレッドシートから現在の予算を読み込む
    daily_budget = get_daily_budget()

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
    elif user_message == "予算設定":
        reply_text = (
            f"⚙️ 予算設定\n"
            f"現在の1日の予算は【{daily_budget:,}円】です。\n\n"
            f"変更したい場合は、\n「予算 3000」のように\n『予算』の後にスペースを空けて数字を送ってね！"
        )

    elif user_message.startswith("予算 ") or user_message.startswith("予算　"):
        raw_price = user_message.replace("予算", "").replace("　", "").replace(" ", "").replace("円", "").replace(",", "").strip()
        if raw_price.isdigit():
            new_budget = int(raw_price)
            try:
                update_daily_budget(new_budget)
                reply_text = f"✅ 1日の予算を【{new_budget:,}円】に変更したよ！"
            except Exception as e:
                reply_text = f"❌ 予算の更新に失敗しました: {e}"
        else:
            reply_text = "予算の金額は数字で送ってね！\n（例：予算 3000）"
    elif " " in user_message or "　" in user_message:
        items = user_message.replace("　", " ").split(" ")
        if len(items) >= 2:
            # 【改良】品目名から余計なスペースを除去
            item_name = items[0].strip()
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "").strip()
            
            if raw_price.isdigit():
                item_price = int(raw_price)
                category = ask_gemini_category(item_name) # AI判定
                
                remaining = daily_budget - item_price
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
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
