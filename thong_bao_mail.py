"""Gửi email khi có gói thầu / yêu cầu báo giá (YCBG) mới trong data/goi_thau.json và data/bao_gia.json.

Chạy trên GitHub Actions sau mỗi lần cập nhật dữ liệu (workflow thong-bao-mail.yml). Không dùng AI.
Cấu hình qua GitHub Secrets (người dùng tự nhập, không ghi vào mã nguồn):
  MAIL_USER  – tài khoản Gmail dùng để gửi
  MAIL_PASS  – mật khẩu ứng dụng (App Password) 16 ký tự của tài khoản đó
  MAIL_TO    – email nhận, nhiều địa chỉ cách nhau bằng dấu phẩy (bỏ trống = gửi về MAIL_USER)

Danh sách mã đã báo lưu ở thong_bao_da_gui.json. Lần chạy đầu chỉ ghi nhận dữ liệu hiện có, không gửi.
  python3 thong_bao_mail.py          # gửi nếu có mới
  python3 thong_bao_mail.py --thu    # in nội dung mail ra thong_bao_thu.html, không gửi, không lưu
"""
import html, json, os, smtplib, sys
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


def main():
    thu = "--thu" in sys.argv
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
    if thu:  # bản thử: lấy 3 gói + 3 YCBG mới nhất để xem mẫu thư
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
        bits = ([f"{len(new_g)} gói thầu"] if new_g else []) + ([f"{len(new_y)} yêu cầu báo giá"] if new_y else [])
        subject = "Test nhanh: " + " và ".join(bits) + " mới"
        html_body = body(new_g, new_y)
        if thu:
            open(os.path.join(HERE, "thong_bao_thu.html"), "w", encoding="utf-8").write(html_body)
            print("Bản thử:", subject, "-> thong_bao_thu.html")
            return
        user, pw = os.environ.get("MAIL_USER", "").strip(), os.environ.get("MAIL_PASS", "").replace(" ", "")
        to = [x.strip() for x in (os.environ.get("MAIL_TO") or user).split(",") if x.strip()]
        if not (user and pw and to):
            print("Chưa cấu hình MAIL_USER / MAIL_PASS -> bỏ qua gửi:", subject)
        else:
            msg = MIMEMultipart("alternative")
            msg["Subject"], msg["From"], msg["To"] = subject, f"Muasamcong ADC <{user}>", ", ".join(to)
            msg.attach(MIMEText(html_body, "html", "utf-8"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
                s.login(user, pw)
                s.sendmail(user, to, msg.as_string())
            print("Đã gửi:", subject, "->", len(to), "người nhận")
    if thu:
        return
    json.dump({"goi": sorted(seen_g | set(cur["goi"])), "ycbg": sorted(seen_y | set(cur["ycbg"])), "cap_nhat": now},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
