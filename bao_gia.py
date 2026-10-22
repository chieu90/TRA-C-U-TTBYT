#!/usr/bin/env python3
"""
Lấy "Giá từ Yêu cầu báo giá" trên muasamcong (mục Hóa chất/vật tư xét nghiệm, thiết bị y tế)
và lọc các mặt hàng thuộc sản phẩm quan tâm (cùng bộ từ khóa với trang Gói thầu).

    python3 bao_gia.py

- Nguồn: POST /o/egp-portal-smart-price/services/smart/search_price (công khai, không cần token).
  Mỗi bản ghi là MỘT báo giá của một nhà cung cấp cho một dòng hàng trong yêu cầu báo giá (YCBG),
  nên một dòng hàng có thể có nhiều mức giá; API không trả tên nhà cung cấp.
- Muasamcong chỉ giữ dữ liệu khoảng 1 tháng gần nhất, nên file đầu ra cộng dồn: dòng cũ được giữ lại.
- Đầu ra: data/bao_gia.json — trang /bao-gia của app.py đọc file này.
"""
import json, os, re, statistics, sys
from datetime import datetime

import goi_thau as g

URL = g.HOST + "/o/egp-portal-smart-price/services/smart/search_price"
OUT_PATH = os.path.join(g.HERE, "data", "bao_gia.json")
# (từ khóa, kiểu khớp) gõ vào ô tìm kiếm; trùng nhau thì gộp theo (mã YCBG, dòng hàng)
TINH_FIX = {"Đăklăk": "Đắk Lắk", "Đắklắk": "Đắk Lắk", "Đaklak": "Đắk Lắk", "Hồ Chí Minh": "TP Hồ Chí Minh", "HCM": "TP Hồ Chí Minh"}
KEYWORDS = [("test", "all-1"), ("test nhanh", "exact"), ("que thử", "exact"), ("khay thử", "exact"),
            ("xét nghiệm nhanh", "exact"), ("chẩn đoán nhanh", "exact"), ("thanh thử", "exact"), ("kit thử", "exact")]


def search(keyword, match, page):
    body = [{"pageSize": 100, "pageNumber": page, "query": [{
        "index": "es-smartprice", "keyWord": keyword, "keyWordNotMatch": "", "matchType": match,
        "matchFields": ["item_name", "description"],
        "filters": [{"fieldName": "quote_group", "searchType": "in", "fieldValues": ["4"]}]}]}]
    return json.loads(g.http(URL, body))["page"]


def fetch():
    """{(mã YCBG id, rowKey): [bản ghi báo giá...]} — lấy theo từ khóa cho nhiều báo giá nhất."""
    best = {}
    for kw, mt in KEYWORDS:
        pg = search(kw, mt, 0)
        rows = list(pg["content"])
        for p in range(1, min(pg["totalPages"], 100)):
            rows += search(kw, mt, p)["content"]
        grp = {}
        for r in rows:
            grp.setdefault((r["requestQuoteId"], r["rowKey"]), []).append(r)
        for k, v in grp.items():
            if len(v) > len(best.get(k, [])):
                best[k] = v
        print(f"{kw}: {len(rows)} báo giá, {len(grp)} dòng hàng", file=sys.stderr)
    return best


def qty(v):
    try:
        f = float(str(v).replace(",", "."))
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return v


def build():
    kw = g.load_kw()
    old = {}
    if os.path.exists(OUT_PATH):
        for it in json.load(open(OUT_PATH, encoding="utf-8")).get("items", []):
            old[it["key"]] = it
    new = {}
    for (rq_id, row_key), quotes in fetch().items():
        r = quotes[0]
        name = g.clean(r.get("itemName"))
        desc = g.clean(r.get("description"))
        nhom = g.group_of(name, kw) or g.group_of(name + " " + desc[:120], kw)
        if not nhom:
            continue
        prices = sorted(q["price"] for q in quotes if (q.get("price") or 0) > 1)  # bỏ giá 0 / 1đ (giá giữ chỗ)
        noi = g.clean(r.get("location"))
        key = rq_id + "|" + row_key
        new[key] = {
            "key": key, "ma": r.get("requestQuoteNo"), "noi": noi, "tinh": TINH_FIX.get(t := g.province({"inv": noi}, []), t),
            "hieu_luc": (r.get("validityFromDate") or "")[:10], "han": (r.get("receptionDateTo") or "")[:16].replace("T", " "),
            "hl_ngay": r.get("validityPeriod"), "nhom": nhom, "ten": name, "mo_ta": desc, "dvt": g.clean(r.get("unit")),
            "sl": qty(r.get("quantity")), "gia": prices, "so_bg": len(prices),
            "min": prices[0] if prices else None, "tv": statistics.median(prices) if prices else None,
            "max": prices[-1] if prices else None,
            "lan_dau": (old.get(key) or {}).get("lan_dau") or datetime.now().strftime("%Y-%m-%d %H:%M")}
    items = list({**old, **new}.values())
    items.sort(key=lambda i: (i["hieu_luc"], i["ma"]), reverse=True)
    res = {"cap_nhat": datetime.now().strftime("%Y-%m-%d %H:%M"), "nhom": [x["ten"] for x in kw["nhom"]], "items": items}
    json.dump(res, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"Xong: {len(items)} dòng hàng ({len(new)} lấy lần này), {len({i['ma'] for i in items})} YCBG -> {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    build()
