import os
import pymysql
from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
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
            # 1. ดึงข้อมูลแบบกว้างๆ ออกมาก่อน
            sql = "SELECT * FROM locations WHERE building_no = %s OR common_name LIKE %s OR official_name LIKE %s"
            cursor.execute(sql, (keyword, f"%{keyword}%", f"%{keyword}%"))
            results = cursor.fetchall()
            
            if not results:
                return None
                
            # 2. 📌 ตัวกรองความแม่นยำ (เพื่อคัดแยก "ตึก 1" ออกจาก "ตึก 11, 12, 13")
            exact_matches = []
            for row in results:
                # กันเหนียวเผื่อ common_name เป็นค่าว่าง (None)
                common_names_str = str(row.get('common_name') or '')
                aliases = [x.strip() for x in common_names_str.split(',')]
                
                # เช็กว่าคำที่พิมพ์มา ตรงกับเลขตึก หรือชื่อทางการ หรือชื่อเรียกทั่วไปแบบเป๊ะๆ ไหม
                if (keyword == str(row.get('building_no', ''))) or \
                   (keyword == str(row.get('official_name', ''))) or \
                   (keyword in aliases):
                    exact_matches.append(row)
            
            # 3. ตัดสินใจ: ถ้าเจอตรงเป๊ะ ส่งอันที่เป๊ะไป / ถ้าไม่เจอเป๊ะ ก็ส่งอันที่ค้นหาเจอทั้งหมดไป
            return exact_matches if exact_matches else results

    except Exception as e:
        print(f"DB Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

def get_service_data(keyword):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM services WHERE keywords LIKE %s OR service_name LIKE %s"
            cursor.execute(sql, (f"%{keyword}%", f"%{keyword}%"))
            return cursor.fetchone()
    except Exception as e:
        print(f"DB Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

def get_building_by_id(building_id):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM locations WHERE location_id = %s", (building_id,))
            return cursor.fetchone()
    except Exception as e:
        print(f"DB Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

# ================== FLEX MESSAGE BUILDERS ==================

def create_building_flex(data):
    img_url = f"{GITHUB_IMAGE_BASE}{data['image_url']}" if data and data.get("image_url") else "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    # 1. สร้างกล่องข้อความเตรียมไว้ก่อน
    body_contents = []
    
    # 2. 📌 เช็กว่ามี "หมายเลขอาคาร" ไหม? (และต้องไม่ใช่เครื่องหมาย - หรือค่าว่าง)
    building_no = data.get('building_no')
    if building_no and str(building_no).strip() not in ["", "-", "None"]:
        # ถ้ามีเลขอาคาร ให้เอาคำว่า "หมายเลขอาคาร X" ใส่เป็นบรรทัดแรก
        body_contents.append({
            "type": "text", 
            "text": f"หมายเลขอาคาร {building_no}", 
            "size": "sm", 
            "color": "#E01B22", # ใส่สีแดงเข้มให้เลขอาคารเด่นขึ้นมานิดนึง
            "weight": "bold"
        })
        
    # 3. ใส่ "ชื่อทางการ" ต่อท้ายลงไป
    body_contents.append({
        "type": "text", 
        "text": data.get('official_name', 'ไม่ทราบชื่ออาคาร'), 
        "weight": "bold", 
        "size": "xl", 
        "wrap": True, 
        "color": "#20364F"
    })
    
    # 4. ใส่ "รายละเอียด" เป็นบรรทัดสุดท้าย
    body_contents.append({
        "type": "text", 
        "text": data.get('description', 'ไม่มีข้อมูลรายละเอียด'), 
        "size": "sm", 
        "color": "#708090", 
        "wrap": True, 
        "margin": "md"
    })

    return {
        "type": "bubble",
        "styles": {"body": {"backgroundColor": "#FFFFFF"}},
        "hero": {"type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
        "body": {
            "type": "box", 
            "layout": "vertical",
            "contents": body_contents # 📌 เอาข้อมูลที่เราจัดเรียง 3 สเตปข้างบนมาใส่ตรงนี้
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#162660", "action": {"type": "uri", "label": " 🗺️ นำทางไปที่นี่", "uri": f"https://www.google.com/maps/search/?api=1&query={data.get('latitude', '')},{data.get('longitude', '')}"}}
            ]
        }
    }

def create_service_flex(service, building):
    # 📌 ดึงลิงก์รูปภาพจากตาราง locations มาโชว์ในส่วนบริการ
    img_url = f"{GITHUB_IMAGE_BASE}{building['image_url']}" if building and building.get("image_url") else "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    return {
        "type": "bubble",
        "styles": {"body": {"backgroundColor": "#FFFFFF"}},
        "hero": {
            "type": "image", 
            "url": img_url, 
            "size": "full", 
            "aspectRatio": "20:13", 
            "aspectMode": "cover"
        },
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": service.get('service_name', 'ไม่ทราบชื่อบริการ'), "weight": "bold", "size": "xl", "color": "#20364F", "wrap": True},
                {"type": "text", "text": f"ตั้งอยู่ที่: {building.get('official_name', 'ไม่ระบุ') if building else 'ไม่ระบุ'}", "size": "md", "margin": "md", "wrap": True, "color": "#20364F"},
                {"type": "text", "text": f"ติดต่อ: {service.get('service_details', 'ไม่ระบุ')}", "size": "sm", "color": "#708090", "wrap": True}
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "button", "style": "primary", "color": "#162660", "action": {"type": "uri", "label": "🗺️ นำทางไปอาคารนี้", "uri": f"https://www.google.com/maps/search/?api=1&query={building.get('latitude', '')},{building.get('longitude', '')}" if building else "#"}}
            ]
        }
    }

# ================== FLASK ROUTES ==================

@app.route("/")
def home():
    return "KPRU Line Bot is running!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
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
            # ดึงมาแค่ 10 รายการเพื่อไม่ให้เกินลิมิตของ Carousel LINE
            bubbles = [create_building_flex(b) for b in buildings_list[:10]]
            carousel = {"type": "carousel", "contents": bubbles}
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(alt_text="ผลการค้นหาสถานที่", contents=FlexContainer.from_dict(carousel))]
            ))

        # 1: แผนที่มหาวิทยาลัย
        if user_msg == "Menu > แผนที่มหาวิทยาลัย":
            img_url = f"{GITHUB_IMAGE_BASE}kpru_map.JPG"
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

        # 2: สถานที่สำคัญ/จุดพักผ่อน
        # โค้ดดักจับเมื่อผู้ใช้กดปุ่มที่ 6 (ติดต่อและประเมิน)
        elif user_msg == "Menu > ติดต่อและประเมิน":
            # เอาโครงสร้าง JSON ที่เราคุยกันมาแปลงเป็น Dictionary ใน Python
            flex_evaluation = {
                "type": "bubble",
                "size": "giga",
                "header": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "รีวิวให้หน่อยน้าา 🥺", "weight": "bold", "size": "xl", "color": "#162660", "align": "center"},
                        {"type": "text", "text": "บอทแนะนำตึกเรียนของเราเวิร์คไหม?", "size": "sm", "color": "#3D597B", "align": "center", "margin": "sm"}
                    ],
                    "paddingAll": "xl"
                },
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "กดเลือกคะแนนได้เลย 👇", "align": "center", "color": "#aaaaaa", "size": "xs", "margin": "md"},
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "margin": "lg",
                            "spacing": "sm",
                            "contents": [
                                {"type": "button", "style": "secondary", "color": "#e8f5e9", "action": {"type": "message", "label": "🤩 ดีเริ่ด!", "text": "#รีวิว 5 ดาว"}},
                                {"type": "button", "style": "secondary", "color": "#fff8e1", "action": {"type": "message", "label": "🤔 เฉยๆ", "text": "#รีวิว 3 ดาว"}},
                                {"type": "button", "style": "secondary", "color": "#ffebee", "action": {"type": "message", "label": "😭 ต้องแก้", "text": "#รีวิว 1 ดาว"}}
                            ]
                        },
                        {"type": "separator", "margin": "xl"},
                        {
                            "type": "button",
                            "style": "link",
                            "height": "sm",
                            "action": {
                                "type": "uri",
                                "label": "📝 พิมพ์ข้อเสนอแนะเพิ่มเติมคลิก",
                                "uri": "https://forms.gle/ใส่ลิงก์ฟอร์มของคุณตรงนี้นะครับ" 
                            },
                            "color": "#162660",
                            "margin": "lg"
                        }
                    ]
                }
            }
            
            # สั่งให้บอทส่ง Flex Message ตัวนี้กลับไป
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token, 
                    messages=[FlexMessage(alt_text="แบบประเมินการใช้งาน", contents=FlexContainer.from_dict(flex_evaluation))]
                )
            )
            return

        elif user_msg in ["ดูสถานที่สำคัญ", "ดูจุดพักผ่อน", "ดูที่ออกกำลังกาย"]:
            try:
                conn = pymysql.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    if "สถานที่สำคัญ" in user_msg:
                        sql = "SELECT * FROM locations WHERE location_id IN (13, 14, 26, 28, 5)"
                    elif "จุดพักผ่อน" in user_msg:
                        sql = "SELECT * FROM locations WHERE location_id IN (56, 60, 50)"
                    else:
                        sql = "SELECT * FROM locations WHERE location_type = 'Exercise'"
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

        # 📌 แก้ไขส่วนแสดงผลของ "บริการนักศึกษา"
        elif user_msg in ["ดูสมัครเรียน", "ดูทุนการศึกษา", "ดูทำบัตรใหม่", "ดูชำระค่าเทอม", "ดูเทียบโอน", "ดูสอบซ้อน", "ดูรักษาสภาพ", "ดูห้องพยาบาล", "ดูเบิกประกัน", "ดูแจ้งของหาย"]:
            keyword_map = {
                "ดูสมัครเรียน": "สมัครเรียน", "ดูทุนการศึกษา": "กยศ", "ดูทำบัตรใหม่": "บัตรนักศึกษา",
                "ดูชำระค่าเทอม": "ค่าเทอม", "ดูเทียบโอน": "เทียบโอน", "ดูสอบซ้อน": "สอบซ้อน", "ดูรักษาสภาพ": "รักษาสภาพ",
                "ดูห้องพยาบาล": "พยาบาล", "ดูเบิกประกัน": "ประกัน", "ดูแจ้งของหาย": "ของหาย"
            }
            search_keyword = keyword_map.get(user_msg)
            
            if search_keyword:
                try:
                    conn = pymysql.connect(**DB_CONFIG)
                    with conn.cursor() as cursor:
                        sql = """
                            SELECT s.service_name, s.service_details, 
                                   l.official_name, l.latitude, l.longitude, l.image_url 
                            FROM services s 
                            LEFT JOIN locations l ON s.location_id = l.location_id 
                            WHERE s.keywords LIKE %s OR s.service_name LIKE %s
                        """
                        cursor.execute(sql, (f"%{search_keyword}%", f"%{search_keyword}%"))
                        results = cursor.fetchall()
                        
                        if results:
                            bubbles = [create_service_flex(row, row) for row in results[:10]]
                            line_bot_api.reply_message(ReplyMessageRequest(
                                reply_token=event.reply_token, 
                                messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles}))]
                            ))
                        else:
                            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="ยังไม่มีข้อมูลบริการนี้ในระบบค่ะ")]))
                except Exception as e:
                    print(f"Error: {e}")
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

        # 📌 ค้นหาทั่วไป (พิมพ์ข้อความเข้ามาเอง)
        service = get_service_data(user_msg)
        if service:
            b = get_building_by_id(service.get('location_id'))
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict(create_service_flex(service, b)))]))
            return
            
        buildings = get_building_data(user_msg)
        if buildings:
            send_building_response(buildings)
            return

        # กรณีหาอะไรไม่เจอเลย
        line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=f"ไม่พบข้อมูล '{user_msg}' ค่ะ 🙏 ลองพิมพ์ชื่อสถานที่ หรือบริการที่ต้องการอีกครั้งนะคะ")]))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))