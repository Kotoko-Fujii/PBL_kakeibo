import os
from flask import Flask, request, abort
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

# 環境変数からトークンを取得（Renderの設定画面で入れたもの）
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
    # ユーザーが送ってきたメッセージ
    user_message = event.message.text
    
    # 1. ヘルプ機能
    if user_message == "ヘルプ":
        reply_text = "【使い方】\n「お菓子 200」のように「品目 金額」の順で送ってね！\n\n「合計」と送ると今の支出がわかるよ（開発中）。"
    
    # 2. 合計確認機能（ロジックの枠組みだけ作成）
    elif user_message == "合計":
        reply_text = "現在、スプレッドシートとの連携機能を準備中です！もう少し待ってね。"

    # 3. 家計簿入力ロジック
    elif " " in user_message or "　" in user_message:
        # 半角または全角スペースで分割
        items = user_message.replace("　", " ").split(" ")
        
        if len(items) >= 2:
            item_name = items[0]
            item_price = items[1]
            
            # 数字かどうかをチェックするバリデーション（ロジック担当の腕の見せ所！）
            if item_price.isdigit():
                reply_text = f"【記録予約】\n品目：{item_name}\n金額：{item_price}円\n\n次はこれをスプレッドシートに保存できるようにしよう！"
            else:
                reply_text = f"金額は「数字」で入れてね！\n（入力されたもの：{item_price}）"
        else:
            reply_text = "「品目 金額」の間にスペースを入れてね！"

    # 4. それ以外のメッセージ
    else:
        reply_text = f"「{user_message}」ですね！\n支出を記録したい時は「品目 金額」で送ってね。"

    # お返事を送信
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
