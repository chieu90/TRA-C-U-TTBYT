#!/usr/bin/env python3
"""
Lấy chi tiết gói thầu trên muasamcong và lọc mặt hàng theo sản phẩm quan tâm.

    python3 goi_thau.py build index/goi_thau_ids.json

- Đầu vào: file JSON {mã TBMT: {id, bidForm, name, inv, prov, close, price, pub}} — danh sách gói
  đang mở do bước quét hằng ngày (trình duyệt) lưu ra.
- Chi tiết lấy qua API công khai của muasamcong (không cần đăng nhập):
    * danh mục lô / mặt hàng / số lượng / giá lô: /api/unau/portal/ebidinv/bido-inv-biddings-sign
    * file Chương V (yêu cầu kỹ thuật):            /api/unau/edocproxy/file/share/<fileId>
- Đầu ra: data/goi_thau.json — chỉ giữ gói còn hạn có mặt hàng thuộc sản phẩm quan tâm
  (data/goi_thau_tu_khoa.json). Trang /goi-thau của app.py đọc file này.

Phần đọc file Chương V dùng thêm (nếu có): textutil (macOS), pymupdf, openpyxl, bsdtar.
Thiếu thì bỏ qua, mặt hàng vẫn có, chỉ trống cột thông số.
"""
import difflib, glob, html as html_lib, json, os, re, shutil, ssl, subprocess, sys, time, unicodedata, urllib.request
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = "https://muasamcong.mof.gov.vn"
FORMS_URL = HOST + "/api/unau/portal/ebidinv/bido-inv-biddings-sign"
FILE_URL = HOST + "/api/unau/edocproxy/file/share/"
CACHE = os.path.join(HERE, "index", "goi_thau_cache")
KW_PATH = os.path.join(HERE, "data", "goi_thau_tu_khoa.json")
OUT_PATH = os.path.join(HERE, "data", "goi_thau.json")
FORM_NAMES = {"DTRR": "Đấu thầu rộng rãi", "CHCT": "Chào hàng cạnh tranh", "CGTTRG": "Chào giá trực tuyến rút gọn",
              "CGTT": "Chào giá trực tuyến", "CDT": "Chỉ định thầu", "MSTT": "Mua sắm trực tiếp"}


def make_ssl_ctx():
    # Python trên macOS không có sẵn kho chứng chỉ gốc -> dùng /etc/ssl/cert.pem.
    # Máy chủ muasamcong dùng khóa DH ngắn nên phải hạ SECLEVEL mới bắt tay được.
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if os.path.exists("/etc/ssl/cert.pem") else ssl.create_default_context()
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    return ctx


SSL_CTX = make_ssl_ctx()


def http(url, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return r.read()
        except Exception:
            if i == 2:
                raise
            time.sleep(3 * (i + 1))


def num(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return None


def clean(s):
    s = html_lib.unescape(str(s or ""))
    s = re.sub(r"([aăâeêioôơuưyAĂÂEÊIOÔƠUƯY])([^\W\d_])([̣̀́̃̉])", r"\1\3\2", str(s or ""))
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s/]", " ", clean(s).lower())).strip()


# ---------- danh mục lô / mặt hàng ----------

def forms(notify_id):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, notify_id + ".json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 3 * 86400:
        return json.load(open(path))
    body = json.loads(http(FORMS_URL, {"body": {"notifyId": notify_id, "bidField": "HH"}})).get("body") or []
    json.dump(body, open(path, "w"), ensure_ascii=False)
    return body


def parse(body):
    lots, items, files = {}, {}, []
    for f in body:
        try:
            v = json.loads(f.get("formValue") or "null")
        except ValueError:
            continue
        if not isinstance(v, dict):
            continue
        ft = v.get("fileTech")
        if isinstance(ft, dict) and ft.get("fileId"):
            files.append((ft["fileId"], ft.get("fileName") or ""))
        for t in v.get("Table") or []:
            if t.get("lotNo"):
                lots[str(t["id"])] = {"lo": t["lotNo"], "ten_lo": clean(t.get("lotName")),
                                      "gia_lo": num(t.get("lotPrice")) or num(t.get("lotEstimatePrice"))}
        for t in v.get("Table") or []:
            if t.get("name") and t.get("qty") is not None:
                key = (str(t.get("parent")), clean(t["name"]), str(t.get("qty")))
                old = items.get(key)
                if old is None or len(str(t.get("specification") or "")) > len(str(old.get("specification") or "")):
                    items[key] = t
    return lots, list(items.values()), files


# ---------- lọc theo sản phẩm quan tâm ----------

def load_kw():
    kw = json.load(open(KW_PATH, encoding="utf-8"))
    kw["_nhom"] = [(g["ten"], [norm(x) for x in g["tu"]]) for g in kw["nhom"]]
    kw["_can"] = [norm(x) for x in kw.get("can_co", [])]
    kw["_bo"] = [norm(x) for x in kw.get("loai_tru", [])]
    return kw


def group_of(name, kw):
    n = " " + norm(name) + " "
    if n.startswith((" máy ", " thiết bị ", " hệ thống ")):  # máy móc, không phải vật tư test
        return None
    if any(b and b in n for b in kw["_bo"]):
        return None
    if kw["_can"] and not any(c in n for c in kw["_can"]):
        return None
    for ten, tus in kw["_nhom"]:
        if any((" " + t + " ") in n if len(t) <= 4 else t in n for t in tus):
            return ten
    return None


# ---------- thông số Chương V ----------

def file_rows(file_id, file_name):
    """Tải file Chương V, trả về các dòng bảng (list các ô)."""
    d = os.path.join(CACHE, "c5_" + file_id)
    rows_path = d + ".rows.json"
    if os.path.exists(rows_path):
        return json.load(open(rows_path))
    os.makedirs(d, exist_ok=True)
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "bin"
    src = os.path.join(d, "c5." + ext)
    try:
        open(src, "wb").write(http(FILE_URL + file_id, timeout=300))
    except Exception:
        return []
    paths = [src]
    if ext in ("rar", "zip", "7z") and shutil.which("bsdtar"):
        subprocess.run(["bsdtar", "-xf", src, "-C", d], capture_output=True)
        paths = [p for p in glob.glob(d + "/**/*", recursive=True) if os.path.isfile(p) and not os.path.basename(p).startswith("~$")]
    rows = []
    for p in paths:
        rows += read_table_file(p)
    json.dump(rows, open(rows_path, "w"), ensure_ascii=False)
    shutil.rmtree(d, ignore_errors=True)
    return rows


def read_table_file(p):
    ext = p.rsplit(".", 1)[-1].lower()
    rows = []
    try:
        if ext in ("doc", "docx", "rtf") and shutil.which("textutil"):
            html = subprocess.run(["textutil", "-convert", "html", "-stdout", p], capture_output=True, timeout=180).stdout.decode("utf-8", "ignore")
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
                cells = [clean(re.sub(r"<[^>]+>", " ", c).replace("&nbsp;", " ")) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
                rows.append(cells)
        elif ext in ("xlsx", "xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
            for ws in wb.worksheets:
                for r in ws.iter_rows(values_only=True):
                    rows.append([clean(c) if c is not None else "" for c in r])
        elif ext == "pdf":
            import fitz
            for page in fitz.open(p):
                for t in page.find_tables().tables:
                    rows += [[clean(c) for c in r] for r in t.extract()]
    except Exception:
        pass
    return [r for r in rows if sum(len(c) for c in r) > 5]


def spec_from_rows(name, qty, rows):
    n = norm(name)
    best = (0, None, None)
    for r in rows:
        for ci, c in enumerate(r):
            if not c or len(c) > len(name) * 3 + 60:
                continue
            cn = norm(c)
            if not cn:
                continue
            sc = difflib.SequenceMatcher(None, n, cn).ratio()
            if n in cn or (cn in n and len(cn) > 8):
                sc = max(sc, 0.85)
            if qty and any(re.sub(r"\D", "", x) == str(qty) for x in r if x and len(x) < 15):
                sc += 0.1
            if any(len(x) > 25 and norm(x) != n for j, x in enumerate(r) if j != ci):
                sc += 0.05
            if sc > best[0]:
                best = (sc, r, ci)
    sc, r, ci = best
    if not r or sc < 0.62:
        return ""
    cands = [c for j, c in enumerate(r) if j != ci and len(c) > 25 and norm(c) != n]
    return max(cands, key=len) if cands else ""


def meta_of(notify_id):
    """Thông tin chung của gói (tên, chủ đầu tư, hạn, giá...) qua API công khai."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "meta_" + notify_id + ".json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 86400:
        return json.load(open(path))
    n = (json.loads(http(HOST + "/api/unau/portal/ebidorg/bid-no-contractor/get-detail", {"body": {"id": notify_id}}))
         .get("body") or {}).get("bidNotification")
    if n:
        m = {"code": n.get("notifyNo"), "name": n.get("bidName"), "inv": n.get("investorName"),
             "prov": n.get("executionLocation") or "", "close": n.get("bidCloseDate"), "pub": n.get("publicDate"),
             "bidForm": n.get("bidForm"), "price": n.get("bidPrice"), "planNo": n.get("planNo"),
             "processApply": n.get("processApply"), "bidMode": n.get("bidMode"), "stepCode": "notify-contractor-step-1-tbmt"}
    else:  # chào giá trực tuyến rút gọn
        r = json.loads(http(HOST + "/o/egp-portal-contractor-selection-v2/services/online-reoffer/detail", {"id": notify_id}))
        ends = [d for d in (r.get("reofferCloseDate"), r.get("reofferOpenDate")) if d]
        m = {"code": r.get("notifyNo"), "name": r.get("bidName"), "inv": r.get("investorName"), "prov": "",
             "close": max(ends) if ends else None, "pub": r.get("publicDate"), "bidForm": r.get("bidForm") or "CGTTRG",
             "price": r.get("priceInit"), "planNo": r.get("planNo"), "processApply": r.get("processApply"),
             "bidMode": r.get("bidMode"), "stepCode": "reoffer-price-step-1"}
    m["id"] = notify_id
    json.dump(m, open(path, "w"), ensure_ascii=False)
    return m


# ---------- ghép lại ----------

def detail_link(code, m):
    if not m.get("planNo"):
        return f"{HOST}/web/guest/contractor-selection?render=search"
    pid = "egpportalcontractorselectionv2_WAR_egpportalcontractorselectionv2"
    return (f"{HOST}/web/guest/contractor-selection?p_p_id={pid}&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
            f"&_{pid}_render=detail-v2&type={m.get('type', 'es-notify-contractor')}&stepCode={m.get('stepCode', '')}"
            f"&id={m['id']}&notifyId={m['id']}&processApply={m.get('processApply', 'LDT')}&bidMode={m.get('bidMode', '')}"
            f"&notifyNo={code}&planNo={m['planNo']}&step=tbmt&isInternet={m.get('isInternet', 1)}&bidForm={m.get('bidForm', '')}")


def build(ids_path):
    kw = load_kw()
    raw = json.load(open(ids_path, encoding="utf-8"))
    ids = raw if isinstance(raw, list) else [v["id"] if isinstance(v, dict) else v for v in raw.values()]
    meta = {}
    for nid in dict.fromkeys(ids):
        try:
            m = meta_of(nid)
            if m.get("code"):
                meta[m["code"]] = m
        except Exception as e:
            print(nid, "lỗi lấy thông tin chung:", e, file=sys.stderr)
    now = datetime.now()
    old = {}
    if os.path.exists(OUT_PATH):
        for p in json.load(open(OUT_PATH, encoding="utf-8")).get("goi", []):
            old[p["ma"]] = p.get("lan_dau") or p.get("dang")
    out = []
    for code, m in meta.items():
        close = m.get("close") or ""
        try:
            if close and datetime.fromisoformat(close[:19]) < now:
                continue
        except ValueError:
            pass
        try:
            lots, items, files = parse(forms(m["id"]))
        except Exception as e:
            print(code, "lỗi lấy chi tiết:", e, file=sys.stderr)
            continue
        per_lot = {}
        for t in items:
            per_lot.setdefault(str(t.get("parent")), []).append(t)
        hit = []
        for t in items:
            g = group_of(t["name"], kw)
            if not g:
                continue
            lot = lots.get(str(t.get("parent")), {})
            qty = num(t.get("qty"))
            gia_lo = lot.get("gia_lo")
            if gia_lo is None and len(lots) <= 1 and len(items) == 1:
                gia_lo = num(m.get("price"))
            one = len(per_lot.get(str(t.get("parent")), [])) == 1
            spec = clean(t.get("specification") or "")
            desc = clean(t.get("description") or "")
            if not spec and desc and "chương v" not in desc.lower():
                spec = desc
            hit.append({"nhom": g, "ten": clean(t["name"]), "dvt": clean(t.get("uom")), "sl": qty,
                        "lo": lot.get("lo", ""), "ten_lo": lot.get("ten_lo", ""), "gia_lo": gia_lo,
                        "don_gia": round(gia_lo / qty) if (one and gia_lo and qty) else None,
                        "ky_ma": clean(t.get("code")), "hang": clean(t.get("manufacture")),
                        "xuat_xu": clean(t.get("goodsOrigin")), "tskt": spec})
        if not hit:
            continue
        if any(not h["tskt"] for h in hit) and files:
            rows = []
            for fid, fname in files:
                rows += file_rows(fid, fname)
            for h in hit:
                if not h["tskt"] and rows:
                    h["tskt"] = clean(spec_from_rows(h["ten"], h["sl"], rows))
        first = old.get(code) or now.strftime("%Y-%m-%d %H:%M")
        out.append({"ma": code, "ten": clean(m.get("name")), "cdt": clean(m.get("inv")), "tinh": clean(m.get("prov")),
                    "han": close[:16].replace("T", " "), "dang": (m.get("pub") or "")[:16].replace("T", " "),
                    "hinh_thuc": FORM_NAMES.get(m.get("bidForm"), m.get("bidForm") or ""), "gia_goi": num(m.get("price")),
                    "lan_dau": first, "link": detail_link(code, m), "hang_hoa": hit})
        print(code, len(hit), "mặt hàng", file=sys.stderr)
    out.sort(key=lambda p: p["han"])
    res = {"cap_nhat": now.strftime("%Y-%m-%d %H:%M"), "nhom": [g["ten"] for g in kw["nhom"]], "goi": out}
    json.dump(res, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"Xong: {len(out)} gói, {sum(len(p['hang_hoa']) for p in out)} mặt hàng -> {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "build":
        build(sys.argv[2])
    else:
        print(__doc__)
