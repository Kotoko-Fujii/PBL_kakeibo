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

# --- Geminiの初期設定（404エラー対策版） ---
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    # 最新の安定版モデル名を使用
    gemini_model = genai.GenerativeModel("gemini-1.5-flash-latest")
except Exception as e:
    print(f"Gemini Init Error: {e}")

# カテゴリの定義
CATEGORIES = ["食費", "日用品", "交通費", "娯楽", "美容・衣服", "交際費", "その他"]

# スプレッドシート認証
def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

# AIカテゴリ判定関数（マッチング強化版）
def ask_gemini_category(item_name):
    options = "、".join(CATEGORIES)
    prompt = f"""
    入力された品名を、以下のカテゴリのいずれか1つに分類してください。
    【選択肢】: {options}
    
    【ルール】:
    - 回答はカテゴリ名のみ。説明不要。
    - コンビニ、外食、スタバ、スーパー、飲み物は「食費」
    - 洗剤、百均、ドラッグストア、日用雑貨は「日用品」
    - 電車、バス、タクシー、ガソリンは「交通費」
    
    品目：{item_name}
    """
    try:
        response = gemini_model.generate_content(prompt)
        result = response.text.strip()
        
        # AIの回答の中にカテゴリ名が含まれているかチェック
        for cat in CATEGORIES:
            if cat in result:
                return cat
        return "その他"
    except Exception as e:
        print(f"Gemini API Error Detail: {e}")
        return "その他"

# 1日の予算（ロジック担当設定）
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

    # 1. 節約アドバイス
    if user_message == "節約":
        advices = ["自炊は最強の節約！🍚", "マイボトルで毎日150円浮くよ🥤", "コンビニのついで買いを我慢！"]
        reply_text = f"💡 アドバイス：\n{random.choice(advices)}"

    # 2. 給料日カウント
    elif user_message == "給料日":
        pay_day = 25
        if now.day < pay_day:
            reply_text = f"給料日まであと【{pay_day - now.day}日】！"
        elif now.day == pay_day:
            reply_text = "今日は給料日だよ！💰"
        else:
            reply_text = "今月の給料日は過ぎたよ！"

    # 3. 今月の合計金額
    elif user_message == "合計":
        try:
            gc = get_gspread_client()
            sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
            worksheet = sh.get_worksheet(0)
            prices = worksheet.col_values(3)[1:]
            total = sum([int(str(p).replace(',', '')) for p in prices if str(p).replace(',', '').isdigit()])
            reply_text = f"💰 合計支出：{total:,}円"
        except Exception as e:
            reply_text = f"❌ 合計エラー: {e}"

    # 4. メイン入力
    elif " " in user_message or "　" in user_message:
        items = user_message.replace("　", " ").split(" ")
        if len(items) >= 2:
            item_name = items[0]
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "")
            
            if raw_price.isdigit():
                item_price = int(raw_price)
                category = ask_gemini_category(item_name) # AI判定

                remaining = DAILY_BUDGET - item_price
                budget_msg = f"\n💰 残予算：{remaining:,}円" if remaining >= 0 else f"\n⚠️ オーバー：{abs(remaining):,}円"

                try:
                    gc = get_gspread_client()
                    sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
                    worksheet = sh.get_worksheet(0)
                    worksheet.append_row([date_str, item_name, item_price, category])
                    save_status = f"\n✅ 「{category}」として記録したよ！"
                except Exception as e:
                    save_status = f"\n❌ 保存エラー: {e}"

                reply_text = (
                    f"【入力完了】\n"
                    f"品目：{item_name}\n"
                    f"金額：{item_price:,}円\n"
                    f"判定：{category}"
                    f"{budget_msg}{save_status}"
                )
            else:
                reply_text = "金額は数字で送ってね！"
        else:
            reply_text = "「品目 金額」で送ってね！"
    else:
        reply_text = f"「{user_message}」ですね！\n「品目 金額」で家計簿を記録するよ。"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
