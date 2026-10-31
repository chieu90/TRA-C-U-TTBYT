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
TT_PATH = os.path.join(g.HERE, "data", "trung_thau.json")  # chi tiết từng mặt hàng trúng thầu cho trang Dashboard
PRC_URL = g.HOST + "/o/egp-portal-winning-bid-data/services/smart/search_prc"
YEAR = "2026"
DASH_BO = {"Que thử nước tiểu"}  # nhóm không đưa vào Dashboard trúng thầu (theo yêu cầu người dùng)
# dấu hiệu test nhanh trong mô tả / nhãn hiệu, dùng khi tên hàng không có chữ test/que thử/khay thử
RAPID_RE = re.compile(r"nhanh|sắc ký|immunochromatograph|lateral flow|rapid|cassette|khay thử|que thử|test strip|quick test")
NOT_RAPID_RE = re.compile(r"elisa|clia|hóa phát quang|hoá phát quang|chemilumin|điện hóa phát quang|miễn dịch huỳnh quang|realtime|real-time|pcr|"
                         r"tải lượng|hplc|cột sắc ký|sắc ký lỏng|reagent kit|kháng thể đa dòng|kháng thể đơn dòng|máy xét nghiệm miễn dịch")

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
    ws = list(kw.get("can_co", [])) + [t.strip() for n in kw["nhom"] for t in n["tu"]]
    return [(w, "exact" if " " in w else "all-1") for w in dict.fromkeys(w for w in ws if len(w) >= 3)]


def classify(r, kw):
    """Nhóm test nhanh của một dòng trúng thầu, None nếu không phải test nhanh."""
    name, uom = ten(r), r.get("donViTinh")
    extra = g.clean(r.get("nhanHieu")) + " " + g.clean(r.get("kyMaHieu")) + " " + g.clean(r.get("cauHinh"))[:300]
    txt = g.norm(name + " " + extra)
    # ELISA, CLIA, PCR, hóa chất chạy máy, pin/phụ kiện máy: xét trong tên + nhãn hiệu
    # (mô tả test nhanh hay ghi "độ nhạy so với PCR/ELISA" nên không xét mô tả)
    short = g.norm(name + " " + g.clean(r.get("nhanHieu")))
    if NOT_RAPID_RE.search(short) or ACCESSORY_RE.search(g.norm(name)) or any(b and b in " " + g.norm(name) + " " for b in kw["_bo"]):
        return None
    if any(c in g.norm(name) for c in kw["_can"]):  # tên đã ghi rõ test/que thử/khay thử...
        return g.group_of(name, kw, uom)
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
    pk, items = {}, []
    for r in rows.values():
        nhom = classify(r, kw)
        if not nhom or not r.get("maTbmt"):
            continue
        tinh = g.short_prov(next((d.get("provName") for d in r.get("diaDiem") or [] if d.get("provName")), ""))
        if nhom not in DASH_BO:
            items.append([r["maTbmt"], g.clean(r.get("tenCdtBmt")), tinh, (r.get("ngayDangTaiKqlcnt") or "")[:10], nhom,
                          ten(r), g.clean(r.get("hangSanXuat")), g.clean(r.get("nhanHieu")), g.clean(r.get("kyMaHieu")),
                          g.clean(r.get("xuatXu")), g.clean(r.get("donViTinh")), r.get("khoiLuongDouble"), don_gia(r),
                          "; ".join(g.clean(w) for w in r.get("winningName") or []), r.get("bidForm") or "", sl_test(r)])
        p = pk.setdefault(r["maTbmt"], {"ma": r["maTbmt"], "cdt": g.clean(r.get("tenCdtBmt")), "ma_cdt": r.get("maCdt"),
                                         "tinh": g.short_prov(next((d.get("provName") for d in r.get("diaDiem") or [] if d.get("provName")), "")),
                                         "kq": (r.get("ngayDangTaiKqlcnt") or "")[:10], "hinh_thuc": g.FORM_NAMES.get(r.get("bidForm"), r.get("bidForm") or ""),
                                         "so_mh": 0, "gia_tri": 0, "nhom": set()})
        p["so_mh"] += 1
        p["gia_tri"] += (don_gia(r) or 0) * (r.get("khoiLuongDouble") or 0)
        p["nhom"].add(nhom)
    return pk, items


def build():
    kw = g.load_kw()
    goi = json.load(open(g.OUT_PATH, encoding="utf-8"))["goi"]
    kq, items = results(kw)
    items.sort(key=lambda r: r[3], reverse=True)
    json.dump({"cap_nhat": now_vn().strftime("%Y-%m-%d %H:%M"), "nam": YEAR, "nhom": [x["ten"] for x in kw["nhom"] if x["ten"] not in DASH_BO],
               "cot": ["ma", "cdt", "tinh", "ngay", "nhom", "ten", "hang", "nhan", "ky_ma", "xuat_xu", "dvt", "sl", "don_gia", "nha_thau", "hinh_thuc", "sl_test"],
               "rows": items}, open(TT_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
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
