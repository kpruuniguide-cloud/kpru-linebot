import os
import pymysql
from flask import Flask, request
from linebot.v3.webhook import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# ================== CONFIGURATION (ดึงค่าจาก Environment Variables) ==================
DB_CONFIG = {
    "host": os.environ.get('DB_HOST'),
    "port": int(os.environ.get('DB_PORT', 18524)),
    "user": os.environ.get('DB_USER'),
    "password": os.environ.get('DB_PASS'),
    "database": os.environ.get('DB_NAME'),
    "cursorclass": pymysql.cursors.DictCursor,
    "ssl": {"ssl_ca": None}  # จำเป็นสำหรับ Aiven MySQL
}

# ใส่ค่า Access Token และ Secret ของเบิร์ด (หรือตั้งใน Render Environment ก็ได้)
handler = WebhookHandler(os.environ.get('CHANNEL_SECRET', '33602e4eb27429c3b1571b6912cd1cf7'))
configuration = Configuration(access_token=os.environ.get('CHANNEL_ACCESS_TOKEN', 'ytBS3PNYaD0Tm9Q8YjwSltuf4Y4T+nWEJxh9f6CGSf2A6g7XJx0MdH9NsL88JbluYfKocFKKqpzlVN8TYENDLdgcjrwnGTP4aUVI0Tb+XEq+f4cbvnPNc7CC9m3N5OK5HiGyf2BACcddBWkkFwRAfwdB04t89/1O/w1cDnyilFU='))

# ================== AUTO-SETUP DATABASE (ด่านตรวจฐานข้อมูล) ==================
def init_db():
    """ฟังก์ชันสร้างตาราง 'locations' ให้อัตโนมัติถ้ายังไม่มีใน Aiven Cloud"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            # ตรวจสอบว่ามีตารางชื่อ locations หรือยัง
            cursor.execute("SHOW TABLES LIKE 'locations'")
            if not cursor.fetchone():
                print("⚠️ ฐานข้อมูลว่างเปล่า! กำลังสร้างตารางและลงข้อมูลทดสอบ...")
                # สร้างตาราง locations ตามโครงสร้างในไฟล์ SQL ของเบิร์ด
                cursor.execute("""
                    CREATE TABLE `locations` (
                      `location_id` int(11) NOT NULL AUTO_INCREMENT,
                      `building_no` varchar(10) DEFAULT NULL,
                      `official_name` varchar(255) NOT NULL,
                      `common_name` text DEFAULT NULL,
                      `location_type` varchar(50) NOT NULL,
                      `latitude` decimal(10,7) NOT NULL,
                      `longitude` decimal(10,7) NOT NULL,
                      `description` text DEFAULT NULL,
                      `image_url` varchar(255) DEFAULT NULL,
                      PRIMARY KEY (`location_id`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)
                # ใส่ข้อมูลตึก 14 (ตึกอธิการ) เป็นข้อมูลเริ่มต้นเพื่อทดสอบการเชื่อมต่อ
                cursor.execute("""
                    INSERT INTO `locations` (building_no, official_name, common_name, location_type, latitude, longitude, description)
                    VALUES ('14', 'อาคารเรียนรวม และอำนวยการ', 'ตึกอธิการบดี, ตึก 14, ตึกอธิการ', 'Building', 16.4537572, 99.5158255, 'สำนักงานอธิการบดีและศูนย์กลางบริหารงาน มรภ.กำแพงเพชร')
                """)
                conn.commit()
                print("✅ สร้างฐานข้อมูลบน Cloud สำเร็จแล้ว!")
        conn.close()
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดตอนตั้งค่า DB: {e}")

# รันฟังก์ชันสร้างตารางทันทีที่เริ่มแอป
init_db()

# ================== LINE BOT LOGIC ==================
def get_building_data(keyword):
    """ฟังก์ชันค้นหาข้อมูลตึกจาก Aiven Cloud"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM locations WHERE building_no = %s OR common_name LIKE %s OR official_name LIKE %s LIMIT 1"
            cursor.execute(sql, (keyword, f"%{keyword}%", f"%{keyword}%"))
            return cursor.fetchone()
    except Exception as e:
        print(f"❌ DB Query Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

def create_flex_message(data):
    """ฟังก์ชันสร้างหน้าตา Flex Message สวยๆ"""
    # กำหนดรูปภาพเริ่มต้นถ้าไม่มีในฐานข้อมูล
    img_url = data.get("image_url") or "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    return {
        "type": "bubble",
        "hero": {
            "type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"
        },
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"📍 อาคาร {data['building_no']}", "weight": "bold", "size": "xl"},
                {"type": "text", "text": data['official_name'], "size": "sm", "color": "#666666", "wrap": True},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": data['description'] or "ไม่มีรายละเอียดเพิ่มเติม", "wrap": True, "size": "sm", "margin": "md"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri", "label": "เปิดแผนที่ (Google Maps)",
                        "uri": f"https://www.google.com/maps?q={data['latitude']},{data['longitude']}"
                    },
                    "style": "primary", "color": "#0056b3"
                }
            ]
        }
    }

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    handler.handle(body, signature)
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg = event.message.text
    
    # ค้นหาข้อมูลจาก Cloud
    building = get_building_data(user_msg)
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        if building:
            flex_msg = create_flex_message(building)
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(alt_text=f"ข้อมูล {user_msg}", contents=FlexContainer.from_dict(flex_msg))]
            ))
        else:
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"ขอโทษครับเบิร์ด ไม่พบข้อมูล '{user_msg}' ลองพิมพ์เลขตึกดูนะครับ เช่น 14")]
            ))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)