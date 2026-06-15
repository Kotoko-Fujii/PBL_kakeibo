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

def get_budget(sh):
    try:
        ws = get_or_create_settings_sheet(sh)
        val = ws.acell('B1').value
        return int(str(val).replace(',', '')) if val else 2000
    except:
        return 2000

def set_budget(sh, amount):
    ws = get_or_create_settings_sheet(sh)
    ws.update_acell('B1', str(amount))

def get_today_spent(ws, today_str):
    try:
        all_values = ws.get_all_values()
        records = all_values[1:]  # ヘッダーをスキップ
        
        if len(records) > 100:
            records = records[-100:]
            
        total = 0
        for r in records:
            if len(r) >= 3 and str(r[0]).startswith(today_str):
                price_str = str(r[2]).replace(',', '').replace('円', '')
                if price_str.isdigit():
                    total += int(price_str)
        return total
    except:
        return 0

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
    - 答えは必ず「{options}」の中から【カテゴリ名のみ】を厳密に返してください。余計な解説は不要です。
    品目：{item_name}
    """
    try:
        response = gemini_model.generate_content(
            prompt,
            generation_config={"temperature": 0.0}
        )
        result = response.text.strip()
        for cat in CATEGORIES:
            if cat in result:
                return cat
        return "その他"
    except Exception as e:
        return "その他"

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
    user_message = re.sub(r'\s+', ' ', event.message.text).strip()
    
    # ★【変更】送信者のLINEユーザーIDを取得
    user_id = event.source.user_id

    now = datetime.now()
    date_str = now.strftime('%Y/%m/%d %H:%M')
    today_str = now.strftime('%Y/%m/%d')

    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
        # ★【変更】一律で左端のシートを開くのではなく、ユーザー専用のタブを開く（無ければ自動生成）
        ws = get_or_create_user_sheet(sh, user_id)
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"スプレッドシート接続エラー: {e}"))
        return

    reply_text = ""

    # 1. メニュー・ボタン機能の判定
    if user_message == "予算":
        current_budget = get_budget(sh)
        reply_text = f"現在の「毎日の予算」は {current_budget:,}円 です。\n変更する場合は、「予算 3000」のように送ってね！💰"
        
    elif user_message.startswith("予算 "):
        try:
            parts = user_message.split(" ")
            if len(parts) >= 2:
                new_budget_str = parts[1].replace(",", "").replace("円", "")
                if new_budget_str.isdigit():
                    set_budget(sh, int(new_budget_str))
                    reply_text = f"✅ 毎日の予算を {int(new_budget_str):,}円 に設定しました！"
                else:
                    reply_text = "予算の金額は数字で教えてね！"
            else:
                reply_text = "「予算 3000」のように送ってね！"
        except:
            reply_text = "設定に失敗しました。"

    elif user_message == "取り消し":
        try:
            records = ws.get_all_values()
            if len(records) > 1:
                recent = records[-5:]
                recent.reverse()
                msg_lines = ["どれを取り消しますか？番号（1〜5）を送ってね！🗑️\n"]
                for i, r in enumerate(recent):
                    if len(r) >= 3:
                        time_part = r[0].split(' ')[1] if ' ' in r[0] else r[0]
                        msg_lines.append(f"{i+1}: {time_part} - {r[1]} {r[2]}円")
                reply_text = "\n".join(msg_lines)
            else:
                reply_text = "取り消せる記録がないよ！"
        except Exception as e:
            reply_text = f"エラーが発生しました: {e}"

    elif user_message.isdigit() and 1 <= int(user_message) <= 5:
        try:
            records = ws.get_all_values()
            delete_num = int(user_message)
            if len(records) >= delete_num + 1:
                target_idx = len(records) - delete_num + 1 
                deleted_row = records[target_idx - 1]
                ws.delete_rows(target_idx)
                reply_text = f"🗑️ 「{deleted_row[1]} ({deleted_row[2]}円)」の記録を取り消しました！"
            else:
                reply_text = "その番号の記録は見つからないよ！"
        except Exception as e:
            reply_text = f"取り消し失敗: {e}"

    elif user_message == "リマインド":
        reply_text = "🔔 消耗品のリマインドは毎日夜10時に自動で届くよ！\nシャンプー、歯ブラシ、洗剤、スポンジの購入間隔をシステムが監視中だよ👀"

    elif user_message in ["カテゴリ設定", "お買い物リスト"]:
        reply_text = f"「{user_message}」機能は現在準備中です！🛠️"

    elif user_message == "節約":
        reply_text = f"💡 アドバイス：\n{random.choice(['自炊は最強！', 'マイボトルで節約！', 'コンビニ買いを我慢！'])}"
        
    elif user_message == "合計":
        try:
            prices = ws.col_values(3)[1:] # 3列目（金額）
            total = sum([int(str(p).replace(',', '')) for p in prices if str(p).replace(',', '').isdigit()])
            reply_text = f"💰 今月の合計支出：{total:,}円"
        except Exception as e:
            reply_text = f"❌ 集計エラー: {e}"

    # 2. 家計簿の入力機能（品目 金額）
    elif " " in user_message:
        items = [i for i in user_message.split(" ") if i]
        if len(items) >= 2:
            item_name = items[0].strip()
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "").strip()
            
            if raw_price.isdigit():
                item_price = int(raw_price)
                category = ask_gemini_category(item_name) # AI判定
                
                try:
                    budget = get_budget(sh)
                    today_spent = get_today_spent(ws, today_str)
                    
                    # ユーザー専用のタブに追加される
                    ws.append_row([date_str, item_name, item_price, category])
                    
                    new_today_spent = today_spent + item_price
                    remaining = budget - new_today_spent
                    
                    budget_msg = f"\n💰 今日の残予算：{remaining:,}円" if remaining >= 0 else f"\n⚠️ 今日の予算オーバー：{abs(remaining):,}円"
                    reply_text = f"【完了】\n品目：{item_name}\n金額：{item_price:,}円\n✅ 「{category}」で記録！{budget_msg}"
                except Exception as e:
                    reply_text = f"❌ 保存失敗: {e}"
            else:
                reply_text = "金額は数字で送ってね！"
        else:
            reply_text = "「品目 金額」で送ってね！"
    else:
        reply_text = "メニューから選ぶか、「品目 金額」のように送ってね！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
