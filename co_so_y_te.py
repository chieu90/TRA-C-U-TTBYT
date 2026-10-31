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
KEYWORDS = [("test", "all-1"), ("test nhanh", "exact"), ("que thử", "exact"), ("khay thử", "exact"),
            ("xét nghiệm nhanh", "exact"), ("chẩn đoán nhanh", "exact"), ("thanh thử", "exact"), ("kit thử", "exact")]


def now_vn():
    return datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)


def key_of(name):
    """Khóa gộp cơ sở: bỏ hoa/thường, khoảng trắng thừa, dấu câu."""
    return re.sub(r"[^\w]+", " ", (name or "").lower()).strip()


def prc(kw, mt, frm, to, page):
    body = [{"pageSize": 100, "pageNumber": page, "query": [{
        "index": "es-smart-pricing", "keyWord": kw, "keyWordNotMatch": "", "matchType": mt,
        "matchFields": ["ten_thiet_bi", "ma_hs", "xuat_xu", "ma_tbmt", "ky_ma_hieu", "nhan_hieu", "hang_san_xuat"],
        "filters": [{"fieldName": "type", "searchType": "in", "fieldValues": ["HANG_HOA"]},
                    {"fieldName": "tab", "searchType": "in", "fieldValues": ["THIET_BI_VAT_TU_Y_TE"]},
                    {"fieldName": "ngay_dang_tai_kqlcnt", "searchType": "range", "from": frm, "to": to}]}]}]
    return json.loads(g.http(PRC_URL, body))["page"]


def results(kw):
    """({mã TBMT: gói đã có kết quả}, [dòng mặt hàng trúng]) từ dữ liệu trúng thầu năm YEAR, chỉ tính mặt hàng test nhanh."""
    rows = {}
    for q, mt in KEYWORDS:
        for m in range(1, 13):  # chia theo tháng: mỗi truy vấn trả tối đa 10.000 dòng
            frm = f"{YEAR}-{m:02d}-01"
            to = f"{YEAR}-{m + 1:02d}-01" if m < 12 else f"{int(YEAR) + 1}-01-01"
            pg = prc(q, mt, frm, to, 0)
            got = list(pg["content"])
            for p in range(1, min(pg["totalPages"], 100)):
                got += prc(q, mt, frm, to, p)["content"]
            for r in got:
                rows[r["id"]] = r
        print(f"{q}: {len(rows)} dòng", file=sys.stderr)
    pk, items = {}, []
    for r in rows.values():
        nhom = g.group_of(g.clean(r.get("tenThietBi")), kw, r.get("donViTinh"))
        if not nhom or not r.get("maTbmt"):
            continue
        tinh = g.short_prov(next((d.get("provName") for d in r.get("diaDiem") or [] if d.get("provName")), ""))
        if nhom not in DASH_BO:
            items.append([r["maTbmt"], g.clean(r.get("tenCdtBmt")), tinh, (r.get("ngayDangTaiKqlcnt") or "")[:10], nhom,
                          g.clean(r.get("tenThietBi")), g.clean(r.get("hangSanXuat")), g.clean(r.get("nhanHieu")), g.clean(r.get("kyMaHieu")),
                          g.clean(r.get("xuatXu")), g.clean(r.get("donViTinh")), r.get("khoiLuongDouble"), r.get("donGia"),
                          "; ".join(g.clean(w) for w in r.get("winningName") or []), r.get("bidForm") or ""])
        p = pk.setdefault(r["maTbmt"], {"ma": r["maTbmt"], "cdt": g.clean(r.get("tenCdtBmt")), "ma_cdt": r.get("maCdt"),
                                         "tinh": g.short_prov(next((d.get("provName") for d in r.get("diaDiem") or [] if d.get("provName")), "")),
                                         "kq": (r.get("ngayDangTaiKqlcnt") or "")[:10], "hinh_thuc": g.FORM_NAMES.get(r.get("bidForm"), r.get("bidForm") or ""),
                                         "so_mh": 0, "gia_tri": 0, "nhom": set()})
        p["so_mh"] += 1
        p["gia_tri"] += (r.get("donGia") or 0) * (r.get("khoiLuongDouble") or 0)
        p["nhom"].add(nhom)
    return pk, items


def build():
    kw = g.load_kw()
    goi = json.load(open(g.OUT_PATH, encoding="utf-8"))["goi"]
    kq, items = results(kw)
    items.sort(key=lambda r: r[3], reverse=True)
    json.dump({"cap_nhat": now_vn().strftime("%Y-%m-%d %H:%M"), "nam": YEAR, "nhom": [x["ten"] for x in kw["nhom"] if x["ten"] not in DASH_BO],
               "cot": ["ma", "cdt", "tinh", "ngay", "nhom", "ten", "hang", "nhan", "ky_ma", "xuat_xu", "dvt", "sl", "don_gia", "nha_thau", "hinh_thuc"],
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
