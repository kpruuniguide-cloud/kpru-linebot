import os
import pymysql
import threading
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

# เปลี่ยนเป็น List เพื่อรองรับการค้นหาแบบครอบคลุม (LIKE)
location_cache = []
service_cache = []  # เก็บข้อมูลตาราง services ในหน่วยความจำ
app = Flask(__name__)

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

# ================= ฟังก์ชันโหลดข้อมูลขึ้น Cache =================
def load_locations_to_cache():
    global location_cache
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM locations")
            location_cache = cursor.fetchall()
            print(f"✅ โหลดข้อมูลตึกเข้า Cache สำเร็จ จำนวน {len(location_cache)} รายการ")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการโหลด Cache: {e}")
    finally:
        if 'conn' in locals(): conn.close()

def load_services_to_cache():
    global service_cache
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM services")
            service_cache = cursor.fetchall()
            print(f"✅ โหลดข้อมูลบริการเข้า Cache สำเร็จ จำนวน {len(service_cache)} รายการ")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการโหลด Service Cache: {e}")
    finally:
        if 'conn' in locals(): conn.close()
# =========================================================

def get_data_by_ids(id_list):
    if not id_list: return {}
    if not location_cache:
        load_locations_to_cache()
    results = {}
    for row in location_cache:
        loc_id = row.get('location_id')
        if loc_id in id_list:
            results[loc_id] = {
                'location_id': loc_id,
                'building_no': row.get('building_no'),
                'display_name': row.get('display_name'),
                'official_name': row.get('official_name')
            }
    return results

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
        "backgroundColor": "#D0E6FD", 
        "cornerRadius": "md", 
        "paddingAll": "10px", 
        "margin": "sm", 
        "action": {"type": "message", "label": btn_label[:40], "text": search_text},
        "contents": [
            {
                "type": "text", "text": btn_label, "size": "xs", 
                "color": "#162660", 
                "weight": "bold", "align": "start", "wrap": True 
            }
        ]
    }

def create_custom_btn(label, text_val, bg_color, text_color, margin_val="md"):
    return {
        "type": "box", "layout": "vertical", "backgroundColor": bg_color, "cornerRadius": "lg", "paddingAll": "12px", "margin": margin_val,
        "action": {"type": "message", "label": label, "text": text_val},
        "contents": [{"type": "text", "text": label, "color": text_color, "weight": "bold", "size": "md", "align": "center"}]
    }

def create_left_align_button(label, text_val):
    return {
        "type": "box", "layout": "horizontal", 
        "backgroundColor": "#162660", 
        "cornerRadius": "md", "paddingAll": "12px", "margin": "xs",
        "action": {"type": "message", "label": label, "text": text_val},
        "contents": [{"type": "text", "text": label, "color": "#FFFFFF", "weight": "bold", "size": "sm", "align": "start"}] 
    }

# ================= ฟังก์ชันค้นหาจาก Cache =================
def get_building_data(keyword):
    # ถ้าจู่ๆ Cache หาย ให้โหลดใหม่เผื่อเหนียว
    if not location_cache:
        load_locations_to_cache()
        
    exact_matches = []
    partial_matches = []
    
    for row in location_cache:
        b_no = str(row.get('building_no', '')).strip()
        official_name = str(row.get('official_name', ''))
        common_names_str = str(row.get('common_name') or '')
        aliases = [x.strip() for x in common_names_str.split(',')]
        
        # ค้นหาแบบตรงตัวเป๊ะๆ
        if keyword == b_no or keyword in aliases or keyword == official_name:
            exact_matches.append(row)
        # ค้นหาแบบมีคำนั้นผสมอยู่ (จำลอง LIKE ใน SQL)
        elif keyword in b_no or any(keyword in alias for alias in aliases) or keyword in official_name:
            partial_matches.append(row)
            
    if exact_matches:
        return exact_matches
    if partial_matches:
        return partial_matches
        
    return None
# =========================================================

def get_service_data(keyword):
    global service_cache
    if not service_cache:
        load_services_to_cache()
    kw_lower = keyword.lower()
    for row in service_cache:
        keywords_str = str(row.get('keywords') or '').lower()
        service_name = str(row.get('service_name') or '').lower()
        if kw_lower in keywords_str or kw_lower in service_name:
            return row
    return None

def get_building_by_id(building_id):
    # เปลี่ยนมาหาจาก Cache ด้วยเหมือนกัน
    for row in location_cache:
        if row.get('location_id') == building_id:
            return row
            
    # ถ้าไม่เจอใน Cache ค่อยไปหาใน DB
    if not location_cache:
        load_locations_to_cache()
        for row in location_cache:
            if row.get('location_id') == building_id:
                return row
    return None

def save_search_log(keyword, is_found, location_id=None, service_id=None):
    def run():
        try:
            conn = pymysql.connect(**DB_CONFIG)
            with conn.cursor() as cursor:
                sql = """
                    INSERT INTO search_logs (keyword, is_found, location_id, service_id)
                    VALUES (%s, %s, %s, %s)
                """
                cursor.execute(sql, (keyword, is_found, location_id, service_id))
                conn.commit()
        except Exception as e:
            print("Error saving log in background:", e)
        finally:
            if 'conn' in locals():
                conn.close()
                
    threading.Thread(target=run, daemon=True).start()

def create_building_flex(data):
    img_url = f"{GITHUB_IMAGE_BASE}{data['image_name']}" if data and data.get("image_name") else "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    body_contents = []
    
    building_no = data.get('building_no')
    if building_no and str(building_no).strip() not in ["", "-", "None"]:
        body_contents.append({
            "type": "text", 
            "text": f"หมายเลขอาคาร {building_no}", 
            "size": "xs", 
            "color": "#162660", 
            "weight": "bold"
        })
        
    body_contents.append({
        "type": "text", 
        "text": data.get('official_name', 'ไม่ทราบชื่ออาคาร'), 
        "weight": "bold", 
        "size": "md", 
        "wrap": True, 
        "color": "#162660" 
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
                    "backgroundColor": "#162660", 
                    "cornerRadius": "md", "paddingAll": "10px",
                    "action": {
                        "type": "uri", 
                        "label": "นำทางไปที่นี่", 
                        "uri": f"https://www.google.com/maps/dir/?api=1&destination={data.get('latitude', '')},{data.get('longitude', '')}&travelmode=walking"
                    },
                    "contents": [{
                        "type": "text", "text": "🗺️ นำทางไปที่นี่", 
                        "color": "#FFFFFF", 
                        "weight": "bold", "size": "sm", "align": "center"
                    }]
                }
            ]
        }
    }

def create_service_flex(service, building):
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
                    "color": "#162660", 
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
                    "backgroundColor": "#162660", 
                    "cornerRadius": "md", "paddingAll": "10px",
                    "action": {"type": "uri", "label": "นำทางไปที่นี่", "uri": f"https://www.google.com/maps/dir/?api=1&destination={building.get('latitude', '')},{building.get('longitude', '')}&travelmode=walking" if building else "#"},
                    "contents": [{"type": "text", "text": "🗺️ นำทางไปที่นี่", "color": "#FFFFFF", "weight": "bold", "size": "sm", "align": "center"}] 
                }
            ]
        }
    }

def create_map_menu_flex():
    main_flow_ids = [
        1, 2, 3, 4, 5, 6, 7, 8,                             
        9, 10, 11, 12, 13, 14, 15, 16, 17,                  
        18, 19, 20, 21, 22, 23, 24, 25, 26,               
        27, 28, 29, 30, 31, 32, 33, 34, 35,                 
        36, 37, 38, 39, 40, 41, 42                      
    ]
    extra_ids = [74, 75, 76, 77, 78, 79]                   
    network_ids = [80, 81]                                 
    
    db_data = get_data_by_ids(main_flow_ids + extra_ids + network_ids)
    img_url = f"{GITHUB_IMAGE_BASE}map_kpru.png"
    bubbles = []

    bubbles.append({
        "type": "bubble", "size": "kilo",
        "body": {
            "type": "box", "layout": "vertical", "paddingAll": "0px",
            "contents": [
                {
                    "type": "image", "url": img_url, "size": "full", 
                    "aspectRatio": "5:8", 
                    "aspectMode": "cover"
                },
                {
                    "type": "box", "layout": "vertical", 
                    "position": "absolute", 
                    "offsetBottom": "25px", 
                    "width": "100%", 
                    "paddingAll": "20px", 
                    "contents": [
                        {
                            "type": "button", "style": "primary", 
                            "color": "#162660", "height": "sm", 
                            "action": {"type": "uri", "label": "🔍 ดูภาพขนาดเต็ม", "uri": img_url}
                        }
                    ]
                }
            ]
        }
    })

    bubbles.append({
        "type": "bubble", "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#162660", "paddingAll": "15px",
            "contents": [{"type": "text", "text": "🏢 รายชื่ออาคารและสถานที่หลัก", "color": "#FFFFFF", "weight": "bold", "align": "center"}]
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [make_list_btn(db_data.get(id)) for id in main_flow_ids[0:8] if db_data.get(id)]}
    })

    for start_idx in [8, 17, 26, 35]:
        end_idx = start_idx + 9
        current_group = main_flow_ids[start_idx:end_idx]
        if not current_group: continue
        bubbles.append({
            "type": "bubble", "size": "kilo",
            "body": {"type": "box", "layout": "vertical", "spacing": "sm", "paddingTop": "25px", "contents": [make_list_btn(db_data.get(id)) for id in current_group if db_data.get(id)]}
        })

    bubbles.append({
        "type": "bubble", "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#162660", "paddingAll": "15px",
            "contents": [{"type": "text", "text": "✨ อาคารและสถานที่เสริม", "color": "#FFFFFF", "weight": "bold", "align": "center"}]
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [make_list_btn(db_data.get(id)) for id in extra_ids if db_data.get(id)]}
    })

    bubbles.append({
        "type": "bubble", "size": "kilo",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#162660", "paddingAll": "15px",
            "contents": [{"type": "text", "text": "🏢 หน่วยงานเครือข่าย", "color": "#FFFFFF", "weight": "bold", "align": "center"}]
        },
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": [make_list_btn(db_data.get(id)) for id in network_ids if db_data.get(id)]}
    })

    return {"type": "carousel", "contents": bubbles}

# ================= ฟังก์ชันสร้าง Flex การหาห้องเรียน =================
def create_classroom_guide_flex():
    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": f"{GITHUB_IMAGE_BASE}classroom_guide.jpg", 
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "📖 วิธีอ่านรหัสห้องเรียน",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#162660"
                },
                {
                    "type": "text",
                    "text": "รหัสห้องของมหาวิทยาลัยจะมี 5 หลัก ประกอบไปด้วย:",
                    "wrap": True,
                    "color": "#708090",
                    "size": "sm"
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🏢 2 ตัวแรก:", "weight": "bold", "color": "#162660", "size": "sm", "flex": 4},
                                {"type": "text", "text": "หมายเลขอาคาร", "size": "sm", "color": "#555555", "flex": 6}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "📶 ตัวที่ 3:", "weight": "bold", "color": "#162660", "size": "sm", "flex": 4},
                                {"type": "text", "text": "ชั้นของอาคาร", "size": "sm", "color": "#555555", "flex": 6}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🚪 2 ตัวท้าย:", "weight": "bold", "color": "#162660", "size": "sm", "flex": 4},
                                {"type": "text", "text": "ลำดับห้อง", "size": "sm", "color": "#555555", "flex": 6}
                            ]
                        }
                    ]
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": "#F3F4F6",
                    "cornerRadius": "md",
                    "paddingAll": "10px",
                    "margin": "lg",
                    "contents": [
                        {"type": "text", "text": "💡 ตัวอย่าง: รหัส 14501", "weight": "bold", "size": "sm", "color": "#162660"},
                        {"type": "text", "text": "หมายถึง อาคาร 14 ชั้น 5 ห้องที่ 01", "size": "sm", "color": "#555555", "wrap": True}
                    ]
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#162660",
                    "action": {
                        "type": "message",
                        "label": "🗺️ ค้นหาแผนที่อาคาร",
                        "text": "Menu > แผนที่มหาวิทยาลัย"
                    }
                }
            ]
        }
    }
# ================================================================

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

        if user_msg == "Menu > แผนที่มหาวิทยาลัย":
            map_carousel = create_map_menu_flex()
            
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[FlexMessage(
                    alt_text="แผนที่และรายชื่ออาคารทั้งหมด", 
                    contents=FlexContainer.from_dict(map_carousel)
                )]
            ))
            return   

        elif user_msg == "Menu > สถานที่สำคัญ/จุดพักผ่อน":
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
            if not location_cache:
                load_locations_to_cache()
            
            results = []
            if "สถานที่สำคัญ" in user_msg:
                target_ids = [13, 14, 26, 36, 5]
                results = [row for row in location_cache if row.get('location_id') in target_ids]
            elif "จุดพักผ่อน" in user_msg:
                target_ids = [56, 60, 50]
                results = [row for row in location_cache if row.get('location_id') in target_ids]
            else:
                results = [row for row in location_cache if row.get('location_type') == 'Exercise']
                
            if results:
                send_building_response(results)
            else:
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="ยังไม่มีข้อมูลในระบบ")]
                ))
            return       
             
        elif user_msg == "Menu > ค่าเทอม/สอบ/ทุน":
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
                if not service_cache:
                    load_services_to_cache()
                if not location_cache:
                    load_locations_to_cache()
                
                kw_lower = search_keyword.lower()
                results = []
                for s in service_cache:
                    keywords_str = str(s.get('keywords') or '').lower()
                    service_name = str(s.get('service_name') or '').lower()
                    if kw_lower in keywords_str or kw_lower in service_name:
                        loc_id = s.get('location_id')
                        loc = next((row for row in location_cache if row.get('location_id') == loc_id), None)
                        joined_row = {
                            'service_name': s.get('service_name'),
                            'service_details': s.get('service_details'),
                            'external_link': s.get('external_link'),
                            'official_name': loc.get('official_name') if loc else 'ไม่ระบุ',
                            'latitude': loc.get('latitude') if loc else '',
                            'longitude': loc.get('longitude') if loc else '',
                            'image_name': loc.get('image_name') if loc else ''
                        }
                        results.append(joined_row)
                
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
            return

        elif user_msg == "Menu > ร้านค้า/จุดบริการ":
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
            if not location_cache:
                load_locations_to_cache()
                
            if "ร้านกาแฟ" in user_msg:
                results = [row for row in location_cache if row.get('location_type') == 'Cafe']
            else:
                results = [row for row in location_cache if row.get('location_type') == 'services']
                
            if results:
                send_building_response(results)
            return

        elif user_msg == "Menu > หอพัก":
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
            if not location_cache:
                load_locations_to_cache()
                
            results = []
            if "หอพักหญิง" in user_msg:
                results = [row for row in location_cache if row.get('location_type') == 'Dormitory' and 'หญิง' in str(row.get('common_name') or '')]
            elif "หอพักชาย" in user_msg:
                results = [row for row in location_cache if row.get('location_type') == 'Dormitory' and 'ชาย' in str(row.get('common_name') or '')]
            else:
                results = [row for row in location_cache if row.get('location_type') == 'Dormitory' and ('บุคลากร' in str(row.get('common_name') or '') or 'อาจารย์' in str(row.get('common_name') or ''))]
                
            if results:
                send_building_response(results)
            return
        
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
                                {"type": "text", "text": "055-706555 ต่อ 1811", "color": "#162660", "size": "xs", "align": "end", "flex": 7}
                            ]
                        },
                        {"type": "separator"},
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "👮🏻‍♂️ ป้อมยาม(หลัง)", "weight": "bold", "color": "#162660", "size": "sm", "flex": 5},
                                {"type": "text", "text": "055-706555 ต่อ 7909", "color": "#162660", "size": "xs", "align": "end", "flex": 7}
                            ]
                        },
                        {"type": "separator"},
                        {
                            "type": "box", "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "👮🏻‍♀️ ป้อมยาม(หน้า)", "weight": "bold", "color": "#162660", "size": "sm", "flex": 5},
                                {"type": "text", "text": "055-706555 ต่อ 7910", "color": "#162660", "size": "xs", "align": "end", "flex": 7}
                            ]
                        },

                        {"type": "separator", "margin": "xl"},
                        {
                            "type": "box", "layout": "vertical", "margin": "lg", "spacing": "xs",
                            "contents": [
                                {"type": "text", "text": "📄 ข้อมูลผู้จัดทำ", "weight": "bold", "color": "#162660", "size": "sm"},

                                {"type": "text", "text": "ผู้พัฒนา: ศรัณย์รักษ์ กัญจน์ไพสิฐ", "color": "#555555", "size": "xs"},

                                {"type": "text", "text": "ที่ปรึกษา: อ.พรนรินทร์ สายกลิ่น", "color": "#555555", "size": "xs"},

                                {"type": "text", "text": "สาขาเทคโนโลยีสารสนเทศ", "color": "#555555", "size": "xs"},

                                {"type": "text", "text": "คณะวิทยาศาสตร์และเทคโนโลยี", "color": "#555555", "size": "xs"},

                                {
                                    "type": "text", 
                                    "text": "Email: sarunrukkan@gmail.com", 
                                    "color": "#162660", 
                                    "size": "xs",
                                    "margin": "md",
                                    "decoration": "underline",
                                    "action": {"type": "uri", "label": "email", "uri": "mailto:sarunrukkan@gmail.com"}
                                }
                            ]
                        }
                    ]
                },
                "footer": {
                    "type": "box", "layout": "vertical", "spacing": "sm", "paddingAll": "lg",
                    "contents": [
                        {
                            "type": "box", "layout": "vertical", 
                            "backgroundColor": "#6FA3E7", 
                            "cornerRadius": "md", "paddingAll": "10px",
                            "action": {"type": "uri", "label": "Facebook", "uri": "https://www.facebook.com/share/1CbnrTmLvY/?mibextid=wwXIfr"},
                            "contents": [{"type": "text", "text": "🅵 Facebook มหาวิทยาลัย", "color": "#FFFFFF", "weight": "bold", "size": "sm", "align": "center"}] 
                        },
                        {
                            "type": "box", "layout": "vertical", 
                            "backgroundColor": "#DD9663", 
                            "cornerRadius": "md", "paddingAll": "10px",
                            "action": {"type": "uri", "label": "Instagram", "uri": "http://instagram.com/KpruOfficial"},
                            "contents": [{"type": "text", "text": "🅸 Instagram มหาวิทยาลัย", "color": "#FFFFFF", "weight": "bold", "size": "sm", "align": "center"}] 
                        },
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

        if user_msg == "Admin>ดูสถิติ":
            connection = None
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
                
                if top_keywords:
                    reply_text = "📊 สถิติ 10 อันดับคำค้นหาสูงสุด\n\n"
                    for index, row in enumerate(top_keywords, start=1):
                        status_icon = "✅ เจอ" if row['found_status'] == 1 else "❌ ไม่เจอ"
                        reply_text += f"{index}. {row['keyword']} ({row['search_count']} ครั้ง) [{status_icon}]\n"
                else:
                    reply_text = "📊 ยังไม่มีข้อมูลประวัติการค้นหาในระบบค่ะ"

                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                ))
                return

            except Exception as e:
                print(f"Database Error (Admin Stats): {e}")
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="❌ ไม่สามารถเชื่อมต่อฐานข้อมูลเพื่อดึงสถิติได้")]
                ))
                return
            finally:
                if connection:
                    connection.close()

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
        
        elif user_msg in ["ประเมิน", "ประเมินระบบ", "แบบประเมิน", "เสนอแนะ"]:
            return 
            
        # ================= 9 CLASSROOM GUIDE =================
        # คลีนข้อความ ลบคำว่า "ห้อง" และช่องว่างออก เพื่อเช็คว่าเป็นเลข 5 หลักหรือไม่
        check_msg = user_msg.replace("ห้อง", "").replace(" ", "").strip()
        
        if user_msg in ["หาห้องเรียน", "วิธีหาห้องเรียน", "ดูรหัสห้อง", "ห้องเรียน", "รหัสห้อง"] or (check_msg.isdigit() and len(check_msg) == 5):
            
            # 1. สร้างการ์ดฮาวทูวิธีอ่านรหัสห้องเรียนเตรียมไว้เป็นข้อความที่ 1
            classroom_flex = create_classroom_guide_flex()
            messages_to_send = [FlexMessage(alt_text="วิธีหารหัสห้องเรียน", contents=FlexContainer.from_dict(classroom_flex))]
            
            # 2. ฟีเจอร์ลับ: ถ้าเป็นเลข 5 หลัก ให้ดึง 2 ตัวแรกไปค้นหาตึกเลย!
            if check_msg.isdigit() and len(check_msg) == 5:
                target_building = check_msg[:2]  # ดึงตัวอักษร 2 ตัวแรก (เช่น 48)
                
                # โหลดความจำมาเตรียมไว้เผื่อ Cache หาย
                if not location_cache:
                    load_locations_to_cache()
                    
                # ส่งเลข 2 ตัวแรกไปค้นหาในฐานข้อมูลสถานที่
                found_buildings = get_building_data(target_building)
                
                # ถ้าเจออาคาร ให้สร้างการ์ดตึกต่อท้ายเป็นข้อความที่ 2 ทันที
                if found_buildings:
                    bubbles = [create_building_flex(b) for b in found_buildings[:10]]
                    carousel = {"type": "carousel", "contents": bubbles}
                    messages_to_send.append(FlexMessage(alt_text="แผนที่อาคาร", contents=FlexContainer.from_dict(carousel)))
            
            # ส่งข้อความทั้งหมดกลับไปหาผู้ใช้พร้อมกัน
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=messages_to_send
            ))
            return

        common_quick_reply = QuickReply(
            items=[
                QuickReplyItem(action=LocationAction(label="ฉันอยู่ตรงไหน")),
                QuickReplyItem(action=MessageAction(label="หาห้องเรียน", text="หาห้องเรียน")),
                QuickReplyItem(action=MessageAction(label="หอประชุมทีปังกร", text="หอประชุมทีปังกร")),
                QuickReplyItem(action=MessageAction(label="ตึกอธิการบดี", text="ตึกอธิการบดี")),
                QuickReplyItem(action=MessageAction(label="รัตนอาภา", text="รัตนอาภา")),
                QuickReplyItem(action=MessageAction(label="ห้องสมุด", text="ห้องสมุด")),
                QuickReplyItem(action=MessageAction(label="โรงอาหาร", text="โรงอาหาร")),
                QuickReplyItem(action=MessageAction(label="คณะครุศาสตร์", text="อาคาร 46")),
                QuickReplyItem(action=MessageAction(label="กยศ.", text="กยศ.")),
                QuickReplyItem(action=MessageAction(label="คณะวิทย์", text="คณะวิทย์")),
                QuickReplyItem(action=MessageAction(label="ศูนย์ภาษา", text="ศูนย์ภาษา"))
            ]
        )

        greeting_words = ["สวัสดี", "ดีจ้า", "hi", "hello", "ทัก", "ดีครับ", "ดีค่ะ", "สวัสดีครับ", "สวัสดีค่ะ"]
        if any(word in user_msg.lower() for word in greeting_words):
            reply_text = "สวัสดีค่ะ! 😊 UniGuide Bot ยินดีให้บริการค่ะ มีสถานที่หรือบริการไหนใน มรภ.กำแพงเพชร ให้ฉันช่วยหาไหมคะ? พิมพ์หรือเลือกจากเมนูด้านล่างได้เลยค่ะ "
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[TextMessage(text=reply_text, quick_reply=common_quick_reply)] 
            ))
            return
    
        thank_words = ["ขอบคุณ", "แต๊งกิ้ว", "thanks", "thank you", "ขอบใจ", "ขอบคุณครับ", "ขอบคุณค่ะ"]
        if any(word in user_msg.lower() for word in thank_words):
            reply_text_1 = "ยินดีมากๆ เลยค่ะ! 🥰 ถ้ามีอะไรให้ช่วยหาอีก เรียก UniGuide Bot ได้เสมอนะคะ"
            reply_text_2 = "เพื่อการพัฒนาบอทให้ดียิ่งขึ้น รบกวนเวลาสักนิด ช่วยทำแบบประเมินให้หน่อยนะคะ 🙏✨\n\nคลิกทำแบบประเมินที่นี่ได้เลยค่ะ \nhttps://docs.google.com/forms/d/e/1FAIpQLSdkT0CreOwVl7o8a_woCrrZ2oAQLDEvMeYOzsTUNO3idXrbUw/viewform"
            
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[
                    TextMessage(text=reply_text_1),TextMessage(text=reply_text_2) 
                ]
            ))
            return

        rude_words = ["ควย", "สัส","ไอ้สัส", "เหี้ย", "ไอ้เหี้ย" , "ไอ้บ้า", "โง่" , "ไอ้ควาย" , "ไอ้โง่"]
        if any(word in user_msg for word in rude_words):
            reply_text = "UniGuide Bot เป็นบอทผู้ช่วยน่ารักๆ นะคะ 🥺 พิมพ์แบบนี้ไม่น่ารักเลยนะ"
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[TextMessage(text=reply_text)]
            ))
            return

        filler_words = [
            "อยากไป", "พาไปหน่อย", "พาไป", "ทางไป", "นำทางไป", "ไป","อยู่ตรงไหนครับ","อยู่ตรงไหนคะ","ค้าบ",
            "อยู่ที่ไหน", "อยู่ไหน", "ที่ไหน", "ตรงไหน", "ชั้นไหน","อยู่ตรงไหน","อยู่ไหนคะ","อยู่ไหนครับ",
            "หน่อย", "ช่วยหา", "ครับ", "ค่ะ", "นะคะ", "นะ", "จ๊ะ","พาฉันไปที่",
        ]
        
        search_keyword = user_msg
        for word in filler_words:
            search_keyword = search_keyword.replace(word, "")
            
        search_keyword = search_keyword.strip()

        if not search_keyword:
            search_keyword = user_msg


        service = get_service_data(search_keyword)
        if service:
            save_search_log(
                search_keyword,
                True,
                location_id=service.get("location_id"),
                service_id=service.get("service_id")
            )
            b = get_building_by_id(service.get("location_id"))
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token, 
                messages=[FlexMessage(alt_text="ข้อมูลบริการ", contents=FlexContainer.from_dict(create_service_flex(service, b)))]
            ))
            return

        buildings = get_building_data(search_keyword)
        if buildings:
            save_search_log(
                search_keyword,
                True,
                location_id=buildings[0].get("location_id")
            )
            send_building_response(buildings)
            return

        save_search_log(search_keyword, False)
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token, 
            messages=[TextMessage(
                text=f"ไม่พบข้อมูลนี้นะคะ🥹 ลองพิมพ์ชื่อสถานที่ หรือเลือกจากเมนูด้านล่างได้เลยค่ะ ",
                quick_reply=common_quick_reply
            )]
        ))


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

# โหลดข้อมูลเข้า Cache ทันทีเมื่อ Import (เพื่อให้พร้อมใน WSGI server เช่น gunicorn)
load_locations_to_cache()
load_services_to_cache()

# ================= คำสั่งรันแอป =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))