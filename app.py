import os
from flask import Flask, request, abort
from datetime import datetime  # 日付取得用
from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
)

app = Flask(__name__)

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
    
    # --- ロジック担当のブラッシュアップ区間 ---
    
    # 1. 現在の日時を取得
    now = datetime.now()
    date_str = now.strftime('%Y/%m/%d %H:%M')

    if user_message == "ヘルプ":
        reply_text = "【使い方】\n「スタバ 600」のように送ってね！\n自動で日付とカテゴリを判定するよ。"
    
    elif user_message == "合計":
        reply_text = "スプレッドシート連携後に、今月の合計金額を表示できるようにします！"

    elif " " in user_message or "　" in user_message:
        # 全角スペースを半角に変換してから分割
        items = user_message.replace("　", " ").split(" ")
        
        if len(items) >= 2:
            item_name = items[0]
            # 金額に含まれる「円」や「,」を消して数字だけにする（クリーニング）
            raw_price = items[1].replace("円", "").replace(",", "").replace("￥", "")
            
            if raw_price.isdigit():
                item_price = int(raw_price)
                
                # 2. 簡単なカテゴリ判定ロジック
                category = "その他"
                food_words = ["食", "肉", "米", "ランチ", "カフェ", "スタバ", "マック"]
                living_words = ["洗剤", "シャンプー", "薬", "ダイソー"]
                
                for word in food_words:
                    if word in item_name:
                        category = "食費"
                for word in living_words:
                    if word in item_name:
                        category = "日用品"

                reply_text = (
                    f"【記録予約】\n"
                    f"日時：{date_str}\n"
                    f"品目：{item_name}\n"
                    f"金額：{item_price:,}円\n"
                    f"カテゴリ：{category}\n\n"
                    f"スプシ連携まであと少し！"
                )
            else:
                reply_text = f"金額は「数字」で教えてね！\n（入力：{items[1]}）"
        else:
            reply_text = "「品目 金額」の間にスペースを入れてね！"

    else:
        reply_text = f"「{user_message}」ですね！\n「品目 金額」で送ると家計簿に記録するよ。"

    # --- ロジック終了 ---

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
