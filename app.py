import os
import json
import time
import threading
from flask import Flask, request, jsonify, render_template_string
from zlapi import ZaloAPI, ThreadType
from zlapi.models import Message

app = Flask(__name__)

# Biến toàn cục quản lý bot
bot_client = None
bot_thread = None
running_status = threading.Event()
logs_list = []

def log_to_web(msg):
    text = f"[{time.strftime('%H:%M:%S')}] {msg}"
    logs_list.append(text)
    print(text)
    if len(logs_list) > 100:
        logs_list.pop(0)

def parse_cookie_string(s):
    s = s.strip()
    try:
        v = json.loads(s)
        if isinstance(v, dict): return v
    except Exception: pass
    c = {}
    for p in s.split(';'):
        if '=' in p:
            k, val = p.strip().split('=', 1)
            c[k] = val
    return c

# Giao diện HTML
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Zalo Bot Render</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #111; color: #0f0; padding: 20px; }
        input, button, textarea, select { width: 100%; padding: 10px; margin: 5px 0; background: #222; color: #0f0; border: 1px solid #333; box-sizing: border-box; }
        button { background: #0a0; color: #000; font-weight: bold; cursor: pointer; }
        button.stop { background: #a00; color: #fff; }
        pre { background: #000; padding: 10px; height: 300px; overflow-y: scroll; border: 1px solid #333; }
        .row { display: flex; gap: 10px; }
    </style>
</head>
<body>
    <h2>Zalo Bot Control (Render)</h2>
    
    <h3>1. Đăng nhập</h3>
    <input type="text" id="imei" placeholder="IMEI">
    <input type="text" id="cookie" placeholder="Cookie">
    <button onclick="login()">Kết nối Zalo</button>

    <hr>
    <h3>2. Gửi tin nhắn</h3>
    <button onclick="fetchGroups()">Lấy danh sách nhóm</button>
    <select id="group_id"></select>
    <input type="text" id="msg" placeholder="Nội dung tin nhắn">
    <div class="row">
        <button onclick="startSpam()">Bắt đầu gửi</button>
        <button class="stop" onclick="stopSpam()">Dừng Bot</button>
    </div>

    <hr>
    <h3>Logs</h3>
    <pre id="logs"></pre>

    <script>
        async function login() {
            const imei = document.getElementById('imei').value;
            const cookie = document.getElementById('cookie').value;
            const res = await fetch('/login', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({imei, cookie}) });
            alert(await res.text());
        }
        async function fetchGroups() {
            const res = await fetch('/groups');
            const data = await res.json();
            const sel = document.getElementById('group_id');
            sel.innerHTML = '';
            if(data.length === 0) { sel.innerHTML = '<option>Chưa login hoặc không có nhóm</option>'; return; }
            data.forEach(g => {
                let opt = document.createElement('option');
                opt.value = g.id;
                opt.innerHTML = g.name;
                sel.appendChild(opt);
            });
        }
        async function startSpam() {
            const gid = document.getElementById('group_id').value;
            const msg = document.getElementById('msg').value;
            const res = await fetch('/start', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({gid, msg}) });
            alert(await res.text());
        }
        async function stopSpam() {
            const res = await fetch('/stop');
            alert(await res.text());
        }
        setInterval(async () => {
            const res = await fetch('/logs');
            document.getElementById('logs').innerText = await res.text();
        }, 2000);
    </script>
</body>
</html>
"""

class RenderBot(ZaloAPI):
    def __init__(self, imei, cookies):
        super().__init__('api_key', 'secret_key', imei, cookies)
    
    def get_groups(self):
        try:
            all_groups = self.fetchAllGroups()
            out = []
            gmap = getattr(all_groups, 'gridVerMap', {})
            for gid in gmap:
                try:
                    name = self.fetchGroupInfo(gid).gridInfoMap[gid].get('name', gid)
                except:
                    name = gid
                out.append({'id': gid, 'name': name})
            return out
        except Exception as e:
            log_to_web(f"Lỗi lấy nhóm: {e}")
            return []

    def send_msg(self, gid, text):
        try:
            msg = Message(text=text)
            self.send(msg, thread_id=gid, thread_type=ThreadType.GROUP)
            return True
        except Exception as e:
            log_to_web(f"Lỗi gửi: {e}")
            return False

@app.route('/')
def home():
    return render_template_string(HTML)

@app.route('/login', methods=['POST'])
def login():
    global bot_client
    data = request.json
    imei = data.get('imei')
    cookies = parse_cookie_string(data.get('cookie', ''))
    try:
        bot_client = RenderBot(imei, cookies)
        log_to_web("Kết nối Zalo thành công!")
        return "Kết nối thành công!"
    except Exception as e:
        return f"Lỗi kết nối: {e}"

@app.route('/groups', methods=['GET'])
def groups():
    if not bot_client: return jsonify([])
    return jsonify(bot_client.get_groups())

@app.route('/start', methods=['POST'])
def start():
    global bot_thread
    if not bot_client: return "Chưa kết nối Zalo!"
    
    if bot_thread and bot_thread.is_alive():
        return "Bot đang chạy rồi!"
        
    data = request.json
    gid = data.get('gid')
    msg = data.get('msg')
    
    def run():
        running_status.set()
        log_to_web(f"Bắt đầu spam vào nhóm {gid}...")
        count = 0
        while running_status.is_set():
            success = bot_client.send_msg(gid, msg)
            if success:
                count += 1
                log_to_web(f"Đã gửi {count} tin nhắn.")
            time.sleep(2) # Nghỉ 2 giây mỗi tin để tránh bị block
        log_to_web("Đã dừng bot.")

    bot_thread = threading.Thread(target=run, daemon=True)
    bot_thread.start()
    return "Đã bắt đầu gửi tin nhắn!"

@app.route('/stop', methods=['GET'])
def stop():
    running_status.clear()
    return "Đã gửi lệnh dừng."

@app.route('/logs', methods=['GET'])
def get_logs():
    return "\n".join(logs_list)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)