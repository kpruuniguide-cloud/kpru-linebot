import os
import pymysql
from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage, FlexContainer,
    QuickReply, QuickReplyItem, MessageAction, LocationAction
)
from linebot.v3.webhooks import (
    MessageEvent, 
    TextMessageContent,
    LocationMessageContent,
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
            results = cursor.fetchall()
            
            if not results:
                return None
                
            exact_matches = []
            for row in results:
                b_no = str(row.get('building_no', '')).strip()
                common_names_str = str(row.get('common_name') or '')
                aliases = [x.strip() for x in common_names_str.split(',')]
                
                if keyword == b_no or keyword in aliases or keyword == str(row.get('official_name')):
                    exact_matches.append(row)
            
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

def save_search_log(keyword, is_found):
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            # ใช้โค้ดนี้เพื่อบันทึกคำค้นหา และสถานะ (1=เจอ, 0=ไม่เจอ)
            sql = "INSERT INTO search_logs (keyword, is_found) VALUES (%s, %s)"
            cursor.execute(sql, (keyword, is_found))
            conn.commit()
    except Exception as e:
        print("Error saving log:", e)
    finally:
        if 'conn' in locals(): conn.close()

# ================== FLEX MESSAGE BUILDERS ==================
def create_building_flex(data):
    # 🟢 เปลี่ยนจาก image_url เป็น image_name ให้ตรงกับฐานข้อมูลใหม่
    img_url = f"{GITHUB_IMAGE_BASE}{data['image_name']}" if data and data.get("image_name") else "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    body_contents = []
    
    building_no = data.get('building_no')
    if building_no and str(building_no).strip() not in ["", "-", "None"]:
        body_contents.append({
            "type": "text", 
            "text": f"หมายเลขอาคาร {building_no}", 
            "size": "xs", 
            "color": "#162660", # Royal Blue
            "weight": "bold"
        })
        
    body_contents.append({
        "type": "text", 
        "text": data.get('official_name', 'ไม่ทราบชื่ออาคาร'), 
        "weight": "bold", 
        "size": "md", 
        "wrap": True, 
        "color": "#162660" # Royal Blue
    })
    
    body_contents.append({
        "type": "text", 
        "text": data.get('description', 'ไม่มีข้อมูลรายละเอียด'), 
        "size": "xs", 
        "color": "#708090", 
        "wrap": True, 
        "margin": "sm"
    })

    return {
        "type": "bubble",
        "styles": {
            "body": {"backgroundColor": "#FFFFFF"},   
            "footer": {"backgroundColor": "#FFFFFF"}  
        },
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
                    "type": "box", "layout": "vertical", 
                    "backgroundColor": "#162660", # Royal Blue
                    "cornerRadius": "md", "paddingAll": "10px",
                    "action": {
                        "type": "uri", 
                        "label": "นำทางไปที่นี่", 
                        "uri": f"https://www.google.com/maps/dir/?api=1&destination={data.get('latitude', '')},{data.get('longitude', '')}&travelmode=walking"
                    },
                    "contents": [{
                        "type": "text", "text": "🗺️ นำทางไปที่นี่", 
                        "color": "#FFFFFF", # White
                        "weight": "bold", "size": "sm", "align": "center"
                    }]
                }
            ]
        }
    }

def create_service_flex(service, building):
    # 🟢 เปลี่ยนจาก image_url เป็น image_name ให้ตรงกับฐานข้อมูลใหม่
    img_url = f"{GITHUB_IMAGE_BASE}{building['image_name']}" if building and building.get("image_name") else "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    link_url = service.get('external_link')
    if not link_url or str(link_url).strip() == "":
        link_url = "https://www.kpru.ac.th"

    return {
        "type": "bubble",
        "styles": {
            "body": {"backgroundColor": "#FFFFFF"},   
            "footer": {"backgroundColor": "#FFFFFF"}  
        },
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
                    "color": "#162660", # Royal Blue
                    "wrap": True
                },
                {
                    "type": "box", "layout": "vertical", "spacing": "sm",
                    "contents": [
                        {
                            "type": "box", "layout": "baseline", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "📍 สถานที่:", "color": "#162660", "size": "xs", "weight": "bold", "flex": 2}, 
                                {"type": "text", "text": building.get('official_name', 'ไม่ระบุ') if building else 'ไม่ระบุ', "wrap": True, "color": "#162660", "size": "xs", "flex": 6} 
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
                    "type": "box", "layout": "vertical", 
                    "backgroundColor": "#BBDEFB", 
                    "cornerRadius": "md", "paddingAll": "10px",
                    "action": {"type": "uri", "label": "ข้อมูลเพิ่มเติม", "uri": link_url},
                    "contents": [{"type": "text", "text": "🌐 ข้อมูลเพิ่มเติม", "color": "#162660", "weight": "bold", "size": "sm", "align": "center"}] 
                },
                {
                    "type": "box", "layout": "vertical", 
                    "backgroundColor": "#162660", # Royal Blue
                    "cornerRadius": "md", "paddingAll": "10px",
                    "action": {"type": "uri", "label": "นำทางไปที่นี่", "uri": f"https://www.google.com/maps/dir/?api=1&destination={building.get('latitude', '')},{building.get('longitude', '')}&travelmode=walking" if building else "#"},
                    "contents": [{"type": "text", "text": "🗺️ นำทางไปที่นี่", "color": "#FFFFFF", "weight": "bold", "size": "sm", "align": "center"}] 
                }
            ]
        }
    }

# 🟢 ฟังก์ชันสร้างการ์ดทั้งหมด

def create_map_menu_flex():
    def get_data_by_ids(id_list):
        if not id_list: return {}
        try:
            conn = pymysql.connect(**DB_CONFIG)
            with conn.cursor() as cursor:
                format_strings = ','.join(['%s'] * len(id_list))
                sql = f"SELECT location_id, building_no, display_name, official_name FROM locations WHERE location_id IN ({format_strings})"
                cursor.execute(sql, tuple(id_list))
                results = cursor.fetchall()
                return {row['location_id']: row for row in results}
        except Exception as e:
            print(f"Error fetching IDs: {e}")
            return {}
        finally:
            if 'conn' in locals(): conn.close()

    def make_list_btn(item_data):
        if not item_data: return None
        b_no = str(item_data.get('building_no', '')).strip()
        d_name = item_data.get('display_name') or item_data.get('official_name', '')
        
        if b_no not in ["", "-", "None"]:
            btn_label = f"{b_no}. {d_name}"
        else:
            btn_label = d_name

        search_text = f"อาคาร {b_no}" if b_no not in ["", "-", "None"] else d_name

        return {
            "type": "box", "layout": "horizontal", 
            "backgroundColor": "#D0E6FD", # ✅ คืนชีพสีฟ้า Powder Blue ตามที่อาจารย์ชอบครับ
            "cornerRadius": "md", "paddingAll": "10px", "margin": "xs",
            "action": {"type": "message", "label": btn_label[:40], "text": search_text},
            "contents": [
                {
                    "type": "text", "text": btn_label, "size": "xs", 
                    "color": "#162660", # ✅ ฟอนต์สีน้ำเงิน Royal Blue
                    "weight": "bold", "align": "start", "wrap": True 
                }
            ]
        }

    # === ลำดับกลุ่มหลัก 1-38 ต่อด้วย A-D (42 IDs) [cite: 13-431] ===
    main_flow_ids = [
        1, 2, 3, 4, 5, 6, 7, 8,                             # การ์ด 2 (8 ปุ่ม)
        9, 10, 11, 12, 13, 14, 15, 16, 17,                  # การ์ด 3 (9 ปุ่ม)
        18, 19, 20, 21, 22, 23, 24, 25, 26,                 # การ์ด 4 (9 ปุ่ม)
        27, 28, 29, 30, 31, 32, 33, 34, 35,                 # การ์ด 5 (9 ปุ่ม)
        36, 37, 38, 39, 40, 41, 42                          # การ์ด 6 (7 ปุ่ม)
    ]
    # === กลุ่มเสริม 74-79 (6 IDs) [cite: 727-783] ===
    extra_ids = [74, 75, 76, 77, 78, 79]   

    db_data = get_data_by_ids(main_flow_ids + extra_ids)
    img_url = f"{GITHUB_IMAGE_BASE}map_kpru.png"
    bubbles = []

    # 🟢 --- การ์ด 1: แผนที่แบบพื้นหลังเต็มใบ (Background Image) ---
    bubbles.append({
        "type": "bubble", "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "0px",
            "contents": [
                # 1. ภาพแผนที่ทำหน้าที่เป็นพื้นหลัง
                {
                    "type": "image", "url": img_url, "size": "full",
                    "aspectRatio": "1:1.1", "aspectMode": "cover"
                },
                # 2. ปุ่มกดที่ลอยอยู่ด้านบน (Overlay) บริเวณด้านล่างของการ์ด
                {
                    "type": "box", "layout": "vertical", 
                    "position": "absolute", # ✅ สั่งให้ลอยทับรูป
                    "offsetBottom": "15px", "width": "100%", "paddingAll": "15px",
                    "contents": [{
                        "type": "button", "style": "primary", 
                        "color": "#162660", "height": "sm", 
                        "action": {"type": "uri", "label": "🔍 ดูภาพขนาดเต็ม", "uri": img_url}
                    }]
                }
            ]
        }
    })

    # --- การ์ด 2: อาคาร 1-8 (Header Royal Blue) ---
    bubbles.append({
        "type": "bubble", "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#162660", "paddingAll": "15px",
            "contents": [{"type": "text", "text": "🏢 รายชื่ออาคารและสถานที่หลัก", "color": "#FFFFFF", "weight": "bold", "align": "center"}]
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "xs", "contents": [make_list_btn(db_data.get(id)) for id in main_flow_ids[0:8] if db_data.get(id)]}
    })

    # --- การ์ด 3 - 6: อาคาร 9 ถึง D (9 ปุ่ม/ใบ) [cite: 104-431] ---
    for start_idx in [8, 17, 26, 35]:
        end_idx = start_idx + 9
        current_group = main_flow_ids[start_idx:end_idx]
        if not current_group: continue
        bubbles.append({
            "type": "bubble", "size": "kilo",
            "body": {"type": "box", "layout": "vertical", "spacing": "xs", "paddingTop": "25px", "contents": [make_list_btn(db_data.get(id)) for id in current_group if db_data.get(id)]}
        })

    # --- การ์ด 7: อาคารเสริม (แยกหมวดชัดเจน) [cite: 727-783] ---
    bubbles.append({
        "type": "bubble", "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#162660", "paddingAll": "15px",
            "contents": [{"type": "text", "text": "✨ อาคารและสถานที่เสริม", "color": "#FFFFFF", "weight": "bold", "align": "center"}]
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "xs", "contents": [make_list_btn(db_data.get(id)) for id in extra_ids if db_data.get(id)]}
    })

    return {"type": "carousel", "contents": bubbles}

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
# 🟢 ระบบตอบกลับข้อความทั่วไป (Text Message Handler)
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

# 1: แผนที่มหาวิทยาลัย (อัปเดตใหม่: Carousel 8 ใบ ไม่มี Quick Reply)
        if user_msg == "Menu > แผนที่มหาวิทยาลัย":
            map_carousel = create_map_menu_flex()
            
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[FlexMessage(
                    alt_text="แผนที่และรายชื่ออาคารทั้งหมด", 
                    contents=FlexContainer.from_dict(map_carousel)
                    # ตัดบรรทัด quick_reply ออกเรียบร้อยครับ
                )]
            ))
            return   

# ================= 2 PLACE (สถานที่สำคัญ/จุดพักผ่อน) =================
        elif user_msg == "Menu > สถานที่สำคัญ/จุดพักผ่อน":
            
            def create_custom_btn(label, text_val, bg_color, text_color, margin_val="md"):
                return {
                    "type": "box", "layout": "vertical", "backgroundColor": bg_color, "cornerRadius": "lg", "paddingAll": "12px", "margin": margin_val,
                    "action": {"type": "message", "label": label, "text": text_val},
                    "contents": [{"type": "text", "text": label, "color": text_color, "weight": "bold", "size": "md", "align": "center"}]
                }

            flex_menu = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical", "paddingAll": "0px",
                    "contents": [
                        {"type": "image", "url": f"{GITHUB_IMAGE_BASE}Landmark.JPG", "size": "full", "aspectRatio": "3:4", "aspectMode": "cover", "gravity": "center"},
                        {
                            "type": "box", "layout": "vertical", "position": "absolute", "offsetTop": "10%", "offsetBottom": "10%", "offsetStart": "8%", "offsetEnd": "8%",
                            "backgroundColor": "#ffffffcc", 
                            "cornerRadius": "xl", "paddingAll": "xl",
                            "contents": [
                                {"type": "text", "text": "KPRU NAVIGATOR", "size": "xxs", "color": "#162660", "weight": "bold", "letterSpacing": "0.3em", "align": "center"}, 
                                {"type": "text", "text": "สถานที่และจุดพักผ่อน", "weight": "bold", "size": "xl", "color": "#162660", "align": "center", "wrap": True, "margin": "xs"}, 
                                {"type": "separator", "margin": "xl", "color": "#162660"}, 
                                create_custom_btn("🏛️ สถานที่สำคัญ", "ดูสถานที่สำคัญ", "#162660", "#FFFFFF", "lg"), 
                                create_custom_btn("⛲ จุดพักผ่อน", "ดูจุดพักผ่อน", "#162660", "#FFFFFF"), 
                                create_custom_btn("🏸 ออกกำลังกาย", "ดูที่ออกกำลังกาย", "#162660", "#FFFFFF") 
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
                    if "สถานที่สำคัญ" in user_msg: sql = "SELECT * FROM locations WHERE location_id IN (13, 14, 26, 36, 5)"
                    elif "จุดพักผ่อน" in user_msg: sql = "SELECT * FROM locations WHERE location_id IN (56, 60, 50)"
                    else: sql = "SELECT * FROM locations WHERE location_type = 'Exercise'"
                    cursor.execute(sql)
                    results = cursor.fetchall()
                    if results: send_building_response(results) 
                    else: line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="ยังไม่มีข้อมูลในระบบ")]))
            finally:
                if 'conn' in locals(): conn.close()
            return       
             
# ================= 3 SERVICES =================
        elif user_msg == "Menu > ค่าเทอม/สอบ/ทุน":
            
            def create_left_align_button(label, text_val):
                return {
                    "type": "box", "layout": "horizontal", 
                    "backgroundColor": "#162660", 
                    "cornerRadius": "md", "paddingAll": "12px", "margin": "xs",
                    "action": {"type": "message", "label": label, "text": text_val},
                    "contents": [{"type": "text", "text": label, "color": "#FFFFFF", "weight": "bold", "size": "sm", "align": "start"}] 
                }

            flex_menu = {
                "type": "carousel",
                "contents": [
                    {
                        "type": "bubble", 
                        "styles": {"body": {"backgroundColor": "#FFFFFF"}}, 
                        "hero": {"type": "image", "url": f"{GITHUB_IMAGE_BASE}services1.JPG", "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                        "body": {
                            "type": "box", "layout": "vertical", "paddingAll": "xl", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "การเงินและทุนการศึกษา", "weight": "bold", "size": "md", "color": "#162660", "align": "center", "lineHeight": "22px"}, 
                                {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "lg",
                                    "contents": [
                                        create_left_align_button("ชำระค่าเทอม", "ดูชำระค่าเทอม"),
                                        create_left_align_button("ทุนการศึกษา / กยศ.", "ดูทุนการศึกษา")
                                    ]
                                }
                            ]
                        }
                    },
                    {
                        "type": "bubble", 
                        "styles": {"body": {"backgroundColor": "#FFFFFF"}}, 
                        "hero": {"type": "image", "url": f"{GITHUB_IMAGE_BASE}services2.JPG", "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                        "body": {
                            "type": "box", "layout": "vertical", "paddingAll": "xl", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "การเรียนและสถานภาพ", "weight": "bold", "size": "md", "color": "#162660", "align": "center", "lineHeight": "22px"}, 
                                {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "lg",
                                    "contents": [
                                        create_left_align_button("สมัครเรียน", "ดูสมัครเรียน"), 
                                        create_left_align_button("สอบซ้อน", "ดูสอบซ้อน"),
                                        create_left_align_button("รักษาสภาพนักศึกษา", "ดูรักษาสภาพ"),
                                        create_left_align_button("เทียบโอนผลการเรียน", "ดูเทียบโอน")
                                    ]
                                }
                            ]
                        }
                    },
                    {
                        "type": "bubble",
                        "styles": {"body": {"backgroundColor": "#FFFFFF"}}, 
                        "hero": {"type": "image", "url": f"{GITHUB_IMAGE_BASE}services3.jpg", "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"},
                        "body": {
                            "type": "box", "layout": "vertical", "paddingAll": "xl", "spacing": "sm",
                            "contents": [
                                {"type": "text", "text": "สวัสดิการและบริการทั่วไป", "weight": "bold", "size": "md", "color": "#162660", "align": "center", "lineHeight": "22px"}, 
                                {"type": "box", "layout": "vertical", "spacing": "sm", "margin": "lg",
                                    "contents": [
                                        create_left_align_button("ทำบัตรนักศึกษาใหม่", "ดูทำบัตรใหม่"),
                                        create_left_align_button("ห้องพยาบาล", "ดูห้องพยาบาล"), 
                                        create_left_align_button("ประกันอุบัติเหตุ", "ดูเบิกประกัน"),
                                        create_left_align_button("แจ้งของหาย", "ดูแจ้งของหาย")  
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
                        # 🟢 เปลี่ยน image_url เป็น image_name ตรงนี้ด้วยครับ
                        sql = """
                            SELECT s.service_name, s.service_details, s.external_link, 
                                   l.official_name, l.latitude, l.longitude, l.image_name 
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
                            line_bot_api.reply_message(ReplyMessageRequest(
                                reply_token=event.reply_token, 
                                messages=[TextMessage(text="ยังไม่มีข้อมูลบริการนี้ในระบบค่ะ")]
                            ))
                finally:
                    if 'conn' in locals(): conn.close()
            return

# ================= 4 SHOPS =================
        elif user_msg == "Menu > ร้านค้า/จุดบริการ":
            def create_custom_btn(label, text_val, bg_color, text_color, margin_val="md"):
                return {
                    "type": "box", "layout": "vertical", "backgroundColor": bg_color, "cornerRadius": "lg", "paddingAll": "12px", "margin": margin_val,
                    "action": {"type": "message", "label": label, "text": text_val},
                    "contents": [{"type": "text", "text": label, "color": text_color, "weight": "bold", "size": "md", "align": "center"}]
                }
                
            flex_menu = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical", "paddingAll": "0px",
                    "contents": [
                        {"type": "image", "url": f"{GITHUB_IMAGE_BASE}Shop2.JPG", "size": "full", "aspectRatio": "3:4", "aspectMode": "cover"},
                        {
                            "type": "box", "layout": "vertical", "position": "absolute", "offsetTop": "10%", "offsetBottom": "10%", "offsetStart": "8%", "offsetEnd": "8%",
                            "backgroundColor": "#ffffffcc", 
                            "cornerRadius": "xl", "paddingAll": "xl",
                            "contents": [
                                {"type": "text", "text": "KPRU NAVIGATOR", "size": "xxs", "color": "#162660", "weight": "bold", "letterSpacing": "0.3em", "align": "center"}, 
                                {"type": "text", "text": "ร้านค้าและบริการ", "weight": "bold", "size": "xl", "color": "#162660", "align": "center", "wrap": True, "margin": "xs"}, 
                                {"type": "separator", "margin": "xl", "color": "#162660"}, 
                                create_custom_btn("ร้านกาแฟ", "ดูร้านกาแฟ", "#162660", "#FFFFFF", "lg"), 
                                create_custom_btn("ร้านถ่ายเอกสาร/บริการ", "ดูร้านบริการ", "#162660", "#FFFFFF") 
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

# ================= 5 DORMITORY =================
        elif user_msg == "Menu > หอพัก":
            
            def create_custom_btn(label, text_val, bg_color, text_color, margin_val="md"):
                return {
                    "type": "box", "layout": "vertical", "backgroundColor": bg_color, "cornerRadius": "lg", "paddingAll": "12px", "margin": margin_val,
                    "action": {"type": "message", "label": label, "text": text_val},
                    "contents": [{"type": "text", "text": label, "color": text_color, "weight": "bold", "size": "md", "align": "center"}]
                }

            flex_menu = {
                "type": "bubble",
                "body": {
                    "type": "box", "layout": "vertical", "paddingAll": "0px",
                    "contents": [
                        {"type": "image", "url": f"{GITHUB_IMAGE_BASE}Dorm2.JPG", "size": "full", "aspectRatio": "3:4", "aspectMode": "cover", "gravity": "center"},
                        {
                            "type": "box", "layout": "vertical", "position": "absolute", "offsetTop": "10%", "offsetBottom": "10%", "offsetStart": "8%", "offsetEnd": "8%",
                            "backgroundColor": "#ffffffcc", 
                            "cornerRadius": "xl", "paddingAll": "xl",
                            "contents": [
                                {"type": "text", "text": "KPRU NAVIGATOR", "size": "xxs", "color": "#162660", "weight": "bold", "letterSpacing": "0.3em", "align": "center"}, 
                                {"type": "text", "text": "เลือกประเภทหอพัก", "weight": "bold", "size": "xl", "color": "#162660", "align": "center", "wrap": True, "margin": "xs"}, 
                                {"type": "separator", "margin": "xl", "color": "#162660"}, 
                                create_custom_btn("หอพักหญิง", "ดูหอพักหญิง", "#162660", "#FFFFFF", "lg"), 
                                create_custom_btn("หอพักชาย", "ดูหอพักชาย", "#162660", "#FFFFFF"), 
                                create_custom_btn("หอพักบุคลากร/อาจารย์", "ดูหอพักบุคลากร", "#162660", "#FFFFFF") 
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
        
# ================= 6 CONTACT & EMERGENCY =================
        elif user_msg == "Menu > ติดต่อ/ฉุกเฉิน":
            flex_menu = {
                "type": "bubble", 
                "size": "mega", 
                "styles": {
                    "header": {"backgroundColor": "#162660"}, 
                    "body": {"backgroundColor": "#FFFFFF"},   
                    "footer": {"backgroundColor": "#FFFFFF", "separator": True} 
                },
                "header": {
                    "type": "box", "layout": "vertical", "paddingAll": "lg",
                    "contents": [{"type": "text", "text": "📞 สายด่วนฉุกเฉิน", "color": "#FFFFFF", "weight": "bold", "size": "md", "align": "center"}] 
                },
                "body": {
                    "type": "box", "layout": "vertical", "spacing": "md", "paddingAll": "lg",
                    "contents": [
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🚨 หัวหน้ารปภ.", "weight": "bold", "color": "#162660", "size": "sm", "flex": 5}, 
                                {"type": "text", "text": "093-923-8526", "color": "#162660", "size": "sm", "weight": "bold", "align": "end", "flex": 6} 
                            ]
                        },
                        {"type": "separator"},
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🏥 ห้องพยาบาล", "weight": "bold", "color": "#162660", "size": "sm", "flex": 4},
                                {"type": "text", "text": "055-706555 ต่อ 1360", "color": "#162660", "size": "xs", "align": "end", "flex": 7}
                            ]
                        },
                        {"type": "separator"},
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "👮 ป้อมยาม(หลัง)", "weight": "bold", "color": "#162660", "size": "sm", "flex": 5},
                                {"type": "text", "text": "055-706555 ต่อ 7909", "color": "#162660", "size": "xs", "align": "end", "flex": 7}
                            ]
                        },
                        {"type": "separator"},
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "👮 ป้อมยาม(หน้า)", "weight": "bold", "color": "#162660", "size": "sm", "flex": 5},
                                {"type": "text", "text": "055-706555 ต่อ 7910", "color": "#162660", "size": "xs", "align": "end", "flex": 7}
                            ]
                        }
                    ]
                },
                "footer": {
                    "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "lg",
                    "contents": [
                        {
                            "type": "box", "layout": "vertical", 
                            "backgroundColor": "#162660", 
                            "cornerRadius": "md", "paddingAll": "10px",
                            "action": {"type": "uri", "label": "เว็บไซต์มหาวิทยาลัย", "uri": "https://www.kpru.ac.th"},
                            "contents": [{"type": "text", "text": "🌐 เว็บไซต์มหาวิทยาลัย", "color": "#FFFFFF", "weight": "bold", "size": "sm", "align": "center"}] 
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
        if user_msg == "Admin>ดูสถิติ":
            try:
                connection = pymysql.connect(**DB_CONFIG)
                with connection.cursor() as cursor:
                    sql = """
                        SELECT keyword, COUNT(*) as search_count, MAX(is_found) as found_status
                        FROM search_logs 
                        GROUP BY keyword 
                        ORDER BY search_count DESC 
                        LIMIT 10
                    """
                    cursor.execute(sql)
                    top_keywords = cursor.fetchall()
                
                connection.close()

                if top_keywords:
                    reply_text = "📊 สถิติ 10 อันดับคำค้นหาสูงสุด\n\n"
                    for index, row in enumerate(top_keywords, start=1):
                        status_icon = "✅ เจอ" if row['found_status'] == 1 else "❌ ไม่เจอ"
                        reply_text += f"{index}. {row['keyword']} ({row['search_count']} ครั้ง) [{status_icon}]\n"
                else:
                    reply_text = "📊 ยังไม่มีข้อมูลประวัติการค้นหาในระบบค่ะ"

                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_text)]
                    ))
                return

            except Exception as e:
                print(f"Database Error (Admin Stats): {e}")
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="❌ ไม่สามารถเชื่อมต่อฐานข้อมูลเพื่อดึงสถิติได้")]
                    ))
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
                        LIMIT 10
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
        
        # ================= 8 EVALUATION =================
        elif user_msg in ["ประเมิน", "ประเมินระบบ", "แบบประเมิน", "เสนอแนะ"]:
            return 

        # ==========================================
        # 💬 ทักทายและพูดคุยทั่วไป (Conversational Reply)
        # ==========================================
        common_quick_reply = QuickReply(
            items=[
                QuickReplyItem(action=LocationAction(label="ฉันอยู่ตรงไหน")),
                QuickReplyItem(action=MessageAction(label="อาคาร 1", text="อาคาร 1")),
                QuickReplyItem(action=MessageAction(label="อาคาร 14", text="อาคาร 14")),
                QuickReplyItem(action=MessageAction(label="ตึกกระป๋องแป้ง", text="ตึกกระป๋องแป้ง")),
                QuickReplyItem(action=MessageAction(label="ห้องสมุด", text="ห้องสมุด")),
                QuickReplyItem(action=MessageAction(label="โรงอาหาร", text="โรงอาหาร")),
                QuickReplyItem(action=MessageAction(label="ตึก sac", text="ตึก sac")),
                QuickReplyItem(action=MessageAction(label="กยศ.", text="กยศ.")),
                QuickReplyItem(action=MessageAction(label="คณะวิทย์", text="คณะวิทย์")),
                QuickReplyItem(action=MessageAction(label="ทีปังกร", text="ทีปังกร"))
            ]
        )

        # ดักจับคำทักทาย
        greeting_words = ["สวัสดี", "ดีจ้า", "hi", "hello", "ทัก", "ดีครับ", "ดีค่ะ", "สวัสดีครับ", "สวัสดีค่ะ"]
        if any(word in user_msg.lower() for word in greeting_words):
            reply_text = "สวัสดีค่ะ! 😊 UniGuide Bot ยินดีให้บริการค่ะ มีสถานที่หรือบริการไหนใน มรภ.กำแพงเพชร ให้ฉันช่วยหาไหมคะ? พิมพ์หรือเลือกจากเมนูด้านล่างได้เลยค่ะ "
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[TextMessage(text=reply_text, quick_reply=common_quick_reply)] 
            ))
            return
            
        # ดักจับคำขอบคุณ
        thank_words = ["ขอบคุณ", "แต๊งกิ้ว", "thanks", "thank you", "ขอบใจ", "ขอบคุณครับ", "ขอบคุณค่ะ"]
        if any(word in user_msg.lower() for word in thank_words):
            reply_text_1 = "ยินดีมากๆ เลยค่ะ! 🥰 ถ้ามีอะไรให้ช่วยหาอีก เรียก UniGuide Bot ได้เสมอนะคะ"
            reply_text_2 = "เพื่อการพัฒนาบอทให้ดียิ่งขึ้น รบกวนเวลาสักนิด ช่วยทำแบบประเมินให้หน่อยนะคะ 🙏✨\n\nคลิกทำแบบประเมินที่นี่ได้เลยค่ะ \nhttps://docs.google.com/forms/d/e/1FAIpQLSdkT0CreOwVl7o8a_woCrrZ2oAQLDEvMeYOzsTUNO3idXrbUw/viewform"
            
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[
                    TextMessage(text=reply_text_1),
                    TextMessage(text=reply_text_2) 
                ]
            ))
            return
            
        # ดักจับคำด่า/คำหยาบ
        rude_words = ["ควย", "สัส","ไอ้สัส", "เหี้ย", "ไอ้เหี้ย" , "ไอ้บ้า", "โง่" , "ไอ้ควาย" , "ไอ้โง่"]
        if any(word in user_msg for word in rude_words):
            reply_text = "UniGuide Bot เป็นบอทผู้ช่วยน่ารักๆ นะคะ 🥺 พิมพ์แบบนี้ไม่น่ารักเลยนะ"
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[TextMessage(text=reply_text)]
            ))
            return

        # 🟢 เติมคอมมา (Comma) หลังคำว่า "ค้าบ", ให้เรียบร้อยแล้วครับ
        filler_words = [
            "อยากไป", "พาไปหน่อย", "พาไป", "ทางไป", "นำทางไป", "ไป","อยู่ตรงไหนครับ","อยู่ตรงไหนคะ","ค้าบ",
            "อยู่ที่ไหน", "อยู่ไหน", "ที่ไหน", "ตรงไหน", "ชั้นไหน","อยู่ตรงไหน","อยู่ไหนคะ","อยู่ไหนครับ",
            "หน่อย", "ช่วยหา", "ขอ", "ครับ", "ค่ะ", "นะคะ", "นะ", "จ๊ะ","พาฉันไปที่",
        ]
        
        search_keyword = user_msg
        for word in filler_words:
            search_keyword = search_keyword.replace(word, "")
            
        search_keyword = search_keyword.strip()

        if not search_keyword:
            search_keyword = user_msg

        # ==========================================
        # 📌 นำคำที่ทำความสะอาดแล้ว (search_keyword) ไปค้นหา
        # ==========================================
        
        buildings = get_building_data(search_keyword)
        if buildings:
            save_search_log(search_keyword, True)
            send_building_response(buildings)
            return

        service = get_service_data(search_keyword)
        if service:
            save_search_log(search_keyword, True)
            b = get_building_by_id(service.get('location_id'))
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict(create_service_flex(service, b)))]
            ))
            return

        save_search_log(search_keyword, False)
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token, 
            messages=[TextMessage(
                text=f"ไม่พบข้อมูลสถานที่/บริการนี้นะคะ🥹 ลองพิมพ์ชื่อสถานที่ หรือเลือกจากเมนูด้านล่างได้เลยค่ะ ",
                quick_reply=common_quick_reply
            )]
        ))

# ==========================================
# 📍 ระบบรับตำแหน่ง (Location Handler)
# ==========================================
@handler.add(MessageEvent, message=LocationMessageContent)
def handle_location_message(event):
    user_lat = event.message.latitude
    user_lon = event.message.longitude
    address = event.message.address or "ไม่ระบุตำแหน่ง"

    save_search_log(address, True)

    reply_text = (
        f"📍 ระบบได้รับตำแหน่งของคุณแล้ว\n\n"
        f"สถานที่ใกล้เคียง: {address}\n"
        f"พิกัด: {user_lat}, {user_lon}\n\n"
        f"คุณสามารถเลือกดูแผนที่อาคารที่ต้องการได้จากเมนู 'ค้นหาสถานที่' เพื่อให้นำทางจากจุดที่คุณอยู่ได้เลยครับ"
    )

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply_text)]
        ))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))