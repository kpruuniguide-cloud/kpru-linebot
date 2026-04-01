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
    
    body_contents = []
    
    building_no = data.get('building_no')
    if building_no and str(building_no).strip() not in ["", "-", "None"]:
        body_contents.append({
            "type": "text", 
            "text": f"หมายเลขอาคาร {building_no}", 
            "size": "xs", # 📌 ขนาดเล็กพิเศษ
            "color": "#162660", 
            "weight": "bold"
        })
        
    body_contents.append({
        "type": "text", 
        "text": data.get('official_name', 'ไม่ทราบชื่ออาคาร'), 
        "weight": "bold", 
        "size": "md", # 📌 ลดจาก xl หรือ lg ลงมาเหลือ md
        "wrap": True, 
        "color": "#20364F"
    })
    
    body_contents.append({
        "type": "text", 
        "text": data.get('description', 'ไม่มีข้อมูลรายละเอียด'), 
        "size": "xs", # 📌 ลดขนาดรายละเอียดให้อ่านง่ายและไม่แย่งซีนหัวข้อ
        "color": "#708090", 
        "wrap": True, 
        "margin": "sm"
    })

    return {
        "type": "bubble",
        "styles": {"body": {"backgroundColor": "#FFFFFF"}},
        "hero": {"type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
        "body": {
            "type": "box", 
            "layout": "vertical",
            "contents": body_contents 
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {
                    "type": "button", 
                    "style": "primary", 
                    "color": "#16266080", # 📌 ปุ่มโปร่งแสง 50%
                    "height": "sm",
                    "action": {
                        "type": "uri", 
                        "label": " 🗺️ นำทางไปที่นี่", 
                        "uri": f"https://www.google.com/maps/search/?api=1&query={data.get('latitude', '')},{data.get('longitude', '')}"
                    }
                }
            ]
        }
    }

def create_service_flex(service, building):
    img_url = f"{GITHUB_IMAGE_BASE}{building['image_url']}" if building and building.get("image_url") else "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    # 📌 ดึงลิงก์จากฐานข้อมูล ถ้าในฐานข้อมูลไม่มี (เป็น None หรือว่างเปล่า) ให้ใช้เว็บมหาลัยเป็นค่าเริ่มต้น
    link_url = service.get('external_link')
    if not link_url or str(link_url).strip() == "":
        link_url = "https://www.kpru.ac.th"

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
            "type": "box", "layout": "vertical", "spacing": "md",
            "contents": [
                {
                    "type": "text", 
                    "text": service.get('service_name', 'ไม่ทราบชื่อบริการ/หน่วยงาน'), 
                    "weight": "bold", 
                    "size": "md", 
                    "color": "#20364F", 
                    "wrap": True
                },
                {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": [
                        {
                            "type": "box", "layout": "baseline", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "📍 สถานที่:", "color": "#162660", "size": "xs", "weight": "bold", "flex": 2},
                                {"type": "text", "text": building.get('official_name', 'ไม่ระบุ') if building else 'ไม่ระบุ', "wrap": True, "color": "#4b5563", "size": "xs", "flex": 6}
                            ]
                        },
                        {
                            "type": "box", "layout": "baseline", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "📄 ข้อมูล:", "color": "#162660", "size": "xs", "weight": "bold", "flex": 2},
                                {"type": "text", "text": service.get('service_details', 'ไม่ระบุ'), "wrap": True, "color": "#708090", "size": "xs", "flex": 6}
                            ]
                        }
                    ]
                }
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical", "spacing": "sm",
            "contents": [
                {
                    "type": "button", 
                    "style": "primary", 
                    "color": "#16266080", 
                    "height": "sm",
                    "action": {
                        "type": "uri", 
                        "label": "🌐 ข้อมูลเพิ่มเติม", 
                        "uri": link_url # 📌 ใส่ตัวแปรลิงก์ที่ดึงมา
                    }
                },
                {
                    "type": "button", 
                    "style": "primary", 
                    "color": "#20364F80", 
                    "height": "sm",
                    "action": {
                        "type": "uri", 
                        "label": "🗺️  นำทางไปที่นี่", 
                        "uri": f"https://www.google.com/maps/search/?api=1&query={building.get('latitude', '')},{building.get('longitude', '')}" if building else "#"
                    }
                }
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

    if not user_msg.startswith("Menu >") and not user_msg.startswith("Admin>"):
        try:
            conn = pymysql.connect(**DB_CONFIG)
            with conn.cursor() as cursor:
                cursor.execute("INSERT INTO search_logs (keyword) VALUES (%s)", (user_msg,))
                conn.commit()
        except Exception as e:
            print("Error saving log:", e)
        finally:
            if 'conn' in locals(): conn.close()
    
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
        
# ================= 3 SERVICES (บริการนักศึกษา 3 หมวดหมู่) =================
        elif user_msg == "Menu > ค่าเทอม/สอบ/ทุน":
            flex_menu = {
                "type": "carousel",
                "contents": [
                    {
                        "type": "bubble", # --- การ์ดที่ 1: การเงินและทุนการศึกษา ---
                        "hero": {"type": "image", "url": f"{GITHUB_IMAGE_BASE}services1.JPG", "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                        "body": {
                            "type": "box", "layout": "vertical", "paddingAll": "xl", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "การเงินและทุนการศึกษา", "weight": "bold", "size": "md", "color": "#111827", "align": "center"},
                                {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "lg",
                                    "contents": [
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "💸 ชำระค่าเทอม", "text": "ดูชำระค่าเทอม"}},
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "🏦 ทุนการศึกษา / กยศ.", "text": "ดูทุนการศึกษา"}}
                                    ]
                                }
                            ]
                        }
                    },
                    {
                        "type": "bubble", # --- การ์ดที่ 2: การเรียนและสถานภาพ ---
                        "hero": {"type": "image", "url": f"{GITHUB_IMAGE_BASE}services2.JPG", "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                        "body": {
                            "type": "box", "layout": "vertical", "paddingAll": "xl", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "การเรียนและสถานภาพ", "weight": "bold", "size": "md", "color": "#111827", "align": "center"},
                                {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "lg",
                                    "contents": [
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "🎓 สมัครเรียน", "text": "ดูสมัครเรียน"}},
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "📝 สอบซ้อน", "text": "ดูสอบซ้อน"}},
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "📈 รักษาสภาพนักศึกษา", "text": "ดูรักษาสภาพ"}},
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "📑 เทียบโอนผลการเรียน", "text": "ดูเทียบโอน"}}
                                    ]
                                }
                            ]
                        }
                    },
                    {
                        "type": "bubble", # --- การ์ดที่ 3: สวัสดิการและบริการทั่วไป ---
                        "hero": {"type": "image", "url": f"{GITHUB_IMAGE_BASE}services3.jpg", "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                        "body": {
                            "type": "box", "layout": "vertical", "paddingAll": "xl", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "สวัสดิการและบริการทั่วไป", "weight": "bold", "size": "md", "color": "#111827", "align": "center"},
                                {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "lg",
                                    "contents": [
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "🪪 ทำบัตรนักศึกษาใหม่", "text": "ดูทำบัตรใหม่"}},
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "🏥 ห้องพยาบาล", "text": "ดูห้องพยาบาล"}},
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "🛡️ ประกันอุบัติเหตุ", "text": "ดูเบิกประกัน"}},
                                        {"type": "button", "style": "primary", "color": "#20364F", "margin": "xs", "height": "sm", "action": {"type": "message", "label": "📦 แจ้งของหาย", "text": "ดูแจ้งของหาย"}}
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
            keyword_map = {
                "ดูสมัครเรียน": "สมัครเรียน", "ดูทุนการศึกษา": "กยศ", "ดูทำบัตรใหม่": "บัตรนักศึกษา", 
                "ดูชำระค่าเทอม": "ค่าเทอม", "ดูเทียบโอน": "เทียบโอน", "ดูสอบซ้อน": "สอบซ้อน", 
                "ดูรักษาสภาพ": "รักษาสภาพ", "ดูห้องพยาบาล": "พยาบาล", "ดูเบิกประกัน": "ประกัน", "ดูแจ้งของหาย": "ของหาย"
            }
            search_keyword = keyword_map.get(user_msg)
            if search_keyword:
                try:
                    conn = pymysql.connect(**DB_CONFIG)
                    with conn.cursor() as cursor:
                        # 📌 เพิ่มการ Select คอลัมน์ s.external_link เข้ามาในคำสั่ง SQL ด้วย
                        sql = "SELECT s.service_name, s.service_details, s.external_link, l.official_name, l.latitude, l.longitude, l.image_url FROM services s LEFT JOIN locations l ON s.location_id = l.location_id WHERE s.keywords LIKE %s OR s.service_name LIKE %s"
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
                                {"type": "button", "style": "primary", "height": "md", "color": "#20364F", "margin": "md", "cornerRadius": "lg", "action": {"type": "message", "label": "🖨️ ร้านถ่ายเอกสาร/บริการ", "text": "ดูร้านบริการ"}}
                            ]
                        }
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[FlexMessage(alt_text="เมนูร้านค้าและบริการ", contents=FlexContainer.from_dict(flex_menu))]))
            return

        elif user_msg in ["ดูร้านกาแฟ", "ดูร้านบริการ"]:
             try:
                conn = pymysql.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    if "ร้านกาแฟ" in user_msg: 
                        sql = "SELECT * FROM locations WHERE location_type = 'Cafe'"
                    elif "ดูร้านบริการ" in user_msg: 
                        sql = "SELECT * FROM locations WHERE location_type = 'services'"
                    
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
        
# ================= 6 CONTACT & EMERGENCY (ติดต่อ) =================
        elif user_msg == "Menu > ติดต่อ/ฉุกเฉิน":
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
                        }
                    ]
                }
            }
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[FlexMessage(alt_text="เมนูติดต่อ", contents=FlexContainer.from_dict(flex_menu))]
            ))
            return

# ================= 7 ADMIN (คำสั่งลับดูสถิติ) =================
        elif user_msg == "Admin>ดูสถิติ":
            try:
                conn = pymysql.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    sql = """
                        SELECT keyword, COUNT(*) as search_count 
                        FROM search_logs 
                        GROUP BY keyword 
                        ORDER BY search_count DESC 
                        LIMIT 5
                    """
                    cursor.execute(sql)
                    top_searches = cursor.fetchall()

                    if top_searches:
                        reply_text = "📊 สถิติคำค้นหายอดฮิต 5 อันดับแรก:\n\n"
                        for i, row in enumerate(top_searches):
                            reply_text += f"{i+1}. {row['keyword']} ({row['search_count']} ครั้ง)\n"
                    else:
                        reply_text = "ยังไม่มีข้อมูลสถิติการค้นหาในระบบค่ะ"

                    line_bot_api.reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token, 
                        messages=[TextMessage(text=reply_text)]
                    ))
            except Exception as e:
                print("Error fetching stats:", e)
            finally:
                if 'conn' in locals(): conn.close()
            return

        elif user_msg == "Admin>เวลาฮิต":
            try:
                conn = pymysql.connect(**DB_CONFIG)
                with conn.cursor() as cursor:
                    sql = """
                        SELECT HOUR(search_time) AS hour_of_day, COUNT(*) as total_searches 
                        FROM search_logs 
                        GROUP BY hour_of_day 
                        ORDER BY total_searches DESC 
                        LIMIT 5
                    """
                    cursor.execute(sql)
                    peak_times = cursor.fetchall()

                    if peak_times:
                        reply_text = "⏰ สถิติช่วงเวลาที่มีการใช้งานสูงสุด:\n\n"
                        for i, row in enumerate(peak_times):
                            h = row['hour_of_day']
                            reply_text += f"{i+1}. ช่วง {h:02d}:00 - {h:02d}:59 น. (ใช้งาน {row['total_searches']} ครั้ง)\n"
                    else:
                        reply_text = "ยังไม่มีข้อมูลสถิติเวลาการใช้งานค่ะ"

                    line_bot_api.reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token, 
                        messages=[TextMessage(text=reply_text)]
                    ))
            except Exception as e:
                print("Error fetching peak times:", e)
            finally:
                if 'conn' in locals(): conn.close()
            return
        
        # ================= 8 EVALUATION (ปล่อยให้เว็บ LINE OA ส่งรูปแทน) =================
        elif user_msg in ["ประเมิน", "ประเมินระบบ"]:
            return # สั่ง return ทิ้งไปเลย เพื่อให้ Python เงียบ แล้วปล่อยให้ LINE Manager ทำงาน



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