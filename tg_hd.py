"""Thời gian thực hiện hợp đồng của các gói đã có kết quả (cột TG HĐ trên trang KQ Test / KQ Đường Huyết).

Dữ liệu trúng thầu (search_prc) không ghi thời gian hợp đồng; thông tin này nằm trong chi tiết TBMT,
tra qua API công khai get-detail nhưng cần id (uuid) của gói. id lấy bằng cách tìm gói trên giao diện web
muasamcong (có reCAPTCHA, làm bằng trình duyệt) rồi lưu bảng mã TBMT -> id vào index/tbmt_map.json.

  python3 tg_hd.py                 # tra các gói chưa có, ghi data/tg_hd.json {mã TBMT: "12 tháng"}
"""
import glob, json, os, sys
from concurrent.futures import ThreadPoolExecutor

import goi_thau as g

MAP_PATH = os.path.join(g.HERE, "index", "tbmt_map.json")
OUT_PATH = os.path.join(g.HERE, "data", "tg_hd.json")


def detail(notify_id):
    """(cperiod, cunit) của gói qua API công khai (như goi_thau.meta_of nhưng không ghi cache)."""
    n = (json.loads(g.http(g.HOST + "/api/unau/portal/ebidorg/bid-no-contractor/get-detail", {"body": {"id": notify_id}}))
         .get("body") or {}).get("bidNotification")
    if n:
        return {"cperiod": n.get("contractPeriod"), "cunit": n.get("contractPeriodUnit")}
    r = json.loads(g.http(g.HOST + "/o/egp-portal-contractor-selection-v2/services/online-reoffer/detail", {"id": notify_id}))
    d = r.get("bidDetail") or {}
    return {"cperiod": d.get("cperiod"), "cunit": d.get("cperiodUnit")}


def text_of(m):
    t = g.contract_time(m, [])
    if not t["text"]:
        return ""
    # ghi theo ngày -> thêm số tháng quy đổi cho dễ so
    if t["text"].endswith("ngày") and t["ngay"] >= 60:
        return f"{t['text']} (~{round(t['ngay'] / 30.4)} tháng)"
    return t["text"]


def known():
    """Gói đã có sẵn thời gian hợp đồng: file cũ + meta các gói đã quét lúc còn mở."""
    out = json.load(open(OUT_PATH, encoding="utf-8")) if os.path.exists(OUT_PATH) else {}
    for f in glob.glob(os.path.join(g.CACHE, "meta_*.json")):
        m = json.load(open(f, encoding="utf-8"))
        if m.get("code") and m.get("code") not in out and text_of(m):
            out[m["code"]] = text_of(m)
    return out


def build():
    out = known()
    ids = json.load(open(MAP_PATH)) if os.path.exists(MAP_PATH) else {}
    kq = set()
    for f in ("trung_thau.json", "trung_thau_2025.json", "duong_huyet.json", "duong_huyet_2025.json"):
        p = os.path.join(g.HERE, "data", f)
        if os.path.exists(p):
            kq |= {r[0] for r in json.load(open(p, encoding="utf-8"))["rows"]}
    todo = [(ma, ids[ma]) for ma in kq if ma not in out and ma in ids]
    print(f"{len(kq)} gói có KQ, đã có {len(kq & set(out))}, cần tra {len(todo)}", file=sys.stderr)

    def one(x):
        try:
            return x[0], text_of(detail(x[1]))
        except Exception as e:
            print(x[0], "lỗi", e, file=sys.stderr)
            return x[0], None
    with ThreadPoolExecutor(6) as ex:
        for ma, t in ex.map(one, todo):
            if t is not None:
                out[ma] = t
    json.dump(dict(sorted(out.items())), open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"Xong: {sum(1 for m in kq if out.get(m))}/{len(kq)} gói có TG HĐ -> {OUT_PATH}", file=sys.stderr)
    patch(out)


def patch(tg):
    """Ghi cột tg_hd thẳng vào các file KQ đã dựng (khỏi chạy lại co_so_y_te.py)."""
    for f in ("trung_thau.json", "trung_thau_2025.json", "duong_huyet.json", "duong_huyet_2025.json"):
        p = os.path.join(g.HERE, "data", f)
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        if "tg_hd" not in d["cot"]:
            d["cot"].append("tg_hd")
            for r in d["rows"]:
                r.append("")
        i = d["cot"].index("tg_hd")
        for r in d["rows"]:
            r[i] = tg.get(r[0], "")
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    build()
