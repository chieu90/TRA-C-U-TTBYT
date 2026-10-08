#!/usr/bin/env python3
"""
Thu thập dữ liệu "Văn bản công bố" từ https://vimda.moh.gov.vn/web/guest/van-ban-cong-bo

Các cột xuất ra:
  Mã hồ sơ, Số công bố / số lưu hành, Thủ tục, Ngày công bố, Công ty công bố,
  Tên sản phẩm (TBYT), Tên thương mại, Hãng / cơ sở sản xuất, Chủ sở hữu, Trạng thái, Link

"Hãng sản xuất" chỉ có trong trang chi tiết của từng hồ sơ, nên mỗi dòng cần 1 request thêm.
Dùng --no-detail nếu chỉ cần danh sách (nhanh hơn nhiều).

Ví dụ:
  python3 vimda_scraper.py --max 200                              # 200 hồ sơ mới nhất
  python3 vimda_scraper.py --tu 01/09/2026 --den 30/09/2026       # theo khoảng ngày công bố
  python3 vimda_scraper.py --cong-ty "B Braun" --max 1000
  python3 vimda_scraper.py --ten-tbyt "máy thở"
  python3 vimda_scraper.py --all --no-detail                      # toàn bộ danh sách (~121k dòng)

Có thể chạy lại cùng lệnh: chi tiết đã tải được lưu cache trong vimda_cache.json.
"""
import argparse, csv, html, json, os, re, ssl, sys, time
import urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://vimda.moh.gov.vn/web/guest/van-ban-cong-bo"
NS = "_vanbancongbo_WAR_trangthietbiyteportlet_"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"
PAGE_SIZE = 200
CACHE_FILE = "vimda_cache.json"

# Máy chủ vimda không gửi kèm chứng chỉ trung gian (GlobalSign GCC R46 OV TLS CA 2025),
# nên Python báo CERTIFICATE_VERIFY_FAILED. Tải chứng chỉ trung gian từ GlobalSign và nạp thêm.
INTERMEDIATE_URL = "http://secure.globalsign.com/cacert/gsgccr46ovtlsca2025.crt"


def make_ssl_ctx():
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        if os.path.exists("/etc/ssl/cert.pem"):
            ctx.load_verify_locations("/etc/ssl/cert.pem")
    try:
        der = urllib.request.urlopen(INTERMEDIATE_URL, timeout=30).read()
        ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(der))
    except Exception as e:
        print(f"Không tải được chứng chỉ trung gian: {e}", file=sys.stderr)
    return ctx


SSL_CTX = make_ssl_ctx()


def fetch(url, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90, context=SSL_CTX) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(3 * (i + 1))


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def list_url(page, a, delta=PAGE_SIZE):
    q = {
        "p_p_id": "vanbancongbo_WAR_trangthietbiyteportlet", "p_p_lifecycle": "0",
        "p_p_state": "normal", "p_p_mode": "view", "p_p_col_id": "column-1", "p_p_col_count": "1",
        NS + "delta": str(delta), NS + "cur": str(page),
        NS + "keyword": a.keyword or "", NS + "tenDoanhNghiep": a.cong_ty or "",
        NS + "tenTTBYT": a.ten_tbyt or "", NS + "ngayCongBoTu": a.tu or "",
        NS + "ngayCongBoDen": a.den or "", NS + "coQuanQuanLyId": "0", NS + "tthcId": "0",
        NS + "showHide": "1" if (a.cong_ty or a.ten_tbyt or a.tu or a.den) else "0",
        NS + "advancedSearch": "false", NS + "andOperator": "true",
    }
    return BASE + "?" + urllib.parse.urlencode(q)


ROW_RE = re.compile(r"<tr>\s*<td style=\"text-align: center;\">\d+</td>(.*?)</tr>", re.S)


def parse_list(page_html):
    total = None
    m = re.search(r"of ([\d.]+) kết quả", page_html)
    if m:
        total = int(m.group(1).replace(".", ""))
    rows = []
    for body in ROW_RE.findall(page_html):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)
        if len(tds) < 7:
            continue
        link = re.search(r'href="([^"]*xemhoso[^"]*)"', tds[2])
        ngay = re.search(r"Ngày công bố:\s*([\d/]+)", tds[2])
        pdf = re.search(r'href="(/documents/[^"]+)"', tds[6])
        rows.append({
            "Mã hồ sơ": clean(tds[0]),
            "Số công bố / số lưu hành": clean(tds[1]),
            "Thủ tục": clean(re.sub(r'<p class="oep-hoso-info">.*', "", tds[2], flags=re.S)),
            "Ngày công bố": ngay.group(1) if ngay else "",
            "Công ty công bố": clean(tds[3]),
            "Tên sản phẩm (TBYT)": clean(tds[4]),
            "Trạng thái": clean(tds[5]),
            "Link chi tiết": html.unescape(link.group(1)) if link else "",
            "File công bố": ("https://vimda.moh.gov.vn" + html.unescape(pdf.group(1))) if pdf else "",
        })
    return total, rows


DETAIL_FIELDS = {
    "Tên thương mại": [r"Tên thương mại(?: \(nếu có\))?"],
    "Hãng / cơ sở sản xuất": [r"Tên cơ sở sản xuất", r"Hãng,? nước sản xuất", r"Hãng sản xuất"],
    "Nước sản xuất": [r"Nước sản xuất"],
    "Chủ sở hữu": [r"Tên chủ sở hữu"],
}


def parse_detail(page_html):
    t = re.sub(r"<(script|style)\b.*?</\1>", "", page_html, flags=re.S)
    t = re.sub(r"<[^>]+>", "|", t)
    t = re.sub(r"\s+", " ", html.unescape(t))
    t = re.sub(r"(\| ?)+", "|", t)
    out = {}
    for field, labels in DETAIL_FIELDS.items():
        vals = []
        for lab in labels:
            for m in re.finditer(r"\|-? ?" + lab + r" ?: ?\|([^|]*)\|", t):
                v = m.group(1).strip().rstrip(",").strip()
                if v and v not in vals and not v.startswith("-"):
                    vals.append(v)
        out[field] = "; ".join(vals)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=200, help="số hồ sơ tối đa (mặc định 200)")
    ap.add_argument("--all", action="store_true", help="lấy toàn bộ kết quả")
    ap.add_argument("--tu", help="ngày công bố từ (dd/mm/yyyy)")
    ap.add_argument("--den", help="ngày công bố đến (dd/mm/yyyy)")
    ap.add_argument("--cong-ty", help="lọc theo tên doanh nghiệp")
    ap.add_argument("--ten-tbyt", help="lọc theo tên thiết bị y tế")
    ap.add_argument("--keyword", help="mã hồ sơ / số công bố")
    ap.add_argument("--no-detail", action="store_true", help="bỏ qua trang chi tiết (không có hãng sản xuất)")
    ap.add_argument("--workers", type=int, default=3, help="số luồng tải chi tiết (mặc định 3)")
    ap.add_argument("-o", "--out", default="vimda_data", help="tên file đầu ra (không đuôi)")
    a = ap.parse_args()
    limit = None if a.all else a.max

    rows, page, total = [], 1, None
    while True:
        total, got = parse_list(fetch(list_url(page, a)))
        rows += got
        print(f"Trang {page}: +{len(got)} (đã có {len(rows)}/{total})", file=sys.stderr)
        if not got or (limit and len(rows) >= limit) or (total and len(rows) >= total):
            break
        page += 1
        time.sleep(0.5)
    if limit:
        rows = rows[:limit]

    if not a.no_detail:
        cache = {}
        if os.path.exists(CACHE_FILE):
            cache = json.load(open(CACHE_FILE, encoding="utf-8"))
        todo = [r for r in rows if r["Link chi tiết"] and r["Link chi tiết"] not in cache]

        def work(r):
            try:
                return r["Link chi tiết"], parse_detail(fetch(r["Link chi tiết"])), None
            except Exception as e:
                return r["Link chi tiết"], None, e

        failed = []
        with ThreadPoolExecutor(a.workers) as ex:
            for i, (url, d, err) in enumerate(ex.map(work, todo), 1):
                if d is not None:
                    cache[url] = d
                else:
                    failed.append(url)
                if i % 50 == 0 or i == len(todo):
                    print(f"Chi tiết: {i}/{len(todo)} (lỗi {len(failed)})", file=sys.stderr)
                    json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        # Tải lại tuần tự các hồ sơ bị lỗi (máy chủ hay quá tải khi nhiều request song song)
        for url in failed:
            time.sleep(1)
            _, d, err = work({"Link chi tiết": url})
            if d is not None:
                cache[url] = d
            else:
                print(f"Bỏ qua (lỗi {err}): {url}", file=sys.stderr)
        if failed:
            json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
        for r in rows:
            r.update(cache.get(r["Link chi tiết"], {k: "" for k in DETAIL_FIELDS}))

    cols = ["Mã hồ sơ", "Số công bố / số lưu hành", "Thủ tục", "Ngày công bố", "Công ty công bố",
            "Tên sản phẩm (TBYT)"]
    if not a.no_detail:
        cols += list(DETAIL_FIELDS)
    cols += ["Trạng thái", "File công bố", "Link chi tiết"]

    with open(a.out + ".csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Đã ghi {a.out}.csv", file=sys.stderr)

    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Văn bản công bố"
        ws.append(cols)
        for r in rows:
            ws.append([r.get(c, "") for c in cols])
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        widths = {"Thủ tục": 45, "Công ty công bố": 40, "Tên sản phẩm (TBYT)": 45,
                  "Hãng / cơ sở sản xuất": 40, "Chủ sở hữu": 35, "Tên thương mại": 30}
        for i, c in enumerate(cols, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = widths.get(c, 20)
        wb.save(a.out + ".xlsx")
        print(f"Đã ghi {a.out}.xlsx", file=sys.stderr)
    except ImportError:
        print("(Cài openpyxl để xuất thêm .xlsx: pip install openpyxl)", file=sys.stderr)


if __name__ == "__main__":
    main()
