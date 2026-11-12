"""Gửi email khi có gói thầu / yêu cầu báo giá (YCBG) mới trong data/goi_thau.json và data/bao_gia.json.

Chạy trên GitHub Actions sau mỗi lần cập nhật dữ liệu (workflow thong-bao-mail.yml). Không dùng AI.
Cấu hình qua GitHub Secrets (người dùng tự nhập, không ghi vào mã nguồn):
  MAIL_USER  – tài khoản Gmail dùng để gửi
  MAIL_PASS  – mật khẩu ứng dụng (App Password) 16 ký tự của tài khoản đó
  MAIL_TO    – email quản lý nhận TOÀN BỘ, nhiều địa chỉ cách nhau bằng dấu phẩy (bỏ trống = MAIL_USER)
  SHEET_ID   – mã Google Sheet phân công (tab Nhân viên / Cơ sở y tế / Theo tỉnh); mỗi nhân viên chỉ nhận cơ sở mình phụ trách

Danh sách mã đã báo lưu ở thong_bao_da_gui.json. Lần chạy đầu chỉ ghi nhận dữ liệu hiện có, không gửi.
  python3 thong_bao_mail.py          # gửi nếu có mới
  python3 thong_bao_mail.py --thu    # in nội dung mail ra thong_bao_thu.html, không gửi, không lưu
"""
import csv, difflib, html, io, json, os, re, smtplib, sys, unicodedata, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "thong_bao_da_gui.json")
SITE = "https://muasamcongadc.vercel.app"
VN = timezone(timedelta(hours=7))


def load(name):
    with open(os.path.join(HERE, "data", name), encoding="utf-8") as f:
        return json.load(f)


def money(v):
    return f"{v:,.0f} đ".replace(",", ".") if v else "–"


def esc(s):
    return html.escape(str(s or ""))


def open_now(han, now):
    return not han or han >= now


def rows_goi(goi):
    out = []
    for p in goi:
        nh = sorted({h.get("nhom", "") for h in p.get("hang_hoa", []) if h.get("nhom")})
        out.append(f"""<tr><td style="padding:8px;border-bottom:1px solid #e5e9f0;vertical-align:top">
<div style="font:12px monospace;color:#667">{esc(p['ma'])} · {esc(p.get('hinh_thuc'))}</div>
<div style="font-weight:600;margin:2px 0">{esc(p.get('ten'))}</div>
<div style="color:#445">{esc(p.get('cdt'))} · {esc(p.get('tinh'))}</div>
<div style="color:#445">Hạn: <b>{esc(p.get('han'))}</b> · Giá gói: {money(p.get('gia_goi'))} · {len(p.get('hang_hoa', []))} mặt hàng</div>
<div style="color:#0a7d6e;font-size:13px">{esc(', '.join(nh))}</div>
<div style="margin-top:4px"><a href="{SITE}/goi-thau?ma={esc(p['ma'])}">Xem trên trang</a> · <a href="{esc(p.get('link'))}">muasamcong</a></div></td></tr>""")
    return "".join(out)


def rows_ycbg(ys):
    out = []
    for y in ys:
        nh = sorted({i.get("nhom", "") for i in y.get("items", []) if i.get("nhom")})
        out.append(f"""<tr><td style="padding:8px;border-bottom:1px solid #e5e9f0;vertical-align:top">
<div style="font:12px monospace;color:#667">{esc(y['ma'])}</div>
<div style="font-weight:600;margin:2px 0">{esc(y.get('ten'))}</div>
<div style="color:#445">{esc(y.get('cdt'))} · {esc(y.get('tinh'))}</div>
<div style="color:#445">Hạn báo giá: <b>{esc(y.get('han'))}</b> · {len(y.get('items', []))} mặt hàng test</div>
<div style="color:#0a7d6e;font-size:13px">{esc(', '.join(nh))}</div>
<div style="margin-top:4px"><a href="{SITE}/bao-gia?ma={esc(y['ma'])}">Xem trên trang</a> · <a href="{esc(y.get('link'))}">muasamcong</a></div></td></tr>""")
    return "".join(out)


def body(goi, ycbg):
    parts = ['<div style="font-family:Arial,sans-serif;font-size:14px;color:#1d2433;max-width:760px">']
    if goi:
        parts.append(f'<h2 style="font-size:17px;margin:12px 0 4px">Gói thầu mới ({len(goi)})</h2><table style="border-collapse:collapse;width:100%">{rows_goi(goi)}</table>')
    if ycbg:
        parts.append(f'<h2 style="font-size:17px;margin:18px 0 4px">Yêu cầu báo giá mới ({len(ycbg)})</h2><table style="border-collapse:collapse;width:100%">{rows_ycbg(ycbg)}</table>')
    parts.append(f'<p style="color:#889;font-size:12px;margin-top:18px">Thư tự động từ {SITE} – chỉ gồm mặt hàng test nhanh còn hạn. '
                 'Muốn ngừng nhận: xóa secret MAIL_PASS trong GitHub.</p></div>')
    return "".join(parts)


def fold(s):
    s = unicodedata.normalize("NFD", str(s or "")).replace("đ", "d").replace("Đ", "D")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def fold_tinh(s):
    return re.sub(r"^(thanh pho|tinh|tp)\s+", "", fold(s))


def sheet_csv(sheet_id, tab):
    url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet="
           + urllib.parse.quote(tab))
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode("utf-8")
    return [row for row in csv.reader(io.StringIO(text))][1:]


def phan_cong(sheet_id):
    """Đọc Google Sheet phân công: trả về hàm cdt, tỉnh -> danh sách email nhân viên phụ trách."""
    nv = {}
    for r in sheet_csv(sheet_id, "Nhân viên"):
        r += [""] * 3
        emails = [e.strip() for e in re.split(r"[,;\s]+", r[1]) if "@" in e]
        if r[0].strip() and emails and fold(r[2]) != "khong":
            nv[fold(r[0])] = emails
    cs, by_tinh = {}, {}
    for r in sheet_csv(sheet_id, "Cơ sở y tế"):
        r += [""] * 3
        if r[0].strip() and r[2].strip():
            cs[fold(r[0])] = (fold_tinh(r[1]), fold(r[2]))
    for r in sheet_csv(sheet_id, "Theo tỉnh"):
        r += [""] * 2
        if r[0].strip() and r[1].strip():
            by_tinh[fold_tinh(r[0])] = fold(r[1])
    names = list(cs)

    def who(cdt, tinh):
        k, t = fold(cdt), fold_tinh(tinh)
        hit = cs.get(k)
        if not hit:  # tên ghi hơi khác (thêm "khu vực", viết hoa...): so gần đúng trong cùng tỉnh
            best = max(((difflib.SequenceMatcher(None, k, n).ratio(), n) for n in names if cs[n][0] == t), default=(0, None))
            if best[0] >= 0.9:
                hit = cs[best[1]]
        person = hit[1] if hit else by_tinh.get(t)
        return nv.get(person, [])
    print(f"Phân công: {len(nv)} nhân viên có email, {len(cs)} cơ sở, {len(by_tinh)} tỉnh")
    return who


def send(user, pw, to, subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"Muasamcong ADC <{user}>", ", ".join(to)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pw)
        s.sendmail(user, to, msg.as_string())


def subject_of(g, y):
    bits = ([f"{len(g)} gói thầu"] if g else []) + ([f"{len(y)} yêu cầu báo giá"] if y else [])
    return "Test nhanh: " + " và ".join(bits) + " mới"


def main():
    thu = "--thu" in sys.argv
    gui_thu = os.environ.get("GUI_THU") == "1"  # gửi 1 thư thử cho quản lý, không gửi nhân viên, không lưu
    now = datetime.now(VN).strftime("%Y-%m-%d %H:%M")
    goi = load("goi_thau.json").get("goi", [])
    ycbg = load("bao_gia.json").get("ycbg", [])
    cur = {"goi": [p["ma"] for p in goi], "ycbg": [y["ma"] for y in ycbg]}
    if not os.path.exists(STATE) and not thu:
        json.dump({**cur, "cap_nhat": now}, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"Lần đầu: ghi nhận {len(cur['goi'])} gói, {len(cur['ycbg'])} YCBG, không gửi mail.")
        return
    st = json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {"goi": [], "ycbg": []}
    seen_g, seen_y = set(st.get("goi", [])), set(st.get("ycbg", []))
    if thu or gui_thu:  # bản thử: 3 gói + 3 YCBG mới nhất để xem mẫu thư, không gửi, không lưu
        new_g = sorted(goi, key=lambda p: p.get("lan_dau") or "", reverse=True)[:3]
        new_y = sorted(ycbg, key=lambda y: y.get("lan_dau") or "", reverse=True)[:3]
    else:
        new_g = [p for p in goi if p["ma"] not in seen_g and open_now(p.get("han"), now)]
        new_y = [y for y in ycbg if y["ma"] not in seen_y and open_now(y.get("han"), now)]
    new_g.sort(key=lambda p: p.get("han") or "")
    new_y.sort(key=lambda y: y.get("han") or "")
    if not new_g and not new_y:
        print("Không có gói thầu / YCBG mới.")
    else:
        # thư cho quản lý (MAIL_TO): toàn bộ; thư cho từng nhân viên: chỉ cơ sở mình phụ trách (Google Sheet)
        mails = {}
        manager = tuple(x.strip() for x in (os.environ.get("MAIL_TO") or os.environ.get("MAIL_USER") or "").split(",") if x.strip())
        if manager:
            mails[manager] = (new_g, new_y)
        sheet_id = os.environ.get("SHEET_ID", "").strip()
        if sheet_id:
            try:
                who = phan_cong(sheet_id)
                per = {}
                for kind, rows in (("g", new_g), ("y", new_y)):
                    for p in rows:
                        for e in who(p.get("cdt"), p.get("tinh")):
                            if e not in manager:
                                per.setdefault(e, {"g": [], "y": []})[kind].append(p)
                for e, d in per.items():
                    mails[(e,)] = (d["g"], d["y"])
            except Exception as e:
                print("Không đọc được Google Sheet phân công:", type(e).__name__, e)
        if gui_thu:
            user, pw = os.environ.get("MAIL_USER", "").strip(), os.environ.get("MAIL_PASS", "").replace(" ", "")
            note = "".join(f"<li>{esc(', '.join(to))}: {len(g)} gói, {len(y)} YCBG</li>" for to, (g, y) in mails.items() if to != manager)
            extra = (f'<div style="font-family:Arial;font-size:14px;background:#fff7e0;padding:10px;border-radius:8px">'
                     f'<b>Thư thử.</b> Với 6 mục mẫu dưới đây, hệ thống sẽ gửi cho nhân viên:<ul>{note or "<li>(chưa có nhân viên nào có email trong Google Sheet)</li>"}</ul>'
                     'Thư thật chỉ gửi khi có gói thầu / YCBG mới.</div>')
            send(user, pw, list(manager), "[Thử] " + subject_of(new_g, new_y), extra + body(new_g, new_y))
            print("Đã gửi thư thử cho quản lý;", len(mails) - 1, "nhân viên sẽ nhận theo phân công")
            return
        if thu:
            for to, (g, y) in mails.items():
                print("Bản thử ->", len(to), "địa chỉ:", subject_of(g, y))
            open(os.path.join(HERE, "thong_bao_thu.html"), "w", encoding="utf-8").write(body(new_g, new_y))
            return
        user, pw = os.environ.get("MAIL_USER", "").strip(), os.environ.get("MAIL_PASS", "").replace(" ", "")
        if not (user and pw and mails):
            print("Chưa cấu hình MAIL_USER / MAIL_PASS -> bỏ qua gửi:", subject_of(new_g, new_y))
        else:
            for to, (g, y) in mails.items():
                send(user, pw, list(to), subject_of(g, y), body(g, y))
                print("Đã gửi:", subject_of(g, y), "->", len(to), "địa chỉ")
    if thu:
        return
    json.dump({"goi": sorted(seen_g | set(cur["goi"])), "ycbg": sorted(seen_y | set(cur["ycbg"])), "cap_nhat": now},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
