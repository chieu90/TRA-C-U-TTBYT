#!/usr/bin/env python3
"""
Gửi mail cảnh báo hợp đồng sắp hết hạn / quá hạn. Không dùng AI.
Chạy hằng ngày bằng GitHub Actions (.github/workflows/canh-bao-hop-dong.yml).

Mỗi hợp đồng thầu đang thực hiện (bỏ qua HĐ nguyên tắc vì tự gia hạn) được báo một lần ở mỗi mốc: còn ≤ 60 ngày, ≤ 30 ngày, ≤ 7 ngày, và khi quá hạn.
Gia hạn bằng phụ lục (ngày hết hạn đổi) thì các mốc được tính lại từ đầu.
Người nhận: người phụ trách hợp đồng + mọi quản lý, lấy email trong mục Người dùng của app.
Nếu chưa quản lý nào có email thì gửi về MAIL_TO.

Biến môi trường:
  DATABASE_URL          chuỗi kết nối PostgreSQL của app (để trống = dùng SQLite trên máy)
  MAIL_USER, MAIL_PASS  tài khoản Gmail gửi thư và mật khẩu ứng dụng
  MAIL_TO               địa chỉ dự phòng (cách nhau dấu phẩy)
  APP_URL               địa chỉ app, để gắn link vào thư
  GUI_THU=1             gửi 1 thư thử cho quản lý, gồm mọi hợp đồng đang trong diện cảnh báo; không ghi nhận
  CHI_XEM=1             chỉ đếm, không gửi, không ghi nhận

Repo này công khai nên nhật ký GitHub Actions ai cũng đọc được:
script chỉ in SỐ LƯỢNG, không in số hợp đồng, tên khách hay địa chỉ email.
"""
import html, os, re, smtplib, sys
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

MOC = [7, 30, 60]          # số ngày còn lại; mốc quá hạn ghi là -1
QUA_HAN = -1
APP_URL = (os.environ.get("APP_URL") or "https://dataadc.vercel.app").rstrip("/")


def moc_cua(con):
    """Mốc chặt nhất mà hợp đồng đã chạm; None nếu còn xa."""
    if con < 0:
        return QUA_HAN
    return next((m for m in MOC if con <= m), None)


def can_bao(db, hom_nay, bo_qua_da_gui=False):
    """Danh sách (hợp đồng, số ngày còn lại, mốc) cần báo hôm nay."""
    ds = db.execute(
        "SELECT v.*, u.email AS email_pt, u.hoat_dong AS pt_hoat_dong FROM v_hop_dong v "
        "LEFT JOIN nguoi_dung u ON u.id = v.phu_trach_id WHERE v.trang_thai = 'dang_thuc_hien' AND v.loai <> 'nguyen_tac' ORDER BY v.het_han").fetchall()
    da_gui = {(r["hop_dong_id"], r["het_han"], r["moc"]) for r in db.execute("SELECT * FROM canh_bao_da_gui").fetchall()}
    kq = []
    for h in ds:
        try:
            con = (date.fromisoformat(h["het_han"]) - hom_nay).days
        except (TypeError, ValueError):
            continue
        m = moc_cua(con)
        if m is not None and (bo_qua_da_gui or (h["id"], h["het_han"], m) not in da_gui):
            kq.append((h, con, m))
    return kq


def noi_dung(muc):
    e = lambda v: html.escape("" if v is None else str(v))
    dong = ""
    for h, con, _ in muc:
        if con < 0:
            tt = f'<b style="color:#b42318">Quá hạn {-con} ngày</b>'
        elif con == 0:
            tt = '<b style="color:#b42318">Hết hạn hôm nay</b>'
        else:
            tt = f'<b style="color:{"#b42318" if con <= 7 else "#8a5a00"}">Còn {con} ngày</b>'
        pt = min(100, round(100 * h["da_giao"] / h["gia_tri"])) if h["gia_tri"] else 0
        o = 'style="padding:8px 10px;border-bottom:1px solid #dfe3ea;text-align:left;vertical-align:top"'
        dong += (f'<tr><td {o}><a href="{APP_URL}/hop-dong/{h["id"]}"><b>{e(h["so_hd"])}</b></a></td>'
                 f'<td {o}>{e(h["khach"])}</td><td {o}>{app.ngay(h["het_han"])}</td><td {o}>{tt}</td>'
                 f'<td {o}>{app.tien(h["gia_tri"])} đ</td><td {o}>{pt}%</td><td {o}>{e(h["phu_trach"] or "—")}</td></tr>')
    th = 'style="padding:8px 10px;text-align:left;background:#eef2f7;font-size:13px;color:#677386"'
    return (f'<div style="font-family:system-ui,Segoe UI,Roboto,sans-serif;font-size:15px;color:#1c2430">'
            f'<p>Các hợp đồng dưới đây sắp hết hạn hoặc đã quá hạn mà vẫn đang ở tình trạng "Đang thực hiện".</p>'
            f'<table style="border-collapse:collapse;width:100%"><tr><th {th}>Số hợp đồng</th><th {th}>Khách hàng</th>'
            f'<th {th}>Hết hạn</th><th {th}>Tình trạng</th><th {th}>Giá trị</th><th {th}>Đã giao</th><th {th}>Phụ trách</th></tr>'
            f'{dong}</table>'
            f'<p style="color:#677386;font-size:13px">Mỗi hợp đồng được báo một lần ở các mốc còn 60, 30, 7 ngày và khi quá hạn. '
            f'Hợp đồng đã xong thì đổi tình trạng trong app để không bị báo nữa. '
            f'<a href="{APP_URL}">Mở app quản lý hợp đồng</a></p></div>')


def tieu_de(muc, thu=False):
    qh = sum(1 for _, con, _ in muc if con < 0)
    sap = len(muc) - qh
    phan = [f"{sap} hợp đồng sắp hết hạn"] if sap else []
    if qh:
        phan.append(f"{qh} hợp đồng quá hạn")
    return ("[THƯ THỬ] " if thu else "") + "[Hợp đồng] " + ", ".join(phan)


def gui(nguoi_gui, mat_khau, den, tieu_de_thu, than_html):
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = tieu_de_thu, f"Quản lý hợp đồng <{nguoi_gui}>", den
    msg.attach(MIMEText(than_html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(nguoi_gui, mat_khau)
        s.sendmail(nguoi_gui, [den], msg.as_string())


def main(gui_thu_ham=gui, hom_nay=None):
    hom_nay = hom_nay or date.today()
    thu = os.environ.get("GUI_THU") == "1"
    chi_xem = os.environ.get("CHI_XEM") == "1"
    db = app.mo_db()
    try:
        muc = can_bao(db, hom_nay, bo_qua_da_gui=thu)
        print(f"Hợp đồng cần báo: {len(muc)}")
        if not muc or chi_xem:
            return 0
        ql = [r["email"] for r in db.execute(
            "SELECT email FROM nguoi_dung WHERE vai_tro = 'quan_ly' AND hoat_dong = 1 AND email <> ''").fetchall()]
        if not ql:
            ql = [x.strip() for x in os.environ.get("MAIL_TO", "").split(",") if x.strip()]
        nhan = {m: list(muc) for m in ql}                      # quản lý nhận tất cả
        if not thu:
            for h, con, m in muc:                              # người phụ trách nhận hợp đồng của mình
                if h["email_pt"] and h["pt_hoat_dong"] and h["email_pt"] not in ql:
                    nhan.setdefault(h["email_pt"], []).append((h, con, m))
        if not nhan:
            print("Chưa có địa chỉ nhận: hãy nhập email cho quản lý trong mục Người dùng, hoặc đặt MAIL_TO.")
            return 1
        nguoi_gui = re.sub(r"\s+", "", os.environ.get("MAIL_USER", ""))
        mat_khau = re.sub(r"\s+", "", os.environ.get("MAIL_PASS", ""))
        if not (nguoi_gui and mat_khau):
            print("Thiếu MAIL_USER / MAIL_PASS.")
            return 1
        for den, cua_ho in nhan.items():
            gui_thu_ham(nguoi_gui, mat_khau, den, tieu_de(cua_ho, thu), noi_dung(cua_ho))
        print(f"Đã gửi {len(nhan)} thư.")
        if not thu:
            luc = datetime.now().isoformat(timespec="seconds")
            for h, _, m in muc:
                db.execute("INSERT INTO canh_bao_da_gui (hop_dong_id, het_han, moc, gui_luc) VALUES (?,?,?,?)",
                           (h["id"], h["het_han"], m, luc))
            db.commit()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except smtplib.SMTPException as loi:
        # không in chi tiết để tránh lộ địa chỉ email trong nhật ký công khai
        print(f"Gửi thư thất bại: {type(loi).__name__}")
        sys.exit(1)
