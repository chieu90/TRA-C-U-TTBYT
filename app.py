#!/usr/bin/env python3
"""
Trang tra cứu thiết bị y tế trên vimda.moh.gov.vn — chạy trên máy:

    python3 app.py

rồi mở http://localhost:8765

Trình duyệt không gọi thẳng vimda được (bị chặn CORS), nên máy chủ nhỏ này
nhận từ khóa, tìm trên vimda rồi trả kết quả cho trang web.
"""
import argparse, gzip, json, os, re, sys, threading, time, unicodedata, urllib.error, urllib.parse, urllib.request
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

# vimda giới hạn theo IP (đo thực tế): cho gửi dồn ~12-15 request, sau đó ~1 request / 2-3 giây;
# vượt mức thì trả 503 vài giây. Dùng "xô token" mô phỏng đúng giới hạn đó để không bị chặn:
#  - xô chứa tối đa BURST lượt, tự đầy lại REFILL lượt/giây
#  - tìm kiếm (danh sách) được ưu tiên: request chi tiết phải chừa lại RESERVE lượt cho tìm kiếm
#  - vẫn gặp 503 thì xả xô và cả app nghỉ một lúc
BURST, REFILL, RESERVE = 10.0, 0.4, 2.0
search_slots = threading.BoundedSemaphore(2)
detail_slots = threading.BoundedSemaphore(3)
bucket_lock = threading.Lock()
tokens, last_refill = BURST, time.time()
pause_until = 0.0


def take_token(kind):
    global tokens, last_refill
    need = 1.0 if kind == "search" else 1.0 + RESERVE
    while True:
        with bucket_lock:
            now = time.time()
            if now >= pause_until:
                tokens = min(BURST, tokens + (now - last_refill) * REFILL)
                last_refill = now
                if tokens >= need:
                    tokens -= 1.0
                    return
            wait = max(pause_until - now, (need - tokens) / REFILL, 0.05)
        time.sleep(min(wait, 1.0))


def exclusive(url):
    # p_p_state=exclusive: vimda chỉ trả phần dữ liệu, bỏ khung giao diện -> nhẹ & nhanh hơn
    return url.replace("p_p_state=normal", "p_p_state=exclusive", 1)


def fetch(url, kind="detail"):
    global pause_until, tokens, last_refill
    slots = search_slots if kind == "search" else detail_slots
    with slots:
        for attempt in range(6):
            take_token(kind)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": v.UA, "Accept-Encoding": "gzip"})
                with urllib.request.urlopen(req, timeout=90, context=v.SSL_CTX) as r:
                    data = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                return data.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    raise
                with bucket_lock:
                    tokens, last_refill = 0.0, time.time() + 5 * (attempt + 1)
                    pause_until = max(pause_until, time.time() + 5 * (attempt + 1))
                print(f"vimda bận ({e.code}) — tạm nghỉ {5 * (attempt + 1)} giây", file=sys.stderr)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 5:
                    raise
                time.sleep(3)


def detail_key(url):
    """Khoá bộ nhớ đệm theo mã hồ sơ + mã văn bản (link chi tiết có nhiều tham số thay đổi theo lần tìm)."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    ho_so, van_ban = q.get(v.NS + "hoSoId", [""])[0], q.get(v.NS + "vanBanId", [""])[0]
    return f"{ho_so}|{van_ban}" if ho_so and van_ban else url


def detail_url(url):
    """Link chi tiết gọn: chỉ giữ các tham số cần thiết, dạng exclusive."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    keep = {k: q[k][0] for k in ("hoSoId", "vanBanId", "doanhNghiepId", "jspPage")
            for k in [v.NS + k] if k in q}
    if len(keep) < 4:
        return exclusive(url)
    return DETAIL_PREFIX + urllib.parse.urlencode({
        "p_p_id": "vanbancongbo_WAR_trangthietbiyteportlet", "p_p_lifecycle": "0",
        "p_p_state": "exclusive", "p_p_mode": "view", **keep})


CACHE_PATH = os.path.join(HERE, "app_cache.json")
detail_cache = {}
for path in (os.path.join(HERE, v.CACHE_FILE), CACHE_PATH):  # nạp cả bộ đệm của script tải hàng loạt
    if os.path.exists(path):
        try:
            for k, d in json.load(open(path, encoding="utf-8")).items():
                detail_cache[detail_key(k) if k.startswith("http") else k] = d
        except Exception:
            pass


# ---------- Kho dữ liệu dựng sẵn (build_index.py) -> tìm theo hãng / chủ sở hữu ----------
INDEX_FILE = os.path.join(HERE, "data", "tbyt_index.json.gz")
DETAIL_FIELDS = ("Tên thương mại", "Hãng / cơ sở sản xuất", "Nước sản xuất", "Chủ sở hữu")


def norm(s):
    s = unicodedata.normalize("NFD", s or "").replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


index_rows, index_maker, index_info = [], [], {"count": 0, "built": None}
if os.path.exists(INDEX_FILE):
    try:
        data = json.load(gzip.open(INDEX_FILE, "rt", encoding="utf-8"))
        cols = data["cols"]
        for a in data["rows"]:
            r = dict(zip(cols, a))
            index_rows.append(r)
            index_maker.append(norm(r["Hãng / cơ sở sản xuất"] + " | " + r["Chủ sở hữu"]))
            detail_cache.setdefault(detail_key(r["Link chi tiết"]), {k: r.get(k, "") for k in DETAIL_FIELDS})
        index_info = {"count": len(index_rows), "built": data.get("built")}
        print(f"Đã nạp kho dữ liệu: {len(index_rows):,} hồ sơ (cập nhật {data.get('built')})", file=sys.stderr)
    except Exception as e:
        print(f"Không nạp được kho dữ liệu: {e}", file=sys.stderr)


def search_maker(q, page, size):
    """Tìm trong kho dựng sẵn theo hãng sản xuất / chủ sở hữu (không cần gọi vimda)."""
    nq = norm(q.strip())
    hits = [i for i, m in enumerate(index_maker) if nq in m]
    part = hits[(page - 1) * size: page * size]
    rows = []
    for i in part:
        r = dict(index_rows[i])
        r["_d"] = {k: r.pop(k, "") for k in DETAIL_FIELDS}
        rows.append(r)
    return {"total": len(hits), "more": len(hits) > page * size, "rows": rows, "exact": True}


search_cache = {}  # (field, q, page, size) -> (thời điểm, kết quả); giữ 30 phút để không gọi lại vimda


def search_one(field, q, page, size=PAGE):
    key = (field, q.lower(), page, size)
    hit = search_cache.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    a = argparse.Namespace(keyword=None, cong_ty=None, ten_tbyt=None, tu=None, den=None)
    setattr(a, field, q)
    total, rows = v.parse_list(fetch(exclusive(v.list_url(page, a, delta=size)), "search"))
    for r in rows:
        r["_khop"] = field
    if total is None:  # vimda không in tổng khi chỉ có 1 trang
        total = len(rows) + (page - 1) * size
    if len(search_cache) > 500:  # chặn bộ nhớ phình ra khi nhiều người dùng
        search_cache.clear()
    search_cache[key] = (time.time(), (total, rows))
    return total, rows


def search(q, mode, page, size=PAGE):
    if mode == "hang":
        return search_maker(q, page, size)
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
    # gắn sẵn hãng sản xuất nếu đã có trong bộ nhớ đệm / kho -> trang hiện ngay, khỏi gọi vimda
    rows = [dict(r, _d=detail_cache[k]) if (k := detail_key(r["Link chi tiết"])) in detail_cache else r for r in rows]
    return {"total": total, "more": more, "rows": rows}


cache_lock = threading.Lock()
unsaved = 0


def save_cache():
    with open(CACHE_PATH + ".tmp", "w", encoding="utf-8") as f:
        json.dump(detail_cache, f, ensure_ascii=False)
    os.replace(CACHE_PATH + ".tmp", CACHE_PATH)


def detail(url):
    global unsaved
    key = detail_key(url)
    if key not in detail_cache:
        d = v.parse_detail(fetch(detail_url(url)))
        with cache_lock:
            detail_cache[key] = d
            unsaved += 1
            if unsaved >= 20:  # ghi xuống đĩa để khởi động lại không phải tải lại
                save_cache()
                unsaved = 0
    return detail_cache[key]


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
            elif u.path == "/api/info":
                self.send(200, index_info)
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
