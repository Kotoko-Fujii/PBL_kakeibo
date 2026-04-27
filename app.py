import os
import random  # アドバイス選択用
from flask import Flask, request, abort
from datetime import datetime
from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage)

app = Flask(__name__)

# 環境変数（Renderの設定画面で入れたもの）
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

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

    # --- 1. 節約アドバイス機能 ---
    if user_message == "節約":
        advices = [
            "自炊は最強の節約術だよ！🍚",
            "コンビニのついで買いを我慢してみよう！",
            "マイボトルを持ち歩くだけで1日150円浮くよ！🥤",
            "「本当に必要？」と3回自分に問いかけてみて。",
            "固定費の見直しが一番効果的だよ！",
            "買う前に、メルカリで相場をチェックしてみるのもアリ！"
        ]
        reply_text = f"💡 節約アドバイス：\n{random.choice(advices)}"

    # --- 2. 給料日カウントダウン機能 ---
    elif user_message == "給料日":
        pay_day = 25  # 毎月25日と設定（自由に変えてOK）
        if now.day < pay_day:
            days_left = pay_day - now.day
            reply_text = f"給料日まであと【{days_left}日】！\n最後まで踏ん張ろう！🔥"
        elif now.day == pay_day:
            reply_text = "今日は給料日だ！お疲れ様！\nでも使いすぎには注意してね。💰"
        else:
            reply_text = "今月の給料日はもう過ぎたよ！\n来月に向けて計画的にね。"

    # --- 3. メインの家計簿入力ロジック ---
    elif " " in user_message or "　" in user_message:
        items = user_message.replace("　", " ").split(" ")
        
        if len(items) >= 2:
            item_name = items[0]
            # 数字のクリーニング（円やコンマを除去）
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "")
            
            if raw_price.isdigit():
                item_price = int(raw_price)
                
                # カテゴリ判定
                category = "その他"
                food_words = ["食", "肉", "米", "ランチ", "カフェ", "スタバ", "マック", "パン", "コンビニ"]
                living_words = ["洗剤", "シャンプー", "薬", "ダイソー", "ニトリ", "セリア"]
                for word in food_words:
                    if word in item_name: category = "食費"
                for word in living_words:
                    if word in item_name: category = "日用品"

                # 予算オーバー警告（3,000円以上に設定）
                warning_msg = ""
                if item_price >= 3000:
                    warning_msg = "\n\n⚠️ 3,000円超え！予算に注意して！"

                # ゾロ目判定（777円など）
                lucky_msg = ""
                price_str = str(item_price)
                if len(price_str) >= 3 and len(set(price_str)) == 1:
                    lucky_msg = "\n✨ おっ、ゾロ目だ！いいことあるかも！"

                reply_text = (
                    f"【記録予約】\n"
                    f"日時：{date_str}\n"
                    f"品目：{item_name}\n"
                    f"金額：{item_price:,}円\n"
                    f"カテゴリ：{category}"
                    f"{warning_msg}{lucky_msg}"
                )
            else:
                reply_text = f"金額は「数字」で教えてね！"
        else:
            reply_text = "「品目 金額」の間にスペースを入れてね！"

    # --- 4. それ以外のメッセージ ---
    else:
        reply_text = f"「{user_message}」ですね！\n「節約」や「給料日」と送るか、「品目 金額」で入力してみてね。"

    # お返事を送信
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
