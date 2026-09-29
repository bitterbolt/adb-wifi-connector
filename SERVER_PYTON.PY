# file-server.py
import http.server
import socketserver
import socket
import os
import webbrowser
from datetime import datetime

PORT = 3000

# Кастомный класс для красивого отображения
class Handler(http.server.SimpleHTTPRequestHandler):
    def list_directory(self, path):
        try:
            listings = super().list_directory(path)
            return listings
        except:
            return super().list_directory(path)
    
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]} {args[1]}")

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

# Запускаем сервер
handler = Handler
with socketserver.TCPServer(("0.0.0.0", PORT), handler) as httpd:
    local_ip = get_local_ip()
    
    print("\n" + "="*50)
    print("📁 ФАЙЛОВЫЙ СЕРВЕР ЗАПУЩЕН")
    print("="*50)
    print(f"Текущая папка: {os.getcwd()}")
    print("\n📱 Доступ с телефона:")
    print(f"   http://{local_ip}:{PORT}/")
    print("\n💻 Доступ локально:")
    print(f"   http://localhost:{PORT}/")
    print(f"   http://127.0.0.1:{PORT}/")
    print("\n📂 Просмотр файлов и каталогов доступен")
    print("="*50 + "\n")
    
    webbrowser.open(f"http://localhost:{PORT}/")
    httpd.serve_forever()