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

# ================== CONFIGURATION ==================
DB_CONFIG = {
    "host": os.environ.get('DB_HOST'),
    "port": int(os.environ.get('DB_PORT', 18524)),
    "user": os.environ.get('DB_USER'),
    "password": os.environ.get('DB_PASS'),
    "database": os.environ.get('DB_NAME'),
    "cursorclass": pymysql.cursors.DictCursor,
    "ssl": {"ca": os.environ.get("DB_SSL_CA") or "/opt/render/project/src/ca.pem"}
}

GITHUB_IMAGE_BASE = "https://raw.githubusercontent.com/kpruuniguide-cloud/kpru-linebot/main/static/images/"

handler = WebhookHandler(os.environ.get('CHANNEL_SECRET', '33602e4eb27429c3b1571b6912cd1cf7'))
configuration = Configuration(access_token=os.environ.get('CHANNEL_ACCESS_TOKEN', 'ytBS3PNYaD0Tm9Q8YjwSltuf4Y4T+nWEJxh9f6CGSf2A6g7XJx0MdH9NsL88JbluYfKocFKKqpzlVN8TYENDLdgcjrwnGTP4aUVI0Tb+XEq+f4cbvnPNc7CC9m3N5OK5HiGyf2BACcddBWkkFwRAfwdB04t89/1O/w1cDnyilFU='))

# ================== DATABASE LOGIC ==================

def get_building_data(keyword):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM locations WHERE building_no = %s OR common_name LIKE %s OR official_name LIKE %s"
            cursor.execute(sql, (keyword, f"%{keyword}%", f"%{keyword}%"))
            return cursor.fetchall()
    except Exception as e:
        print(f"DB Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

def get_service_data(keyword):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM services WHERE service_name LIKE %s"
            cursor.execute(sql, (f"%{keyword}%",))
            return cursor.fetchone()
    except Exception:
        return None
    finally:
        if 'conn' in locals(): conn.close()

def get_building_by_id(building_id):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM locations WHERE location_id = %s", (building_id,))
            return cursor.fetchone()
    except Exception:
        return None
    finally:
        if 'conn' in locals(): conn.close()

# ================== FLEX MESSAGE BUILDERS ==================

def create_building_flex(data):
    img_url = f"{GITHUB_IMAGE_BASE}{data['image_url']}" if data.get("image_url") else "https://www.kpru.ac.th/th/images/logo-kpru.png"
    return {
        "type": "bubble",
        "styles": {"body": {"backgroundColor": "#F1E4D1"}, "footer": {"backgroundColor": "#F1E4D1"}},
        "hero": {"type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": data['official_name'], "weight": "bold", "size": "xl", "wrap": True, "color": "#162660"},
                {"type": "text", "text": f"ชื่อเรียก: {data['common_name']}", "size": "sm", "color": "#162660", "margin": "sm"},
                {"type": "text", "text": data.get('description', 'ไม่มีข้อมูลรายละเอียด'), "size": "sm", "color": "#666666", "wrap": True, "margin": "md"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#162660", "action": {"type": "uri", "label": "เปิดแผนที่นำทาง", "uri": f"https://www.google.com/maps/search/?api=1&query={data['latitude']},{data['longitude']}"}}
            ]
        }
    }

def create_service_flex(service, building):
    return {
        "type": "bubble",
        "styles": {"body": {"backgroundColor": "#F1E4D1"}, "footer": {"backgroundColor": "#F1E4D1"}},
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": service['service_name'], "weight": "bold", "size": "xl", "color": "#162660"},
                {"type": "text", "text": f"ตั้งอยู่ที่: {building['official_name'] if building else 'ไม่ระบุ'}", "size": "md", "margin": "md", "wrap": True},
                {"type": "text", "text": f"ชั้น: {service.get('floor', 'ไม่ระบุ')}", "size": "sm", "color": "#666666"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#162660", "action": {"type": "uri", "label": "ดูแผนที่อาคาร", "uri": f"https://www.google.com/maps/search/?api=1&query={building['latitude']},{building['longitude']}" if building else "#"}}
            ]
        }
    }

# ================== MAIN HANDLER ==================

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    handler.handle(body, signature)
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg = event.message.text.strip()
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        def send_building_response(buildings_list):
            bubbles = [create_building_flex(b) for b in buildings_list[:10]]
            carousel = {"type": "carousel", "contents": bubbles}
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(alt_text="ผลการค้นหาสถานที่", contents=FlexContainer.from_dict(carousel))]
            ))

        # --- 1. แผนที่มหาวิทยาลัย ---
        if user_msg == "Menu > แผนที่มหาวิทยาลัย":
            img_url = "https://raw.githubusercontent.com/kpruuniguide-cloud/kpru-linebot/main/static/images/kpru_map.jpg"
            flex_map = {
                "type": "bubble",
                "styles": {"body": {"backgroundColor": "#F1E4D1"}, "footer": {"backgroundColor": "#F1E4D1"}},
                "hero": {"type": "image", "url": img_url, "size": "full", "aspectRatio": "1:1", "aspectMode": "cover"},
                "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "แผนที่มหาวิทยาลัย KPRU", "weight": "bold", "size": "lg", "align": "center", "color": "#162660"}]},
                "footer": {"type": "box", "layout": "vertical", "contents": [{"type": "button", "style": "primary", "color": "#162660", "action": {"type": "uri", "label": "ดูแผนที่ความละเอียดสูง", "uri": img_url}}]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="แผนที่", contents=FlexContainer.from_dict(flex_map))]))
            return

        # --- 2. สถานที่สำคัญ/จุดพักผ่อน ---
        elif user_msg == "Menu > สถานที่สำคัญ/จุดพักผ่อน":
            flex_menu = {
                "type": "bubble",
                "styles": {"body": {"backgroundColor": "#F1E4D1"}},
                "body": {
                    "type": "box", "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "เลือกหมวดหมู่ที่ต้องการ", "weight": "bold", "size": "xl", "align": "center", "color": "#162660"},
                        {"type": "separator", "margin": "md", "color": "#162660"},
                        {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "สถานที่สำคัญ", "text": "ดูสถานที่สำคัญ"}},
                        {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "จุดพักผ่อน", "text": "ดูจุดพักผ่อน"}},
                        {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "ออกกำลังกาย", "text": "ดูที่ออกกำลังกาย"}}
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="หมวดหมู่สถานที่", contents=FlexContainer.from_dict(flex_menu))]))
            return

        # --- 3. ค่าเทอม/สอบ/ทุน ---
        elif user_msg == "Menu > ค่าเทอม/สอบ/ทุน":
            flex_carousel = {
                "type": "carousel",
                "contents": [
                    {"type": "bubble", "styles": {"body": {"backgroundColor": "#F1E4D1"}}, "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "การเงินและทุน", "weight": "bold", "size": "lg", "align": "center", "color": "#162660"}, {"type": "separator", "margin": "md"}, {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "ชำระค่าเทอม", "text": "ดูชำระค่าเทอม"}}, {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "ทุนการศึกษา", "text": "ดูทุนการศึกษา"}}]}},
                    {"type": "bubble", "styles": {"body": {"backgroundColor": "#F1E4D1"}}, "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "ทะเบียนและการสอบ", "weight": "bold", "size": "lg", "align": "center", "color": "#162660"}, {"type": "separator", "margin": "md"}, {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "สอบซ่อม/สอบซ้อน", "text": "ดูการสอบ"}}, {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "เทียบโอน/รักษาสภาพ", "text": "ดูรักษาสภาพ"}}]}}
                ]
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เลือกบริการ", contents=FlexContainer.from_dict(flex_carousel))]))
            return

        # --- 4. ร้านค้า/จุดบริการ ---
        elif user_msg == "Menu > ร้านค้า/จุดบริการ":
            flex_shop = {
                "type": "bubble", "styles": {"body": {"backgroundColor": "#F1E4D1"}},
                "body": {"type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "ร้านค้าและจุดบริการ", "weight": "bold", "size": "xl", "align": "center", "color": "#162660"},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "ร้านกาแฟ/เครื่องดื่ม", "text": "ดูร้านกาแฟ"}},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "ร้านถ่ายเอกสาร", "text": "ดูร้านบริการ"}},
                    {"type": "button", "style": "secondary", "margin": "md", "action": {"type": "message", "label": "ดูร้านทั้งหมด", "text": "ดูร้านทั้งหมด"}}
                ]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูร้านค้า", contents=FlexContainer.from_dict(flex_shop))]))
            return

        # --- 5. หอพัก ---
        elif user_msg == "Menu > หอพัก":
            flex_dorm = {
                "type": "bubble", "styles": {"body": {"backgroundColor": "#F1E4D1"}},
                "body": {"type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "เลือกประเภทหอพัก", "weight": "bold", "size": "xl", "align": "center", "color": "#162660"},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "หอพักหญิง", "text": "ดูหอพักหญิง"}},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "หอพักชาย", "text": "ดูหอพักชาย"}},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#162660", "action": {"type": "message", "label": "หอพักบุคลากร", "text": "ดูหอพักบุคลากร"}}
                ]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูหอพัก", contents=FlexContainer.from_dict(flex_dorm))]))
            return

        # --- 6. ติดต่อ/ประเมิน ---
        elif user_msg == "Menu > ติดต่อ/ประเมิน":
            contact_flex = {
                "type": "bubble", "styles": {"body": {"backgroundColor": "#F1E4D1"}},
                "body": {"type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "ติดต่อ / ฉุกเฉิน", "weight": "bold", "size": "xl", "align": "center", "color": "#162660"},
                    {"type": "text", "text": "เหตุด่วน / รปภ.", "weight": "bold", "margin": "lg", "color": "#FF0000"},
                    {"type": "button", "style": "primary", "color": "#FF0000", "margin": "sm", "action": {"type": "uri", "label": "📞 หัวหน้า รปภ.", "uri": "tel:0939238526"}},
                    {"type": "button", "style": "primary", "color": "#FF0000", "margin": "sm", "action": {"type": "uri", "label": "📞 ป้อมยาม (ต่อ 7909)", "uri": "tel:055706555,,7909"}},
                    {"type": "text", "text": "บริการสุขภาพ", "weight": "bold", "margin": "lg", "color": "#162660"},
                    {"type": "button", "style": "primary", "color": "#162660", "margin": "sm", "action": {"type": "uri", "label": "📞 ห้องพยาบาล (ต่อ 1360)", "uri": "tel:055706555,,1360"}},
                    {"type": "separator", "margin": "xl"},
                    {"type": "button", "style": "link", "action": {"type": "uri", "label": "🌐 เว็บไซต์", "uri": "https://www.kpru.ac.th"}},
                    {"type": "button", "style": "link", "action": {"type": "uri", "label": "⭐ ประเมินความพึงพอใจ", "uri": "https://forms.gle/your_link"}}
                ]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ติดต่อ", contents=FlexContainer.from_dict(contact_flex))]))
            return

        # --- Logic ดึงข้อมูลปุ่มย่อย ---
        if user_msg in ["ดูสถานที่สำคัญ", "ดูจุดพักผ่อน", "ดูที่ออกกำลังกาย", "ดูหอพักหญิง", "ดูหอพักชาย", "ดูหอพักบุคลากร", "ดูร้านกาแฟ", "ดูร้านบริการ", "ดูร้านทั้งหมด"]:
            if "หอพักหญิง" in user_msg: sql = "SELECT * FROM locations WHERE location_type = 'Dormitory' AND common_name LIKE '%หญิง%'"
            elif "หอพักชาย" in user_msg: sql = "SELECT * FROM locations WHERE location_type = 'Dormitory' AND common_name LIKE '%ชาย%'"
            elif "จุดพักผ่อน" in user_msg: sql = "SELECT * FROM locations WHERE location_id IN (56, 60)"
            elif "สถานที่สำคัญ" in user_msg: sql = "SELECT * FROM locations WHERE location_id IN (13, 14, 26, 28, 5)"
            elif "ร้านกาแฟ" in user_msg: sql = "SELECT * FROM locations WHERE location_type = 'Cafe'"
            else: sql = "SELECT * FROM locations WHERE location_type IN ('Cafe', 'services', 'Exercise')"
            
            conn = pymysql.connect(**DB_CONFIG)
            with conn.cursor() as cursor:
                cursor.execute(sql)
                results = cursor.fetchall()
                if results: send_building_response(results)
            conn.close()
            return

        # --- กรณีพิมพ์หาปกติ ---
        service = get_service_data(user_msg)
        if service:
            b = get_building_by_id(service['location_id'])
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict(create_service_flex(service, b)))]))
            return
            
        buildings = get_building_data(user_msg)
        if buildings:
            send_building_response(buildings)
            return

        line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=f"ไม่พบข้อมูล '{user_msg}' ลองตรวจสอบชื่อเรียกอีกครั้งนะคะ 🙏")]))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)