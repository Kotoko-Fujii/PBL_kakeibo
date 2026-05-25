import os
import random
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request, abort
from datetime import datetime
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)

app = Flask(__name__)

# LINEの環境変数
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

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

    # 3. 【追加】合計金額の計算
    elif user_message == "合計":
        try:
            gc = get_gspread_client()
            sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
            worksheet = sh.get_worksheet(0)
            # 3列目（金額）をすべて取得
            prices = worksheet.col_values(3)[1:] 
            total = sum([int(p.replace(',', '')) for p in prices if p.replace(',', '').isdigit()])
            reply_text = f"💰 今月の合計支出は {total:,}円 だよ！"
        except Exception as e:
            reply_text = f"❌ 合計の計算でエラーが出たよ: {e}"

    # 4. 家計簿の記録（スペースが含まれる場合）
    elif " " in user_message or " " in user_message:
        items = user_message.replace(" ", " ").split(" ")
        if len(items) >= 2:
            item_name = items[0]
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "")
            
            if raw_price.isdigit():
                item_price = int(raw_price)
                category = "その他"
                if any(w in item_name for w in ["食", "肉", "ランチ", "スタバ"]): category = "食費"
                if any(w in item_name for w in ["薬", "洗剤", "ダイソー"]): category = "日用品"

                remaining = DAILY_BUDGET - item_price
                budget_msg = f"\n💰 今日の残り予算：あと {remaining:,}円" if remaining >= 0 else f"\n⚠️ 予算オーバー！ {abs(remaining):,}円 使いすぎだよ"

                try:
                    gc = get_gspread_client()
                    sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
                    worksheet = sh.get_worksheet(0)
                    worksheet.append_row([date_str, item_name, item_price, category])
                    save_status = "\n✅ スプレッドシートに記録したよ！"
                except Exception as e:
                    save_status = f"\n❌ スプシ保存エラー: {e}"

                reply_text = (
                    f"【入力完了】\n"
                    f"日時：{date_str}\n"
                    f"品目：{item_name}\n"
                    f"金額：{item_price:,}円\n"
                    f"カテゴリ：{category}"
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
