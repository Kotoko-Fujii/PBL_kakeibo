import os
import json
import gspread
from datetime import datetime, timedelta # ★ timedelta を追加！
from collections import defaultdict
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi
from linebot.models import TextSendMessage
import google.generativeai as genai

# --- 1. LINEとGeminiの設定 ---
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

def get_gspread_client():
    key_json = json.loads(os.getenv('GCP_SERVICE_ACCOUNT_KEY'))
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_json, scope)
    return gspread.authorize(creds)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
try:
    gemini_model = genai.GenerativeModel("gemini-2.5-flash")
except:
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# ★Renderの時差対策：強制的に日本時間（JST）を取得する関数
def get_jst_now():
    return datetime.utcnow() + timedelta(hours=9)

# --- 2. データ集計と特徴量抽出ロジック ---
def analyze_purchase_cycles(records):
    today = get_jst_now() # ★ ここを datetime.now() から get_jst_now() に変更！
    purchase_dates = defaultdict(list)
    
    for r in records:
        if len(r) >= 2:
            try:
                date_str = r[0].split(' ')[0]
                dt = datetime.strptime(date_str, '%Y/%m/%d')
                item_name = r[1].strip()
                purchase_dates[item_name].append(dt)
            except:
                continue

    alerts = []
    for item, dates in purchase_dates.items():
        dates.sort()
        if len(dates) >= 2:
            intervals = []
            for i in range(1, len(dates)):
                delta = (dates[i] - dates[i-1]).days
                if delta > 0:
                    intervals.append(delta)
            
            if not intervals:
                continue
                
            avg_cycle = sum(intervals) / len(intervals)
            last_date = dates[-1]
            days_passed = (today - last_date).days
            
            if avg_cycle > 0 and days_passed >= (avg_cycle * 0.9):
                alerts.append({
                    "item": item,
                    "cycle": round(avg_cycle),
                    "passed": days_passed
                })
    return alerts

# --- 3. メイン処理（マルチテナント対応版） ---
def main():
    print("🚀 リマインダー処理を開始します...")
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(os.getenv('SPREADSHEET_ID'))
        
        # スプレッドシート内のすべてのタブ（ワークシート）を取得
        worksheets = sh.worksheets()
        today_str = get_jst_now().strftime('%Y/%m/%d') # ★ ここも get_jst_now() に変更！
        print(f"📅 今日の日付(JST): {today_str}")
        
        # 各ユーザー（タブ）ごとに処理を繰り返す
        for ws in worksheets:
            ws_title = ws.title
            
            # ★「設定」タブ、「リスト_」から始まるタブ、Uから始まらないタブは無視する
            if not ws_title.startswith("U") or "リスト" in ws_title:
                continue
            
            # タブの名前＝送信先のLINEユーザーID
            target_user_id = ws_title.strip()
            print(f"👤 送信対象のLINE IDを発見: {target_user_id}")
            
            records = ws.get_all_values()[1:] # ヘッダーを飛ばす
            
            has_input_today = any(r[0].startswith(today_str) for r in records if len(r) > 0)
            alerts = analyze_purchase_cycles(records)
            
            final_message = ""
            
            # --- 4. メッセージ生成（Gemini担当） ---
            if alerts:
                alerts_str = "\n".join([f"・{a['item']} (平均{a['cycle']}日周期 / 現在{a['passed']}日経過)" for a in alerts])
                
                prompt = f"""
                あなたは優秀で親しみやすいパーソナルアシスタントです。
                以下のデータは、ユーザーがそろそろ買い替えやリピート時期を迎える品目のリストです。
                
                【アラート候補】
                {alerts_str}
                
                これをもとに、夜10時にLINEで送る、自然で優しいリマインドメッセージを150字程度で作成してください。
                今日の家計簿の入力確認（入力が終わっていなければ促す、終わっていれば労う）も含めてください。
                今日は入力済みか？：{'はい（労って）' if has_input_today else 'いいえ（入力を促して）'}
                
                注意：機械的な箇条書きは避け、まるで友達のように1つの自然なメッセージとして話しかけてください。
                """
                
                response = gemini_model.generate_content(prompt)
                final_message = response.text.strip()
                
            else:
                if not has_input_today:
                    final_message = "🌙 夜10時だよ！今日の家計簿の入力は忘れてない？\n「品目 金額」で送ってね！"
                else:
                    final_message = "🌙 夜10時の定期連絡だよ！今日も家計簿の記録ありがとう！ゆっくり休んでね✨"
            
            # そのタブの持ち主（ユーザーID）に直接送信
            try:
                line_bot_api.push_message(target_user_id, TextSendMessage(text=final_message))
                print(f"✅ {target_user_id} に送信成功しました。")
            except Exception as push_e:
                print(f"❌ {target_user_id} への送信に失敗: {push_e}")
                
    except Exception as e:
        print(f"❌ リマインダー全体の実行エラー: {e}")

if __name__ == "__main__":
    main()
