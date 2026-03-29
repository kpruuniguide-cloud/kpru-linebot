import os
import pymysql
from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage, FlexContainer,
    QuickReply, QuickReplyItem, MessageAction
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
            # 1. ค้นหาแบบกว้างๆ เหมือนเดิม
            sql = "SELECT * FROM locations WHERE building_no = %s OR common_name LIKE %s OR official_name LIKE %s"
            cursor.execute(sql, (keyword, f"%{keyword}%", f"%{keyword}%"))
            results = cursor.fetchall()
            
            if not results:
                return None
                
            # 📌 2. ตัวกรองใหม่: ถ้าพิมพ์เลขตัวเดียว (เช่น "1") ต้องหาอันที่ตรงเป๊ะเท่านั้น
            exact_matches = []
            for row in results:
                b_no = str(row.get('building_no', '')).strip()
                common_names_str = str(row.get('common_name') or '')
                aliases = [x.strip() for x in common_names_str.split(',')]
                
                # เช็กว่าคำค้นหาตรงกับเลขตึกแบบเป๊ะๆ หรืออยู่ในชื่อเรียกทั่วไปแบบเป๊ะๆ
                if keyword == b_no or keyword in aliases or keyword == str(row.get('official_name')):
                    exact_matches.append(row)
            
            # 3. ถ้าเจออันที่ "ตรงเป๊ะ" (เช่น ตึก 1) ให้ส่งแค่อันนั้นอันเดียวไปเลย
            # ไม่ต้องส่งตึก 11, 12, 14 ที่แค่มีเลข 1 ติดมาด้วย
            if exact_matches:
                return exact_matches
            
            return results

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
            "color": "#162660", 
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
                {"type": "text", "text": f"{service.get('service_details', 'ไม่ระบุ')}", "size": "sm", "color": "#708090", "wrap": True}
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
            img_url = f"{GITHUB_IMAGE_BASE}map_kpru.png" 
            
            # 1. รายชื่ออาคารทั้งหมด (เรียงตามแผนที่ 1-49 และ A-D)
            building_names = [
                "1. อาคาร 1 สถาบันวิจัยและพัฒนา",
                "2. อาคาร 2 (คณะครุศาสตร์เก่า)",
                "3. อาคาร 3 (คณะมนุษยศาสตร์และสังคมศาสตร์เก่า)",
                "4. อาคาร 4 (คณะพยาบาลศาสตร์)",
                "5. โรงอาหาร",
                "6. อาคารเรียนศูนย์การแพทย์ทางเลือก",
                "7. อาคารน้ำเพชร 1",
                "8. อาคารโปรแกรมดนตรี",
                "9. อาคารโปรแกรมศิลปะ",
                "10. กองพัฒนานักศึกษา (หลังเก่า)",
                "11. อาคารเฉลิมพระเกียรติ ๖ รอบพระชนมพรรษา อาคาร 2 (คณะวิทยาการจัดการ)",
                "12. อาคารเฉลิมพระเกียรติ ๖ รอบพระชนมพรรษา อาคาร 1 (อาคารเรียนรวม)",
                "13. หอประชุมทีปังกรรัศมีโชติ",
                "14. อาคารเรียนรวมและอำนวยการ",
                "15. อาคารศูนย์กีฬารวม",
                "16. อาคารจุฬาภรณ์วลัยลักษณ์",
                "17. อาคารคณะวิทยาศาสตร์และเทคโนโลยี (เก่า)",
                "18. อาคารเฉลิมพระเกียรติ ๕๐ พรรษา มหาวชิราลงกรณ์ (คณะเทคโนโลยีอุตสาหกรรม)",
                "19. อาคารเรียนภาควิชาเกษตรศาสตร์",
                "20. อาคารเทคโนโลยีไฟฟ้า",
                "21. อาคารศูนย์ส่งเสริมและตรวจสอบการผลิตฯ",
                "22. อาคารเรียนภาควิชาคหกรรมศาสตร์",
                "23. อาคารศูนย์การศึกษาพิเศษ",
                "24. อาคารศูนย์เด็กปฐมวัย",
                "25. อาคารศูนย์ภาษาและคอมพิวเตอร์",
                "26. อาคารบรรณราชนครินทร์ (สำนักวิทยบริการฯ)",
                "27. อาคารเอวี",
                "28. หอประชุมรัตนอาภา (หอประชุมเก่า)",
                "29. อาคารออกแบบและพัฒนาผลิตภัณฑ์",
                "30. อาคารเทคโนโลยีก่อสร้าง",
                "32. ศูนย์กีฬาในร่มเอนกประสงค์ (โรงยิมใหม่)",
                "38. คณะมนุษยศาสตร์และสังคมศาสตร์",
                "41. อาคารภูมิภาคพิทยา (ศูนย์ศิลปะและวัฒนธรรม)",
                "44. สำนักวิทยบริการและเทคโนโลยีสารสนเทศ (ใหม่)",
                "46. คณะครุศาสตร์",
                "47. อาคารกองพัฒนานักศึกษา (SAC)",
                "48. อาคารเรียนและปฏิบัติการทางวิทยาศาสตร์",
                "49. KPRU HOME",
                "A. ศาลาพระพุทธวิทานปัญญาบดี",
                "B. ลานกิจกรรมหน้าหอประชุมทีปังกรรัศมีโชติ",
                "C. สวนพลังงาน KPRU",
                "D. KPRU Place"
            ]

            # 2. แปลงข้อความใน List ให้เป็นรูปแบบ Flex Message แบบอัตโนมัติ
            building_contents = []
            for name in building_names:
                building_contents.append({
                    "type": "text", 
                    "text": name, 
                    "size": "xs",  
                    "color": "#4A4A4A", 
                    "wrap": True, 
                    "margin": "sm"
                })

            # 3. สร้างโครงสร้าง Flex Message
            flex_map = {
                "type": "bubble",
                "size": "giga", 
                "hero": {
                    "type": "image", 
                    "url": img_url, 
                    "size": "full", 
                    "aspectRatio": "1.5:1", 
                    "aspectMode": "cover",
                    "action": {"type": "uri", "label": "ดูแผนที่ความละเอียดสูง", "uri": img_url} 
                },
                "body": {
                    "type": "box", "layout": "vertical", 
                    "contents": [
                        {
                            "type": "text", "text": "รายชื่ออาคารทั้งหมด ", 
                            "weight": "bold", "size": "md", "color": "#20364F"
                        },
                        {"type": "separator", "margin": "md"},
                        {
                            "type": "box", "layout": "vertical", "margin": "md", 
                            "contents": building_contents 
                        }
                    ]
                },
                "footer": {
                    "type": "box", "layout": "vertical", "spacing": "md",
                    "contents": [
                        # 📌 เพิ่มข้อความแนะนำที่นี่
                        {
                            "type": "text", 
                            "text": "💡 พิมพ์ \"หมายเลข\" หรือ \"ชื่ออาคาร\"\nเพื่อดูรายละเอียดได้เลยค่ะ!", 
                            "size": "xs", 
                            "color": "#666666",  
                            "align": "center", 
                            "wrap": True,
                            "weight": "bold",
                            "margin": "lg"
                        },
                        {
                            "type": "button", "style": "primary", "color": "#162660", "margin": "md",
                            "action": {"type": "uri", "label": "🔍 ซูมดูแผนที่ขนาดเต็ม", "uri": img_url}
                        }
                    ]
                }
            }
            
            # 📌 4. สร้างปุ่ม Quick Reply 
            quick_reply_buttons = QuickReply(
                items=[
                    QuickReplyItem(action=MessageAction(label="อาคาร 1", text="อาคาร 1")),
                    QuickReplyItem(action=MessageAction(label="อาคาร 14", text="อาคาร 14")),
                    QuickReplyItem(action=MessageAction(label="ตึกกระป๋องแป้ง", text="ตึกกระป๋องแป้ง")),
                    QuickReplyItem(action=MessageAction(label="ห้องสมุด", text="ห้องสมุด")),
                    QuickReplyItem(action=MessageAction(label="โรงอาหาร", text="โรงอาหาร"))
                ]
            )
            
            # 📌 5. ส่ง Flex Message (ใส่ quick_reply พ่วงเข้าไปกับ Flex เลย)
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[FlexMessage(
                    alt_text="แผนที่มหาวิทยาลัยและรายชื่ออาคาร", 
                    contents=FlexContainer.from_dict(flex_map),
                    quick_reply=quick_reply_buttons  # แนบปุ่มด่วนตรงนี้!
                )]
            ))
            return
        
# ================= 2 PLACE (สถานที่สำคัญ/จุดพักผ่อน) =================
        elif user_msg == "Menu > สถานที่สำคัญ/จุดพักผ่อน":
            flex_menu = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical", "paddingAll": "0px",
                    "contents": [
                        {"type": "image", "url": f"{GITHUB_IMAGE_BASE}Landmark.JPG", "size": "full", "aspectRatio": "3:4", "aspectMode": "cover", "gravity": "center"},
                        {
                            "type": "box", "layout": "vertical", "position": "absolute", "offsetTop": "10%", "offsetBottom": "10%", "offsetStart": "8%", "offsetEnd": "8%",
                            "backgroundColor": "#ffffff80",
                            "cornerRadius": "xl", "paddingAll": "xl",
                            "contents": [
                                {"type": "text", "text": "KPRU NAVIGATOR", "size": "xxs", "color": "#162660", "weight": "bold", "letterSpacing": "0.3em", "align": "center"},
                                {"type": "text", "text": "สถานที่และจุดพักผ่อน", "weight": "bold", "size": "xl", "color": "#20364F", "align": "center", "wrap": True, "margin": "xs"},
                                {"type": "separator", "margin": "xl", "color": "#20364F1a"},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "lg", "cornerRadius": "lg", "action": {"type": "message", "label": "🏛️ สถานที่สำคัญ", "text": "ดูสถานที่สำคัญ"}},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "md", "cornerRadius": "lg", "action": {"type": "message", "label": "⛲ จุดพักผ่อน", "text": "ดูจุดพักผ่อน"}},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "md", "cornerRadius": "lg", "action": {"type": "message", "label": "🏸 ออกกำลังกาย", "text": "ดูที่ออกกำลังกาย"}}
                            ]
                        }
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูสถานที่สำคัญ", contents=FlexContainer.from_dict(flex_menu))]))
            return

        elif user_msg in ["ดูสถานที่สำคัญ", "ดูจุดพักผ่อน", "ดูที่ออกกำลังกาย"]:
            try:
                conn = pymysql.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    if "สถานที่สำคัญ" in user_msg: sql = "SELECT * FROM locations WHERE location_id IN (13, 14, 26, 28, 5)"
                    elif "จุดพักผ่อน" in user_msg: sql = "SELECT * FROM locations WHERE location_id IN (56, 60, 50)"
                    else: sql = "SELECT * FROM locations WHERE location_type = 'Exercise'"
                    cursor.execute(sql)
                    results = cursor.fetchall()
                    if results: send_building_response(results) 
                    else: line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="ยังไม่มีข้อมูลในระบบ")]))
            finally:
                if 'conn' in locals(): conn.close()
            return
        
       # ================= 3 SERVICES (ค่าเทอม/สอบ/ทุน) =================
        elif user_msg == "Menu > ค่าเทอม/สอบ/ทุน":
            flex_menu = {
                "type": "carousel",
                "contents": [
                    {
                        "type": "bubble",
                        # 📌 จุดสังเกต: เช็คไฟล์ service1.JPG ใน GitHub ว่านามสกุลตัวพิมพ์ใหญ่หรือเล็ก
                        "hero": {"type": "image", "url": f"{GITHUB_IMAGE_BASE}services1.JPG", "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                        "body": {
                            "type": "box", "layout": "vertical", "paddingAll": "xl", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "บริการนักศึกษา KPRU", "weight": "bold", "size": "lg", "color": "#111827", "align": "center"},
                                {"type": "separator", "margin": "md", "color": "#e0e0e0"},
                                {
                                    "type": "box", "layout": "vertical", "spacing": "sm", "margin": "lg",
                                    "contents": [
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "สมัครเรียน", "text": "ดูสมัครเรียน"}, "contents": [{"type": "text", "text": "🎓 สมัครเรียน", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]},
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "ทุนการศึกษา", "text": "ดูทุนการศึกษา"}, "contents": [{"type": "text", "text": "🏦 ทุนการศึกษา / กยศ.", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]},
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "ทำบัตรนักศึกษา", "text": "ดูทำบัตรใหม่"}, "contents": [{"type": "text", "text": "🪪 ทำบัตรนักศึกษาใหม่", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]},
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "ชำระค่าเทอม", "text": "ดูชำระค่าเทอม"}, "contents": [{"type": "text", "text": "💸 ชำระค่าเทอม", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]},
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "เทียบโอน", "text": "ดูเทียบโอน"}, "contents": [{"type": "text", "text": "📑 เทียบโอนผลการเรียน", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]}
                                    ]
                                }
                            ]
                        }
                    },
                    {
                        "type": "bubble",
                        # 📌 จุดสังเกต: เช็คไฟล์ service3.JPG ใน GitHub เช่นกันครับ
                        "hero": {"type": "image", "url": f"{GITHUB_IMAGE_BASE}services3.jpg", "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                        "body": {
                            "type": "box", "layout": "vertical", "paddingAll": "xl", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "บริการนักศึกษา KPRU", "weight": "bold", "size": "lg", "color": "#111827", "align": "center"},
                                {"type": "separator", "margin": "md", "color": "#e0e0e0"},
                                {
                                    "type": "box", "layout": "vertical", "spacing": "sm", "margin": "lg",
                                    "contents": [
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "สอบซ้อน", "text": "ดูสอบซ้อน"}, "contents": [{"type": "text", "text": "📝 สอบซ้อน", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]},
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "รักษาสภาพ", "text": "ดูรักษาสภาพ"}, "contents": [{"type": "text", "text": "📈 รักษาสภาพนักศึกษา", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]},
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "ห้องพยาบาล", "text": "ดูห้องพยาบาล"}, "contents": [{"type": "text", "text": "🏥 ห้องพยาบาล", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]},
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "เบิกประกัน", "text": "ดูเบิกประกัน"}, "contents": [{"type": "text", "text": "🛡️ ประกันอุบัติเหตุ", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]},
                                        {"type": "box", "layout": "horizontal", "backgroundColor": "#20364F", "cornerRadius": "md", "paddingAll": "12px", "action": {"type": "message", "label": "แจ้งของหาย", "text": "ดูแจ้งของหาย"}, "contents": [{"type": "text", "text": "📦 แจ้งของหาย", "color": "#FFFFFF", "weight": "bold", "size": "sm"}]}
                                    ]
                                }
                            ]
                        }
                    }
                ]
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูบริการนักศึกษา", contents=FlexContainer.from_dict(flex_menu))]))
            return

        elif user_msg in ["ดูสมัครเรียน", "ดูทุนการศึกษา", "ดูทำบัตรใหม่", "ดูชำระค่าเทอม", "ดูเทียบโอน", "ดูสอบซ้อน", "ดูรักษาสภาพ", "ดูห้องพยาบาล", "ดูเบิกประกัน", "ดูแจ้งของหาย"]:
            keyword_map = {"ดูสมัครเรียน": "สมัครเรียน", "ดูทุนการศึกษา": "กยศ", "ดูทำบัตรใหม่": "บัตรนักศึกษา", "ดูชำระค่าเทอม": "ค่าเทอม", "ดูเทียบโอน": "เทียบโอน", "ดูสอบซ้อน": "สอบซ้อน", "ดูรักษาสภาพ": "รักษาสภาพ", "ดูห้องพยาบาล": "พยาบาล", "ดูเบิกประกัน": "ประกัน", "ดูแจ้งของหาย": "ของหาย"}
            search_keyword = keyword_map.get(user_msg)
            if search_keyword:
                try:
                    conn = pymysql.connect(**DB_CONFIG)
                    with conn.cursor() as cursor:
                        sql = "SELECT s.service_name, s.service_details, l.official_name, l.latitude, l.longitude, l.image_url FROM services s LEFT JOIN locations l ON s.location_id = l.location_id WHERE s.keywords LIKE %s OR s.service_name LIKE %s"
                        cursor.execute(sql, (f"%{search_keyword}%", f"%{search_keyword}%"))
                        results = cursor.fetchall()
                        if results:
                            bubbles = [create_service_flex(row, row) for row in results[:10]]
                            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict({"type": "carousel", "contents": bubbles}))]))
                        else:
                            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="ยังไม่มีข้อมูลบริการนี้ในระบบค่ะ")]))
                finally:
                    if 'conn' in locals(): conn.close()
            return

        # ================= 4 SHOPS (ร้านค้าและจุดบริการ) =================
        elif user_msg == "Menu > ร้านค้า/จุดบริการ":
            flex_menu = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical", "paddingAll": "0px",
                    "contents": [
                        {"type": "image", "url": f"{GITHUB_IMAGE_BASE}Shop2.JPG", "size": "full", "aspectRatio": "3:4", "aspectMode": "cover"},
                        {
                            "type": "box", "layout": "vertical", "position": "absolute", "offsetTop": "10%", "offsetBottom": "10%", "offsetStart": "8%", "offsetEnd": "8%",
                            "backgroundColor": "#ffffff80",
                            "cornerRadius": "xl", "paddingAll": "xl",
                            "contents": [
                                {"type": "text", "text": "KPRU NAVIGATOR", "size": "xxs", "color": "#162660", "weight": "bold", "letterSpacing": "0.3em", "align": "center"},
                                {"type": "text", "text": "ร้านค้าและบริการ", "weight": "bold", "size": "xl", "color": "#20364F", "align": "center", "wrap": True, "margin": "xs"},
                                {"type": "separator", "margin": "xl", "color": "#20364F1a"},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "lg", "cornerRadius": "lg", "action": {"type": "message", "label": "☕ ร้านกาแฟ", "text": "ดูร้านกาแฟ"}},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "md", "cornerRadius": "lg", "action": {"type": "message", "label": "🖨️ ร้านถ่ายเอกสาร/บริการ", "text": "ดูร้านบริการ"}},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "md", "cornerRadius": "lg", "action": {"type": "message", "label": "🏪 ร้านทั้งหมด", "text": "ดูร้านทั้งหมด"}}
                            ]
                        }
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูร้านค้าและบริการ", contents=FlexContainer.from_dict(flex_menu))]))
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

       # ================= 5 DORMITORY (หอพัก) =================
        elif user_msg == "Menu > หอพัก":
            flex_menu = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical", "paddingAll": "0px",
                    "contents": [
                        {"type": "image", "url": f"{GITHUB_IMAGE_BASE}Dorm2.JPG", "size": "full", "aspectRatio": "3:4", "aspectMode": "cover", "gravity": "center"},
                        {
                            "type": "box", "layout": "vertical", "position": "absolute", "offsetTop": "10%", "offsetBottom": "10%", "offsetStart": "8%", "offsetEnd": "8%",
                            "backgroundColor": "#ffffff80",
                            "cornerRadius": "xl", "paddingAll": "xl",
                            "contents": [
                                {"type": "text", "text": "KPRU NAVIGATOR", "size": "xxs", "color": "#162660", "weight": "bold", "letterSpacing": "0.3em", "align": "center"},
                                {"type": "text", "text": "เลือกประเภทหอพัก", "weight": "bold", "size": "xl", "color": "#20364F", "align": "center", "wrap": True, "margin": "xs"},
                                {"type": "separator", "margin": "xl", "color": "#20364F1a"},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "lg", "cornerRadius": "lg", "action": {"type": "message", "label": "หอพักหญิง", "text": "ดูหอพักหญิง"}},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "md", "cornerRadius": "lg", "action": {"type": "message", "label": "หอพักชาย", "text": "ดูหอพักชาย"}},
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "md", "cornerRadius": "lg", "action": {"type": "message", "label": "หอพักบุคลากร/อาจารย์", "text": "ดูหอพักบุคลากร"}}
                            ]
                        }
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูหอพัก", contents=FlexContainer.from_dict(flex_menu))]))
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
        
# ================= 6 CONTACT & EMERGENCY (ติดต่อ/ประเมิน) =================
        elif user_msg == "Menu > ติดต่อ/ประเมิน":
            flex_menu = {
                "type": "bubble", 
                "size": "mega", # ปรับขนาดให้ใหญ่ขึ้นเล็กน้อยเพื่อให้กดง่าย
                "styles": {
                    "header": {"backgroundColor": "#f44336"},
                    "footer": {"separator": True}
                },
                "header": {
                    "type": "box", "layout": "vertical", "paddingAll": "lg",
                    "contents": [{"type": "text", "text": "📞 สายด่วนฉุกเฉิน", "color": "#ffffff", "weight": "bold", "size": "md", "align": "center"}]
                },
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "lg",
                    "contents": [
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🚨 หัวหน้ารปภ.", "weight": "bold", "color": "#20364F", "size": "sm", "flex": 5},
                                {"type": "text", "text": "093-923-8526", "color": "#e30000", "size": "sm", "weight": "bold", "align": "end", "flex": 6}
                            ]
                        },
                        {"type": "separator"},
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🏥 ห้องพยาบาล", "weight": "bold", "color": "#20364F", "size": "sm", "flex": 4},
                                {"type": "text", "text": "055-706555 ต่อ 1360", "color": "#666666", "size": "xs", "align": "end", "flex": 7}
                            ]
                        },
                        {"type": "separator"},
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "👮 ป้อมยาม(หลัง)", "weight": "bold", "color": "#20364F", "size": "sm", "flex": 5},
                                {"type": "text", "text": "055-706555 ต่อ 7909", "color": "#666666", "size": "xs", "align": "end", "flex": 7}
                            ]
                        },
                        {"type": "separator"},
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "👮 ป้อมยาม(หน้า)", "weight": "bold", "color": "#20364F", "size": "sm", "flex": 5},
                                {"type": "text", "text": "055-706555 ต่อ 7910", "color": "#666666", "size": "xs", "align": "end", "flex": 7}
                            ]
                        }
                    ]
                },
                "footer": {
                    "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "lg",
                    "contents": [
                        {
                            "type": "button", "style": "primary", "color": "#20364F", "height": "sm",
                            "action": {
                                "type": "uri", "label": "🌐 เว็บไซต์มหาวิทยาลัย", "uri": "https://www.kpru.ac.th"
                            }
                        },
                        {
                            "type": "button", "style": "primary", "color": "#20364F", "height": "sm",
                            "action": {
                                "type": "uri", "label": "📝 ทำแบบประเมิน", 
                                "uri": "https://forms.gle/GV6yWpDRYPu5Zino7"
                            }
                        }
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[FlexMessage(alt_text="เมนูติดต่อ/ประเมิน", contents=FlexContainer.from_dict(flex_menu))]
            ))
            return



       # ==========================================
        # 📌 แก้ไขลำดับการค้นหาใหม่ (Location First)
        # ==========================================
        
        # 1. ค้นหาสถานที่ก่อน (เช่น พิมพ์ "ตึก 1" ต้องเจอสถานที่ก่อน)
        buildings = get_building_data(user_msg)
        if buildings:
            send_building_response(buildings)
            return

        # 2. ถ้าไม่เจอสถานที่ ค่อยไปค้นหาบริการ (Services)
        service = get_service_data(user_msg)
        if service:
            b = get_building_by_id(service.get('location_id'))
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict(create_service_flex(service, b)))]
            ))
            return

        # 3. กรณีหาอะไรไม่เจอเลย
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token, 
            messages=[TextMessage(text=f"ไม่พบข้อมูล '{user_msg}' ค่ะ 🙏 ลองพิมพ์ชื่อสถานที่ หรือบริการที่ต้องการอีกครั้งนะคะ")]
        ))
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))