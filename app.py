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

def get_service_data(keyword):
    """ค้นหาข้อมูลงานบริการ"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM services WHERE keywords LIKE %s OR service_name LIKE %s LIMIT 1"
            cursor.execute(sql, (f"%{keyword}%", f"%{keyword}%"))
            return cursor.fetchone()
    except Exception as e:
        print(f"Service DB Error: {e}")
        return None
    finally:
        if 'conn' in locals(): conn.close()

def get_building_data(keyword):
    """ค้นหาข้อมูลพิกัดตึก"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        with conn.cursor() as cursor:
            sql = "SELECT * FROM locations WHERE building_no = %s OR common_name LIKE %s OR official_name LIKE %s LIMIT 1"
            cursor.execute(sql, (keyword, f"%{keyword}%", f"%{keyword}%"))
            return cursor.fetchone()
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

def create_flex_message(data):
    """สร้าง Flex Message สำหรับข้อมูลตึก"""
    if data.get("image_url"):
        img_url = f"{GITHUB_IMAGE_BASE}{data['image_url']}"
    else:
        img_url = "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    return {
        "type": "bubble",
        "hero": {
            "type": "image", "url": img_url, "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"
        },
        "body": {
            "type": "box", "layout": "vertical",
            "contents": [
                {"type": "text", "text": f"อาคาร {data['building_no'] or ''}", "weight": "bold", "size": "xl"},
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
    """สร้าง Flex Message สำหรับงานบริการ (ไม่มีไอคอน)"""
    if building_data and building_data.get("image_url"):
        img_url = f"{GITHUB_IMAGE_BASE}{building_data['image_url']}"
    else:
        img_url = "https://www.kpru.ac.th/th/images/logo-kpru.png"
    
    building_name = building_data['official_name'] if building_data else "ไม่ระบุอาคาร"
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
                    "text": building_name,
                    "weight": "bold", "size": "md", "color": "#5482B4", "wrap": True
                },
                {
                    "type": "text", 
                    "text": service_data['service_name'], 
                    "weight": "bold", "size": "xl", "margin": "md", "wrap": True
                },
                {"type": "separator", "margin": "md"},
                {
                    "type": "text", 
                    "text": "รายละเอียดบริการ", 
                    "size": "sm", "color": "#666666", "margin": "md", "weight": "bold"
                },
                {
                    "type": "text", 
                    "text": service_data['service_details'] or "ไม่มีรายละเอียดเพิ่มเติม", 
                    "wrap": True, "size": "sm", "margin": "xs"
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

# ================== FLASK ROUTES ==================

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
        
        # 1. ลองหาในตารางงานบริการก่อน
        service = get_service_data(user_msg)
        if service:
            building = get_building_by_id(service['location_id'])
            if building:
                flex_content = create_service_flex(service, building)
                line_bot_api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[FlexMessage(
                        alt_text=f"ข้อมูลบริการ: {service['service_name']}", 
                        contents=FlexContainer.from_dict(flex_content)
                    )]
                ))
                return

        # 2. ถ้าไม่เจอค่อยหาข้อมูลตึก
        building = get_building_data(user_msg)
        if building:
            flex_msg = create_flex_message(building)
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(
                    alt_text=f"ข้อมูลตึก: {user_msg}", 
                    contents=FlexContainer.from_dict(flex_msg)
                )]
            ))
        else:
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=f"ไม่พบข้อมูล {user_msg} กรุณาลองพิมพ์ชื่อตึกหรือบริการใหม่อีกครั้ง")]
            ))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)