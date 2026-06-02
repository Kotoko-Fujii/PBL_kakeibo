import os
from linebot import LineBotApi
from linebot.models import TextSendMessage

# 1. LINE APIの準備
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

# 2. あなたのユーザーIDを読み込む
user_id = os.getenv('USER_ID')

# 3. 送るメッセージを作成
message = TextSendMessage(text="夜10時だよ！今日の入力は忘れてない？🌙")

# 4. メッセージを送信（Push API）
try:
    line_bot_api.push_message(user_id, message)
    print("✅ リマインダーの送信に成功しました！")
except Exception as e:
    print(f"❌ 送信エラー: {e}")
