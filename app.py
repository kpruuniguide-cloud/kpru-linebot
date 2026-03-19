import os
import ssl
import httpx
from flask import Flask, request, send_from_directory

from linebot.v3.webhook import WebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    FlexMessage,
    FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import pymysql

# ================== DATABASE ==================
def get_building(keyword):
    # จุดที่ต้องแก้: ถ้าใช้ Cloud DB ให้เปลี่ยน localhost เป็น URL ของ DB นั้นๆ
    conn = pymysql.connect(
        host=os.environ.get('DB_HOST', 'localhost'),
        user=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASS', ''),
        database='kpru_uniguide',
        cursorclass=pymysql.cursors.DictCursor
    )
    with conn:
        with conn.cursor() as cursor:
            sql = """
            SELECT * FROM locations 
            WHERE building_no LIKE %s
            OR common_name LIKE %s
            OR official_name LIKE %s
            LIMIT 1
            """
            cursor.execute(sql, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"))
            return cursor.fetchone()

# ================== FLEX BUILDER ==================
def build_flex(result, img_url):
    try:
        lat = float(str(result.get("latitude", "")).strip())
        lon = float(str(result.get("longitude", "")).strip())
        map_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
    except:
        map_url = "https://www.google.com/maps"

    building_no = str(result.get("building_no", "-")).strip()
    official_name = str(result.get("official_name", "-")).strip()
    description = str(result.get("description", "-")).strip()

    return {
        "type": "bubble",
        "size": "mega",
        "hero": {
            "type": "image",
            "url": img_url if img_url else "https://via.placeholder.com/800x520",
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": f"อาคาร {building_no}", "weight": "bold", "size": "xl"},
                {"type": "text", "text": official_name, "size": "sm", "color": "#555555", "wrap": True},
                {"type": "separator"},
                {"type": "text", "text": "รายละเอียด", "weight": "bold", "size": "md"},
                {"type": "text", "text": description, "wrap": True, "size": "sm", "color": "#666666"}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "paddingAll": "12px",
                    "backgroundColor": "#6FA8C6",
                    "cornerRadius": "md",
                    "contents": [
                        {"type": "image", "url": "https://cdn-icons-png.flaticon.com/512/684/684908.png", "size": "xs", "flex": 0, "gravity": "center"},
                        {"type": "text", "text": "เปิดใน Google Maps", "color": "#FFFFFF", "weight": "bold", "margin": "md", "gravity": "center", "flex": 1}
                    ],
                    "action": {"type": "uri", "uri": map_url}
                }
            ]
        }
    }

# ================== APP SETTINGS ==================
app = Flask(__name__)

# ดึงค่าจาก Environment Variables เพื่อความปลอดภัย
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN', 'ytBS3PNYaD0Tm9Q8YjwSltuf4Y4T+nWEJxh9f6CGSf2A6g7XJx0MdH9NsL88JbluYfKocFKKqpzlVN8TYENDLdgcjrwnGTP4aUVI0Tb+XEq+f4cbvnPNc7CC9m3N5OK5HiGyf2BACcddBWkkFwRAfwdB04t89/1O/w1cDnyilFU=')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', '33602e4eb27429c3b1571b6912cd1cf7')

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

@app.route('/static/images/<path:filename>')
def serve_image(filename):
    return send_from_directory('static/images', filename)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print("ERROR:", e)
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text
    # 🔥 จุดสำคัญ: ใช้ request.host_url เพื่อสร้างลิงก์รูปภาพอัตโนมัติ (ไม่ต้องแก้ลิงก์ Tunnel อีกต่อไป)
    base_url = request.host_url.replace("http://", "https://")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        result = get_building(user_text)

        if result:
            img_url = result.get("image_url") or f"{base_url}static/images/{result['building_no']}.jpg"
            flex_content = build_flex(result, img_url)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[FlexMessage(alt_text="ข้อมูลสถานที่", contents=FlexContainer.from_dict(flex_content))]
                )
            )
        else:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="ไม่พบข้อมูลอาคารนี้ในระบบครับ ")]
                )
            )

# ================== RUN ==================
if __name__ == "__main__":
    # Render จะเป็นคนกำหนด Port ให้เองผ่านตัวแปร PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)