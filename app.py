import os
import pymysql
from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# ================= CONFIG =================
DB_CONFIG = {
    "host": os.environ.get('DB_HOST'),
    "port": int(os.environ.get('DB_PORT', 3306)),
    "user": os.environ.get('DB_USER'),
    "password": os.environ.get('DB_PASS'),
    "database": os.environ.get('DB_NAME'),
    "cursorclass": pymysql.cursors.DictCursor
}

GITHUB_IMAGE_BASE = "https://raw.githubusercontent.com/kpruuniguide-cloud/kpru-linebot/main/static/images/"

handler = WebhookHandler(os.environ.get('CHANNEL_SECRET'))
configuration = Configuration(access_token=os.environ.get('CHANNEL_ACCESS_TOKEN'))

# ================= DB =================
def query(sql, params=None):
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchall()
    finally:
        conn.close()

# ================= CARD =================
def build_card(d):
    img = GITHUB_IMAGE_BASE + (d.get("image_url") or "kpru_logo.png")

    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": img,
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"🏢 {d.get('official_name','-')}",
                    "weight": "bold",
                    "size": "lg",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": d.get("description","ไม่มีข้อมูล"),
                    "size": "sm",
                    "wrap": True,
                    "color": "#666666"
                }
            ]
        },
        "footer": {
            "type": "button",
            "style": "primary",
            "color": "#1E40AF",
            "action": {
                "type": "uri",
                "label": "📍 นำทาง",
                "uri": f"https://www.google.com/maps?q={d.get('latitude')},{d.get('longitude')}"
            }
        }
    }

def send_carousel(api, token, rows):
    bubbles = [build_card(r) for r in rows[:10]]
    api.reply_message(ReplyMessageRequest(
        reply_token=token,
        messages=[FlexMessage(
            alt_text="ผลการค้นหา",
            contents=FlexContainer.from_dict({
                "type": "carousel",
                "contents": bubbles
            })
        )]
    ))

# ================= ROUTE =================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

# ================= MAIN =================
@handler.add(MessageEvent, message=TextMessageContent)
def handle(event):
    msg = event.message.text.strip()

    with ApiClient(configuration) as client:
        api = MessagingApi(client)

        # ================= 1 MAP =================
        if msg == "Menu > แผนที่มหาวิทยาลัย":
            img = GITHUB_IMAGE_BASE + "kpru_map.JPG"
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(
                    alt_text="แผนที่",
                    contents=FlexContainer.from_dict({
                        "type": "bubble",
                        "hero": {
                            "type": "image",
                            "url": img,
                            "size": "full",
                            "aspectRatio": "1:1",
                            "aspectMode": "cover"
                        },
                        "footer": {
                            "type": "button",
                            "style": "primary",
                            "color": "#1E40AF",
                            "action": {
                                "type": "uri",
                                "label": "ดูภาพความละเอียดสูง",
                                "uri": img
                            }
                        }
                    })
                )]
            ))

        # ================= 2 PLACE =================
        elif msg == "Menu > สถานที่สำคัญ/จุดพักผ่อน":
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(
                    alt_text="เลือกหมวด",
                    contents=FlexContainer.from_dict({
                        "type": "bubble",
                        "body": {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [
                                {
                                    "type": "image",
                                    "url": GITHUB_IMAGE_BASE+"hero_Landmark.JPG",
                                    "size": "full",
                                    "aspectRatio": "20:13",
                                    "aspectMode": "cover"
                                },
                                {"type":"button","style":"primary","color":"#1E40AF",
                                 "action":{"type":"message","label":"🏢 สถานที่สำคัญ","text":"ดูสถานที่สำคัญ"}},
                                {"type":"button","style":"primary","color":"#1E40AF",
                                 "action":{"type":"message","label":"🌳 จุดพักผ่อน","text":"ดูจุดพักผ่อน"}},
                                {"type":"button","style":"primary","color":"#1E40AF",
                                 "action":{"type":"message","label":"🏃 ออกกำลังกาย","text":"ดูที่ออกกำลังกาย"}}
                            ]
                        }
                    })
                )]
            ))

        elif msg == "ดูสถานที่สำคัญ":
            send_carousel(api, event.reply_token, query("SELECT * FROM locations WHERE location_type='Building'"))

        elif msg == "ดูจุดพักผ่อน":
            send_carousel(api, event.reply_token, query("SELECT * FROM locations WHERE location_type='Rest_Area'"))

        elif msg == "ดูที่ออกกำลังกาย":
            send_carousel(api, event.reply_token, query("SELECT * FROM locations WHERE location_type='Exercise'"))

        # ================= 3 SERVICE =================
        elif msg == "Menu > ค่าเทอม/สอบ/ทุน":
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(
                    alt_text="บริการ",
                    contents=FlexContainer.from_dict({
                        "type": "carousel",
                        "contents": [

                            {
                                "type": "bubble",
                                "body": {
                                    "type": "box","layout":"vertical",
                                    "contents":[
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"🎓 สมัครเรียน","text":"ดูสมัครเรียน"}},
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"🏦 ทุน/กยศ","text":"ดูทุนการศึกษา"}},
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"🪪 ทำบัตร","text":"ดูทำบัตรใหม่"}},
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"💰 ค่าเทอม","text":"ดูชำระค่าเทอม"}},
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"📄 เทียบโอน","text":"ดูเทียบโอน"}}
                                    ]
                                }
                            },

                            {
                                "type": "bubble",
                                "body": {
                                    "type": "box","layout":"vertical",
                                    "contents":[
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"📝 สอบซ้อน","text":"ดูสอบซ้อน"}},
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"📊 รักษาสภาพ","text":"ดูรักษาสภาพ"}},
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"🏥 พยาบาล","text":"ดูห้องพยาบาล"}},
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"🛡️ ประกัน","text":"ดูเบิกประกัน"}},
                                        {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"📦 ของหาย","text":"ดูแจ้งของหาย"}}
                                    ]
                                }
                            }

                        ]
                    })
                )]
            ))

        elif msg.startswith("ดู"):
            keyword = msg.replace("ดู", "")
            rows = query("""
                SELECT l.*
                FROM services s
                JOIN locations l ON s.location_id = l.location_id
                WHERE s.service_name LIKE %s OR s.keywords LIKE %s
            """, (f"%{keyword}%", f"%{keyword}%"))

            if rows:
                send_carousel(api, event.reply_token, rows)
            else:
                api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="ไม่พบข้อมูลบริการ")]
                ))

        # ================= 4 SHOP =================
        elif msg == "Menu > ร้านค้า/จุดบริการ":
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(
                    alt_text="ร้านค้า",
                    contents=FlexContainer.from_dict({
                        "type": "bubble",
                        "body": {
                            "type": "box","layout":"vertical",
                            "contents":[
                                {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"☕ ร้านกาแฟ","text":"ดูร้านกาแฟ"}},
                                {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"🛠️ ร้านบริการ","text":"ดูร้านบริการ"}},
                                {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"📋 ทั้งหมด","text":"ดูร้านทั้งหมด"}}
                            ]
                        }
                    })
                )]
            ))

        elif msg == "ดูร้านกาแฟ":
            send_carousel(api, event.reply_token, query("SELECT * FROM locations WHERE location_type='Cafe'"))

        elif msg == "ดูร้านบริการ":
            send_carousel(api, event.reply_token, query("SELECT * FROM locations WHERE location_type='services'"))

        elif msg == "ดูร้านทั้งหมด":
            send_carousel(api, event.reply_token, query("SELECT * FROM locations WHERE location_type IN ('Cafe','services')"))

        # ================= 5 DORM =================
        elif msg == "Menu > หอพัก":
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(
                    alt_text="หอพัก",
                    contents=FlexContainer.from_dict({
                        "type": "bubble",
                        "body": {
                            "type": "box","layout":"vertical",
                            "contents":[
                                {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"👩 หอพักหญิง","text":"ดูหอพักหญิง"}},
                                {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"👨 หอพักชาย","text":"ดูหอพักชาย"}},
                                {"type":"button","style":"primary","color":"#1E40AF","action":{"type":"message","label":"🏢 บุคลากร","text":"ดูหอพักบุคลากร"}}
                            ]
                        }
                    })
                )]
            ))

        elif msg == "ดูหอพักหญิง":
            send_carousel(api, event.reply_token, query("SELECT * FROM locations WHERE location_type='Dormitory' AND common_name LIKE '%หญิง%'"))

        elif msg == "ดูหอพักชาย":
            send_carousel(api, event.reply_token, query("SELECT * FROM locations WHERE location_type='Dormitory' AND common_name LIKE '%ชาย%'"))

        elif msg == "ดูหอพักบุคลากร":
            send_carousel(api, event.reply_token, query("SELECT * FROM locations WHERE location_type='Dormitory' AND common_name LIKE '%อาจารย์%'"))

        # ================= 6 CONTACT =================
        elif msg == "Menu > ติดต่อ/ประเมิน":
            api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="📞 093-923-8526\n🌐 www.kpru.ac.th")]
            ))

        # ================= SEARCH =================
        else:
            rows = query("SELECT * FROM locations WHERE building_no=%s OR common_name LIKE %s OR official_name LIKE %s",
                         (msg, f"%{msg}%", f"%{msg}%"))
            if rows:
                send_carousel(api, event.reply_token, rows)
            else:
                api.reply_message(ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=f"ไม่พบข้อมูล {msg}")]
                ))

# ================= RUN =================
if __name__ == "__main__":
    app.run(port=5000)