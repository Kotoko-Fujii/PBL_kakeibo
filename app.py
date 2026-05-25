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

# --- 環境設定 ---
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# Geminiの設定
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# スプレッドシートの認証設定
def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

# AIにカテゴリを判定してもらう関数
def ask_gemini_category(item_name):
    prompt = f"""
    あなたは家計簿管理のアシスタントです。
    「{item_name}」という品目を、以下のカテゴリのいずれか1つに分類してください。
    
    【カテゴリ一覧】
    食費、日用品、娯楽、交通費、美容・衣服、その他
    
    回答はカテゴリ名（例：食費）のみを返し、余計な説明は一切しないでください。
    """
    try:
        response = gemini_model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "その他"

# 1日の予算
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

    # 2. 給料日
    elif user_message == "給料日":
        pay_day = 25
        days_left = pay_day - now.day if now.day < pay_day else "完了"
        reply_text = f"給料日まであと【{days_left}日】！" if isinstance(days_left, int) else "今月の給料日は過ぎたよ！"

    # 3. 合計金額の確認
    elif user_message == "合計":
        try:
            gc = get_gspread_client()
            sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
            worksheet = sh.get_worksheet(0)
            prices = worksheet.col_values(3)[1:] 
            total = sum([int(p.replace(',', '')) for p in prices if p.replace(',', '').isdigit()])
            reply_text = f"💰 今月の合計支出は {total:,}円 だよ！"
        except Exception as e:
            reply_text = f"❌ 合計の計算でエラーが出たよ: {e}"

    # 4. 家計簿入力（スペース区切りのメッセージ）
    elif " " in user_message or " " in user_message:
        items = user_message.replace(" ", " ").split(" ")
        if len(items) >= 2:
            item_name = items[0]
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "")
            
            if raw_price.isdigit():
                item_price = int(raw_price)
                
                # --- AIによるカテゴリ判定 ---
                category = ask_gemini_category(item_name)

                # 残予算計算
                remaining = DAILY_BUDGET - item_price
                budget_msg = f"\n💰 今日の残り予算：あと {remaining:,}円" if remaining >= 0 else f"\n⚠️ 予算オーバー！ {abs(remaining):,}円 使いすぎだよ"

                # スプシへの書き込み
                try:
                    gc = get_gspread_client()
                    sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
                    worksheet = sh.get_worksheet(0)
                    worksheet.append_row([date_str, item_name, item_price, category])
                    save_status = f"\n✅ 「{category}」として記録したよ！"
                except Exception as e:
                    save_status = f"\n❌ スプシ保存エラー: {e}"

                reply_text = (
                    f"【入力完了】\n"
                    f"日時：{date_str}\n"
                    f"品目：{item_name}\n"
                    f"金額：{item_price:,}円\n"
                    f"判定カテゴリ：{category}"
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
    app.run(host="0.0.0.0", port=port)
