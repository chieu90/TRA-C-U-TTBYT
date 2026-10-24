#!/usr/bin/env python3
"""
Lấy chi tiết gói thầu trên muasamcong và lọc mặt hàng theo sản phẩm quan tâm.

    python3 goi_thau.py build index/goi_thau_ids.json
    python3 goi_thau.py refresh      # chỉ làm mới hạn/tên/giá các gói đã có (chạy tự động trên máy chủ)

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
    lots, items, files, eval_files, texts = {}, {}, [], [], []
    bdl162 = None
    for f in body:
        try:
            v = json.loads(f.get("formValue") or "null")
        except ValueError:
            continue
        if not isinstance(v, dict):
            continue
        texts.append(json.dumps(v, ensure_ascii=False))
        if v.get("radioValue162") in (0, 1, "0", "1"):  # Bảng dữ liệu E-CDNT 16.2: giấy phép bán hàng
            bdl162 = (int(v["radioValue162"]), clean(v.get("radioValue162Content") or ""))
        ft = v.get("fileTech")
        if isinstance(ft, dict) and ft.get("fileId"):
            files.append((ft["fileId"], ft.get("fileName") or ""))
        f3 = v.get("fileName2")  # Chương III – tiêu chuẩn đánh giá kỹ thuật
        if isinstance(f3, dict) and f3.get("fileId"):
            eval_files.append((f3["fileId"], f3.get("fileName") or ""))
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
    return lots, list(items.values()), files, eval_files, "\n".join(texts), bdl162


# ---------- lọc theo sản phẩm quan tâm ----------

def load_kw():
    kw = json.load(open(KW_PATH, encoding="utf-8"))
    kw["_nhom"] = [(g["ten"], [norm(x) for x in g["tu"]]) for g in kw["nhom"]]
    kw["_can"] = [norm(x) for x in kw.get("can_co", [])]
    kw["_bo"] = [norm(x) for x in kw.get("loai_tru", [])]
    return kw


TEST_UOM = {"test", "que", "khay", "thanh", "test/khay", "test/que", "kit"}
REAGENT_RE = re.compile(r"chủng|atcc|cấy|kiểm soát|\bdna\b|\brna\b|môi trường|chất xét nghiệm|hóa chất|hoá chất|thuốc thử|chất chuẩn|chất hiệu chuẩn|hiệu chuẩn|calibrat|control|chứng|elecsys|architect|alinity|cobas|access|advia|vidas|liaison|maglumi|atellica|dxi|immulite")


def group_of(name, kw, uom=None):
    n = " " + norm(name) + " "
    if n.startswith((" máy ", " thiết bị ", " hệ thống ")):  # máy móc, không phải vật tư test
        return None
    if any(b and b in n for b in kw["_bo"]):
        return None
    # tên phải có chữ kiểu test/que thử/khay thử...; riêng mặt hàng tính theo Test/Que/Khay
    # mà tên chỉ ghi thương hiệu + chỉ số (vd "SDN BioNTN HbsAg") thì vẫn nhận, trừ hóa chất chạy máy
    if kw["_can"] and not any(c in n for c in kw["_can"]) and not (
            norm(uom or "") in TEST_UOM and not REAGENT_RE.search(n)):
        return None
    for ten, tus in kw["_nhom"]:
        if any((" " + t + " ") in n if len(t) <= 4 else t in n for t in tus):
            return ten
    return None


# ---------- thông số Chương V ----------

def file_data(file_id, file_name):
    """Tải file đính kèm HSMT (Chương III/V), trả về {"rows": dòng bảng, "text": toàn văn}."""
    d = os.path.join(CACHE, "c5_" + file_id)
    data_path = d + ".data.json"
    if os.path.exists(data_path):
        return json.load(open(data_path))
    os.makedirs(d, exist_ok=True)
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "bin"
    src = os.path.join(d, "c5." + ext)
    try:
        open(src, "wb").write(http(FILE_URL + file_id, timeout=300))
    except Exception:
        return {"rows": [], "text": ""}
    paths = [src]
    if ext in ("rar", "zip", "7z") and shutil.which("bsdtar"):
        subprocess.run(["bsdtar", "-xf", src, "-C", d], capture_output=True)
        paths = [p for p in glob.glob(d + "/**/*", recursive=True) if os.path.isfile(p) and not os.path.basename(p).startswith("~$")]
    rows, text = [], []
    for p in paths:
        rows += read_table_file(p)
        text.append(read_text_file(p))
    data = {"rows": rows, "text": clean_lines("\n".join(text))}
    json.dump(data, open(data_path, "w"), ensure_ascii=False)
    shutil.rmtree(d, ignore_errors=True)
    return data


def file_rows(file_id, file_name):
    return file_data(file_id, file_name)["rows"]


def clean_lines(t):
    return "\n".join(clean(x) for x in t.splitlines() if x.strip())


def read_text_file(p):
    ext = p.rsplit(".", 1)[-1].lower()
    try:
        if ext in ("doc", "docx", "rtf") and shutil.which("textutil"):
            return subprocess.run(["textutil", "-convert", "txt", "-stdout", p], capture_output=True, timeout=180).stdout.decode("utf-8", "ignore")
        if ext in ("xlsx", "xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
            return "\n".join(" | ".join(str(c) for c in r if c is not None) for ws in wb.worksheets for r in ws.iter_rows(values_only=True))
        if ext == "pdf":
            import fitz
            return "".join(page.get_text() for page in fitz.open(p))
    except Exception:
        pass
    return ""


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
        m = json.load(open(path))
        if "cperiod" in m and "prov_v" in m:
            return m
    n = (json.loads(http(HOST + "/api/unau/portal/ebidorg/bid-no-contractor/get-detail", {"body": {"id": notify_id}}))
         .get("body") or {}).get("bidNotification")
    if n:
        m = {"code": n.get("notifyNo"), "name": n.get("bidName"), "inv": n.get("investorName"),
             "prov": n.get("executionLocation") or "", "close": n.get("bidCloseDate"), "pub": n.get("publicDate"),
             "bidForm": n.get("bidForm"), "price": n.get("bidPrice"), "planNo": n.get("planNo"),
             "processApply": n.get("processApply"), "bidMode": n.get("bidMode"), "stepCode": "notify-contractor-step-1-tbmt",
             "cperiod": n.get("contractPeriod"), "cunit": n.get("contractPeriodUnit")}
    else:  # chào giá trực tuyến rút gọn
        r = json.loads(http(HOST + "/o/egp-portal-contractor-selection-v2/services/online-reoffer/detail", {"id": notify_id}))
        ends = [d for d in (r.get("reofferCloseDate"), r.get("reofferOpenDate")) if d]
        locs = (r.get("bidDetail") or {}).get("bidLocation") or []
        m = {"code": r.get("notifyNo"), "name": r.get("bidName"), "inv": r.get("investorName"),
             "prov": next((l.get("provName") for l in locs if l.get("provName")), ""),
             "close": max(ends) if ends else None, "pub": r.get("publicDate"), "bidForm": r.get("bidForm") or "CGTTRG",
             "price": r.get("priceInit"), "planNo": r.get("planNo"), "processApply": r.get("processApply"),
             "bidMode": r.get("bidMode"), "stepCode": "reoffer-price-step-1",
             "cperiod": (r.get("bidDetail") or {}).get("cperiod"), "cunit": (r.get("bidDetail") or {}).get("cperiodUnit")}
    m["id"] = notify_id
    m["prov_v"] = 1
    json.dump(m, open(path, "w"), ensure_ascii=False)
    return m


PROV_RE = re.compile(r"(?:Tỉnh|tỉnh|Thành phố|thành phố|TP\.?)\s+([A-ZĐ][^,;.\\/()\n\d]{1,30}?)\s*(?=$|[,;.\\/()\n]|\s-)")


def short_prov(s):
    """'Tỉnh Thái Nguyên' -> 'Thái Nguyên'; 'Thành phố Hồ Chí Minh' -> 'TP Hồ Chí Minh'."""
    s = re.sub(r"[\'\"{}\[\]]", "", clean(s or "")).strip()
    s = re.sub(r"^(Tỉnh|tỉnh|Thành phố|thành phố|TP\.?)\s+", "", s).strip()
    return "TP Hồ Chí Minh" if s.lower() in ("hồ chí minh", "hcm") else s


def province(m, form_list):
    """Tỉnh/TP của gói: địa điểm (chào giá) -> địa chỉ chủ đầu tư trong HSMT -> tên chủ đầu tư."""
    if m.get("prov"):
        return short_prov(m["prov"])
    for f in form_list:
        try:
            v = json.loads(f.get("formValue") or "null")
        except ValueError:
            continue
        if isinstance(v, dict):
            for k in ("investorAddress", "e_dkc_1_4_address", "procuringEntityAddress"):
                found = PROV_RE.findall(clean(v.get(k) or ""))
                if found:
                    return short_prov(found[-1])
    found = PROV_RE.findall(clean(m.get("inv") or ""))
    return short_prov(found[-1]) if found else ""


# ---------- yêu cầu ủy quyền của hãng / chủ sở hữu ----------

UQ = r"[uủ][yỷ] ?quyền"
AUTH_RE = re.compile(r"giấy phép bán hàng|giấy " + UQ + "|" + UQ + r" (bán hàng )?(của|từ) (nhà sản xuất|hãng|chủ sở hữu|nhà phân phối|tổ chức|đơn vị)|được (nhà sản xuất|hãng|chủ sở hữu)[^.;]{0,30}" + UQ, re.I)
AUTH_WHO = re.compile(r"nhà sản xuất|hãng|chủ sở hữu|nhà phân phối|đứng tên|giấy phép nhập khẩu|đăng ký lưu hành|số lưu hành|bán hàng", re.I)
AUTH_NOT = re.compile(r"người được " + UQ + "|" + UQ + r" đại diện|đại diện (theo pháp luật|nhà thầu|hợp pháp)|người ký|ký đơn|liên danh|giấy " + UQ + r" \(nếu có\)|trường hợp " + UQ, re.I)
AUTH_ALT = re.compile(r"hoặc (giấy chứng nhận )?quan hệ đối tác|hoặc (các )?tài liệu khác có giá trị tương đương|hoặc giấy cam kết|hoặc cam kết", re.I)
AUTH_NO = re.compile(r"không (yêu cầu|bắt buộc)[^.;]{0,40}" + UQ + "|" + UQ + r"[^.;]{0,40}không (yêu cầu|bắt buộc)", re.I)


def sentences(text):
    for s in re.split(r"(?<=[.;])\s+|\n|\\n|\s-\s|\s\+\s", text):
        s = s.strip(" -+'\"")
        if 20 < len(s) < 700:
            yield s


def auth_requirement(sources):
    """sources: [(nguồn, văn bản)] -> {"muc", "trich", "nguon"}.
    Có yêu cầu / Không yêu cầu / Không ghi rõ (dùng cho gói không có Bảng dữ liệu E-CDNT 16.2)."""
    best = None
    rank = {"Có yêu cầu": 2, "Không yêu cầu": 1}
    for src, text in sources:
        for s in sentences(text or ""):
            if AUTH_NO.search(s):
                cand = ("Không yêu cầu", s, src)
            elif AUTH_RE.search(s) and AUTH_WHO.search(s) and not AUTH_NOT.search(s):
                cand = ("Có yêu cầu", s, src)
            else:
                continue
            if best is None or rank[cand[0]] > rank[best[0]]:
                best = cand
    if not best:
        return {"muc": "Không ghi rõ", "trich": "", "nguon": ""}
    return {"muc": best[0], "trich": best[1][:400], "nguon": best[2]}


def contract_time(m, lots_raw):
    """Thời gian thực hiện hợp đồng -> {"text": "365 ngày", "ngay": 365}. 12 tháng = 365 ngày."""
    n, u = num(m.get("cperiod")), (m.get("cunit") or "").upper()
    if n is None:  # lấy theo lô nếu gói không ghi
        for t in lots_raw:
            if num(t.get("cperiod")) is not None:
                n, u = num(t.get("cperiod")), (t.get("cperiodUnit") or "").upper()
                break
    if n is None:
        return {"text": "", "ngay": None}
    unit = {"D": "ngày", "M": "tháng", "Y": "năm", "W": "tuần"}.get(u, u.lower())
    days = {"D": n, "M": round(n * 365 / 12), "Y": n * 365, "W": n * 7}.get(u, n)
    return {"text": f"{n} {unit}", "ngay": days}


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
        close = m.get("close") or ""  # giữ cả gói đã đóng thầu; trang web tự đánh dấu và lọc
        try:
            lots, items, files, eval_files, form_text, bdl162 = parse(forms(m["id"]))
        except Exception as e:
            print(code, "lỗi lấy chi tiết:", e, file=sys.stderr)
            continue
        per_lot = {}
        for t in items:
            per_lot.setdefault(str(t.get("parent")), []).append(t)
        hit = []
        for t in items:
            g = group_of(t["name"], kw, t.get("uom"))
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
                        "xuat_xu": clean(t.get("goodsOrigin")), "tskt": spec,
                        "uy_quyen": auth_requirement([("Yêu cầu khác của mặt hàng", clean(t.get("otherRequirement") or "")),
                                                      ("Thông số mặt hàng", spec)])})
        if not hit:
            continue
        if any(not h["tskt"] for h in hit) and files:
            rows = []
            for fid, fname in files:
                rows += file_rows(fid, fname)
            for h in hit:
                if not h["tskt"] and rows:
                    h["tskt"] = clean(spec_from_rows(h["ten"], h["sl"], rows))
        lots_raw = [t for f in forms(m["id"]) for t in ((json.loads(f.get("formValue") or "null") or {}).get("Table") or []
                                                         if isinstance(json.loads(f.get("formValue") or "null"), dict) else []) if t.get("lotNo")]
        tg_hd = contract_time(m, lots_raw)
        if bdl162 is not None:  # nguồn chính thức: Bảng dữ liệu, mục E-CDNT 16.2
            pkg_auth = {"muc": "Có yêu cầu" if bdl162[0] else "Không yêu cầu", "nguon": "Bảng dữ liệu E-CDNT 16.2",
                        "trich": bdl162[1] or ("Có yêu cầu Giấy phép hoặc Giấy ủy quyền bán hàng của nhà sản xuất, đại lý phân phối "
                                               "hoặc Giấy chứng nhận quan hệ đối tác hoặc tài liệu khác có giá trị tương đương"
                                               if bdl162[0] else "Không yêu cầu Giấy phép hoặc Giấy ủy quyền bán hàng")}
            for h in hit:
                h["uy_quyen"] = pkg_auth
        else:  # chào giá trực tuyến: không có Bảng dữ liệu -> dò trong yêu cầu của mặt hàng / hồ sơ
            srcs = [("Hồ sơ mời thầu (webform)", form_text)]
            for fid, fname in eval_files:
                srcs.append(("Chương III – tiêu chuẩn đánh giá", file_data(fid, fname)["text"]))
            for fid, fname in files:
                srcs.append(("Chương V – yêu cầu kỹ thuật", file_data(fid, fname)["text"]))
            pkg_auth = auth_requirement(srcs)
            for h in hit:
                if h["uy_quyen"]["muc"] == "Không ghi rõ":
                    h["uy_quyen"] = pkg_auth
        first = old.get(code) or now.strftime("%Y-%m-%d %H:%M")
        out.append({"ma": code, "ten": clean(m.get("name")), "cdt": clean(m.get("inv")), "tinh": province(m, forms(m["id"])),
                    "han": close[:16].replace("T", " "), "dang": (m.get("pub") or "")[:16].replace("T", " "),
                    "hinh_thuc": FORM_NAMES.get(m.get("bidForm"), m.get("bidForm") or ""), "gia_goi": num(m.get("price")),
                    "lan_dau": first, "link": detail_link(code, m), "uy_quyen": pkg_auth, "tg_hd": tg_hd, "hang_hoa": hit})
        print(code, len(hit), "mặt hàng", file=sys.stderr)
    out.sort(key=lambda p: p["han"])
    res = {"cap_nhat": now.strftime("%Y-%m-%d %H:%M"), "nhom": [g["ten"] for g in kw["nhom"]], "goi": out}
    json.dump(res, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"Xong: {len(out)} gói, {sum(len(p['hang_hoa']) for p in out)} mặt hàng -> {OUT_PATH}", file=sys.stderr)


def refresh():
    """Làm mới thông tin chung các gói đang có trong data/goi_thau.json (hạn khi gia hạn, tên, giá, tỉnh...)
    qua API công khai, GIỮ NGUYÊN danh mục + thông số Chương V. Dùng cho chạy tự động trên máy chủ
    (GitHub Actions) — việc tìm gói MỚI vẫn cần trình duyệt (reCAPTCHA) và lệnh build."""
    res = json.load(open(OUT_PATH, encoding="utf-8"))
    changed = 0
    for p in res.get("goi", []):
        nid = (re.search(r"notifyId=([0-9a-f-]{36})", p.get("link") or "") or [None, None])[1]
        if not nid:
            continue
        cached = os.path.join(CACHE, "meta_" + nid + ".json")
        if os.path.exists(cached):
            os.remove(cached)  # luôn lấy bản mới nhất
        try:
            m = meta_of(nid)
        except Exception as e:
            print(p["ma"], "lỗi lấy thông tin chung:", e, file=sys.stderr)
            continue
        new = {"ten": clean(m.get("name")) or p.get("ten"), "cdt": clean(m.get("inv")) or p.get("cdt"),
               "han": (m.get("close") or "")[:16].replace("T", " ") or p.get("han"),
               "hinh_thuc": FORM_NAMES.get(m.get("bidForm"), m.get("bidForm") or "") or p.get("hinh_thuc"),
               "gia_goi": num(m.get("price")) or p.get("gia_goi"), "link": detail_link(p["ma"], m)}
        if m.get("prov"):
            new["tinh"] = province(m, [])
        if any(p.get(k) != v for k, v in new.items()):
            changed += 1
            p.update(new)
    res["cap_nhat"] = (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")
    json.dump(res, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"Làm mới {len(res.get('goi', []))} gói, {changed} gói có thay đổi -> {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "build":
        build(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "refresh":
        refresh()
    else:
        print(__doc__)
