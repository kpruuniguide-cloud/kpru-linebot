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

def get_service_data(user_msg):
    """ค้นหาข้อมูลงานบริการแบบฉลาด"""
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
    """ค้นหาข้อมูลตึกแบบครอบจักรวาล (คืนค่ากลับมาทั้งหมดที่หาเจอ)"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM locations WHERE building_no = %s OR common_name LIKE %s OR official_name LIKE %s"
            cursor.execute(sql, (keyword, f"%{keyword}%", f"%{keyword}%"))
            buildings = cursor.fetchall()
            
            if not buildings:
                return None
                
            if len(buildings) > 1 and "เก่า" not in keyword:
                filtered_buildings = []
                for b in buildings:
                    official = b['official_name'] or ""
                    common = b['common_name'] or ""
                    if "เก่า" not in official and "เก่า" not in common:
                        filtered_buildings.append(b)
                if filtered_buildings:
                    return filtered_buildings
            
            return buildings
            
    except Exception as e:
        print(f"Building DB Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

def get_building_by_id(building_id):
    """ค้นหาข้อมูลตึกโดยใช้ ID โดยตรง"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM locations WHERE location_id = %s LIMIT 1"
            cursor.execute(sql, (building_id,))
            return cursor.fetchone()
    except Exception as e:
        print(f"Building ID Query Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

# ================== MESSAGE BUILDER ==================

def create_building_flex(data):
    """สร้าง Flex Message สำหรับตึก (การ์ดรูปภาพ)"""
    if data.get("image_url"):
        img_url = f"{GITHUB_IMAGE_BASE}{data['image_url']}"
    else:
        img_url = "https://www.kpru.ac.th/th/images/logo-kpru.png"
        
    building_no = data['building_no'] if data.get('building_no') else ""
    b_text = f"อาคาร {building_no}".strip() if building_no else data['official_name']
    
    return {
        "type": "bubble",
        "hero": {
            "type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"
        },
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
                {
                    "type": "button",
                    "action": {
                        "type": "uri", 
                        "label": "เปิดแผนที่ (Google Maps)",
                        "uri": f"https://www.google.com/maps/search/?api=1&query={data['latitude']},{data['longitude']}"
                    },
                    "style": "primary", "color": "#5482B4"
                }
            ]
        }
    }

def create_service_flex(service_data, building_data):
    """สร้าง Flex Message สำหรับงานบริการ"""
    if building_data and building_data.get("image_url"):
        img_url = f"{GITHUB_IMAGE_BASE}{building_data['image_url']}"
    else:
        img_url = "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    building_name = building_data['official_name'] if building_data else "ไม่ระบุอาคาร"
    building_no = building_data['building_no'] if building_data and building_data.get('building_no') else ""
    b_text = f"อาคาร {building_no} {building_name}".strip() if building_no else building_name
    
    latitude = building_data['latitude'] if building_data else 16.4537572
    longitude = building_data['longitude'] if building_data else 99.5158255

    return {
        "type": "bubble",
        "hero": {
            "type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"
        },
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {
                    "type": "text", 
                    "text": service_data['service_name'], 
                    "weight": "bold", "size": "xl", "wrap": True
                },
                {
                    "type": "text", 
                    "text": f"สถานที่: {b_text}",
                    "weight": "bold", "size": "md", "color": "#5482B4", "wrap": True, "margin": "md"
                }
            ]
        },
        "footer": {
            "type": "box", "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri", 
                        "label": "เปิดแผนที่ (Google Maps)",
                        "uri": f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
                    },
                    "style": "primary", "color": "#5482B4"
                }
            ]
        }
    }

def create_detail_flex(title, description):
    """สร้าง Flex Message การ์ดแยกสำหรับแสดงรายละเอียด"""
    raw_desc = description or ""
    formatted_desc = raw_desc.replace('\\n', '\n').strip()
    
    return {
        "type": "bubble",
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {
                    "type": "text", 
                    "text": "รายละเอียด", 
                    "weight": "bold", 
                    "size": "lg", 
                    "color": "#5482B4"
                },
                {
                    "type": "text", 
                    "text": title, 
                    "size": "xs", 
                    "color": "#999999", 
                    "wrap": True,
                    "margin": "sm"
                },
                {
                    "type": "separator", 
                    "margin": "md"
                },
                {
                    "type": "text", 
                    "text": formatted_desc, 
                    "wrap": True, 
                    "size": "sm", 
                    "margin": "md"
                }
            ]
        }
    }

# ================== FLASK ROUTES ==================

# 🟢 เพิ่มหน้า Home เพื่อให้ Render ตรวจสอบว่าบอททำงานปกติ (แก้ 404 Error)
@app.route("/")
def home():
    return "KPRU UniGuide Bot is running successfully!", 200

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    handler.handle(body, signature)
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg = event.message.text.strip()
    clean_msg = user_msg.replace(" ", "")
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        # --- ตัวแยกแยะเจตนา (Intent Checker) ---
        is_building_only = False
        if clean_msg.isdigit():
            is_building_only = True
        elif any(clean_msg.startswith(prefix) for prefix in ["ตึก", "อาคาร", "หอ", "ศูนย์"]):
            is_building_only = True

        def send_service_response(s_data):
            b_data = get_building_by_id(s_data['location_id'])
            if b_data:
                flex_content = create_service_flex(s_data, b_data)
                
                raw_details = s_data['service_details'] or ""
                if raw_details.strip() not in ["", "-"]:
                    detail_flex = create_detail_flex(s_data['service_name'], raw_details)
                    line_bot_api.reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            FlexMessage(alt_text=f"บริการ: {s_data['service_name']}", contents=FlexContainer.from_dict(flex_content)),
                            FlexMessage(alt_text=f"รายละเอียด: {s_data['service_name']}", contents=FlexContainer.from_dict(detail_flex))
                        ]
                    ))
                else:
                    line_bot_api.reply_message(ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text=f"บริการ: {s_data['service_name']}", contents=FlexContainer.from_dict(flex_content))]
                    ))
                return True
            return False

        def send_building_response(buildings_list):
            bubbles = []
            
            for b_data in buildings_list[:5]:
                flex_msg = create_building_flex(b_data)
                bubbles.append(flex_msg)
                
                raw_desc = b_data['description'] or ""
                formatted_desc = raw_desc.replace('\\n', '\n').strip()
                
                if formatted_desc not in ["", "-", "ไม่มีรายละเอียดเพิ่มเติม"]:
                    b_title = f"อาคาร {b_data['building_no'] or ''} {b_data['official_name']}".strip()
                    detail_flex = create_detail_flex(b_title, formatted_desc)
                    bubbles.append(detail_flex)
            
            bubbles = bubbles[:10]
            
            if len(buildings_list) == 1:
                messages = []
                for b in bubbles:
                    messages.append(FlexMessage(alt_text="ข้อมูลตึก", contents=FlexContainer.from_dict(b)))
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=messages
                ))
            else:
                carousel_flex = {
                    "type": "carousel",
                    "contents": bubbles
                }
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[FlexMessage(alt_text="ผลการค้นหา (ปัดเพื่อดูเพิ่มเติม)", contents=FlexContainer.from_dict(carousel_flex))]
                ))

        # --- ลำดับการทำงาน (Logic) ---
        if is_building_only:
            buildings = get_building_data(user_msg)
            if buildings:
                send_building_response(buildings)
                return
            
            service = get_service_data(user_msg)
            if service and send_service_response(service):
                return
        else:
            service = get_service_data(user_msg)
            if service and send_service_response(service):
                return
            
            buildings = get_building_data(user_msg)
            if buildings:
                send_building_response(buildings)
                return

        line_bot_api.reply_message(ReplyMessageRequest