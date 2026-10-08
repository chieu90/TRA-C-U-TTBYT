#!/usr/bin/env python3
"""
Trang tra cứu thiết bị y tế trên vimda.moh.gov.vn — chạy trên máy:

    python3 app.py

rồi mở http://localhost:8765

Trình duyệt không gọi thẳng vimda được (bị chặn CORS), nên máy chủ nhỏ này
nhận từ khóa, tìm trên vimda rồi trả kết quả cho trang web.
"""
import argparse, json, os, re, sys, threading, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import vimda_scraper as v

PORT = int(os.environ.get("PORT", 8765))
# Trên máy chủ (Render…) đặt HOST=0.0.0.0 để nhận kết nối từ bên ngoài
HOST = os.environ.get("HOST", "127.0.0.1")
HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = 50
DETAIL_PREFIX = "https://vimda.moh.gov.vn/web/guest/van-ban-cong-bo?"
SCRIPT_RE = re.compile(r"^https://script\.google\.com/macros/s/[\w-]+/exec$")

# vimda trả 503 khi bị gọi dồn dập. Quy tắc gọi:
#  - tách hàng chờ: tìm kiếm (danh sách) không phải đợi sau hàng trăm request chi tiết
#  - giãn cách tối thiểu giữa 2 request
#  - gặp 503 thì cả app tạm nghỉ một lúc (thay vì mỗi luồng tự gọi lại liên tục)
search_slots = threading.BoundedSemaphore(2)
detail_slots = threading.BoundedSemaphore(2)
MIN_GAP = 0.5
gap_lock = threading.Lock()
last_call = 0.0
pause_until = 0.0


def fetch(url, kind="detail"):
    global last_call, pause_until
    slots = search_slots if kind == "search" else detail_slots
    with slots:
        for attempt in range(6):
            wait = pause_until - time.time()
            if wait > 0:
                time.sleep(wait)
            with gap_lock:
                wait = last_call + MIN_GAP - time.time()
                if wait > 0:
                    time.sleep(wait)
                last_call = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": v.UA})
                with urllib.request.urlopen(req, timeout=90, context=v.SSL_CTX) as r:
                    return r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    raise
                pause_until = max(pause_until, time.time() + 10 * (attempt + 1))
                print(f"vimda bận ({e.code}) — tạm nghỉ {10 * (attempt + 1)} giây", file=sys.stderr)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 5:
                    raise
                time.sleep(3)


detail_cache = {}
if os.path.exists(os.path.join(HERE, v.CACHE_FILE)):
    try:
        detail_cache.update(json.load(open(os.path.join(HERE, v.CACHE_FILE), encoding="utf-8")))
    except Exception:
        pass


search_cache = {}  # (field, q, page) -> (thời điểm, kết quả); giữ 10 phút để không gọi lại vimda


def search_one(field, q, page, size=PAGE):
    key = (field, q.lower(), page, size)
    hit = search_cache.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    a = argparse.Namespace(keyword=None, cong_ty=None, ten_tbyt=None, tu=None, den=None)
    setattr(a, field, q)
    total, rows = v.parse_list(fetch(v.list_url(page, a, delta=size), "search"))
    for r in rows:
        r["_khop"] = field
    if total is None:  # vimda không in tổng khi chỉ có 1 trang
        total = len(rows) + (page - 1) * size
    if len(search_cache) > 500:  # chặn bộ nhớ phình ra khi nhiều người dùng
        search_cache.clear()
    search_cache[key] = (time.time(), (total, rows))
    return total, rows


def search(q, mode, page, size=PAGE):
    fields = {"san_pham": ["ten_tbyt"], "cong_ty": ["cong_ty"], "so": ["keyword"]}.get(
        mode, ["ten_tbyt", "cong_ty"])
    with ThreadPoolExecutor(len(fields)) as ex:
        results = list(ex.map(lambda f: search_one(f, q, page, size), fields))
    seen, rows, total, more = set(), [], 0, False
    for t, rs in results:
        total += t
        more = more or t > page * size
        for r in rs:
            key = (r["Mã hồ sơ"], r["Số công bố / số lưu hành"])
            if key not in seen:
                seen.add(key)
                rows.append(r)
    rows.sort(key=lambda r: "/".join(reversed(r["Ngày công bố"].split("/"))), reverse=True)
    return {"total": total, "more": more, "rows": rows}


cache_lock = threading.Lock()
unsaved = 0


def save_cache():
    path = os.path.join(HERE, v.CACHE_FILE)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(detail_cache, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def detail(url):
    global unsaved
    if url not in detail_cache:
        d = v.parse_detail(fetch(url))
        with cache_lock:
            detail_cache[url] = d
            unsaved += 1
            if unsaved >= 20:  # ghi xuống đĩa để khởi động lại không phải tải lại
                save_cache()
                unsaved = 0
    return detail_cache[url]


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # trình duyệt đã đóng/tải lại trang

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = {k: x[0] for k, x in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/":
                self.send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8")
            elif u.path == "/api/search":
                q = p.get("q", "").strip()
                if not q:
                    return self.send(400, {"error": "Chưa nhập từ khóa"})
                size = min(200, max(10, int(p.get("size", PAGE))))
                self.send(200, search(q, p.get("mode", "tat_ca"), max(1, int(p.get("page", 1))), size))
            elif u.path == "/apps-script.gs":
                self.send(200, open(os.path.join(HERE, "google_apps_script.gs"), "rb").read(), "text/plain; charset=utf-8")
            elif u.path == "/api/detail":
                url = p.get("url", "")
                if not url.startswith(DETAIL_PREFIX):  # chỉ cho phép link chi tiết của vimda
                    return self.send(400, {"error": "Link không hợp lệ"})
                self.send(200, detail(url))
            else:
                self.send(404, {"error": "Không tìm thấy"})
        except Exception as e:
            self.send(502, {"error": f"vimda không phản hồi ({e}). Thử lại sau ít giây."})

    def do_POST(self):
        # Chuyển dữ liệu sang Apps Script của người dùng (trình duyệt gọi thẳng sẽ bị chặn CORS)
        if self.path != "/api/sheets":
            return self.send(404, {"error": "Không tìm thấy"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            url = body.get("url", "").strip()
            if not SCRIPT_RE.match(url):
                return self.send(400, {"error": "URL Apps Script phải có dạng https://script.google.com/macros/s/…/exec"})
            req = urllib.request.Request(url, data=json.dumps(body["payload"], ensure_ascii=False).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120, context=v.SSL_CTX) as r:
                text = r.read().decode("utf-8", "replace")
            try:
                res = json.loads(text)
            except ValueError:
                return self.send(502, {"error": "Apps Script không trả về JSON — kiểm tra lại đã triển khai dạng Ứng dụng web, quyền truy cập 'Bất kỳ ai'."})
            self.send(200 if res.get("ok") else 502, res)
        except Exception as e:
            self.send(502, {"error": f"Không gửi được tới Google Sheets ({e})"})

    def log_message(self, fmt, *args):
        if "/api/detail" not in self.path:  # bỏ log từng hồ sơ chi tiết cho đỡ rối
            sys.stderr.write("%s\n" % (fmt % args))


if __name__ == "__main__":
    print(f"Mở trình duyệt: http://localhost:{PORT}  (Ctrl+C để dừng)", file=sys.stderr, flush=True)
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with cache_lock:
            save_cache()
