#!/usr/bin/env python3
"""
Gom gói thầu test nhanh năm 2026 theo cơ sở y tế (chủ đầu tư) kèm tình trạng gói.

    python3 co_so_y_te.py

Nguồn (đều là API công khai / dữ liệu sẵn có, không đụng trang tìm kiếm có reCAPTCHA):
- data/goi_thau.json: gói đang mở / đã đóng do bước quét trình duyệt tìm ra.
- index/goi_thau_cache/meta_*.json: thông tin chung các gói đã quét -> gói đã hủy (status 03).
- Kết quả lựa chọn nhà thầu 2026: POST /o/egp-portal-winning-bid-data/services/smart/search_prc
  (index es-smart-pricing), lọc mặt hàng test nhanh bằng cùng bộ từ khóa với trang Gói thầu.

Tình trạng: "Đã có kết quả" (có trong dữ liệu KQLCNT) > "Đã hủy" > theo hạn đóng thầu
("Đang mở" / "Đã đóng – chờ kết quả", trang web tự tính theo giờ hiện tại).
Đầu ra: data/co_so_y_te.json (trang /co-so-y-te) và data/trung_thau.json (trang /trung-thau, Dashboard kết quả trúng thầu).
"""
import glob, json, os, re, sys
from datetime import datetime, timedelta, timezone

import goi_thau as g

OUT_PATH = os.path.join(g.HERE, "data", "co_so_y_te.json")
TT_PATH = os.path.join(g.HERE, "data", "trung_thau.json")  # chi tiết từng mặt hàng trúng thầu cho trang KQ Test
DH_PATH = os.path.join(g.HERE, "data", "duong_huyet.json")  # que thử đường huyết cho trang KQ Đường Huyết
DH_NHOM = "Đường huyết"
PRC_URL = g.HOST + "/o/egp-portal-winning-bid-data/services/smart/search_prc"
YEAR = "2026"
DASH_BO = {"Que thử nước tiểu", "Đường huyết"}  # nhóm không đưa vào Dashboard trúng thầu (theo yêu cầu người dùng)
DASH_BO_RE = re.compile(r"hba1c|hb a1c|hemoglobin a1c|\bcrp\b|c-reactive|protein phản ứng c")  # mặt hàng không đưa vào Dashboard
DASH_TEN = {"Đường huyết / HbA1c": "Đường huyết", "Troponin / CRP": "Troponin"}
HBA1C_RE = re.compile(r"hba1c|hb a1c|hemoglobin a1c")  # tên nhóm hiển thị trên Dashboard
# dấu hiệu test nhanh trong mô tả / nhãn hiệu, dùng khi tên hàng không có chữ test/que thử/khay thử
RAPID_RE = re.compile(r"nhanh|sắc ký|immunochromatograph|lateral flow|rapid|cassette|khay thử|que thử|test strip|quick test")
NOT_RAPID_RE = re.compile(r"elisa|clia|hóa phát quang|hoá phát quang|chemilumin|điện hóa phát quang|miễn dịch huỳnh quang|realtime|real-time|pcr|"
                         r"tải lượng|hplc|cột sắc ký|sắc ký lỏng|reagent kit|kháng thể đa dòng|kháng thể đơn dòng|máy xét nghiệm miễn dịch|"
                         r"chất thử|\\brgt\\b|hiscl|eiagen|allplex|real-tm|tách chiết|bactec|mgit|độ nhạy cảm|hơi thở|breath|license|bản quyền|windows")
# hãng chỉ làm hóa chất chạy máy / ELISA / PCR / vi sinh: không phải test nhanh
NOT_RAPID_MAKER = re.compile(r"sysmex|siemens|dia\.?\s?pro|bio-?rad|adaltis|\bdrg\b|maccura|seegene|sansure|sacace|elitech|becton|\bbd\b|infai|beckman|ortho clinical|mindray|snibe|diasorin|euroimmun|abbott gmbh|abbott ireland")

ACCESSORY_RE = re.compile(r"^(pin|kim|bút|lancet|dung dịch|vỏ|hộp đựng|giá đỡ|máy|thiết bị|hệ thống)\b|\bpin\b|\bcột\b|hóa chất|hoá chất")
PER_TEST = {"test", "que", "khay", "thanh", "test/khay", "test/que", "kit"}

def ten(r):
    """Tên hàng: kết quả tab Thiết bị y tế ghi ở tenThietBi, tab Hàng hóa ghi ở danhMucHangHoa."""
    return g.clean(r.get("tenThietBi") or r.get("danhMucHangHoa"))


PACK_RE = re.compile(r"(\d{1,4})\s*(?:que|test|miếng|strip|strips|tests)\s*/\s*(?:hộp|lọ|hop|box|vial)|(?:hộp|lọ|box)\s*(?:\d+\s*lọ\s*x\s*)?(\d{1,4})\s*(?:que|test|miếng|strips?)")


def sl_test(r):
    """Số test: đơn vị test/que/khay -> số lượng; đơn vị hộp/lọ -> số lượng x quy cách (vd 'hộp 50 que') nếu đọc được."""
    sl = r.get("khoiLuongDouble")
    if not sl:
        return None
    u = g.norm(r.get("donViTinh") or "")
    if u in PER_TEST:
        return sl
    # que/test tính theo "cái", "miếng", "1 que+1 kim"...: mỗi đơn vị là một lần thử
    if (u in ("cái", "chiếc", "miếng", "test/cái", "que/cái") or u.startswith("1 que")) and re.search(r"\b(que|test|khay)\b", g.norm(ten(r))):
        return sl
    if g.norm(r.get("donViTinh") or "") in ("hộp", "lọ", "hop", "box"):
        t = g.norm(" ".join(g.clean(r.get(k)) for k in ("tenThietBi", "danhMucHangHoa", "nhanHieu", "cauHinh")))
        m2 = re.search(r"(\d{1,2})\s*lọ\s*x\s*(\d{1,4})\s*(?:que|test|miếng|strips?)", t)  # hộp 2 lọ x 25 que
        m = PACK_RE.search(t)
        if m2 or m:
            n = int(m2.group(1)) * int(m2.group(2)) if m2 else int(m.group(1) or m.group(2))
            if 5 <= n <= 1000:
                return sl * n
    return None


def don_gia(r):
    v = r.get("donGia") if r.get("donGia") is not None else r.get("donGiaDuThau")
    sl = r.get("khoiLuongDouble") or 0
    # lỗi nhập liệu hay gặp: ghi thành tiền vào ô đơn giá (vd 4.000 test x 196 triệu/test) -> chia lại theo số lượng
    if v and sl > 1 and g.norm(r.get("donViTinh") or "") in PER_TEST and v > 1_000_000:
        v = v / sl
    return v


def keywords(kw):
    """Từ khóa tìm trong dữ liệu trúng thầu: chữ chỉ dạng test nhanh + tên chỉ số của từng nhóm
    (để bắt cả mặt hàng ghi kiểu "Sinh phẩm chẩn đoán HIV", "Determine HBsAg 2")."""
    ws = list(kw.get("can_co", [])) + [t.strip() for n in kw["nhom"] for t in n["tu"]] + EXTRA_Q
    return [(w, "exact" if " " in w else "all-1") for w in dict.fromkeys(w for w in ws if len(w) >= 3)]


# tìm thêm theo cách ghi tắt và theo hãng test nhanh lớn: bắt mặt hàng tên chỉ ghi "TB IgG/IgM combo", "OnSite ...", "Bioline ..."
EXTRA_Q = ["TB IgG", "IgG/IgM", "Rapid Test", "Combo Rapid", "OnSite", "Bioline", "Determine", "CTK Biotech", "Beijing Genesee", "SD Biosensor",
           "Abbott Diagnostics", "ACON", "Wondfo", "InTec", "Alltest", "Assure Tech", "Medicon", "GenBody", "Citest", "Healgen", "Orient Gene",
           "Testsea", "Hangzhou Biotest", "Hightop", "ABON", "Atlas", "GeneSign", "Asan", "Humasis", "Standard Q"]


def classify(r, kw):
    """Nhóm test nhanh của một dòng trúng thầu, None nếu không phải test nhanh."""
    name, uom = ten(r), r.get("donViTinh")
    extra = g.clean(r.get("nhanHieu")) + " " + g.clean(r.get("kyMaHieu")) + " " + g.clean(r.get("cauHinh"))[:300]
    txt = g.norm(name + " " + extra)
    # ELISA, CLIA, PCR, hóa chất chạy máy, pin/phụ kiện máy: xét trong tên + nhãn hiệu
    # (mô tả test nhanh hay ghi "độ nhạy so với PCR/ELISA" nên không xét mô tả)
    short = g.norm(name + " " + g.clean(r.get("nhanHieu")))
    if NOT_RAPID_RE.search(short) or NOT_RAPID_MAKER.search(g.norm(r.get("hangSanXuat") or "")) or ACCESSORY_RE.search(g.norm(name)) or any(b and b in " " + g.norm(name) + " " for b in kw["_bo"]):
        return None
    if any(c in g.norm(name) for c in kw["_can"]):  # tên đã ghi rõ test/que thử/khay thử...
        # tên chung chung ("Test nhanh", "Que thử xét nghiệm định tính"): xác định nhóm theo nhãn hiệu / ký mã, rồi mô tả
        return (g.group_of(name, kw, uom) or g.group_of(name + " " + g.clean(r.get("nhanHieu")) + " " + g.clean(r.get("kyMaHieu")), kw, uom)
                or g.group_of(name + " " + g.clean(r.get("cauHinh"))[:150], kw, uom))
    # tên chỉ ghi chỉ số / thương hiệu: cần dấu hiệu test nhanh trong nhãn hiệu, mô tả,
    # hoặc tính theo đơn vị test/que/khay mà không phải hóa chất chạy máy
    if RAPID_RE.search(txt) or (g.norm(uom or "") in PER_TEST and not g.REAGENT_RE.search(short)):
        return g.group_of("test " + name + " " + g.clean(r.get("nhanHieu")), kw, uom) or g.group_of("test " + name + " " + extra, kw, uom)
    return None


def now_vn():
    return datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)


def key_of(name):
    """Khóa gộp cơ sở: bỏ hoa/thường, khoảng trắng thừa, dấu câu."""
    return re.sub(r"[^\w]+", " ", (name or "").lower()).strip()


def prc(kw, mt, frm, to, page):
    body = [{"pageSize": 100, "pageNumber": page, "query": [{
        "index": "es-smart-pricing", "keyWord": kw, "keyWordNotMatch": "", "matchType": mt,
        "matchFields": ["ten_thiet_bi", "danh_muc_hang_hoa", "ma_hs", "xuat_xu", "ma_tbmt", "ky_ma_hieu", "nhan_hieu", "hang_san_xuat"],
        # không lọc theo tab: muasamcong xếp nhiều kết quả test nhanh vào tab "Hàng hóa" thay vì "Thiết bị, vật tư y tế"
        "filters": [{"fieldName": "ngay_dang_tai_kqlcnt", "searchType": "range", "from": frm, "to": to}]}]}]
    return json.loads(g.http(PRC_URL, body))["page"]


def results(kw):
    """({mã TBMT: gói đã có kết quả}, [dòng mặt hàng trúng]) từ dữ liệu trúng thầu năm YEAR, chỉ tính mặt hàng test nhanh."""
    rows = {}
    year = [(f"{YEAR}-01-01", f"{int(YEAR) + 1}-01-01")]
    months = [(f"{YEAR}-{m:02d}-01", f"{YEAR}-{m + 1:02d}-01" if m < 12 else f"{int(YEAR) + 1}-01-01") for m in range(1, 13)]
    for q, mt in keywords(kw):
        first = prc(q, mt, *year[0], 0)
        # mỗi truy vấn trả tối đa 10.000 dòng -> từ khóa nhiều kết quả thì chia theo tháng
        for frm, to in (year if first["totalElements"] < 9500 else months):
            pg = first if (frm, to) == year[0] else prc(q, mt, frm, to, 0)
            got = list(pg["content"])
            for p in range(1, min(pg["totalPages"], 100)):
                got += prc(q, mt, frm, to, p)["content"]
            for r in got:
                rows[r["id"]] = r
        print(f"{q}: {first['totalElements']} -> tổng {len(rows)} dòng", file=sys.stderr)
    # cùng một mặt hàng trúng thầu đôi khi có 2 bản ghi giống hệt nhau (khác id) -> chỉ tính một lần
    uniq = {}
    for r in rows.values():
        k = (r.get("maTbmt"), ten(r), r.get("kyMaHieu"), r.get("khoiLuongDouble"), don_gia(r), tuple(r.get("winningName") or []))
        uniq.setdefault(k, r)
    print(f"Bỏ {len(rows) - len(uniq)} bản ghi trùng", file=sys.stderr)
    pk, items, dh_items = {}, [], []
    for r in uniq.values():
        nhom = classify(r, kw)
        if not nhom or not r.get("maTbmt"):
            continue
        tinh = g.short_prov(next((d.get("provName") for d in r.get("diaDiem") or [] if d.get("provName")), ""))
        row = [r["maTbmt"], g.clean(r.get("tenCdtBmt")), tinh, (r.get("ngayDangTaiKqlcnt") or "")[:10], DASH_TEN.get(nhom, nhom),
               ten(r), g.clean(r.get("hangSanXuat")), g.clean(r.get("nhanHieu")), g.clean(r.get("kyMaHieu")),
               g.clean(r.get("xuatXu")), g.clean(r.get("donViTinh")), r.get("khoiLuongDouble"), don_gia(r),
               "; ".join(g.clean(w) for w in r.get("winningName") or []), r.get("bidForm") or "", sl_test(r)]
        hba1c = HBA1C_RE.search(g.norm(ten(r) + " " + g.clean(r.get("nhanHieu"))))
        # KQ Test: bỏ nước tiểu, đường huyết, HbA1c, CRP; KQ Đường Huyết: chỉ que thử đường huyết (không HbA1c)
        if nhom not in DASH_BO and not DASH_BO_RE.search(g.norm(ten(r) + " " + g.clean(r.get("nhanHieu")))):
            items.append(row)
        elif nhom == DH_NHOM and not hba1c:
            dh_items.append(row)
        p = pk.setdefault(r["maTbmt"], {"ma": r["maTbmt"], "cdt": g.clean(r.get("tenCdtBmt")), "ma_cdt": r.get("maCdt"),
                                         "tinh": g.short_prov(next((d.get("provName") for d in r.get("diaDiem") or [] if d.get("provName")), "")),
                                         "kq": (r.get("ngayDangTaiKqlcnt") or "")[:10], "hinh_thuc": g.FORM_NAMES.get(r.get("bidForm"), r.get("bidForm") or ""),
                                         "so_mh": 0, "gia_tri": 0, "nhom": set()})
        p["so_mh"] += 1
        p["gia_tri"] += (don_gia(r) or 0) * (r.get("khoiLuongDouble") or 0)
        p["nhom"].add(nhom)
    return pk, items, dh_items


import difflib, unicodedata

BRAND_STOP = set("cong ty tnhh co phan cty ct ctcp tap doan san xuat hang thuong hieu nha may hangzhou hang zhou zhejiang beijing shanghai guangzhou "
                 "shenzhen xiamen jiangsu nanjing wuhan tianjin changchun qingdao jiangxi shandong hunan suzhou anhui dai loan taiwan trung quoc "
                 "china han quoc korea republic viet nam vietnam my usa duc germany nhat ban japan an do india anh uk phap italy y canada "
                 "province of the and inc ltd co corp corporation gmbh llc limited company sa ag srl".split())
GENERIC = {"khac", "ap ung", "dap ung", "theo", "dengue", "thc", "drug", "drugs", "panel", "test", "khong", "khong co", "n a", "na", "g",
           "a", "hop", "pl", "que", "phat", "thanh"}
# thương hiệu sản phẩm ghi vào cột hãng -> hãng sản xuất
BRAND_ALIAS = {"uright": "taidoc", "u right": "taidoc", "fora": "taidoc", "oncallplus": "acon", "on call": "acon", "oncall": "acon",
               "bioline": "sd biosensor", "sd bioline": "sd biosensor", "sd": "sd biosensor", "standard": "sd biosensor",
               "oriengene": "orient", "accu": "roche", "onetouch": "lifescan", "determine": "abbott nhat ban", "mp biomedicals": "mp biomedical", "sd bionline": "sd biosensor", "ctk": "ctk biotech"}


def _fold(t):
    return unicodedata.normalize("NFD", (t or "").replace("đ", "d").replace("Đ", "D")).encode("ascii", "ignore").decode().lower()


def maker_text(h):
    """Phần ghi hãng của que thử khi cột hãng ghi cả que lẫn kim: 'Que: Roche...; Kim: Asahi...' -> 'Roche...'."""
    t = h or ""
    m = re.search(r"(?:que(?:\s*sx\s*tại)?|hãng sản xuất test)\s*:\s*([^;]+?)(?:[;,]?\s*-?\s*kim\b|;|$)", t, re.I)
    return m.group(1) if m else t


def brand_key(h):
    w = [x for x in re.sub(r"[^a-z0-9]+", " ", re.sub(r"\(.*?\)", " ", _fold(maker_text(h)))).split() if x not in BRAND_STOP]
    if not w:
        return ""
    return w[0] + " " + w[1] if len(w[0]) <= 3 and len(w) > 1 else w[0]


def brand_label(h):
    """Tên hiển thị: bỏ quốc gia / ghi chú sau dấu / hoặc ' - '."""
    t = re.split(r"\s*/\s*|\s+-\s+|;", maker_text(h).strip(" \"',.;-"))[0]
    return t.strip(" \"',.;-") or h


def abbott_site(r):
    t = _fold(" ".join(str(x or "") for x in (r[6], r[9] if len(r) > 9 else "", r[7], r[5])))
    if re.search(r"korea|han quoc|bioline", t):
        return "abbott han quoc"
    if re.search(r"medical|chiba|nhat|japan|determine", t):
        return "abbott nhat ban"
    return "abbott khac"


def canon_brands(items, idx_hang):
    """Gộp tên hãng ghi nhiều kiểu về một tên chuẩn: khóa theo từ chính, tên chứa sẵn khóa của hãng lớn, sửa lỗi chính tả gần giống."""
    from collections import Counter
    keys = [brand_key(r[idx_hang]) for r in items]
    cnt = Counter(k for k in keys if k)
    majors = sorted([k for k, n in cnt.items() if n >= 5 and len(k.replace(" ", "")) >= 4], key=lambda k: -len(k))
    out = []
    for r, k in zip(items, keys):
        compact = re.sub(r"[^a-z0-9]", "", _fold(maker_text(r[idx_hang])))
        # hãng lớn được nhắc tới sớm nhất trong chuỗi (vd "Genesee ... (chủ sở hữu: CTK)" -> Genesee)
        pos = [(compact.find(m.replace(" ", "")), -len(m), m) for m in majors if m.replace(" ", "") in compact]
        hit = min(pos)[2] if pos else None
        if not hit and k and cnt[k] < 20:
            close = difflib.get_close_matches(k, majors, n=1, cutoff=0.8)
            hit = close[0] if close and close[0][0] == k[0] else None
        k = BRAND_ALIAS.get(hit or k, hit or k)
        if k == "abbott":  # Abbott Hàn Quốc (Bioline, Abbott Diagnostics Korea) khác Abbott Nhật Bản (Determine, Chiba)
            k = abbott_site(r)
        out.append("" if (not k or k in GENERIC or len(r[idx_hang]) > 90) else k)
    # gộp các khóa gần giống nhau (lỗi chính tả: "sd biosenso" -> "sd biosensor") về khóa nhiều dòng hơn
    c2 = Counter(k for k in out if k)
    order = sorted(c2, key=lambda k: -c2[k])
    merge = {}
    for i, k in enumerate(order):
        for big in order[:i]:
            if big not in merge and big[0] == k[0] and difflib.SequenceMatcher(None, k, big).ratio() >= 0.88:
                merge[k] = big
                break
    out = [merge.get(k, k) for k in out]
    # cùng ký mã hiệu thì cùng hãng: theo hãng được ghi nhiều nhất cho ký mã đó (vd R0053C ghi lúc CTK, lúc Genesee)
    km = {}
    for r, k in zip(items, out):
        code = re.sub(r"[^a-z0-9]", "", _fold(r[8] if len(r) > 8 else ""))
        if len(code) >= 4 and k:
            km.setdefault(code, Counter())[k] += 1
    fix = {code: cn.most_common(1)[0][0] for code, cn in km.items() if sum(cn.values()) >= 3 and cn.most_common(1)[0][1] / sum(cn.values()) >= 0.6}
    out = [fix.get(re.sub(r"[^a-z0-9]", "", _fold(r[8] if len(r) > 8 else "")), k) for r, k in zip(items, out)]
    labels = {}
    for r, k in zip(items, out):
        if k:
            labels.setdefault(k, Counter())[brand_label(r[idx_hang])] += 1
    fixed = {"abbott han quoc": "Abbott Diagnostics Korea (Hàn Quốc)", "abbott nhat ban": "Abbott Diagnostics Medical (Nhật Bản)",
             "abbott khac": "Abbott (Mỹ / khác)"}
    return [fixed.get(k) or labels[k].most_common(1)[0][0] if k else "Không ghi rõ" for k in out]


def build():
    kw = g.load_kw()
    goi = json.load(open(g.OUT_PATH, encoding="utf-8"))["goi"]
    kq, items, dh_items = results(kw)
    cot = ["ma", "cdt", "tinh", "ngay", "nhom", "ten", "hang", "nhan", "ky_ma", "xuat_xu", "dvt", "sl", "don_gia", "nha_thau", "hinh_thuc", "sl_test", "hang_chuan"]
    for path, rows, nhom in [(TT_PATH, items, [DASH_TEN.get(x["ten"], x["ten"]) for x in kw["nhom"] if x["ten"] not in DASH_BO]),
                             (DH_PATH, dh_items, ["Đường huyết"])]:
        rows.sort(key=lambda r: r[3], reverse=True)
        for r, h in zip(rows, canon_brands(rows, 6)):
            r.append(h)
        json.dump({"cap_nhat": now_vn().strftime("%Y-%m-%d %H:%M"), "nam": YEAR, "nhom": nhom, "cot": cot, "rows": rows},
                  open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    pk = {}
    for p in goi:
        if (p.get("dang") or p.get("lan_dau") or "")[:4] != YEAR:
            continue
        pk[p["ma"]] = {"ma": p["ma"], "ten": p["ten"], "cdt": p["cdt"], "tinh": p["tinh"], "dang": p["dang"], "han": p["han"],
                       "hinh_thuc": p["hinh_thuc"], "so_mh": len(p["hang_hoa"]), "gia_tri": p.get("gia_goi"),
                       "nhom": sorted({h["nhom"] for h in p["hang_hoa"]}), "link": p["link"], "tt": ""}
    # gói đã hủy trong số các gói đã quét (bước build của goi_thau.py bỏ chúng khỏi trang Gói thầu)
    for f in glob.glob(os.path.join(g.CACHE, "meta_*.json")):
        m = json.load(open(f, encoding="utf-8"))
        if m.get("status") == g.HUY and m.get("code") and (m.get("pub") or "")[:4] == YEAR and m["code"] not in pk:
            pk[m["code"]] = {"ma": m["code"], "ten": g.clean(m.get("name")), "cdt": g.clean(m.get("inv")),
                             "tinh": g.province(m, []), "dang": (m.get("pub") or "")[:16].replace("T", " "),
                             "han": (m.get("close") or "")[:16].replace("T", " "),
                             "hinh_thuc": g.FORM_NAMES.get(m.get("bidForm"), m.get("bidForm") or ""), "so_mh": None,
                             "gia_tri": g.num(m.get("price")), "nhom": [], "link": g.detail_link(m["code"], m), "tt": "huy"}
    for ma, r in kq.items():
        p = pk.get(ma)
        if p:
            p.update({"tt": "kq", "kq": r["kq"], "gia_trung": round(r["gia_tri"])})
            p["nhom"] = sorted(set(p["nhom"]) | r["nhom"])
        else:
            pk[ma] = {"ma": ma, "ten": "", "cdt": r["cdt"], "tinh": r["tinh"], "dang": "", "han": "", "hinh_thuc": r["hinh_thuc"],
                      "so_mh": r["so_mh"], "gia_tri": None, "nhom": sorted(r["nhom"]), "link": "", "tt": "kq",
                      "kq": r["kq"], "gia_trung": round(r["gia_tri"])}
    # gộp theo cơ sở y tế; tỉnh lấy theo gói có thông tin
    cs = {}
    for p in pk.values():
        k = key_of(p["cdt"])
        if not k:
            continue
        c = cs.setdefault(k, {"ten": p["cdt"], "tinh": "", "goi": []})
        c["tinh"] = c["tinh"] or p["tinh"]
        c["goi"].append(p)
    out = []
    for c in cs.values():
        c["goi"].sort(key=lambda p: p.get("kq") or p.get("dang") or "", reverse=True)
        out.append(c)
    out.sort(key=lambda c: (-len(c["goi"]), c["ten"]))
    res = {"cap_nhat": now_vn().strftime("%Y-%m-%d %H:%M"), "nam": YEAR, "nhom": [x["ten"] for x in kw["nhom"]], "co_so": out}
    json.dump(res, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    n = sum(len(c["goi"]) for c in out)
    print(f"Xong: {len(out)} cơ sở y tế, {n} gói ({len(kq)} gói đã có kết quả) -> {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    build()
