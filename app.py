import os
import pymysql
from flask import Flask, request
from linebot.v3.webhook import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import (
    MessageEvent, 
    TextMessageContent,
    FollowEvent
)

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

handler = WebhookHandler(os.environ.get('CHANNEL_SECRET'))
configuration = Configuration(access_token=os.environ.get('CHANNEL_ACCESS_TOKEN'))

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
        "styles": {"body": {"backgroundColor": "#FFFFFF"}},
        "hero": {"type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": data['official_name'], "weight": "bold", "size": "xl", "wrap": True, "color": "#20364F"},
                {"type": "text", "text": data.get('description', 'ไม่มีข้อมูลรายละเอียด'), "size": "sm", "color": "#708090", "wrap": True, "margin": "md"}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#162660", "action": {"type": "uri", "label": "นำทางไปที่นี่", "uri": f"https://www.google.com/maps/search/?api=1&query={data['latitude']},{data['longitude']}"}}
            ]
        }
    }

def create_service_flex(service, building):
    return {
        "type": "bubble",
        "styles": {"body": {"backgroundColor": "#FFFFFF"}},
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": service['service_name'], "weight": "bold", "size": "xl", "color": "#20364F"},
                {"type": "text", "text": f"ตั้งอยู่ที่: {building['official_name'] if building else 'ไม่ระบุ'}", "size": "md", "margin": "md", "wrap": True, "color": "#20364F"},
                {"type": "text", "text": f"ติดต่อ: {service.get('service_details', 'ไม่ระบุ')}", "size": "sm", "color": "#708090", "wrap": True}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#162660", "action": {"type": "uri", "label": "นำทางไปอาคารนี้", "uri": f"https://www.google.com/maps/search/?api=1&query={building['latitude']},{building['longitude']}" if building else "#"}}
            ]
        }
    }

@app.route("/")
def home():
    return "KPRU Line Bot is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    handler.handle(body, signature)
    return 'OK', 200

# ==========================================
# 🟢 ระบบตอบกลับข้อความ (Message Handler)
# ==========================================
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

        # 1: แผนที่มหาวิทยาลัย
        if user_msg == "Menu > แผนที่มหาวิทยาลัย":
            img_url = "https://raw.githubusercontent.com/kpruuniguide-cloud/kpru-linebot/main/static/images/kpru_map.JPG"
            flex_map = {
                "type": "bubble",
                "hero": {"type": "image", "url": img_url, "size": "full", "aspectRatio": "1:1", "aspectMode": "cover"},
                "body": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "แผนที่มหาวิทยาลัย KPRU", "weight": "bold", "size": "lg", "align": "center", "color": "#20364F"}]},
                "footer": {"type": "box", "layout": "vertical", "contents": [
                    {"type": "button", "style": "primary", "color": "#3D597B", "action": {"type": "uri", "label": "ดูแผนที่ความละเอียดสูง", "uri": img_url}}
                ]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="แผนที่", contents=FlexContainer.from_dict(flex_map))]))
            return

# 2: สถานที่สำคัญ/จุดพักผ่อน (New Design Inspired by image_11.png)
        elif user_msg == "Menu > สถานที่สำคัญ/จุดพักผ่อน":
            flex_menu = {
                "type": "bubble",
                "styles": {
                    "body": {
                        "paddingAll": "0px" # ถมเต็มเพื่อเอาขอบขาวออก!
                    }
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        # --- ส่วนภาพพื้นหลัง (ถมเต็มด้านบน) ---
                        {
                            "type": "image",
                            # 📌 เช็กชื่อไฟล์รูปบน GitHub ของเบิร์ดให้ตรงนะครับ!
                            "url": f"{GITHUB_IMAGE_BASE}hero_Landmark.JPG", 
                            "size": "full",
                            "aspectRatio": "20:13", 
                            "aspectMode": "cover",
                            "gravity": "center"
                        },
                        
                        # --- ส่วนเนื้อหา (The Content Box ลอยขึ้นมาทับด้านล่างของภาพ) ---
                        {
                            "type": "box",
                            "layout": "vertical",
                            "position": "absolute", # วางแบบ Absolute เพื่อให้ลอยขึ้นไปทับ
                            "offsetTop": "25%", # ระยะที่ส่วนเนื้อหาจะลอยขึ้นไปทับภาพ (ปรับเปอร์เซ็นต์ได้ตามความชอบ)
                            "offsetBottom": "0px",
                            "offsetStart": "0px",
                            "offsetEnd": "0px",
                            
                            # 📌 แก้โจทย์ 1: เปลี่ยนเงาดำเป็นสีขาวโปร่งแสง (เพื่อให้ดูคล้ายกระจก)
                            "backgroundColor": "#ffffffcc", # สีขาว (White) โปร่งแสง 80% (Hex Alpha cc)
                            "cornerRadius": "xl", # ความโค้งมนระดับพรีเมียม
                            "paddingAll": "xl", # ระยะห่างข้างใน ดูโปร่งตา
                            "spacing": "md", # ระยะห่างระหว่างปุ่ม
                            
                            "contents": [
                                # หัวข้อ
                                {"type": "text", "text": "KPRU NAVIGATOR", "size": "xxs", "color": "#20364F", "weight": "bold", "letterSpacing": "0.3em", "align": "center"},
                                {"type": "text", "text": "สถานที่และจุดพักผ่อน", "weight": "bold", "size": "xl", "color": "#20364F", "align": "center", "wrap": True, "margin": "xs"},
                                
                                # เส้นคั่นแบบโปร่งแสง
                                {"type": "separator", "margin": "xl", "color": "#20364F1a"}, 

                                # 📌 แก้โจทย์ 2: เปลี่ยนปุ่มเป็นสีเข้ม (ใช้สีน้ำเงินเข้ม KPRU) และตัวหนังสือสีขาว
                                {"type": "button", "style": "primary", "height": "md", "color": "#162660", "margin": "lg", "cornerRadius": "lg", "action": {"type": "message", "label": "สถานที่สำคัญ", "text": "ดูสถานที่สำคัญ"}},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "md", "cornerRadius": "lg", "action": {"type": "message", "label": "จุดพักผ่อน", "text": "ดูจุดพักผ่อน"}},
                                {"type": "button", "style": "primary", "height": "md", "color": "#3D597B", "margin": "md", "cornerRadius": "lg", "action": {"type": "message", "label": "ออกกำลังกาย", "text": "ดูที่ออกกำลังกาย"}}
                            ]
                        }
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูสถานที่สำคัญแบบพรีเมียม", contents=FlexContainer.from_dict(flex_menu))]))
            return

        elif user_msg in ["ดูสถานที่สำคัญ", "ดูจุดพักผ่อน", "ดูที่ออกกำลังกาย"]:
            try:
                conn = pymysql.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    if "สถานที่สำคัญ" in user_msg:
                        sql = "SELECT * FROM locations WHERE location_id IN (13, 14, 26, 28, 5) "
                    elif "จุดพักผ่อน" in user_msg:
                        sql = "SELECT * FROM locations WHERE location_id IN (56, 60, 50) "
                    else:
                        sql = "SELECT * FROM locations WHERE location_type = 'Exercise' "
                    cursor.execute(sql)
                    results = cursor.fetchall()
                    if results: send_building_response(results)
                    else: line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="ยังไม่มีข้อมูลในระบบ")]))
            finally:
                if 'conn' in locals(): conn.close()
            return

        # 3: ค่าเทอม/สอบ/ทุน
        elif user_msg == "Menu > ค่าเทอม/สอบ/ทุน":
            flex_single = {
                "type": "bubble",
                "hero": {
                    "type": "image",
                    "url": f"{GITHUB_IMAGE_BASE}hero_academic_service.JPG", 
                    "size": "full", "aspectRatio": "20:13", "aspectMode": "fit"
                },
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "บริการนักศึกษา KPRU", "weight": "bold", "size": "xl", "align": "center", "color": "#20364F"},
                        {"type": "separator", "margin": "md", "color": "#E5E7EB"},
                        {"type": "button", "style": "primary", "height": "sm", "color": "#20364F", "margin": "md", "action": {"type": "message", "label": "สมัครเรียน", "text": "ดูสมัครเรียน"}},
                        {"type": "button", "style": "primary", "height": "sm", "color": "#20364F", "action": {"type": "message", "label": "ทุนการศึกษา / กยศ.", "text": "ดูทุนการศึกษา"}},
                        {"type": "button", "style": "primary", "height": "sm", "color": "#20364F", "action": {"type": "message", "label": "ทำบัตรนักศึกษาใหม่", "text": "ดูทำบัตรใหม่"}},
                        {"type": "button", "style": "primary", "height": "sm", "color": "#3D597B", "margin": "md", "action": {"type": "message", "label": "ชำระค่าเทอม", "text": "ดูชำระค่าเทอม"}},
                        {"type": "button", "style": "primary", "height": "sm", "color": "#3D597B", "action": {"type": "message", "label": "เทียบโอนผลการเรียน", "text": "ดูเทียบโอน"}}, 
                        {"type": "button", "style": "primary", "height": "sm", "color": "#3D597B", "action": {"type": "message", "label": "สอบซ้อน", "text": "ดูสอบซ้อน"}},
                        {"type": "button", "style": "primary", "height": "sm", "color": "#3D597B", "action": {"type": "message", "label": "รักษาสภาพนักศึกษา", "text": "ดูรักษาสภาพ"}},
                        {"type": "button", "style": "primary", "height": "sm", "color": "#6084AB", "margin": "md", "action": {"type": "message", "label": "ห้องพยาบาล", "text": "ดูห้องพยาบาล"}},
                        {"type": "button", "style": "primary", "height": "sm", "color": "#6084AB", "action": {"type": "message", "label": "ประกันอุบัติเหตุ", "text": "ดูเบิกประกัน"}},
                        {"type": "button", "style": "primary", "height": "sm", "color": "#6084AB", "action": {"type": "message", "label": "แจ้งของหาย", "text": "ดูแจ้งของหาย"}} 
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูบริการนักศึกษา", contents=FlexContainer.from_dict(flex_single))]))
            return

        elif user_msg in ["ดูสมัครเรียน", "ดูทุนการศึกษา", "ดูทำบัตรใหม่", "ดูชำระค่าเทอม", "ดูเทียบโอน", "ดูสอบซ้อน", "ดูรักษาสภาพ", "ดูห้องพยาบาล", "ดูเบิกประกัน", "ดูแจ้งของหาย"]:
            keyword_map = {
                "ดูสมัครเรียน": "สมัครเรียน", "ดูทุนการศึกษา": "กยศ", "ดูทำบัตรใหม่": "บัตรนักศึกษา",
                "ดูชำระค่าเทอม": "ค่าเทอม", "ดูเทียบโอน": "เทียบโอน", "ดูสอบซ้อน": "สอบซ้อน", "ดูรักษาสภาพ": "รักษาสภาพ",
                "ดูห้องพยาบาล": "พยาบาล", "ดูเบิกประกัน": "ประกัน", "ดูแจ้งของหาย": "ของหาย"
            }
            search_keyword = keyword_map[user_msg]
            try:
                conn = pymysql.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    sql = "SELECT s.*, l.official_name, l.latitude, l.longitude, l.image_url FROM services s LEFT JOIN locations l ON s.location_id = l.location_id WHERE s.service_name LIKE %s"
                    cursor.execute(sql, (f"%{search_keyword}%",))
                    results = cursor.fetchall()
                    if results:
                        bubbles = []
                        for row in results:
                            bubbles.append(create_service_flex(row, row))
                        line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles}))]))
            finally:
                if 'conn' in locals(): conn.close()
            return

        # 4: ร้านค้า/จุดบริการ
        elif user_msg == "Menu > ร้านค้า/จุดบริการ":
            flex_shop = {
                "type": "bubble",
                "body": {"type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "ร้านค้าและบริการ", "weight": "bold", "size": "xl", "align": "center", "color": "#20364F"},
                    {"type": "separator", "margin": "md", "color": "#E5E7EB"},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#20364F", "action": {"type": "message", "label": "ร้านกาแฟ", "text": "ดูร้านกาแฟ"}},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#3D597B", "action": {"type": "message", "label": "ร้านถ่ายเอกสาร/บริการ", "text": "ดูร้านบริการ"}},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#6084AB", "action": {"type": "message", "label": "ร้านทั้งหมด", "text": "ดูร้านทั้งหมด"}}
                ]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูร้านค้า", contents=FlexContainer.from_dict(flex_shop))]))
            return

        elif user_msg in ["ดูร้านกาแฟ", "ดูร้านบริการ", "ดูร้านทั้งหมด"]:
             try:
                conn = pymysql.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    if "ร้านกาแฟ" in user_msg: sql = "SELECT * FROM locations WHERE location_type = 'Cafe'"
                    elif "ดูร้านบริการ" in user_msg: sql = "SELECT * FROM locations WHERE location_type = 'services'"
                    else: sql = "SELECT * FROM locations WHERE location_type IN ('Cafe', 'services')"
                    cursor.execute(sql)
                    results = cursor.fetchall()
                    if results: send_building_response(results)
             finally:
                if 'conn' in locals(): conn.close()
             return

        # 5: หอพัก
        elif user_msg == "Menu > หอพัก":
            flex_dorm = {
                "type": "bubble",
                "body": {"type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "เลือกประเภทหอพัก", "weight": "bold", "size": "xl", "align": "center", "color": "#20364F"},
                    {"type": "separator", "margin": "md", "color": "#E5E7EB"},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#20364F", "action": {"type": "message", "label": "หอพักหญิง", "text": "ดูหอพักหญิง"}},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#3D597B", "action": {"type": "message", "label": "หอพักชาย", "text": "ดูหอพักชาย"}},
                    {"type": "button", "style": "primary", "margin": "md", "color": "#6084AB", "action": {"type": "message", "label": "หอพักบุคลากร/อาจารย์", "text": "ดูหอพักบุคลากร"}}
                ]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูหอพัก", contents=FlexContainer.from_dict(flex_dorm))]))
            return

        elif user_msg in ["ดูหอพักหญิง", "ดูหอพักชาย", "ดูหอพักบุคลากร"]:
            try:
                conn = pymysql.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    if "หอพักหญิง" in user_msg: sql = "SELECT * FROM locations WHERE location_type = 'Dormitory' AND common_name LIKE '%หญิง%'"
                    elif "หอพักชาย" in user_msg: sql = "SELECT * FROM locations WHERE location_type = 'Dormitory' AND common_name LIKE '%ชาย%'"
                    else: sql = "SELECT * FROM locations WHERE location_type = 'Dormitory' AND (common_name LIKE '%บุคลากร%' OR common_name LIKE '%อาจารย์%')"
                    cursor.execute(sql)
                    results = cursor.fetchall()
                    if results: send_building_response(results)
            finally:
                if 'conn' in locals(): conn.close()
            return

        # 6: ติดต่อ/ประเมิน
        elif user_msg == "Menu > ติดต่อ/ประเมิน":
            contact_flex = {
                "type": "bubble",
                "body": {"type": "box", "layout": "vertical", "spacing": "md", "contents": [
                    {"type": "text", "text": "ติดต่อสอบถาม / ฉุกเฉิน", "weight": "bold", "size": "xl", "align": "center", "color": "#20364F"},
                    {"type": "button", "style": "primary", "height": "sm", "color": "#3D597B", "action": {"type": "uri", "label": "หัวหน้า รปภ.", "uri": "tel:0939238526"}},
                    {"type": "button", "style": "primary", "height": "sm", "color": "#6084AB", "action": {"type": "uri", "label": "เว็บไซต์มหาวิทยาลัย", "uri": "https://www.kpru.ac.th"}},
                    {"type": "button", "style": "primary", "height": "sm", "color": "#6084AB", "action": {"type": "uri", "label": "ประเมินความพึงพอใจ", "uri": "https://forms.gle/your_link"}}
                ]}
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ติดต่อ", contents=FlexContainer.from_dict(contact_flex))]))
            return

        # ค้นหาทั่วไป
        service = get_service_data(user_msg)
        if service:
            b = get_building_by_id(service['location_id'])
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict(create_service_flex(service, b)))]))
            return
            
        buildings = get_building_data(user_msg)
        if buildings:
            send_building_response(buildings)
            return

        line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=f"ไม่พบข้อมูล '{user_msg}' ค่ะ 🙏")]))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))