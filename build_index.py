#!/usr/bin/env python3
"""
Xây kho dữ liệu đầy đủ từ vimda để tìm được theo hãng sản xuất / chủ sở hữu.

    python3 build_index.py           # chạy (hoặc chạy tiếp) toàn bộ: danh sách -> chi tiết -> đóng gói
    python3 build_index.py update    # chỉ lấy hồ sơ mới công bố từ lần trước rồi đóng gói
    python3 build_index.py export    # đóng gói phần đã có ra data/tbyt_index.json.gz (để đưa lên web)
    python3 build_index.py status    # xem tiến độ

Mọi thứ lưu trong thư mục index/ (ghi nối từng dòng, an toàn khi bị ngắt giữa chừng).
vimda giới hạn ~1 request / 2-3 giây cho mỗi IP, nên lần đầu mất khoảng 3 ngày.
"""
import argparse, gzip, json, os, sys, time, urllib.error, urllib.parse, urllib.request

import vimda_scraper as v

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "index")
LIST_FILE = os.path.join(DIR, "list.jsonl")
DETAIL_FILE = os.path.join(DIR, "details.jsonl")
STATE_FILE = os.path.join(DIR, "state.json")
OUT_FILE = os.path.join(HERE, "data", "tbyt_index.json.gz")
PAGE_SIZE = 200
DETAIL_PREFIX = "https://vimda.moh.gov.vn/web/guest/van-ban-cong-bo?"

# Cột trong file đóng gói (mỗi hồ sơ là 1 mảng theo đúng thứ tự này cho gọn)
COLS = ["Số công bố / số lưu hành", "Mã hồ sơ", "Thủ tục", "Ngày công bố", "Công ty công bố",
        "Tên sản phẩm (TBYT)", "Tên thương mại", "Hãng / cơ sở sản xuất", "Chủ sở hữu", "Trạng thái",
        "File công bố", "Link chi tiết"]


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ---------- gọi vimda theo đúng giới hạn: xô token tự điều chỉnh ----------
class Pacer:
    def __init__(self):
        self.burst, self.rate = 10.0, 0.4          # rate: lượt/giây, tự tăng/giảm
        self.tokens, self.last = self.burst, time.time()
        self.ok_streak = 0

    def take(self):
        while True:
            now = time.time()
            self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            time.sleep((1 - self.tokens) / self.rate)

    def ok(self):
        self.ok_streak += 1
        if self.ok_streak >= 300 and self.rate < 0.6:   # lâu không bị chặn -> nhanh lên 5%
            self.rate *= 1.05
            self.ok_streak = 0

    def blocked(self, attempt):
        self.rate = max(0.2, self.rate * 0.9)          # bị chặn -> chậm lại 10%
        self.ok_streak, self.tokens = 0, 0.0
        wait = 5 * (attempt + 1)
        log(f"vimda bận (503) — nghỉ {wait}s, tốc độ còn {self.rate * 60:.0f} hồ sơ/phút")
        time.sleep(wait)
        self.last = time.time()


pacer = Pacer()


def fetch(url):
    for attempt in range(10):
        pacer.take()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": v.UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=90, context=v.SSL_CTX) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
            pacer.ok()
            return data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            pacer.blocked(attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            log(f"lỗi mạng ({e}) — thử lại sau 15s")
            time.sleep(15)
    raise RuntimeError("vimda không phản hồi sau 10 lần thử")


# ---------- khoá & link ----------
def ids(url):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return {k: q.get(v.NS + k, [""])[0] for k in ("hoSoId", "vanBanId", "doanhNghiepId", "jspPage")}


def key_of(url):
    i = ids(url)
    return f"{i['hoSoId']}|{i['vanBanId']}" if i["hoSoId"] and i["vanBanId"] else url


def detail_url(url):
    i = ids(url)
    if not all(i.values()):
        return url.replace("p_p_state=normal", "p_p_state=exclusive", 1)
    return DETAIL_PREFIX + urllib.parse.urlencode({
        "p_p_id": "vanbancongbo_WAR_trangthietbiyteportlet", "p_p_lifecycle": "0",
        "p_p_state": "exclusive", "p_p_mode": "view", **{v.NS + k: x for k, x in i.items()}})


def list_page_url(page):
    a = argparse.Namespace(keyword=None, cong_ty=None, ten_tbyt=None, tu=None, den=None)
    return v.list_url(page, a, delta=PAGE_SIZE).replace("p_p_state=normal", "p_p_state=exclusive", 1)


def row_key(r):
    return r["Mã hồ sơ"] + "|" + r["Số công bố / số lưu hành"]


# ---------- lưu trữ ----------
def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE, encoding="utf-8"))
    return {"list_done_page": 0, "list_total": None, "list_complete": False}


def save_state(st):
    with open(STATE_FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(STATE_FILE + ".tmp", STATE_FILE)


def load_rows():
    rows = {}
    if os.path.exists(LIST_FILE):
        for line in open(LIST_FILE, encoding="utf-8"):
            try:
                r = json.loads(line)
                rows[row_key(r)] = r
            except ValueError:
                pass  # dòng cuối bị cắt dở khi tắt máy
    return rows


def load_details():
    det = {}
    # nạp sẵn những gì app / script cũ đã tải để khỏi tải lại
    for path in (os.path.join(HERE, v.CACHE_FILE), os.path.join(HERE, "app_cache.json")):
        if os.path.exists(path):
            try:
                for k, d in json.load(open(path, encoding="utf-8")).items():
                    det[key_of(k) if k.startswith("http") else k] = d
            except ValueError:
                pass
    if os.path.exists(DETAIL_FILE):
        for line in open(DETAIL_FILE, encoding="utf-8"):
            try:
                x = json.loads(line)
                det[x["k"]] = x["d"]
            except ValueError:
                pass
    return det


# ---------- các bước ----------
def crawl_list(st, rows):
    if st["list_complete"]:
        return
    page = st["list_done_page"] + 1
    with open(LIST_FILE, "a", encoding="utf-8") as f:
        while True:
            total, got = v.parse_list(fetch(list_page_url(page)))
            if total:
                st["list_total"] = total
            for r in got:
                rows[row_key(r)] = r
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            st["list_done_page"] = page
            save_state(st)
            pages = -(-(st["list_total"] or 0) // PAGE_SIZE)
            log(f"Danh sách: trang {page}/{pages} — có {len(rows):,} hồ sơ")
            if not got or page >= pages:
                break
            page += 1
    st["list_complete"] = True
    save_state(st)


def crawl_details(rows, det):
    todo = [r for r in rows.values()
            if r["Tên sản phẩm (TBYT)"] and r["Link chi tiết"] and key_of(r["Link chi tiết"]) not in det]
    todo.sort(key=lambda r: "/".join(reversed(r["Ngày công bố"].split("/"))), reverse=True)  # mới trước
    log(f"Chi tiết: cần tải {len(todo):,} hồ sơ (đã có {len(det):,})")
    t0, n = time.time(), 0
    with open(DETAIL_FILE, "a", encoding="utf-8") as f:
        for r in todo:
            k = key_of(r["Link chi tiết"])
            try:
                d = v.parse_detail(fetch(detail_url(r["Link chi tiết"])))
            except Exception as e:
                log(f"bỏ qua {r['Mã hồ sơ']}: {e}")
                continue
            det[k] = d
            f.write(json.dumps({"k": k, "d": d}, ensure_ascii=False) + "\n")
            n += 1
            if n % 100 == 0:
                f.flush()
                rate = n / (time.time() - t0) * 60
                left = (len(todo) - n) / max(rate, 0.1) / 60
                log(f"Chi tiết: {n:,}/{len(todo):,} — {rate:.0f} hồ sơ/phút — còn khoảng {left:.1f} giờ")
            if n % 2000 == 0:
                export(rows, det)  # đóng gói định kỳ để có thể đưa phần đã có lên web


def update(rows, det):
    """Lấy hồ sơ mới: đọc từ trang 1 cho đến khi gặp liền 400 hồ sơ đã có."""
    page, known_streak, new = 1, 0, 0
    with open(LIST_FILE, "a", encoding="utf-8") as f:
        while known_streak < 400:
            total, got = v.parse_list(fetch(list_page_url(page)))
            if not got:
                break
            for r in got:
                if row_key(r) in rows:
                    known_streak += 1
                else:
                    known_streak, new = 0, new + 1
                rows[row_key(r)] = r  # cập nhật cả trạng thái (còn hiệu lực / thu hồi)
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            log(f"Cập nhật: trang {page} — {new} hồ sơ mới")
            page += 1
    crawl_details(rows, det)


def export(rows, det):
    out = []
    for r in rows.values():
        if not r["Tên sản phẩm (TBYT)"]:
            continue
        d = det.get(key_of(r["Link chi tiết"]))
        if not d:
            continue
        x = dict(r, **d)
        out.append([x.get(c, "") for c in COLS])
    out.sort(key=lambda a: "/".join(reversed(a[3].split("/"))), reverse=True)
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with gzip.open(OUT_FILE + ".tmp", "wt", encoding="utf-8") as f:
        json.dump({"cols": COLS, "built": time.strftime("%d/%m/%Y %H:%M"), "rows": out}, f,
                  ensure_ascii=False, separators=(",", ":"))
    os.replace(OUT_FILE + ".tmp", OUT_FILE)
    log(f"Đã đóng gói {len(out):,} hồ sơ -> {os.path.relpath(OUT_FILE, HERE)} "
        f"({os.path.getsize(OUT_FILE) / 1e6:.1f} MB)")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    os.makedirs(DIR, exist_ok=True)
    st, rows, det = load_state(), load_rows(), load_details()
    if cmd == "status":
        with_prod = sum(1 for r in rows.values() if r["Tên sản phẩm (TBYT)"])
        done = sum(1 for r in rows.values() if r["Tên sản phẩm (TBYT)"] and key_of(r["Link chi tiết"]) in det)
        print(f"Danh sách: {len(rows):,} hồ sơ (trang {st['list_done_page']}, xong: {st['list_complete']})")
        print(f"Chi tiết: {done:,}/{with_prod:,} hồ sơ có sản phẩm")
        return
    if cmd == "export":
        return export(rows, det)
    if cmd == "update":
        update(rows, det)
    else:
        crawl_list(st, rows)
        crawl_details(rows, det)
    export(rows, det)
    log("Hoàn tất.")


if __name__ == "__main__":
    main()
