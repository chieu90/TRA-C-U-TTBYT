"""Discover new tenders using the reference site's public search service.

Details use the same public service; product filtering uses goi_thau.py. No AI calls or CAPTCHA solving.
The third-party search service can change or stop without notice.
"""
import argparse
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import goi_thau as g

SEARCH_URL = os.environ.get("TENDER_SEARCH_URL", "https://tender-insight-pro.vercel.app/api/msc/search")
KEYWORDS = ("test", "que thử", "hóa chất", "hoá chất", "vật tư", "sinh phẩm", "xét nghiệm")


def search(keyword, number, since):
    payload = {"keyWord": keyword, "category": "tbmt", "searchTarget": "bidName",
               "pageSize": 50, "pageNumber": number, "bidField": "HH",
               "advanced": {"publicDateFrom": since}}
    req = urllib.request.Request(SEARCH_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = json.load(response)
    if data.get("success") is not True:
        raise RuntimeError("Search service did not return success")
    page = (data.get("data") or {}).get("page")
    if not isinstance(page, dict) or not isinstance(page.get("content"), list):
        raise ValueError("Unexpected search response; existing data is unchanged")
    return page


def discover(days=14, max_pages=30):
    now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    found = {}
    for keyword in KEYWORDS:
        seen_pages = set()
        for number in range(max_pages):
            page = search(keyword, number, since)
            rows = page["content"]
            signature = tuple(str(r.get("notifyId") or r.get("id")) for r in rows)
            if rows and signature in seen_pages:
                raise RuntimeError("Search service repeated a page; refusing incomplete discovery")
            seen_pages.add(signature)
            for row in rows:
                nid = row.get("notifyId") or row.get("id")
                code = row.get("notifyNo")
                close = str(row.get("bidCloseDate") or "")[:16].replace("T", " ")
                if (code and isinstance(nid, str) and re.fullmatch(r"[0-9a-f-]{36}", nid)
                        and close >= now.strftime("%Y-%m-%d %H:%M") and row.get("status") != g.HUY):
                    found[code] = row
            if not rows or page.get("last") is True or number + 1 >= int(page.get("totalPages", 1)):
                break
            time.sleep(1)
        else:
            raise RuntimeError("Search page limit reached; increase --max-pages")
        print(f"{keyword}: {len(found)} open candidate tenders", flush=True)
        time.sleep(1)
    return found


def detail(row):
    payload = {key: row.get(key) for key in ("id", "notifyId", "notifyNo", "bidForm", "processApply", "bidMode")}
    payload["targetMode"] = "hsmt"
    endpoint = SEARCH_URL.rsplit("/", 1)[0] + "/hsmt"
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        result = json.load(response)
    data = result.get("data") or {}
    if result.get("success") is not True or not isinstance(data.get("items"), list):
        raise RuntimeError("Detail service returned an invalid response")
    overview = data.get("overview") or {}
    if not overview:
        raise RuntimeError("Detail service omitted the tender overview")
    return data


def package(row, data):
    kw = g.load_kw()
    items = [item for item in data["items"] if not item.get("isParentLot")]
    counts = {}
    for item in items:
        lot = item.get("lotNo") or ""
        counts[lot] = counts.get(lot, 0) + 1
    matched = []
    unknown = {"muc": "Không ghi rõ", "nguon": "", "trich": ""}
    for item in items:
        name = g.clean(item.get("itemName"))
        category = g.clean(item.get("categoryName") or item.get("lotName"))
        if not name or g.norm(name) in ("không yêu cầu", "không áp dụng", "không", "-"):
            name = category
        group = g.group_of(name, kw, item.get("unit")) or g.group_of(category, kw, item.get("unit"))
        if not group or group in getattr(g, "BO_NHOM_BG", set()):
            continue
        quantity = g.num(item.get("quantity"))
        lot = item.get("lotNo") or ""
        lot_price = g.num(item.get("lotPrice"))
        unit_price = g.num(item.get("estimatedUnitPrice")) or None
        if unit_price is None and counts[lot] == 1 and lot_price and quantity:
            unit_price = round(lot_price / quantity)
        matched.append({"nhom": group, "ten": name, "dvt": g.clean(item.get("unit")), "sl": quantity,
                        "lo": lot, "ten_lo": g.clean(item.get("lotName")), "gia_lo": lot_price,
                        "don_gia": unit_price, "ky_ma": g.clean(item.get("itemCode")),
                        "hang": g.clean(item.get("manufacture") or item.get("brand")),
                        "xuat_xu": g.clean(item.get("goodsOrigin")),
                        "tskt": g.clean(item.get("specification")), "uy_quyen": dict(unknown)})
    if not matched:
        return None
    title = row.get("bidName") or ""
    if isinstance(title, list): title = title[0] if title else ""
    price = row.get("bidPrice")
    if isinstance(price, list): price = price[0] if price else None
    meta = dict(row, id=row.get("notifyId") or row["id"])
    locations = row.get("locations") or []
    return {"ma": row["notifyNo"], "ten": g.clean(title), "cdt": g.clean(row.get("investorName")),
            "tinh": g.clean(locations[0].get("provName")) if locations else "",
            "han": str(row.get("bidCloseDate") or "")[:16].replace("T", " "),
            "dang": str(row.get("publicDate") or "")[:16].replace("T", " "),
            "hinh_thuc": g.FORM_NAMES.get(row.get("bidForm"), row.get("bidForm") or ""),
            "gia_goi": g.num(price), "link": g.detail_link(row["notifyNo"], meta),
            "lan_dau": datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M"),
            "uy_quyen": unknown, "tg_hd": {"text": g.clean(data["overview"].get("contractDuration")), "ngay": None},
            "hang_hoa": matched, "nguon_tim_kiem": SEARCH_URL}


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)


def sync(candidates, limit=40):
    output = Path(g.OUT_PATH)
    state_path = output.with_name("goi_thau_discovery.json")
    previous = json.loads(output.read_text(encoding="utf-8"))
    known = {row["ma"]: row for row in previous.get("goi", [])}
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    now = datetime.now(timezone.utc).timestamp()
    pending = []
    for code, row in candidates.items():
        key = code + ":" + str(row.get("notifyId") or row.get("id")) + ":" + str(row.get("notifyVersion", "")) + ":parser-v2"
        if code not in known and now - state.get(key, 0) >= 86400:
            pending.append((key, row))
    medical = re.compile(r"test|que thử|xét nghiệm|sinh phẩm|hóa chất|hoá chất|y tế|bệnh viện|truyền máu|huyết học|sản nhi", re.I)
    def priority(pair):
        row = pair[1]
        text = str(row.get("bidName") or "") + " " + str(row.get("investorName") or "")
        return bool(medical.search(text)), row.get("publicDate") or ""
    pending.sort(key=priority, reverse=True)
    added, errors = 0, 0
    print(f"{len(pending)} new candidates; processing up to {limit} this run", flush=True)
    for key, row in pending[:limit]:
        try:
            fresh = package(row, detail(row))
            if fresh:
                known[fresh["ma"]] = fresh
                previous["goi"] = sorted(known.values(), key=lambda p: p.get("han", ""))
                # Discovery does not claim that old records have been refreshed.
                previous["phat_hien_moi"] = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
                save(output, previous)
                added += 1
                print("Added", row["notifyNo"], len(fresh["hang_hoa"]), "items", flush=True)
            state[key] = now
            save(state_path, state)
        except Exception as error:
            errors += 1
            print(row.get("notifyNo"), type(error).__name__, "- will retry next run", flush=True)
        time.sleep(1)
    print(f"Added {added} tenders, {errors} failed, {max(0, len(pending)-limit)} queued", flush=True)
    if errors:
        raise RuntimeError(f"{errors} tender details failed; successful additions were saved")
    return added


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    candidates = discover(args.days, args.max_pages)
    print(f"Discovered {len(candidates)} open candidate tenders", flush=True)
    if not args.discover_only:
        sync(candidates, args.limit)
