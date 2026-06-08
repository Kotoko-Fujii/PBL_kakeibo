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

# --- Gemini設定 ---
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def get_available_gemini_model():
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if 'flash' in m.name: return genai.GenerativeModel(m.name)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods: return genai.GenerativeModel(m.name)
    except Exception as e: print(f"Model List Error: {e}")
    return genai.GenerativeModel("gemini-1.5-flash")

gemini_model = get_available_gemini_model()

# --- カテゴリ定義 ---
CATEGORIES = ["食費", "日用品", "交通費", "娯楽", "美容・衣服", "交際費", "その他"]

# --- スプレッドシート認証 ---
def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

# --- AI判定関数 ---
def ask_gemini_category(item_name):
    options = "、".join(CATEGORIES)
    prompt = f"""
    あなたは家計簿のプロです。入力された単語を、以下の【カテゴリ】のいずれか1つに分類してください。
    【カテゴリ】{options}
    【判定ルール】
    - スーパー、外食、飲み物、コンビニ、スタバは「食費」
    - 洗剤、薬、ティッシュ、百均、ダイソーは「日用品」
    - 電車、バス、タクシー、ガソリン、Suicaは「交通費」
    - 映画、本、ゲーム、趣味の品は「娯楽」
    - 美容院、服、コスメは「美容・衣服」
    - 友人との食事、贈り物、お祝いは「交際費」
    - どれにも当てはまらない場合は「その他」
    【回答ルール】
    - 数字や「円」などの金額が含まれていても無視して、名称だけで判断してください。
    - 答えは「{options}」の中から【カテゴリ名のみ】を返してください。
    品目：{item_name}
    """
    try:
        response = gemini_model.generate_content(prompt)
        result = response.text.strip()
        for cat in CATEGORIES:
            if cat in result: return cat
        return f"その他（原因: {result}）"
    except Exception as e:
        return f"その他（エラー: {e}）"

DAILY_BUDGET = 2000 

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['x-line-signature']
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    now = datetime.now()
    date_str = now.strftime('%Y/%m/%d %H:%M')

    # --- [追加機能] リッチメニュー・取り消し・残高操作 ---
    if user_message == "節約":
        reply_text = f"💡 アドバイス：\n{random.choice(['自炊は最強！', 'マイボトルで節約！', 'コンビニ買いを我慢！'])}"
    elif user_message == "合計":
        try:
            gc = get_gspread_client()
            ws = gc.open_by_key(os.getenv('SPREADSHEET_ID')).get_worksheet(0)
            prices = ws.col_values(3)[1:]
            total = sum([int(str(p).replace(',', '')) for p in prices if str(p).replace(',', '').isdigit()])
            reply_text = f"💰 今月の合計：{total:,}円"
        except Exception as e: reply_text = f"❌ 集計エラー: {e}"
    elif user_message == "とりけし":
        try:
            gc = get_gspread_client()
            ws = gc.open_by_key(os.getenv('SPREADSHEET_ID')).get_worksheet(0)
            data = ws.get_all_values()
            if len(data) > 1:
                recent = data[-5:][::-1]
                reply_text = "どれを取り消す？番号で返信してね！\n" + "\n".join([f"{i+1}: {row[1]} {row[2]}円" for i, row in enumerate(recent)])
            else: reply_text = "削除できる記録がないよ！"
        except Exception as e: reply_text = f"❌ エラー: {e}"
    elif user_message.isdigit() and 1 <= int(user_message) <= 5:
        try:
            gc = get_gspread_client()
            ws = gc.open_by_key(os.getenv('SPREADSHEET_ID')).get_worksheet(0)
            data = ws.get_all_values()
            idx = len(data) - int(user_message)
            item_name = data[idx-1][1]
            ws.delete_rows(idx)
            reply_text = f"🗑️ {item_name} を削除したよ！"
        except Exception as e: reply_text = f"❌ 削除失敗: {e}"
    elif user_message == "残高":
        try:
            gc = get_gspread_client()
            ws = gc.open_by_key(os.getenv('SPREADSHEET_ID')).get_worksheet(0)
            data = ws.get_all_values()
            today_str = datetime.now().strftime('%Y/%m/%d')
            today_spent = sum([int(str(r[2]).replace(',', '')) for r in data[1:] if r[0].startswith(today_str)])
            reply_text = f"📅 今日の支出合計：{today_spent:,}円\n💰 残り予算：{DAILY_BUDGET - today_spent:,}円"
        except Exception as e: reply_text = f"❌ 集計エラー: {e}"
    elif user_message.startswith("【記録】"):
        reply_text = f"{user_message.replace('【記録】', '')} ですね！「品目 金額」で送ってね📝"

    # --- [既存ロジック] 家計簿入力判定 ---
    elif " " in user_message or " " in user_message:
        items = user_message.replace(" ", " ").split(" ")
        if len(items) >= 2:
            item_name = items[0].strip()
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "").strip()
            if raw_price.isdigit():
                item_price = int(raw_price)
                category = ask_gemini_category(item_name)
                
                remaining = DAILY_BUDGET - item_price
                budget_msg = f"\n💰 残予算：{remaining:,}円" if remaining >= 0 else f"\n⚠️ オーバー：{abs(remaining):,}円"
                
                try:
                    gc = get_gspread_client()
                    ws = gc.open_by_key(os.getenv('SPREADSHEET_ID')).get_worksheet(0)
                    ws.append_row([date_str, item_name, item_price, category])
                    save_status = f"\n✅ 「{category}」で記録！"
                except Exception as e: save_status = f"\n❌ 保存失敗: {e}"
                reply_text = f"【完了】\n品目：{item_name}\n金額：{item_price:,}円\n判定：{category}{budget_msg}{save_status}"
            else: reply_text = "金額は数字で送ってね！"
        else: reply_text = "「品目 金額」で送ってね！"
    else: reply_text = "メニューから選ぶか、「品目 金額」で入力してね！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
