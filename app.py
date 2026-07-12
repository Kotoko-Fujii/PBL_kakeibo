import os
import random
import json
import re
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
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if 'flash' in m.name:
                    return genai.GenerativeModel(m.name)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                return genai.GenerativeModel(m.name)
    except Exception as e:
        print(f"Model List Error: {e}")
    return genai.GenerativeModel("gemini-1.5-flash")

gemini_model = get_available_gemini_model()
CATEGORIES = ["食費", "日用品", "交通費", "娯楽", "美容・衣服", "交際費", "その他"]

# --- スプレッドシート認証 ---
def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)



# ★【新規】ユーザー専用の「お買い物リスト」タブを取得または作成
def get_or_create_list_sheet(sh, user_id):
    list_title = f"リスト_{user_id}"
    try:
        return sh.worksheet(list_title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=list_title, rows=100, cols=2)
        ws.append_row(["追加日時", "品目"])
        return ws
# ユーザー専用の家計簿タブを取得または作成
def get_or_create_user_sheet(sh, user_id):
    try:
        return sh.worksheet(user_id)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=user_id, rows=1000, cols=10)
        # E列に「当時の予算」を追加
        ws.append_row(["日時", "品目", "金額", "カテゴリ", "当時の予算"])
        # カスタムカテゴリ設定用（I列・J列）
        ws.update_acell('I1', 'カスタム単語')
        ws.update_acell('J1', '指定カテゴリ')
        return ws

# ユーザーシート（ws）のG1セルで予算を管理する ---

def get_budget(ws):
    try:
        val = ws.acell('G1').value
        # まだG1セルに予算が書かれていない場合の初期設定
        if not val:
            ws.update_acell('F1', '毎日の予算')
            ws.update_acell('G1', '2000')
            return 2000
        return int(str(val).replace(',', ''))
    except:
        return 2000

def set_budget(ws, amount):
    ws.update_acell('F1', '毎日の予算')
    ws.update_acell('G1', str(amount))

def get_today_spent(ws, today_str):
    try:
        all_values = ws.get_all_values()
        records = all_values[1:]
        
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

# --- カスタムカテゴリルール用関数 ---
def get_custom_categories(ws):
    try:
        keywords = ws.col_values(9)[1:] # I列
        categories = ws.col_values(10)[1:] # J列
        custom_rules = {}
        for k, c in zip(keywords, categories):
            if k and c:
                custom_rules[k] = c
        return custom_rules
    except:
        return {}

def add_custom_category(ws, keyword, category):
    keywords = ws.col_values(9)
    next_row = len(keywords) + 1
    ws.update_acell(f'I{next_row}', keyword)
    ws.update_acell(f'J{next_row}', category)

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
    user_id = event.source.user_id

    now = datetime.now()
    date_str = now.strftime('%Y/%m/%d %H:%M')
    today_str = now.strftime('%Y/%m/%d')

    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
        ws = get_or_create_user_sheet(sh, user_id)
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"スプレッドシート接続エラー: {e}"))
        return

    reply_text = ""

    # 1. メニュー・ボタン機能の判定
   if user_message == "予算":
        current_budget = get_budget(ws)
        reply_text = f"現在の「毎日の予算」は {current_budget:,}円 です。\n変更する場合は、「予算 3000」のように送ってね！💰"
        
    elif user_message.startswith("予算 "):
        try:
            parts = user_message.split(" ")
            if len(parts) >= 2:
                new_budget_str = parts[1].replace(",", "").replace("円", "")
                if new_budget_str.isdigit():
                    set_budget(ws, int(new_budget_str))
                    reply_text = f"✅ 毎日の予算を {int(new_budget_str):,}円 に設定しました！"
                else:
                    reply_text = "予算の金額は数字で教えてね！"
            else:
                reply_text = "「予算 3000」のように送ってね！"
        except:
            reply_text = "設定に失敗しました。"

    elif user_message == "取り消し":
        try:
            all_records = ws.get_all_values()
            data_records = all_records[1:]
            
            if len(data_records) > 0:
                recent = data_records[-10:]
                recent.reverse()
                msg_lines = ["どれを取り消しますか？番号（1〜10）を送ってね！🗑️\n"]
                for i, r in enumerate(recent):
                    if len(r) >= 3:
                        time_part = r[0].split(' ')[1] if ' ' in r[0] else r[0]
                        msg_lines.append(f"{i+1}: {time_part} - {r[1]} {r[2]}円")
                reply_text = "\n".join(msg_lines)
            else:
                reply_text = "取り消せる記録がないよ！"
        except Exception as e:
            reply_text = f"エラーが発生しました: {e}"

    elif user_message.isdigit() and 1 <= int(user_message) <= 10:
        try:
            all_records = ws.get_all_values()
            data_records = all_records[1:]
            delete_num = int(user_message)
            
            if delete_num <= len(data_records):
                target_idx = len(all_records) - delete_num + 1 
                deleted_row = all_records[target_idx - 1]
                
                ws.delete_rows(target_idx)
                reply_text = f"🗑️ 「{deleted_row[1]} ({deleted_row[2]}円)」の記録を取り消しました！"
            else:
                reply_text = "その番号の記録は見つからないよ！"
        except Exception as e:
            reply_text = f"取り消し失敗: {e}"

    elif user_message == "リマインド":
        reply_text = "🔔 消耗品のリマインドは毎日夜10時に自動で届くよ！\nシャンプー、歯ブラシ、洗剤、スポンジの購入間隔をシステムが監視中だよ👀"

    # ★【新規】お買い物リストの確認（リッチメニューのボタン対応）
    elif user_message == "お買い物リスト":
        try:
            list_ws = get_or_create_list_sheet(sh, user_id)
            records = list_ws.get_all_values()[1:]
            if records:
                msg_lines = ["📝 今のお買い物リストだよ！\n"]
                for i, r in enumerate(records):
                    if len(r) >= 2:
                        msg_lines.append(f"{i+1}. {r[1]}")
                reply_text = "\n".join(msg_lines)
            else:
                reply_text = "📝 今のお買い物リストは空っぽだよ！\n「買う 洗剤」のように送って追加してね✨"
        except Exception as e:
            reply_text = f"リストの取得に失敗したよ: {e}"

    # ★【新規】お買い物リストへの追加
    elif user_message.startswith("買う ") or user_message.startswith("メモ "):
        try:
            parts = user_message.split(" ", 1)
            if len(parts) >= 2:
                item_name = parts[1].strip()
                list_ws = get_or_create_list_sheet(sh, user_id)
                list_ws.append_row([date_str, item_name])
                reply_text = f"📝 お買い物リストに「{item_name}」を追加したよ！\n確認するときはメニューのボタンを押してね。"
            else:
                reply_text = "「買う 洗剤」のように、スペースを空けて品目を教えてね！"
        except Exception as e:
            reply_text = f"リストへの追加に失敗したよ: {e}"

 # === (前略: 予算や取り消しの処理) ===

    # 「カテゴリ設定」ボタンを押した時の説明
    elif user_message == "カテゴリ設定":
        reply_text = "【カテゴリ設定】\n特定の単語を好きなカテゴリに固定できます！\n\n「カテゴリ設定 スタバ 食費」\n\nのように送ってね！💡\n設定できるカテゴリ: " + "、".join(CATEGORIES)

    # 実際のカテゴリ設定処理
    elif user_message.startswith("カテゴリ設定 "):
        try:
            parts = user_message.split(" ")
            if len(parts) >= 3:
                keyword = parts[1].strip()
                category = parts[2].strip()
                
                if category in CATEGORIES:
                    add_custom_category(ws, keyword, category)
                    reply_text = f"✅ 「{keyword}」を「{category}」に設定しました！\n次から自動分類されます✨"
                else:
                    reply_text = f"❌ カテゴリは以下のいずれかを指定してね！\n{', '.join(CATEGORIES)}"
            else:
                reply_text = "「カテゴリ設定 [単語] [カテゴリ]」の形式で送ってね！\n例: カテゴリ設定 タバコ 娯楽"
        except Exception as e:
            reply_text = f"❌ 設定に失敗しました: {e}"

  

    elif user_message == "節約":
        reply_text = f"💡 アドバイス：\n{random.choice(['自炊は最強！', 'マイボトルで節約！', 'コンビニ買いを我慢！'])}"
        
    elif user_message == "合計":
        try:
            prices = ws.col_values(3)[1:]
            total = sum([int(str(p).replace(',', '')) for p in prices if str(p).replace(',', '').isdigit()])
            reply_text = f"💰 今月の合計支出：{total:,}円"
        except Exception as e:
            reply_text = f"❌ 集計エラー: {e}"

    # 2. 家計簿の入力機能（品目 金額）＆ ★【新規】自動チェックオフ
    elif " " in user_message:
        items = [i for i in user_message.split(" ") if i]
        if len(items) >= 2:
            item_name = items[0].strip()
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "").strip()
            
            if raw_price.isdigit():
                item_price = int(raw_price)
              # --- カスタムルールを優先 ---
                category = None
                custom_rules = get_custom_categories(ws)
                for k, c in custom_rules.items():
                    if k in item_name:
                        category = c
                        break
                
                # ルールになければAI判定
                if not category:
                    category = ask_gemini_category(item_name)
                # ---------------------------------------------
                
                try:
                    budget = get_budget(ws)
                    today_spent = get_today_spent(ws, today_str)
                    
                   # ★E列に当時の予算も記録するよう修正
                    ws.append_row([date_str, item_name, item_price, category, budget], table_range="A:E")
                    
                    new_today_spent = today_spent + item_price
                    
                    remaining = budget - new_today_spent
                    
                    budget_msg = f"\n💰 今日の残予算：{remaining:,}円" if remaining >= 0 else f"\n⚠️ 今日の予算オーバー：{abs(remaining):,}円"
                    
                    # ★【新規】リストからの自動削除ロジック
                    deleted_msg = ""
                    try:
                        list_ws = get_or_create_list_sheet(sh, user_id)
                        list_records = list_ws.get_all_values()
                        # 下（最新）から順番に探して、一致したら行ごと削除
                        for i in range(len(list_records) - 1, 0, -1):
                            if len(list_records[i]) >= 2 and list_records[i][1] == item_name:
                                list_ws.delete_rows(i + 1)
                                deleted_msg = f"\n✨ 買えたんだね！リストから「{item_name}」を消しておいたよ！"
                                break
                    except Exception as e:
                        print(f"リスト自動削除エラー: {e}") # メイン処理を止めないように裏側でエラーログだけ出す

                    reply_text = f"【完了】\n品目：{item_name}\n金額：{item_price:,}円\n✅ 「{category}」で記録！{deleted_msg}{budget_msg}"
                except Exception as e:
                    reply_text = f"❌ 保存失敗: {e}"
            else:
                reply_text = "金額は数字で送ってね！"
        else:
            reply_text = "「品目 金額」で送ってね！"
    else:
        reply_text = "メニューから選ぶか、「品目 金額」のように送ってね！"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# =====================================================================
# ★【新規追加】毎朝の自動通知機能
# =====================================================================
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

def send_morning_reminder():
    try:
        line_bot_api.broadcast(TextSendMessage(text="☀️ 今日も家計簿を登録しよう！💰"))
        print("朝の通知メッセージを正常に配信しました。")
    except Exception as e:
        print(f"朝の通知配信でエラーが発生しました: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(
    send_morning_reminder, 
    'cron', 
    hour=8, 
    minute=0, 
    timezone=pytz.timezone('Asia/Tokyo')
)
scheduler.start()
# =====================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
