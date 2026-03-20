import os
import pymysql
from flask import Flask, request
from linebot.v3.webhook import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage
)
from linebot.v3.messaging.models import FlexContainer
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

def get_service_data(user_msg):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM services"
            cursor.execute(sql)
            all_services = cursor.fetchall()
            clean_msg = user_msg.replace(' ', '').replace('.', '').lower()
            for service in all_services:
                if service['keywords']:
                    keywords_list = service['keywords'].split(',')
                    for kw in keywords_list:
                        clean_kw = kw.strip().replace(' ', '').replace('.', '').lower()
                        if clean_kw and (clean_kw in clean_msg):
                            return service
                clean_sname = service['service_name'].replace(' ', '').replace('.', '').lower()
                if clean_sname in clean_msg:
                    return service
            return None
    except Exception as e:
        print(f"Service DB Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

def get_building_data(keyword):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM locations WHERE building_no = %s OR common_name LIKE %s OR official_name LIKE %s"
            cursor.execute(sql, (keyword, f"%{keyword}%", f"%{keyword}%"))
            buildings = cursor.fetchall()
            if not buildings: return None
            return buildings
    except Exception as e:
        print(f"Building DB Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

def get_building_by_id(building_id):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM locations WHERE location_id = %s LIMIT 1"
            cursor.execute(sql, (building_id,))
            return cursor.fetchone()
    except Exception as e:
        return None
    finally:
        if 'conn' in locals(): conn.close()

# ================== MESSAGE BUILDER ==================

def create_building_flex(data):
    img_url = f"{GITHUB_IMAGE_BASE}{data['image_url']}" if data.get("image_url") else "https://www.kpru.ac.th/th/images/logo-kpru.png"
    building_no = data['building_no'] if data.get('building_no') else ""
    b_text = f"อาคาร {building_no}".strip() if building_no else data['official_name']
    return {
        "type": "bubble",
        "hero": {"type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": b_text, "weight": "bold", "size": "xl", "wrap": True},
                {"type": "text", "text": data['official_name'], "size": "sm", "color": "#666666", "wrap": True, "margin": "md"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#4A90E2", "action": {"type": "uri", "label": "เปิดแผนที่ (Google Maps)", "uri": f"https://www.google.com/maps/search/?api=1&query={data['latitude']},{data['longitude']}"}}
            ]
        }
    }

def create_service_flex(service_data, building_data):
    img_url = f"{GITHUB_IMAGE_BASE}{building_data['image_url']}" if building_data and building_data.get("image_url") else "https://www.kpru.ac.th/th/images/logo-kpru.png"
    building_name = building_data['official_name'] if building_data else "ไม่ระบุอาคาร"
    return {
        "type": "bubble",
        "hero": {"type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": service_data['service_name'], "weight": "bold", "size": "xl", "wrap": True},
                {"type": "text", "text": f"สถานที่: {building_name}", "weight": "bold", "size": "md", "color": "#4A90E2", "wrap": True, "margin": "md"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#4A90E2", "action": {"type": "uri", "label": "เปิดแผนที่", "uri": f"https://www.google.com/maps/search/?api=1&query={building_data['latitude'] if building_data else 16.45},{building_data['longitude'] if building_data else 99.51}"}}
            ]
        }
    }

def create_detail_flex(title, description):
    return {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": "รายละเอียด", "weight": "bold", "size": "lg", "color": "#4A90E2"},
                {"type": "text", "text": title, "size": "xs", "color": "#999999", "wrap": True, "margin": "sm"},
                {"type": "separator", "margin": "md"},
                {"type": "text", "text": description.replace('\\n', '\n'), "wrap": True, "size": "sm", "margin": "md"}
            ]
        }
    }

# ================== FLASK ROUTES ==================

@app.route("/")
def home(): return "KPRU UniGuide Bot is running!", 200

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

        # ฟังก์ชันช่วยส่งข้อความ (ย้ายมาไว้ตรงนี้เพื่อให้เรียกใช้ง่าย)
        def send_building_response(buildings_list):
            bubbles = []
            for b in buildings_list[:5]:
                bubbles.append(create_building_flex(b))
                if b.get('description') and b['description'] not in ["", "-"]:
                    bubbles.append(create_detail_flex(b['official_name'], b['description']))
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(alt_text="ข้อมูลสถานที่", contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles[:10]}))]
            ))

        def send_service_response(results):
            bubbles = []
            for s in results:
                b = get_building_by_id(s['location_id'])
                bubbles.append(create_service_flex(s, b))
                if s.get('service_details') and s['service_details'] not in ["", "-"]:
                    bubbles.append(create_detail_flex(s['service_name'], s['service_details']))
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles[:10]}))]
            ))

        # ==========================================
        # 🟢 ดักจับปุ่มจาก Rich Menu (แบบพิมพ์ติดกัน)
        # ==========================================

        # 1. แผนที่
        if user_msg == "Menu > แผนที่มหาวิทยาลัย":
            img_url = "https://raw.githubusercontent.com/kpruuniguide-cloud/kpru-linebot/main/static/images/kpru_map.jpg"
            flex_map = {
                "type": "bubble",
                "hero": {"type": "image", "url": img_url, "size": "full", "aspectRatio": "1:1", "aspectMode": "cover"},
                "footer": {"type": "box", "layout": "vertical", "contents": [{"type": "button", "style": "primary", "color": "#112250", "action": {"type": "uri", "label": "ดูแผนที่ความละเอียดสูง", "uri": img_url}}]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="แผนที่", contents=FlexContainer.from_dict(flex_map))]))
            return

        # 2. สถานที่สำคัญ
        elif user_msg == "Menu > สถานที่สำคัญ/จุดพักผ่อน":
            flex_menu = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical", "contents": [
                        {"type": "text", "text": "เลือกหมวดหมู่ที่ต้องการ", "weight": "bold", "size": "xl", "align": "center", "color": "#4A90E2"},
                        {"type": "separator", "margin": "md"},
                        {"type": "button", "style": "primary", "margin": "md", "color": "#4A90E2", "action": {"type": "message", "label": "สถานที่สำคัญ", "text": "ดูสถานที่สำคัญ"}},
                        {"type": "button", "style": "primary", "margin": "md", "color": "#7FB3D5", "action": {"type": "message", "label": "จุดพักผ่อนริมน้ำ", "text": "ดูจุดพักผ่อน"}},
                        {"type": "button", "style": "primary", "margin": "md", "color": "#A9CCE3", "action": {"type": "message", "label": "ออกกำลังกาย", "text": "ดูที่ออกกำลังกาย"}}
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เลือกหมวดหมู่", contents=FlexContainer.from_dict(flex_menu))]))
            return

        elif user_msg in ["ดูสถานที่สำคัญ", "ดูจุดพักผ่อน", "ดูที่ออกกำลังกาย"]:
            sql = "SELECT * FROM locations WHERE location_id IN (13,14,26,28,5)" if user_msg == "ดูสถานที่สำคัญ" else "SELECT * FROM locations WHERE location_type = 'Rest_Area'" if user_msg == "ดูจุดพักผ่อน" else "SELECT * FROM locations WHERE location_type = 'Exercise'"
            try:
                conn = pymysql.connect(**DB_CONFIG); cursor = conn.cursor()
                cursor.execute(sql); res = cursor.fetchall()
                if res: send_building_response(res)
                else: line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="ไม่พบข้อมูล")]))
            finally: conn.close()
            return

        # 3. ค่าเทอม/การสอบ/ทุนการศึกษา
        elif user_msg == "Menu > ค่าเทอม/การสอบ/ทุนการศึกษา":
            flex_carousel = {
                "type": "carousel",
                "contents": [
                    {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "การเงินและทุน", "weight": "bold", "size": "lg", "align": "center", "color": "#4A90E2"}, {"type": "separator", "margin": "md"}, {"type": "button", "style": "primary", "margin": "md", "color": "#4A90E2", "action": {"type": "message", "label": "ชำระค่าเทอม", "text": "ดูชำระค่าเทอม"}}, {"type": "button", "style": "primary", "margin": "md", "color": "#7FB3D5", "action": {"type": "message", "label": "ทุนการศึกษา", "text": "ดูทุนการศึกษา"}}]}},
                    {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "ทะเบียนและการสอบ", "weight": "bold", "size": "lg", "align": "center", "color": "#4A90E2"}, {"type": "separator", "margin": "md"}, {"type": "button", "style": "primary", "margin": "md", "color": "#4A90E2", "action": {"type": "message", "label": "สอบซ่อม/สอบซ้อน", "text": "ดูการสอบ"}}, {"type": "button", "style": "primary", "margin": "md", "color": "#7FB3D5", "action": {"type": "message", "label": "เทียบโอน/รักษาสภาพ", "text": "ดูรักษาสภาพ"}}]}},
                    {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "บริการอื่นๆ", "weight": "bold", "size": "lg", "align": "center", "color": "#4A90E2"}, {"type": "separator", "margin": "md"}, {"type": "button", "style": "primary", "margin": "md", "color": "#4A90E2", "action": {"type": "message", "label": "บัตรนักศึกษา", "text": "ดูบัตรนักศึกษา"}}, {"type": "button", "style": "primary", "margin": "md", "color": "#7FB3D5", "action": {"type": "message", "label": "ห้องพยาบาล/ประกัน", "text": "ดูห้องพยาบาล"}}]}}
                ]
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เลือกบริการ", contents=FlexContainer.from_dict(flex_carousel))]))
            return

        elif user_msg in ["ดูชำระค่าเทอม", "ดูทุนการศึกษา", "ดูการสอบ", "ดูรักษาสภาพ", "ดูบัตรนักศึกษา", "ดูห้องพยาบาล"]:
            kw = "ค่าเทอม" if "ค่าเทอม" in user_msg else "ทุน" if "ทุน" in user_msg else "สอบ" if "สอบ" in user_msg else "รักษาสภาพ" if "รักษาสภาพ" in user_msg else "บัตร" if "บัตร" in user_msg else "พยาบาล"
            try:
                conn = pymysql.connect(**DB_CONFIG); cursor = conn.cursor()
                cursor.execute(f"SELECT * FROM services WHERE service_name LIKE '%{kw}%'"); res = cursor.fetchall()
                if res: send_service_response(res)
            finally: conn.close()
            return

        # 4. ร้านค้า/จุดบริการ
        elif user_msg == "Menu > ร้านค้า/จุดบริการ":
            flex_menu = {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "เลือกร้านค้าหรือจุดบริการ", "weight": "bold", "size": "xl", "align": "center", "color": "#4A90E2"}, {"type": "separator", "margin": "md"}, {"type": "button", "style": "primary", "margin": "md", "color": "#4A90E2", "action": {"type": "message", "label": "ร้านกาแฟ/เครื่องดื่ม", "text": "ดูร้านกาแฟ"}}, {"type": "button", "style": "primary", "margin": "md", "color": "#7FB3D5", "action": {"type": "message", "label": "ร้านถ่ายเอกสาร", "text": "ดูร้านถ่ายเอกสาร"}}, {"type": "button", "style": "secondary", "margin": "md", "action": {"type": "message", "label": "ดูร้านค้าทั้งหมด", "text": "ดูร้านค้าทั้งหมด"}}]}}
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ร้านค้า", contents=FlexContainer.from_dict(flex_menu))]))
            return

        # 5. หอพัก
        elif user_msg == "Menu > หอพัก":
            flex_menu = {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "เลือกประเภทหอพัก", "weight": "bold", "size": "xl", "align": "center", "color": "#4A90E2"}, {"type": "separator", "margin": "md"}, {"type": "button", "style": "primary", "margin": "md", "color": "#4A90E2", "action": {"type": "message", "label": "หอพักหญิง", "text": "ดูหอพักหญิง"}}, {"type": "button", "style": "primary", "margin": "md", "color": "#7FB3D5", "action": {"type": "message", "label": "หอพักชาย", "text": "ดูหอพักชาย"}}, {"type": "button", "style": "primary", "margin": "md", "color": "#A9CCE3", "action": {"type": "message", "label": "หอพักบุคลากร", "text": "ดูหอพักบุคลากร"}}]}}
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="หอพัก", contents=FlexContainer.from_dict(flex_menu))]))
            return

        elif user_msg in ["ดูหอพักหญิง", "ดูหอพักชาย", "ดูหอพักบุคลากร"]:
            kw = "หอพักหญิง" if "หญิง" in user_msg else "หอพักชาย" if "ชาย" in user_msg else "บุคลากร"
            try:
                conn = pymysql.connect(**DB_CONFIG); cursor = conn.cursor()
                cursor.execute(f"SELECT * FROM locations WHERE location_type = 'Dormitory' AND common_name LIKE '%{kw}%'"); res = cursor.fetchall()
                if res: send_building_response(res)
            finally: conn.close()
            return

        # 6. ติดต่อ/ประเมิน
        elif user_msg == "Menu > ติดต่อ/ประเมิน":
            contact_flex = {
                "type": "bubble",
                "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [
                    {"type": "text", "text": "📞 ติดต่อสอบถาม & ฉุกเฉิน", "weight": "bold", "size": "xl", "align": "center", "color": "#4A90E2"},
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": "เหตุด่วน / ความปลอดภัย (รปภ.)", "weight": "bold", "size": "sm", "color": "#333333"},
                    {"type": "button", "style": "primary", "height": "sm", "color": "#4A90E2", "action": {"type": "uri", "label": "โทร: หัวหน้า รปภ.", "uri": "tel:0939238526"}},
                    {"type": "button", "style": "primary", "height": "sm", "color": "#7FB3D5", "action": {"type": "uri", "label": "โทร: ป้อมยาม (เบอร์กลาง)", "uri": "tel:055706555"}},
                    {"type": "text", "text": "เจ็บป่วย / ห้องพยาบาล", "weight": "bold", "size": "sm", "margin": "lg", "color": "#333333"},
                    {"type": "button", "style": "primary", "height": "sm", "color": "#4A90E2", "action": {"type": "uri", "label": "โทร: ห้องพยาบาล", "uri": "tel:055706555"}},
                    {"type": "separator", "margin": "lg"},
                    {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "uri", "label": "🌐 เว็บไซต์มหาวิทยาลัย", "uri": "https://www.kpru.ac.th"}},
                    {"type": "button", "style": "secondary", "height": "sm", "action": {"type": "uri", "label": "⭐ ประเมินความพึงพอใจ", "uri": "https://forms.gle/your_link"}},
                ]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ติดต่อ", contents=FlexContainer.from_dict(contact_flex))]))
            return

        # --- ลำดับการทำงาน (Logic ปกติ) ---
        service = get_service_data(user_msg)
        if service:
            b = get_building_by_id(service['location_id'])
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict(create_service_flex(service, b)))]))
            return
            
        buildings = get_building_data(user_msg)
        if buildings:
            send_building_response(buildings)
            return

        line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=f"ไม่พบข้อมูล '{user_msg}' ลองพิมพ์หมายเลขตึกดูนะคะ")]))

if __name__ == "__main__":
    app.run(port=5000)