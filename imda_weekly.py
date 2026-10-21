#!/usr/bin/env python3
"""
Lấy hồ sơ "Khay thử" MỚI công bố trên vimda để chèn vào tab IMDA (Google Sheet "THÔNG TIN ĐỐI THỦ TEST NHANH").

    python3 imda_weekly.py            # tìm hồ sơ mới -> xuat/imda_moi.json
    python3 imda_weekly.py --commit   # sau khi đã chèn vào Google Sheet: ghi nhận là đã có

xuat/imda_moi.json gồm:
  rows      : các dòng đúng thứ tự cột A..M của tab IMDA (cột G "TÊN CHUNG" để trống), mới nhất trước
  new_names : tên hãng gốc chưa có trong bảng đồng bộ -> [tên gốc, tên chuẩn đề xuất]
Trạng thái (các hồ sơ đã có trong sheet) lưu ở xuat/imda_state.json.
"""
import argparse, json, os, re, sys, time, unicodedata

import vimda_scraper as v
import build_index as b

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "xuat", "imda_state.json")
OUT = os.path.join(HERE, "xuat", "imda_moi.json")
KEYWORD = "Khay thử"

LEGAL = {"co", "ltd", "limited", "inc", "incorporated", "corp", "corporation", "company", "llc", "gmbh", "sa", "srl",
         "plc", "pte", "pty", "jsc", "ag", "bv", "kk", "sdn", "bhd", "cong", "ty", "tnhh", "the", "sas", "spa", "s", "a",
         "l", "r", "oy", "ab", "nv", "kg", "mbh", "lp", "pvt", "private", "group", "holdings", "international"}


def name_key(s):
    s = unicodedata.normalize("NFD", s or "").replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower().replace("&", " and ")
    return " ".join(w for w in re.sub(r"[^a-z0-9]+", " ", s).split() if w not in LEGAL)


def clean(s):
    return re.sub(r"[.,;\s]+$", "", re.sub(r"\s+", " ", s or "").strip())


def maker_raw(hang, csh):
    bad = lambda x: not x or re.search(r"theo ph[uụ] l[uụ]c", x, re.I)
    return clean(csh if bad(hang) else hang) if not (bad(hang) and bad(csh)) else ""


def short_link(u):
    """Bỏ tham số chuyển hướng dài dòng; link vẫn mở đúng hồ sơ."""
    return re.sub(r"&_vanbancongbo_WAR_trangthietbiyteportlet_redirectVanBanURL=[^&]*", "", u or "")


def date_key(d):
    p = (d or "").split("/")
    return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else ""


def load_state():
    return json.load(open(STATE, encoding="utf-8"))


def find_new(st):
    a = argparse.Namespace(keyword=None, cong_ty=None, ten_tbyt=KEYWORD, tu=None, den=None)
    seen, new, page = set(st["keys"]), [], 1
    while True:
        url = v.list_url(page, a, delta=200).replace("p_p_state=normal", "p_p_state=exclusive", 1)
        _, rows = v.parse_list(b.fetch(url))
        if not rows:
            break
        stop = False
        for r in rows:
            k = r["Mã hồ sơ"] + "|" + r["Số công bố / số lưu hành"]
            if date_key(r["Ngày công bố"]) < st["last_date"]:
                stop = True          # cũ hơn lần cập nhật trước -> chắc chắn đã có
                continue
            if k not in seen:
                new.append(r)
        if stop:
            break
        page += 1
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    a = ap.parse_args()
    st = load_state()

    if a.commit:
        out = json.load(open(OUT, encoding="utf-8"))
        for row in out["rows"]:
            st["keys"].append(row[1] + "|" + row[0])
        if out["rows"]:
            st["last_date"] = max(st["last_date"], max(date_key(r[3]) for r in out["rows"]))
        for raw, canon in out["new_names"]:
            st["map"][raw] = canon
        st["updated"] = time.strftime("%d/%m/%Y %H:%M")
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"Đã ghi nhận {len(out['rows'])} hồ sơ, {len(out['new_names'])} tên hãng mới.")
        return

    new = find_new(st)
    det = b.load_details()
    rows, new_names = [], []
    canon_by_key = {name_key(c): c for c in set(st["map"].values())}
    for r in sorted(new, key=lambda r: date_key(r["Ngày công bố"]), reverse=True):
        d = det.get(b.key_of(r["Link chi tiết"]))
        if d is None:
            try:
                d = v.parse_detail(b.fetch(b.detail_url(r["Link chi tiết"])))
            except Exception as e:
                print(f"Không lấy được chi tiết {r['Mã hồ sơ']}: {e}", file=sys.stderr)
                d = {}
        rows.append([r["Số công bố / số lưu hành"], r["Mã hồ sơ"], r["Thủ tục"], r["Ngày công bố"], r["Công ty công bố"],
                     r["Tên sản phẩm (TBYT)"], "", d.get("Tên thương mại", ""), d.get("Hãng / cơ sở sản xuất", ""),
                     d.get("Chủ sở hữu", ""), r["Trạng thái"], r["File công bố"], short_link(r["Link chi tiết"])])
        raw = maker_raw(d.get("Hãng / cơ sở sản xuất", ""), d.get("Chủ sở hữu", ""))
        if raw and raw not in st["map"] and raw not in [n[0] for n in new_names]:
            canon = canon_by_key.get(name_key(raw), raw)   # trùng khoá chuẩn hoá -> gộp vào hãng đã có
            new_names.append([raw, canon])
    json.dump({"rows": rows, "new_names": new_names, "checked": time.strftime("%d/%m/%Y %H:%M")},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"{len(rows)} hồ sơ khay thử mới (từ {st['last_date']}), {len(new_names)} tên hãng mới -> {os.path.relpath(OUT, HERE)}")


if __name__ == "__main__":
    main()
