#!/usr/bin/env python3
"""
Quản lý hợp đồng khách hàng — chạy trên máy:

    python3 app.py

rồi mở http://localhost:8770

Trên máy: chỉ dùng thư viện có sẵn của Python, dữ liệu nằm trong du-lieu/hop_dong.db (SQLite).
Trên Vercel: đặt biến môi trường DATABASE_URL (PostgreSQL) — xem api/index.py và vercel.json.
Lần chạy đầu tiên app sẽ hỏi tạo tài khoản quản lý.
"""
import csv, hashlib, hmac, html, io, json, math, mimetypes, os, re, secrets, sqlite3, time, unicodedata, urllib.parse, zipfile
import xml.etree.ElementTree as ET
from email import policy as email_policy
from email.parser import BytesParser
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import docx_mau

PORT = int(os.environ.get("PORT", 8770))
HOST = os.environ.get("HOST", "127.0.0.1")
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("HD_DB", os.path.join(HERE, "du-lieu", "hop_dong.db"))
# Có DATABASE_URL (hoặc POSTGRES_URL) thì dùng PostgreSQL, không thì dùng file SQLite ở trên
PG_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
if PG_URL:
    import psycopg
    from psycopg.rows import dict_row
LOI_TRUNG = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if PG_URL else ())
COOKIE = "hd_phien"
PHIEN_NGAY = 14          # số ngày giữ đăng nhập
SAP_HET_HAN = 60         # cảnh báo khi còn ≤ 60 ngày
SAP_HET_SL = 0.8         # cảnh báo khi đã giao ≥ 80% giá trị
HAU_TO_HDNT = "-HĐNT/PBH"  # số hợp đồng nguyên tắc: 26001-HĐNT/PBH

TRANG_THAI = [
    ("dang_thuc_hien", "Đang thực hiện"),
    ("hoan_thanh", "Hoàn thành"),
    ("thanh_ly", "Đã thanh lý"),
    ("huy", "Đã hủy"),
]
VAI_TRO = [("nhan_vien", "Nhân viên"), ("quan_ly", "Quản lý")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS nguoi_dung (
  id INTEGER PRIMARY KEY, ten_dang_nhap TEXT UNIQUE NOT NULL, ho_ten TEXT NOT NULL,
  mat_khau TEXT NOT NULL, muoi TEXT NOT NULL,
  vai_tro TEXT NOT NULL DEFAULT 'nhan_vien', hoat_dong INTEGER NOT NULL DEFAULT 1, email TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS phien (
  ma TEXT PRIMARY KEY, nguoi_dung_id INTEGER NOT NULL REFERENCES nguoi_dung(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, het_han TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS khach_hang (
  id INTEGER PRIMARY KEY, ten TEXT UNIQUE NOT NULL, ma_so_thue TEXT DEFAULT '', dia_chi TEXT DEFAULT '',
  lien_he TEXT DEFAULT '', dien_thoai TEXT DEFAULT '', ghi_chu TEXT DEFAULT '',
  dai_dien TEXT DEFAULT '', chuc_vu TEXT DEFAULT '', email TEXT DEFAULT '', nhan_vien_bh TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS hop_dong (
  id INTEGER PRIMARY KEY, so_hd TEXT UNIQUE NOT NULL,
  khach_hang_id INTEGER NOT NULL REFERENCES khach_hang(id),
  ten_goi_thau TEXT DEFAULT '', so_tbmt TEXT DEFAULT '',
  ngay_ky TEXT DEFAULT '', ngay_hieu_luc TEXT DEFAULT '', ngay_het_han TEXT NOT NULL,
  phu_trach_id INTEGER REFERENCES nguoi_dung(id),
  trang_thai TEXT NOT NULL DEFAULT 'dang_thuc_hien',
  link_file TEXT DEFAULT '', ghi_chu TEXT DEFAULT '', tao_luc TEXT NOT NULL, loai TEXT DEFAULT 'thau');
CREATE TABLE IF NOT EXISTS dong_hang (
  id INTEGER PRIMARY KEY, hop_dong_id INTEGER NOT NULL REFERENCES hop_dong(id) ON DELETE CASCADE,
  ma_hang TEXT NOT NULL, ten_hang TEXT DEFAULT '', hang_sx TEXT DEFAULT '', don_vi TEXT DEFAULT '',
  so_luong REAL NOT NULL, don_gia REAL NOT NULL);
CREATE TABLE IF NOT EXISTS phu_luc (
  id INTEGER PRIMARY KEY, hop_dong_id INTEGER NOT NULL REFERENCES hop_dong(id) ON DELETE CASCADE,
  so_pl TEXT NOT NULL, ngay_ky TEXT DEFAULT '', noi_dung TEXT DEFAULT '',
  ngay_het_han_moi TEXT DEFAULT '', link_file TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS giao_hang (
  id INTEGER PRIMARY KEY, dong_hang_id INTEGER NOT NULL REFERENCES dong_hang(id),
  ngay TEXT NOT NULL, so_luong REAL NOT NULL, so_phieu TEXT DEFAULT '', ghi_chu TEXT DEFAULT '',
  nguoi_nhap_id INTEGER REFERENCES nguoi_dung(id));
CREATE TABLE IF NOT EXISTS canh_bao_da_gui (
  hop_dong_id INTEGER NOT NULL REFERENCES hop_dong(id) ON DELETE CASCADE,
  het_han TEXT NOT NULL, moc INTEGER NOT NULL, gui_luc TEXT NOT NULL,
  PRIMARY KEY (hop_dong_id, het_han, moc));
CREATE TABLE IF NOT EXISTS tep (
  ma TEXT PRIMARY KEY, ten_tep TEXT NOT NULL, noi_dung BLOB NOT NULL, cap_nhat TEXT NOT NULL, nguoi TEXT DEFAULT '');
"""

# cột thêm sau khi database đã có dữ liệu: (bảng, cột, kiểu)
COT_THEM = [
    ("nguoi_dung", "email", "TEXT DEFAULT ''"),
    ("khach_hang", "dai_dien", "TEXT DEFAULT ''"), ("khach_hang", "chuc_vu", "TEXT DEFAULT ''"),
    ("khach_hang", "email", "TEXT DEFAULT ''"), ("khach_hang", "nhan_vien_bh", "TEXT DEFAULT ''"),
    ("hop_dong", "loai", "TEXT DEFAULT 'thau'"),
]

SCHEMA_VIEW = """
DROP VIEW IF EXISTS v_hop_dong;
CREATE VIEW v_hop_dong AS
SELECT h.*, k.ten AS khach, u.ho_ten AS phu_trach,
  COALESCE((SELECT MAX(p.ngay_het_han_moi) FROM phu_luc p
            WHERE p.hop_dong_id = h.id AND p.ngay_het_han_moi <> ''), h.ngay_het_han) AS het_han,
  COALESCE((SELECT SUM(d.so_luong * d.don_gia) FROM dong_hang d WHERE d.hop_dong_id = h.id), 0) AS gia_tri,
  COALESCE((SELECT SUM(g.so_luong * d.don_gia) FROM giao_hang g
            JOIN dong_hang d ON d.id = g.dong_hang_id WHERE d.hop_dong_id = h.id), 0) AS da_giao
FROM hop_dong h
JOIN khach_hang k ON k.id = h.khach_hang_id
LEFT JOIN nguoi_dung u ON u.id = h.phu_trach_id;
"""


# ───────────────────────── tiện ích ─────────────────────────

class Loi(Exception):
    def __init__(self, ma, tb):
        self.ma, self.tb = ma, tb


class Chuyen:
    def __init__(self, url, tb=None):
        self.url, self.tb = url, tb


class Tep:
    """Trả về một file để trình duyệt tải xuống."""
    def __init__(self, ten, du_lieu, kieu="application/octet-stream"):
        self.ten, self.du_lieu, self.kieu = ten, du_lieu, kieu


def gap(s):
    """Chữ thường, bỏ dấu, gộp khoảng trắng — để so tên khách và tiêu đề cột."""
    s = unicodedata.normalize("NFD", str(s or "")).replace("đ", "d").replace("Đ", "D")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def gon(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().strip('"').strip()


class KetNoi:
    """Một kết nối database; câu SQL viết kiểu SQLite (dấu ?), tự đổi khi chạy trên PostgreSQL."""

    def __init__(self):
        if PG_URL:
            self.c = psycopg.connect(PG_URL, row_factory=dict_row, prepare_threshold=None, connect_timeout=10)
        else:
            os.makedirs(os.path.dirname(DB), exist_ok=True)
            self.c = sqlite3.connect(DB, timeout=10)
            self.c.row_factory = sqlite3.Row
            self.c.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _sql(sql):
        return sql.replace("?", "%s").replace(" LIKE ", " ILIKE ") if PG_URL else sql

    def execute(self, sql, ts=()):
        return self.c.execute(self._sql(sql), tuple(ts))

    def executemany(self, sql, ds):
        self.c.cursor().executemany(self._sql(sql), ds)

    def them(self, sql, ts):
        """Chạy INSERT và trả về id của dòng vừa thêm."""
        if PG_URL:
            return self.execute(sql + " RETURNING id", ts).fetchone()["id"]
        return self.execute(sql, ts).lastrowid

    def khoi_tao(self):
        sch = SCHEMA
        if PG_URL:
            sch = (sch.replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY").replace(" REAL ", " DOUBLE PRECISION ")
                   .replace(" BLOB ", " BYTEA "))
        for cau in sch.split(";"):
            if cau.strip():
                self.c.execute(cau)
        for bang, cot, kieu in COT_THEM:
            if PG_URL:
                self.c.execute(f"ALTER TABLE {bang} ADD COLUMN IF NOT EXISTS {cot} {kieu}")
            elif cot not in [r["name"] for r in self.c.execute(f"PRAGMA table_info({bang})")]:
                self.c.execute(f"ALTER TABLE {bang} ADD COLUMN {cot} {kieu}")
        # view tạo sau cùng để có đủ các cột vừa thêm
        for cau in SCHEMA_VIEW.split(";"):
            if cau.strip():
                self.c.execute(cau)
        self.c.commit()

    def commit(self):
        self.c.commit()

    def rollback(self):
        self.c.rollback()

    def close(self):
        self.c.close()


_san_sang = False


def mo_db():
    """Mở kết nối; lần đầu của tiến trình thì tạo bảng nếu chưa có."""
    global _san_sang
    db = KetNoi()
    if not _san_sang:
        # trên PostgreSQL chỉ chạy khi thiếu bảng thêm gần đây nhất (đổi tên này mỗi lần thêm bảng / cột)
        if not PG_URL or not db.execute("SELECT to_regclass('tep') AS v").fetchone()["v"]:
            db.khoi_tao()
        _san_sang = True
    return db


def e(v):
    return html.escape("" if v is None else str(v), quote=True)


def tien(n):
    return f"{round(n or 0):,}".replace(",", ".")


def sl(n):
    n = n or 0
    if abs(n - round(n)) < 1e-9:
        return tien(n)
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def ngay(s):
    try:
        return date.fromisoformat(s).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


def bam(mat_khau, muoi_hex):
    return hashlib.pbkdf2_hmac("sha256", mat_khau.encode(), bytes.fromhex(muoi_hex), 200_000).hex()


def bam_ma(ma):
    return hashlib.sha256(ma.encode()).hexdigest()


def phan_tram(h):
    return min(100, round(100 * h["da_giao"] / h["gia_tri"])) if h["gia_tri"] else 0


def nhan_hd(h):
    if h["loai"] == "nguyen_tac" and h["trang_thai"] == "dang_thuc_hien":
        return '<span class="nhan xanh">HĐ nguyên tắc</span>'
    if h["trang_thai"] != "dang_thuc_hien":
        return f'<span class="nhan xam">{e(dict(TRANG_THAI).get(h["trang_thai"], ""))}</span>'
    try:
        con = (date.fromisoformat(h["het_han"]) - date.today()).days
    except ValueError:
        return '<span class="nhan xanh">Đang thực hiện</span>'
    if con < 0:
        return f'<span class="nhan do">Quá hạn {-con} ngày</span>'
    if con <= SAP_HET_HAN:
        return f'<span class="nhan vang">Còn {con} ngày</span>'
    return '<span class="nhan xanh">Đang thực hiện</span>'


def chon(ten, lua_chon, dang_chon="", trong=None):
    o = [f'<option value="">{e(trong)}</option>'] if trong is not None else []
    for gt, nhan in lua_chon:
        sel = " selected" if str(gt) == str(dang_chon) else ""
        o.append(f'<option value="{e(gt)}"{sel}>{e(nhan)}</option>')
    return f'<select name="{ten}" id="{ten}">{"".join(o)}</select>'


def o(nhan, ten, gt="", kieu="text", bat_buoc=False, them=""):
    bb = " required" if bat_buoc else ""
    sao = ' <b class="sao">*</b>' if bat_buoc else ""
    return (f'<label>{e(nhan)}{sao}<input type="{kieu}" name="{ten}" value="{e(gt)}"{bb} {them}></label>')


# ───────────────────────── ngữ cảnh một yêu cầu ─────────────────────────

class Ctx:
    def __init__(self, h, method, path, query):
        self.h, self.method, self.path = h, method, path
        self.q = {k: v[-1].strip() for k, v in urllib.parse.parse_qs(query).items()}
        self.form, self.tep = {}, {}
        if method == "POST":
            n = int(h.headers.get("Content-Length") or 0)
            kieu = h.headers.get("Content-Type", "")
            co_tep = kieu.startswith("multipart/form-data")
            if n > (4_500_000 if co_tep else 1_000_000):
                raise Loi(413, "Dữ liệu gửi lên quá lớn (tối đa khoảng 4 MB).")
            raw = h.rfile.read(n)
            if co_tep:
                msg = BytesParser(policy=email_policy.default).parsebytes(
                    b"Content-Type: " + kieu.encode("latin-1", "replace") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
                for phan in msg.iter_parts():
                    ten = phan.get_param("name", header="content-disposition")
                    dl = phan.get_payload(decode=True) or b""
                    if ten is None:
                        continue
                    if phan.get_filename() is not None:
                        self.tep[ten] = (phan.get_filename(), dl)
                    else:
                        self.form[ten] = dl.decode("utf-8", "replace")
            else:
                self.form = {k: v[-1] for k, v in urllib.parse.parse_qs(raw.decode("utf-8", "replace"),
                                                                       keep_blank_values=True).items()}
        ck = SimpleCookie(h.headers.get("Cookie", ""))
        self.ma_phien = ck[COOKIE].value if COOKIE in ck else ""
        self.tb = urllib.parse.unquote(ck["hd_tb"].value) if "hd_tb" in ck else ""
        self.cookies = []
        self.db = mo_db()
        self.user, self.csrf = None, ""
        if self.ma_phien:
            r = self.db.execute(
                "SELECT u.*, p.csrf FROM phien p JOIN nguoi_dung u ON u.id = p.nguoi_dung_id "
                "WHERE p.ma = ? AND p.het_han > ? AND u.hoat_dong = 1",
                (bam_ma(self.ma_phien), datetime.now().isoformat())).fetchone()
            if r:
                self.user, self.csrf = r, r["csrf"]

    @property
    def ql(self):
        return bool(self.user) and self.user["vai_tro"] == "quan_ly"

    def dat_cookie(self, ten, gt, giay):
        an_toan = "; Secure" if self.h.headers.get("X-Forwarded-Proto") == "https" else ""
        self.cookies.append(f"{ten}={gt}; Path=/; Max-Age={giay}; HttpOnly; SameSite=Lax{an_toan}")

    # đọc ô nhập
    def chu(self, ten, nhan, bat_buoc=False, toi_da=500):
        v = (self.form.get(ten) or "").strip()
        if bat_buoc and not v:
            raise Loi(400, f"Chưa nhập: {nhan}.")
        return v[:toi_da]

    def so(self, ten, nhan, bat_buoc=False):
        v = (self.form.get(ten) or "").strip().replace(",", ".")
        if not v:
            if bat_buoc:
                raise Loi(400, f"Chưa nhập: {nhan}.")
            return 0.0
        try:
            x = float(v)
        except ValueError:
            raise Loi(400, f"{nhan} phải là số.")
        if not math.isfinite(x) or x < 0:
            raise Loi(400, f"{nhan} không hợp lệ.")
        return x

    def ngay(self, ten, nhan, bat_buoc=False):
        v = (self.form.get(ten) or "").strip()
        if not v:
            if bat_buoc:
                raise Loi(400, f"Chưa nhập: {nhan}.")
            return ""
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            raise Loi(400, f"{nhan} không đúng định dạng ngày.")

    def link(self, ten, nhan):
        v = self.chu(ten, nhan, toi_da=1000)
        if v and not re.match(r"^https?://", v):
            raise Loi(400, f"{nhan} phải bắt đầu bằng http:// hoặc https://.")
        return v


# ───────────────────────── khung trang ─────────────────────────

def trang(c, tieu_de, than, muc=""):
    nav = ""
    if c.user:
        cac_muc = [("/", "Tổng quan", "tq"), ("/hop-dong", "Hợp đồng", "hd"), ("/hdnt/moi", "Làm HĐ nguyên tắc", "hdnt"),
                   ("/khach-hang", "Khách hàng", "kh")]
        if c.ql:
            cac_muc += [("/mau-hop-dong", "Mẫu HĐ", "mau"), ("/nguoi-dung", "Người dùng", "nd")]
        lk = "".join(f'<a href="{u}"{" class=chon" if m == muc else ""}>{t}</a>' for u, t, m in cac_muc)
        nav = (f'<header><div class="khung dau"><a class="ten-app" href="/">Hợp đồng</a><nav>{lk}</nav>'
               f'<div class="tk"><a href="/doi-mat-khau">{e(c.user["ho_ten"])}</a>'
               f'<form method="post" action="/dang-xuat"><input type="hidden" name="csrf" value="{e(c.csrf)}">'
               f'<button class="nut-chu">Đăng xuất</button></form></div></div></header>')
    tb = ""
    if c.tb:
        tb = f'<div class="thong-bao">{e(c.tb)}</div>'
        c.dat_cookie("hd_tb", "", 0)
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{e(tieu_de)} · Hợp đồng</title><link rel="stylesheet" href="/static/style.css">'
            f'<script src="/static/app.js" defer></script></head><body>{nav}'
            f'<main class="khung">{tb}{than}</main></body></html>')


def an_csrf(c):
    return f'<input type="hidden" name="csrf" value="{e(c.csrf)}">'


def nut_xoa(c, url, hoi, nhan="Xóa"):
    return (f'<form method="post" action="{url}" class="trong-dong" data-xac-nhan="{e(hoi)}">{an_csrf(c)}'
            f'<button class="nut-chu nguy">{nhan}</button></form>')


# ───────────────────────── đăng nhập ─────────────────────────

def tao_phien(c, uid):
    ma, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    het = (datetime.now() + timedelta(days=PHIEN_NGAY)).isoformat()
    c.db.execute("DELETE FROM phien WHERE het_han < ?", (datetime.now().isoformat(),))
    c.db.execute("INSERT INTO phien VALUES (?,?,?,?)", (bam_ma(ma), uid, csrf, het))
    c.db.commit()
    c.dat_cookie(COOKIE, ma, PHIEN_NGAY * 86400)


def kiem_mk(mk, lai=None):
    if len(mk) < 8:
        raise Loi(400, "Mật khẩu phải có ít nhất 8 ký tự.")
    if lai is not None and mk != lai:
        raise Loi(400, "Hai lần nhập mật khẩu không khớp.")


def doc_email(c):
    v = c.chu("email", "Email", toi_da=200).lower()
    if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
        raise Loi(400, "Email không đúng định dạng.")
    return v


def them_nguoi_dung(c, vai_tro):
    ten = c.chu("ten_dang_nhap", "Tên đăng nhập", True, 50).lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,50}", ten):
        raise Loi(400, "Tên đăng nhập chỉ gồm chữ thường không dấu, số, dấu chấm, gạch; từ 3 ký tự.")
    ho_ten = c.chu("ho_ten", "Họ tên", True, 100)
    email = doc_email(c)
    mk = c.form.get("mat_khau", "")
    kiem_mk(mk, c.form.get("mat_khau_2"))
    muoi = secrets.token_hex(16)
    try:
        uid = c.db.them("INSERT INTO nguoi_dung (ten_dang_nhap, ho_ten, mat_khau, muoi, vai_tro, email) VALUES (?,?,?,?,?,?)",
                        (ten, ho_ten, bam(mk, muoi), muoi, vai_tro, email))
    except LOI_TRUNG:
        raise Loi(400, "Tên đăng nhập này đã có.")
    c.db.commit()
    return uid


def thiet_lap(c):
    if c.db.execute("SELECT 1 FROM nguoi_dung").fetchone():
        return Chuyen("/")
    if c.method == "POST":
        tao_phien(c, them_nguoi_dung(c, "quan_ly"))
        return Chuyen("/", "Đã tạo tài khoản quản lý.")
    return trang(c, "Thiết lập", f"""
      <div class="the hep"><h1>Thiết lập lần đầu</h1>
      <p class="mo">Tạo tài khoản quản lý đầu tiên. Tài khoản này thấy mọi hợp đồng và thêm được người dùng khác.</p>
      <form method="post" class="luoi-1">
        {o("Họ tên", "ho_ten", bat_buoc=True)}
        {o("Email (để nhận mail cảnh báo)", "email", kieu="email")}
        {o("Tên đăng nhập", "ten_dang_nhap", bat_buoc=True, them='autocomplete="username"')}
        {o("Mật khẩu (ít nhất 8 ký tự)", "mat_khau", kieu="password", bat_buoc=True, them='autocomplete="new-password"')}
        {o("Nhập lại mật khẩu", "mat_khau_2", kieu="password", bat_buoc=True, them='autocomplete="new-password"')}
        <button class="nut">Tạo tài khoản</button></form></div>""")


def dang_nhap(c):
    if c.user:
        return Chuyen("/")
    loi = ""
    if c.method == "POST":
        ten = (c.form.get("ten_dang_nhap") or "").strip().lower()
        u = c.db.execute("SELECT * FROM nguoi_dung WHERE ten_dang_nhap = ? AND hoat_dong = 1", (ten,)).fetchone()
        if u and hmac.compare_digest(bam(c.form.get("mat_khau", ""), u["muoi"]), u["mat_khau"]):
            tao_phien(c, u["id"])
            return Chuyen("/")
        time.sleep(0.6)
        loi = '<div class="thong-bao loi">Sai tên đăng nhập hoặc mật khẩu.</div>'
    return trang(c, "Đăng nhập", f"""
      <div class="the hep"><h1>Đăng nhập</h1>{loi}
      <form method="post" class="luoi-1">
        {o("Tên đăng nhập", "ten_dang_nhap", bat_buoc=True, them='autocomplete="username" autofocus')}
        {o("Mật khẩu", "mat_khau", kieu="password", bat_buoc=True, them='autocomplete="current-password"')}
        <button class="nut">Đăng nhập</button></form></div>""")


def dang_xuat(c):
    c.db.execute("DELETE FROM phien WHERE ma = ?", (bam_ma(c.ma_phien),))
    c.db.commit()
    c.dat_cookie(COOKIE, "", 0)
    return Chuyen("/dang-nhap")


def doi_mat_khau(c):
    if c.method == "POST":
        if not hmac.compare_digest(bam(c.form.get("mat_khau_cu", ""), c.user["muoi"]), c.user["mat_khau"]):
            raise Loi(400, "Mật khẩu hiện tại không đúng.")
        mk = c.form.get("mat_khau", "")
        kiem_mk(mk, c.form.get("mat_khau_2"))
        muoi = secrets.token_hex(16)
        c.db.execute("UPDATE nguoi_dung SET mat_khau = ?, muoi = ? WHERE id = ?", (bam(mk, muoi), muoi, c.user["id"]))
        c.db.execute("DELETE FROM phien WHERE nguoi_dung_id = ? AND ma <> ?", (c.user["id"], bam_ma(c.ma_phien)))
        c.db.commit()
        return Chuyen("/", "Đã đổi mật khẩu.")
    return trang(c, "Đổi mật khẩu", f"""
      <div class="the hep"><h1>Đổi mật khẩu</h1><form method="post" class="luoi-1">{an_csrf(c)}
        {o("Mật khẩu hiện tại", "mat_khau_cu", kieu="password", bat_buoc=True, them='autocomplete="current-password"')}
        {o("Mật khẩu mới (ít nhất 8 ký tự)", "mat_khau", kieu="password", bat_buoc=True, them='autocomplete="new-password"')}
        {o("Nhập lại mật khẩu mới", "mat_khau_2", kieu="password", bat_buoc=True, them='autocomplete="new-password"')}
        <button class="nut">Lưu</button></form></div>""")


# ───────────────────────── người dùng (quản lý) ─────────────────────────

def nguoi_dung(c):
    ds = c.db.execute("SELECT u.*, (SELECT COUNT(*) FROM hop_dong h WHERE h.phu_trach_id = u.id) AS n "
                      "FROM nguoi_dung u ORDER BY u.hoat_dong DESC, u.ho_ten").fetchall()
    dong = ""
    for u in ds:
        khoa = ""
        if u["id"] != c.user["id"]:
            nhan = "Khóa" if u["hoat_dong"] else "Mở lại"
            khoa = (f'<form method="post" action="/nguoi-dung/{u["id"]}/khoa" class="trong-dong">{an_csrf(c)}'
                    f'<button class="nut-chu">{nhan}</button></form>')
        dong += (f'<tr><td>{e(u["ho_ten"])}</td><td>{e(u["ten_dang_nhap"])}</td>'
                 f'<td>{e(u["email"]) or "<span class=mo>chưa có</span>"}</td>'
                 f'<td>{e(dict(VAI_TRO)[u["vai_tro"]])}</td><td class="so">{u["n"]}</td>'
                 f'<td>{"Đang dùng" if u["hoat_dong"] else "<span class=mo>Đã khóa</span>"}</td>'
                 f'<td class="thao-tac"><a href="/nguoi-dung/{u["id"]}/sua">Sửa</a>'
                 f'<a href="/nguoi-dung/{u["id"]}/mat-khau">Đặt lại mật khẩu</a>{khoa}</td></tr>')
    return trang(c, "Người dùng", f"""
      <h1>Người dùng</h1>
      <div class="the cuon"><table><thead><tr><th>Họ tên</th><th>Tên đăng nhập</th><th>Email</th><th>Vai trò</th>
        <th class="so">Hợp đồng</th><th>Tình trạng</th><th></th></tr></thead><tbody>{dong}</tbody></table></div>
      <div class="the"><h2>Thêm người dùng</h2>
      <p class="mo">Nhân viên chỉ thấy hợp đồng mình phụ trách. Quản lý thấy tất cả.
        Mail cảnh báo hết hạn gửi cho người phụ trách và mọi quản lý có email.</p>
      <form method="post" action="/nguoi-dung" class="luoi">{an_csrf(c)}
        {o("Họ tên", "ho_ten", bat_buoc=True)}
        {o("Email", "email", kieu="email")}
        {o("Tên đăng nhập", "ten_dang_nhap", bat_buoc=True, them='autocomplete="off"')}
        <label>Vai trò{chon("vai_tro", VAI_TRO, "nhan_vien")}</label>
        {o("Mật khẩu tạm (ít nhất 8 ký tự)", "mat_khau", kieu="password", bat_buoc=True, them='autocomplete="new-password"')}
        <div class="hang-nut"><button class="nut">Thêm</button></div></form></div>""", "nd")


def nguoi_dung_them(c):
    vt = c.form.get("vai_tro")
    if vt not in dict(VAI_TRO):
        raise Loi(400, "Vai trò không hợp lệ.")
    them_nguoi_dung(c, vt)
    return Chuyen("/nguoi-dung", "Đã thêm người dùng.")


def nguoi_dung_sua(c, uid):
    u = c.db.execute("SELECT * FROM nguoi_dung WHERE id = ?", (uid,)).fetchone()
    if not u:
        raise Loi(404, "Không tìm thấy người dùng.")
    chinh_minh = uid == c.user["id"]
    if c.method == "POST":
        vt = u["vai_tro"] if chinh_minh else c.form.get("vai_tro")
        if vt not in dict(VAI_TRO):
            raise Loi(400, "Vai trò không hợp lệ.")
        c.db.execute("UPDATE nguoi_dung SET ho_ten = ?, email = ?, vai_tro = ? WHERE id = ?",
                     (c.chu("ho_ten", "Họ tên", True, 100), doc_email(c), vt, uid))
        c.db.commit()
        return Chuyen("/nguoi-dung", "Đã lưu.")
    o_vt = "" if chinh_minh else f'<label>Vai trò{chon("vai_tro", VAI_TRO, u["vai_tro"])}</label>'
    return trang(c, "Sửa người dùng", f"""
      <div class="the hep"><h1>Sửa người dùng</h1><p class="mo">Tên đăng nhập: {e(u["ten_dang_nhap"])}</p>
      <form method="post" class="luoi-1">{an_csrf(c)}
        {o("Họ tên", "ho_ten", u["ho_ten"], bat_buoc=True)}
        {o("Email (để nhận mail cảnh báo)", "email", u["email"], kieu="email")}{o_vt}
        <div class="hang-nut"><button class="nut">Lưu</button><a href="/nguoi-dung">Hủy</a></div></form></div>""", "nd")


def nguoi_dung_khoa(c, uid):
    if uid == c.user["id"]:
        raise Loi(400, "Không thể tự khóa tài khoản của mình.")
    c.db.execute("UPDATE nguoi_dung SET hoat_dong = 1 - hoat_dong WHERE id = ?", (uid,))
    c.db.execute("DELETE FROM phien WHERE nguoi_dung_id = ?", (uid,))
    c.db.commit()
    return Chuyen("/nguoi-dung", "Đã cập nhật.")


def nguoi_dung_mat_khau(c, uid):
    u = c.db.execute("SELECT * FROM nguoi_dung WHERE id = ?", (uid,)).fetchone()
    if not u:
        raise Loi(404, "Không tìm thấy người dùng.")
    if c.method == "POST":
        mk = c.form.get("mat_khau", "")
        kiem_mk(mk)
        muoi = secrets.token_hex(16)
        c.db.execute("UPDATE nguoi_dung SET mat_khau = ?, muoi = ? WHERE id = ?", (bam(mk, muoi), muoi, uid))
        if uid != c.user["id"]:
            c.db.execute("DELETE FROM phien WHERE nguoi_dung_id = ?", (uid,))
        c.db.commit()
        return Chuyen("/nguoi-dung", f"Đã đặt lại mật khẩu cho {u['ho_ten']}.")
    return trang(c, "Đặt lại mật khẩu", f"""
      <div class="the hep"><h1>Đặt lại mật khẩu</h1><p class="mo">{e(u["ho_ten"])} ({e(u["ten_dang_nhap"])})</p>
      <form method="post" class="luoi-1">{an_csrf(c)}
        {o("Mật khẩu mới (ít nhất 8 ký tự)", "mat_khau", kieu="password", bat_buoc=True, them='autocomplete="new-password"')}
        <div class="hang-nut"><button class="nut">Lưu</button><a href="/nguoi-dung">Hủy</a></div></form></div>""", "nd")


# ───────────────────────── khách hàng ─────────────────────────

COT_KHACH = ["ten", "ma_so_thue", "dia_chi", "dai_dien", "chuc_vu", "dien_thoai", "email", "lien_he",
             "nhan_vien_bh", "ghi_chu"]


def o_khach(k=None):
    g = (lambda f: k[f] if k else "")
    return (o("Tên khách hàng", "ten", g("ten"), bat_buoc=True) + o("Mã số thuế", "ma_so_thue", g("ma_so_thue"))
            + o("Địa chỉ", "dia_chi", g("dia_chi")) + o("Người đại diện", "dai_dien", g("dai_dien"))
            + o("Chức vụ", "chuc_vu", g("chuc_vu")) + o("Điện thoại", "dien_thoai", g("dien_thoai"))
            + o("Email", "email", g("email"), kieu="email") + o("Người liên hệ", "lien_he", g("lien_he"))
            + o("Nhân viên bán hàng", "nhan_vien_bh", g("nhan_vien_bh")) + o("Ghi chú", "ghi_chu", g("ghi_chu")))


def doc_khach(c):
    return (c.chu("ten", "Tên khách hàng", True, 300), c.chu("ma_so_thue", "Mã số thuế", toi_da=20),
            c.chu("dia_chi", "Địa chỉ"), c.chu("dai_dien", "Người đại diện", toi_da=100),
            c.chu("chuc_vu", "Chức vụ", toi_da=100), c.chu("dien_thoai", "Điện thoại", toi_da=50),
            c.chu("email", "Email", toi_da=200), c.chu("lien_he", "Người liên hệ", toi_da=100),
            c.chu("nhan_vien_bh", "Nhân viên bán hàng", toi_da=200), c.chu("ghi_chu", "Ghi chú", toi_da=1000))


def khach_hang(c):
    tu, nv = c.q.get("q", ""), c.q.get("nv", "")
    dk, ts = "", []
    if tu:
        dk += " AND (k.ten LIKE ? OR k.ma_so_thue LIKE ? OR k.dai_dien LIKE ?)"
        ts += [f"%{tu}%"] * 3
    if nv:
        dk += " AND k.nhan_vien_bh LIKE ?"
        ts.append(f"%{nv}%")
    ds = c.db.execute("SELECT k.*, (SELECT COUNT(*) FROM hop_dong h WHERE h.khach_hang_id = k.id) AS n "
                      f"FROM khach_hang k WHERE 1=1{dk} ORDER BY k.ten", ts).fetchall()
    tong = c.db.execute("SELECT COUNT(*) AS n FROM khach_hang").fetchone()["n"]
    cac_nv = sorted({x.strip() for r in c.db.execute("SELECT DISTINCT nhan_vien_bh FROM khach_hang").fetchall()
                     for x in (r["nhan_vien_bh"] or "").split(",") if x.strip()})
    dong = "".join(
        f'<tr><td><a href="/khach-hang/{k["id"]}">{e(k["ten"])}</a></td><td>{e(k["ma_so_thue"])}</td>'
        f'<td>{e(k["dai_dien"])}</td><td>{e(k["nhan_vien_bh"])}</td>'
        f'<td class="so"><a href="/hop-dong?kh={k["id"]}">{k["n"]}</a></td>'
        f'<td class="thao-tac"><a href="/hdnt/moi?kh={k["id"]}">Làm HĐNT</a></td></tr>' for k in ds)
    if ds:
        bang = (f'<div class="the cuon"><table><thead><tr><th>Tên</th><th>Mã số thuế</th><th>Đại diện</th>'
                f'<th>Nhân viên BH</th><th class="so">Hợp đồng</th><th></th></tr></thead><tbody>{dong}</tbody></table></div>')
    elif tong:
        bang = '<div class="the trong">Không có khách hàng nào khớp.</div>'
    else:
        bang = '<div class="the trong">Chưa có khách hàng nào. Nhập danh sách từ Excel hoặc thêm khách ở bên dưới.</div>'
    nhap = '<a class="nut phu" href="/khach-hang/nhap">Nhập từ Excel</a>' if c.ql else ""
    return trang(c, "Khách hàng", f"""
      <div class="dau-trang"><h1>Khách hàng <span class="dem">{len(ds)}</span></h1>{nhap}</div>
      <form class="bo-loc"><input type="search" name="q" value="{e(tu)}" placeholder="Tên, mã số thuế, người đại diện…">
        {chon("nv", [(x, x) for x in cac_nv], nv, "Mọi nhân viên BH")}
        <button class="nut phu">Lọc</button>{'<a href="/khach-hang">Bỏ lọc</a>' if c.q else ""}</form>
      {bang}
      <div class="the"><h2>Thêm khách hàng</h2><form method="post" action="/khach-hang" class="luoi">{an_csrf(c)}
        {o_khach()}<div class="hang-nut"><button class="nut">Thêm</button></div></form></div>""", "kh")


def khach_hang_them(c):
    try:
        c.db.execute(f"INSERT INTO khach_hang ({', '.join(COT_KHACH)}) VALUES ({', '.join('?' * len(COT_KHACH))})",
                     doc_khach(c))
    except LOI_TRUNG:
        raise Loi(400, "Đã có khách hàng trùng tên này.")
    c.db.commit()
    return Chuyen("/khach-hang", "Đã thêm khách hàng.")


def khach_hang_sua(c, kid):
    k = c.db.execute("SELECT * FROM khach_hang WHERE id = ?", (kid,)).fetchone()
    if not k:
        raise Loi(404, "Không tìm thấy khách hàng.")
    if c.method == "POST":
        try:
            c.db.execute(f"UPDATE khach_hang SET {', '.join(x + ' = ?' for x in COT_KHACH)} WHERE id = ?",
                         doc_khach(c) + (kid,))
        except LOI_TRUNG:
            raise Loi(400, "Đã có khách hàng trùng tên này.")
        c.db.commit()
        return Chuyen("/khach-hang", "Đã lưu.")
    n = c.db.execute("SELECT COUNT(*) AS n FROM hop_dong WHERE khach_hang_id = ?", (kid,)).fetchone()["n"]
    xoa = ""
    if c.ql and n == 0:
        xoa = nut_xoa(c, f"/khach-hang/{kid}/xoa", f"Xóa khách hàng {k['ten']}?", "Xóa khách hàng")
    return trang(c, k["ten"], f"""
      <div class="dau-trang"><h1>{e(k["ten"])}</h1><a class="nut" href="/hdnt/moi?kh={kid}">Làm HĐ nguyên tắc</a></div>
      <p class="mo"><a href="/hop-dong?kh={kid}">{n} hợp đồng</a></p>
      <div class="the"><form method="post" class="luoi">{an_csrf(c)}{o_khach(k)}
        <div class="hang-nut"><button class="nut">Lưu</button><a href="/khach-hang">Hủy</a></div></form></div>{xoa}""", "kh")


def khach_hang_xoa(c, kid):
    if c.db.execute("SELECT 1 FROM hop_dong WHERE khach_hang_id = ?", (kid,)).fetchone():
        raise Loi(400, "Khách hàng đã có hợp đồng nên không xóa được.")
    c.db.execute("DELETE FROM khach_hang WHERE id = ?", (kid,))
    c.db.commit()
    return Chuyen("/khach-hang", "Đã xóa khách hàng.")


# ───────────────────────── hợp đồng ─────────────────────────

def lay_hd(c, hid):
    h = c.db.execute("SELECT * FROM v_hop_dong WHERE id = ?", (hid,)).fetchone()
    if not h:
        raise Loi(404, "Không tìm thấy hợp đồng.")
    if not c.ql and h["phu_trach_id"] != c.user["id"]:
        raise Loi(403, "Bạn không phụ trách hợp đồng này.")
    return h


def loc_quyen(c):
    return ("", []) if c.ql else (" AND phu_trach_id = ?", [c.user["id"]])


def bang_hd(ds):
    dong = ""
    for h in ds:
        pt = phan_tram(h)
        if h["loai"] == "nguyen_tac":
            gt_td = '<td class="so mo">—</td><td class="mo">theo đơn hàng</td>'
        else:
            gt_td = (f'<td class="so">{tien(h["gia_tri"])}</td>'
                     f'<td><progress max="100" value="{pt}"></progress> <span class="mo">{pt}%</span></td>')
        dong += (f'<tr><td><a href="/hop-dong/{h["id"]}"><b>{e(h["so_hd"])}</b></a></td><td>{e(h["khach"])}</td>'
                 f'<td>{ngay(h["het_han"])}</td>{gt_td}'
                 f'<td>{e(h["phu_trach"] or "—")}</td><td>{nhan_hd(h)}</td></tr>')
    return ('<div class="the cuon"><table><thead><tr><th>Số hợp đồng</th><th>Khách hàng</th><th>Hết hạn</th>'
            '<th class="so">Giá trị (đ)</th><th>Đã giao</th><th>Phụ trách</th><th>Tình trạng</th></tr></thead>'
            f'<tbody>{dong}</tbody></table></div>')


def tong_quan(c):
    dk, ts = loc_quyen(c)
    ds = c.db.execute(f"SELECT * FROM v_hop_dong WHERE trang_thai = 'dang_thuc_hien' AND loai <> 'nguyen_tac'{dk} "
                      "ORDER BY het_han", ts).fetchall()
    n_hdnt = c.db.execute(f"SELECT COUNT(*) AS n FROM hop_dong WHERE loai = 'nguyen_tac' AND trang_thai = 'dang_thuc_hien'{dk}",
                          ts).fetchone()["n"]
    hom_nay = date.today().isoformat()
    moc = (date.today() + timedelta(days=SAP_HET_HAN)).isoformat()
    qua_han = [h for h in ds if h["het_han"] < hom_nay]
    sap_han = [h for h in ds if hom_nay <= h["het_han"] <= moc]
    sap_sl = [h for h in ds if h["gia_tri"] and h["da_giao"] >= SAP_HET_SL * h["gia_tri"]]
    gt, dg = sum(h["gia_tri"] for h in ds), sum(h["da_giao"] for h in ds)

    def khoi(td, lst, trong):
        return f'<h2>{td} <span class="dem">{len(lst)}</span></h2>' + (bang_hd(lst) if lst else f'<div class="the trong">{trong}</div>')

    if not ds and not c.db.execute(f"SELECT 1 FROM hop_dong WHERE 1=1{dk}", ts).fetchone():
        return trang(c, "Tổng quan", """<h1>Tổng quan</h1><div class="the trong">Chưa có hợp đồng nào.
          <p><a class="nut" href="/hdnt/moi">Làm hợp đồng nguyên tắc</a> <a class="nut phu" href="/hop-dong/moi">Thêm hợp đồng thầu</a></p>
          </div>""", "tq")
    return trang(c, "Tổng quan", f"""
      <div class="dau-trang"><h1>Tổng quan</h1><div class="hang-nut"><a class="nut" href="/hdnt/moi">Làm HĐ nguyên tắc</a>
        <a class="nut phu" href="/hop-dong/moi">Thêm hợp đồng thầu</a></div></div>
      <p class="mo">{"Tất cả hợp đồng thầu đang thực hiện" if c.ql else "Hợp đồng thầu đang thực hiện do bạn phụ trách"}
        · <a href="/hop-dong?loai=nguyen_tac">{n_hdnt} hợp đồng nguyên tắc</a> (tự gia hạn, không cảnh báo hết hạn)</p>
      <div class="o-so">
        <div class="the"><span>Đang thực hiện</span><b>{len(ds)}</b></div>
        <div class="the"><span>Tổng giá trị (đ)</span><b>{tien(gt)}</b></div>
        <div class="the"><span>Đã giao (đ)</span><b>{tien(dg)}</b></div>
        <div class="the"><span>Còn lại (đ)</span><b>{tien(gt - dg)}</b></div>
      </div>
      {khoi("Quá hạn", qua_han, "Không có hợp đồng quá hạn.")}
      {khoi(f"Hết hạn trong {SAP_HET_HAN} ngày", sap_han, "Không có hợp đồng sắp hết hạn.")}
      {khoi(f"Đã giao từ {round(SAP_HET_SL * 100)}% giá trị", sap_sl, "Không có hợp đồng sắp hết số lượng.")}""", "tq")


def ds_hop_dong(c):
    dk, ts = loc_quyen(c)
    tu, tt, pt, kh = c.q.get("q", ""), c.q.get("tt", ""), c.q.get("pt", ""), c.q.get("kh", "")
    loai = c.q.get("loai", "")
    if loai in ("thau", "nguyen_tac"):
        dk += " AND loai = ?"
        ts.append(loai)
    if tu:
        dk += (" AND (so_hd LIKE ? OR khach LIKE ? OR ten_goi_thau LIKE ? OR so_tbmt LIKE ? OR id IN "
               "(SELECT hop_dong_id FROM dong_hang WHERE ma_hang LIKE ? OR ten_hang LIKE ?))")
        ts += [f"%{tu}%"] * 6
    if tt in dict(TRANG_THAI):
        dk += " AND trang_thai = ?"
        ts.append(tt)
    if pt.isdigit() and c.ql:
        dk += " AND phu_trach_id = ?"
        ts.append(int(pt))
    if kh.isdigit():
        dk += " AND khach_hang_id = ?"
        ts.append(int(kh))
    ds = c.db.execute(f"SELECT * FROM v_hop_dong WHERE 1=1{dk} ORDER BY (trang_thai <> 'dang_thuc_hien'), het_han", ts).fetchall()
    loc_pt = ""
    if c.ql:
        nd = c.db.execute("SELECT id, ho_ten FROM nguoi_dung ORDER BY ho_ten").fetchall()
        loc_pt = chon("pt", [(u["id"], u["ho_ten"]) for u in nd], pt, "Mọi người phụ trách")
    an_kh = f'<input type="hidden" name="kh" value="{e(kh)}">' if kh.isdigit() else ""
    bang = bang_hd(ds) if ds else '<div class="the trong">Không có hợp đồng nào khớp.</div>'
    return trang(c, "Hợp đồng", f"""
      <div class="dau-trang"><h1>Hợp đồng <span class="dem">{len(ds)}</span></h1><a class="nut" href="/hop-dong/moi">Thêm hợp đồng</a></div>
      <form class="bo-loc">{an_kh}
        <input type="search" name="q" value="{e(tu)}" placeholder="Số hợp đồng, khách, gói thầu, mã hàng…">
        {chon("loai", [("thau", "Hợp đồng thầu"), ("nguyen_tac", "HĐ nguyên tắc")], loai, "Mọi loại")}
        {chon("tt", TRANG_THAI, tt, "Mọi tình trạng")}{loc_pt}
        <button class="nut phu">Lọc</button>{'<a href="/hop-dong">Bỏ lọc</a>' if c.q else ""}</form>
      {bang}""", "hd")


def form_hd(c, h=None):
    g = (lambda f: h[f] if h else "")
    kh = c.db.execute("SELECT id, ten FROM khach_hang ORDER BY ten").fetchall()
    o_pt = ""
    if c.ql:
        nd = c.db.execute("SELECT id, ho_ten FROM nguoi_dung WHERE hoat_dong = 1 OR id = ? ORDER BY ho_ten",
                          (g("phu_trach_id") or 0,)).fetchall()
        o_pt = f'<label>Người phụ trách{chon("phu_trach_id", [(u["id"], u["ho_ten"]) for u in nd], g("phu_trach_id") or c.user["id"])}</label>'
    o_tt = f'<label>Tình trạng{chon("trang_thai", TRANG_THAI, g("trang_thai"))}</label>' if h else ""
    huy = f'/hop-dong/{h["id"]}' if h else "/hop-dong"
    return f"""<div class="the"><form method="post" class="luoi">{an_csrf(c)}
      {o("Số hợp đồng", "so_hd", g("so_hd"), bat_buoc=True)}
      <label>Khách hàng <b class="sao">*</b>{chon("khach_hang_id", [(k["id"], k["ten"]) for k in kh], g("khach_hang_id"), "— chọn —")}</label>
      {"" if h else o("Hoặc nhập khách hàng mới", "khach_moi")}
      {o("Tên gói thầu", "ten_goi_thau", g("ten_goi_thau"))}
      {o("Số TBMT / mã gói thầu", "so_tbmt", g("so_tbmt"))}
      {o("Ngày ký", "ngay_ky", g("ngay_ky"), kieu="date")}
      {o("Ngày hiệu lực", "ngay_hieu_luc", g("ngay_hieu_luc"), kieu="date")}
      {o("Ngày hết hạn", "ngay_het_han", g("ngay_het_han"), kieu="date", bat_buoc=True)}
      {o_pt}{o_tt}
      {o("Link file hợp đồng (Google Drive…)", "link_file", g("link_file"), kieu="url")}
      <label class="rong">Ghi chú<textarea name="ghi_chu" rows="2">{e(g("ghi_chu"))}</textarea></label>
      <div class="hang-nut"><button class="nut">Lưu</button><a href="{huy}">Hủy</a></div></form></div>"""


def doc_hd(c, h=None):
    kid = c.form.get("khach_hang_id", "")
    moi = c.chu("khach_moi", "Khách hàng mới", toi_da=300)
    if moi:
        r = c.db.execute("SELECT id FROM khach_hang WHERE ten = ?", (moi,)).fetchone()
        kid = r["id"] if r else c.db.them("INSERT INTO khach_hang (ten) VALUES (?)", (moi,))
    elif not (kid.isdigit() and c.db.execute("SELECT 1 FROM khach_hang WHERE id = ?", (kid,)).fetchone()):
        raise Loi(400, "Chưa chọn khách hàng.")
    pt = h["phu_trach_id"] if h else c.user["id"]
    if c.ql:
        v = c.form.get("phu_trach_id", "")
        if not (v.isdigit() and c.db.execute("SELECT 1 FROM nguoi_dung WHERE id = ?", (v,)).fetchone()):
            raise Loi(400, "Chưa chọn người phụ trách.")
        pt = int(v)
    tt = c.form.get("trang_thai", "dang_thuc_hien") if h else "dang_thuc_hien"
    if tt not in dict(TRANG_THAI):
        raise Loi(400, "Tình trạng không hợp lệ.")
    hl, hh = c.ngay("ngay_hieu_luc", "Ngày hiệu lực"), c.ngay("ngay_het_han", "Ngày hết hạn", True)
    if hl and hh < hl:
        raise Loi(400, "Ngày hết hạn phải sau ngày hiệu lực.")
    return dict(so_hd=c.chu("so_hd", "Số hợp đồng", True, 100), khach_hang_id=int(kid),
                ten_goi_thau=c.chu("ten_goi_thau", "Tên gói thầu"), so_tbmt=c.chu("so_tbmt", "Số TBMT", toi_da=100),
                ngay_ky=c.ngay("ngay_ky", "Ngày ký"), ngay_hieu_luc=hl, ngay_het_han=hh, phu_trach_id=pt,
                trang_thai=tt, link_file=c.link("link_file", "Link file hợp đồng"),
                ghi_chu=c.chu("ghi_chu", "Ghi chú", toi_da=2000))


def hd_moi(c):
    if c.method == "POST":
        d = doc_hd(c)
        d["tao_luc"] = datetime.now().isoformat(timespec="seconds")
        try:
            hid = c.db.them(f"INSERT INTO hop_dong ({', '.join(d)}) VALUES ({', '.join('?' * len(d))})", list(d.values()))
        except LOI_TRUNG:
            c.db.rollback()
            raise Loi(400, "Số hợp đồng này đã có.")
        c.db.commit()
        return Chuyen(f"/hop-dong/{hid}", "Đã tạo hợp đồng. Hãy thêm các mã hàng bên dưới.")
    return trang(c, "Thêm hợp đồng", "<h1>Thêm hợp đồng</h1>" + form_hd(c), "hd")


def hd_sua(c, hid):
    h = lay_hd(c, hid)
    if c.method == "POST":
        d = doc_hd(c, h)
        try:
            c.db.execute(f"UPDATE hop_dong SET {', '.join(k + ' = ?' for k in d)} WHERE id = ?", list(d.values()) + [hid])
        except LOI_TRUNG:
            c.db.rollback()
            raise Loi(400, "Số hợp đồng này đã có.")
        c.db.commit()
        return Chuyen(f"/hop-dong/{hid}", "Đã lưu.")
    return trang(c, f"Sửa {h['so_hd']}", f"<h1>Sửa hợp đồng {e(h['so_hd'])}</h1>" + form_hd(c, h), "hd")


def hd_xoa(c, hid):
    h = lay_hd(c, hid)
    c.db.execute("DELETE FROM giao_hang WHERE dong_hang_id IN (SELECT id FROM dong_hang WHERE hop_dong_id = ?)", (hid,))
    c.db.execute("DELETE FROM hop_dong WHERE id = ?", (hid,))
    c.db.commit()
    return Chuyen("/hop-dong", f"Đã xóa hợp đồng {h['so_hd']}.")


def dong_cua_hd(c, hid):
    return c.db.execute(
        "SELECT d.*, COALESCE((SELECT SUM(g.so_luong) FROM giao_hang g WHERE g.dong_hang_id = d.id), 0) AS da_giao "
        "FROM dong_hang d WHERE d.hop_dong_id = ? ORDER BY d.id", (hid,)).fetchall()


def o_dong_hang(d=None):
    g = (lambda f: d[f] if d else "")
    so = (lambda f: (f"{d[f]:g}" if d else ""))
    return (o("Mã hàng", "ma_hang", g("ma_hang"), bat_buoc=True) + o("Tên hàng", "ten_hang", g("ten_hang"))
            + o("Hãng sản xuất", "hang_sx", g("hang_sx")) + o("Đơn vị tính", "don_vi", g("don_vi"))
            + o("Số lượng", "so_luong", so("so_luong"), kieu="number", bat_buoc=True, them='step="any" min="0"')
            + o("Đơn giá (đ)", "don_gia", so("don_gia"), kieu="number", bat_buoc=True, them='step="any" min="0"'))


def doc_dong_hang(c):
    return (c.chu("ma_hang", "Mã hàng", True, 100), c.chu("ten_hang", "Tên hàng"), c.chu("hang_sx", "Hãng sản xuất", toi_da=100),
            c.chu("don_vi", "Đơn vị tính", toi_da=30), c.so("so_luong", "Số lượng", True), c.so("don_gia", "Đơn giá", True))


def hd_xem(c, hid):
    h = lay_hd(c, hid)
    dong = dong_cua_hd(c, hid)
    pt = phan_tram(h)
    url = f"/hop-dong/{hid}"

    def dl(nhan, gt):
        return f"<div><dt>{nhan}</dt><dd>{gt or '—'}</dd></div>"

    het_han = ngay(h["het_han"])
    if h["het_han"] != h["ngay_het_han"]:
        het_han += f' <span class="mo">(gốc {ngay(h["ngay_het_han"])}, đã gia hạn)</span>'
    tep = f'<a href="{e(h["link_file"])}" target="_blank" rel="noopener noreferrer">Mở file</a>' if h["link_file"] else ""
    thong_tin = (dl("Khách hàng", f'<a href="/khach-hang/{h["khach_hang_id"]}">{e(h["khach"])}</a>')
                 + dl("Gói thầu", e(h["ten_goi_thau"])) + dl("Số TBMT", e(h["so_tbmt"]))
                 + dl("Ngày ký", ngay(h["ngay_ky"])) + dl("Hiệu lực", ngay(h["ngay_hieu_luc"])) + dl("Hết hạn", het_han)
                 + dl("Phụ trách", e(h["phu_trach"])) + dl("File hợp đồng", tep) + dl("Ghi chú", e(h["ghi_chu"])))

    # mã hàng
    hang = ""
    for d in dong:
        con = d["so_luong"] - d["da_giao"]
        p = min(100, round(100 * d["da_giao"] / d["so_luong"])) if d["so_luong"] else 0
        xoa = "" if d["da_giao"] else nut_xoa(c, f"/dong-hang/{d['id']}/xoa", f"Xóa mã hàng {d['ma_hang']}?")
        hang += (f'<tr><td><b>{e(d["ma_hang"])}</b><div class="mo">{e(d["ten_hang"])}</div></td><td>{e(d["hang_sx"])}</td>'
                 f'<td>{e(d["don_vi"])}</td><td class="so">{sl(d["so_luong"])}</td><td class="so">{tien(d["don_gia"])}</td>'
                 f'<td class="so">{tien(d["so_luong"] * d["don_gia"])}</td><td class="so">{sl(d["da_giao"])}</td>'
                 f'<td class="so"><b>{sl(con)}</b></td><td><progress max="100" value="{p}"></progress> <span class="mo">{p}%</span></td>'
                 f'<td class="thao-tac"><a href="/dong-hang/{d["id"]}/sua">Sửa</a>{xoa}</td></tr>')
    bang_hang = (f'<div class="the cuon"><table><thead><tr><th>Mã hàng</th><th>Hãng</th><th>ĐVT</th><th class="so">Số lượng</th>'
                 f'<th class="so">Đơn giá</th><th class="so">Thành tiền</th><th class="so">Đã giao</th><th class="so">Còn lại</th>'
                 f'<th>Tiến độ</th><th></th></tr></thead><tbody>{hang}</tbody></table></div>'
                 if dong else '<div class="the trong">Chưa có mã hàng. Thêm ở bên dưới.</div>')

    # giao hàng
    con_giao = [d for d in dong if d["so_luong"] - d["da_giao"] > 1e-9]
    form_giao = ""
    if con_giao:
        o_sl = "".join(
            f'<label>{e(d["ma_hang"])} <span class="mo">(còn {sl(d["so_luong"] - d["da_giao"])} {e(d["don_vi"])})</span>'
            f'<input type="number" name="sl_{d["id"]}" step="any" min="0" max="{d["so_luong"] - d["da_giao"]:g}"></label>'
            for d in con_giao)
        form_giao = f"""<details class="the"><summary>Ghi nhận một đợt giao hàng</summary>
          <form method="post" action="{url}/giao-hang" class="luoi">{an_csrf(c)}
          {o("Ngày giao", "ngay", date.today().isoformat(), kieu="date", bat_buoc=True)}
          {o("Số phiếu / hóa đơn", "so_phieu")}{o("Ghi chú", "ghi_chu")}
          <div class="rong"><b>Số lượng giao theo từng mã</b> <span class="mo">(để trống mã không giao)</span></div>
          {o_sl}<div class="hang-nut"><button class="nut">Lưu đợt giao</button></div></form></details>"""
    lich_su = c.db.execute(
        "SELECT g.*, d.ma_hang, d.don_vi, d.don_gia, u.ho_ten FROM giao_hang g JOIN dong_hang d ON d.id = g.dong_hang_id "
        "LEFT JOIN nguoi_dung u ON u.id = g.nguoi_nhap_id WHERE d.hop_dong_id = ? ORDER BY g.ngay DESC, g.id DESC", (hid,)).fetchall()
    ls = "".join(
        f'<tr><td>{ngay(g["ngay"])}</td><td>{e(g["so_phieu"])}</td><td>{e(g["ma_hang"])}</td>'
        f'<td class="so">{sl(g["so_luong"])} {e(g["don_vi"])}</td><td class="so">{tien(g["so_luong"] * g["don_gia"])}</td>'
        f'<td>{e(g["ghi_chu"])}</td><td class="mo">{e(g["ho_ten"])}</td>'
        f'<td class="thao-tac">{nut_xoa(c, f"/giao-hang/{g["id"]}/xoa", "Xóa dòng giao hàng này?")}</td></tr>' for g in lich_su)
    bang_ls = (f'<div class="the cuon"><table><thead><tr><th>Ngày</th><th>Số phiếu</th><th>Mã hàng</th><th class="so">Số lượng</th>'
               f'<th class="so">Giá trị (đ)</th><th>Ghi chú</th><th>Người nhập</th><th></th></tr></thead><tbody>{ls}</tbody></table></div>'
               if lich_su else '<div class="the trong">Chưa có đợt giao hàng nào.</div>')

    # phụ lục
    pl = c.db.execute("SELECT * FROM phu_luc WHERE hop_dong_id = ? ORDER BY ngay_ky, id", (hid,)).fetchall()
    dong_pl = ""
    for p in pl:
        tep_pl = f'<a href="{e(p["link_file"])}" target="_blank" rel="noopener noreferrer">Mở file</a>' if p["link_file"] else ""
        xoa_pl = nut_xoa(c, f"/phu-luc/{p['id']}/xoa", f"Xóa phụ lục {p['so_pl']}?")
        dong_pl += (f'<tr><td><b>{e(p["so_pl"])}</b></td><td>{ngay(p["ngay_ky"])}</td><td>{e(p["noi_dung"])}</td>'
                    f'<td>{ngay(p["ngay_het_han_moi"])}</td><td>{tep_pl}</td><td class="thao-tac">{xoa_pl}</td></tr>')
    bang_pl = (f'<div class="the cuon"><table><thead><tr><th>Số phụ lục</th><th>Ngày ký</th><th>Nội dung</th>'
               f'<th>Hết hạn mới</th><th>File</th><th></th></tr></thead><tbody>{dong_pl}</tbody></table></div>' if pl else "")

    xoa_hd = nut_xoa(c, f"{url}/xoa", f"Xóa hợp đồng {h['so_hd']} cùng mọi mã hàng, phụ lục và lịch sử giao hàng?",
                     "Xóa hợp đồng") if c.ql else ""
    phan_pl = f"""<h2>Phụ lục <span class="dem">{len(pl)}</span></h2>{bang_pl}
      <details class="the"><summary>Thêm phụ lục</summary>
        <form method="post" action="{url}/phu-luc" class="luoi">{an_csrf(c)}
        {o("Số phụ lục", "so_pl", bat_buoc=True)}{o("Ngày ký", "ngay_ky", kieu="date")}
        {o("Ngày hết hạn mới (nếu gia hạn)", "ngay_het_han_moi", kieu="date")}
        {o("Link file phụ lục", "link_file", kieu="url")}
        <label class="rong">Nội dung thay đổi<textarea name="noi_dung" rows="2"></textarea></label>
        <div class="hang-nut"><button class="nut">Thêm phụ lục</button></div></form></details>"""
    if h["loai"] == "nguyen_tac":
        tu_tai = " data-tu-tai" if c.q.get("tai") == "1" else ""
        return trang(c, h["so_hd"], f"""
      <div class="dau-trang"><h1>{e(h["so_hd"])} {nhan_hd(h)}</h1><div class="hang-nut">
        <a class="nut" href="{url}/tai-hdnt"{tu_tai}>Tải file Word</a><a class="nut phu" href="{url}/sua">Sửa</a></div></div>
      <div class="the"><dl class="thong-tin">{thong_tin}</dl></div>
      <p class="mo">File Word lấy thông tin bên mua hiện có trong mục Khách hàng. Sửa thông tin khách rồi tải lại nếu cần.</p>
      {phan_pl}{xoa_hd}""", "hd")
    return trang(c, h["so_hd"], f"""
      <div class="dau-trang"><h1>{e(h["so_hd"])} {nhan_hd(h)}</h1><a class="nut phu" href="{url}/sua">Sửa</a></div>
      <div class="the"><dl class="thong-tin">{thong_tin}</dl></div>
      <div class="o-so">
        <div class="the"><span>Giá trị (đ)</span><b>{tien(h["gia_tri"])}</b></div>
        <div class="the"><span>Đã giao (đ)</span><b>{tien(h["da_giao"])}</b></div>
        <div class="the"><span>Còn lại (đ)</span><b>{tien(h["gia_tri"] - h["da_giao"])}</b></div>
        <div class="the"><span>Tiến độ</span><b>{pt}%</b><progress max="100" value="{pt}"></progress></div>
      </div>
      <h2>Mã hàng <span class="dem">{len(dong)}</span></h2>{bang_hang}
      <details class="the"{"" if dong else " open"}><summary>Thêm mã hàng</summary>
        <form method="post" action="{url}/dong-hang" class="luoi">{an_csrf(c)}{o_dong_hang()}
        <div class="hang-nut"><button class="nut">Thêm mã hàng</button></div></form></details>
      <h2>Giao hàng</h2>{form_giao}{bang_ls}
      <h2>Phụ lục <span class="dem">{len(pl)}</span></h2>{bang_pl}
      <details class="the"><summary>Thêm phụ lục</summary>
        <form method="post" action="{url}/phu-luc" class="luoi">{an_csrf(c)}
        {o("Số phụ lục", "so_pl", bat_buoc=True)}{o("Ngày ký", "ngay_ky", kieu="date")}
        {o("Ngày hết hạn mới (nếu gia hạn)", "ngay_het_han_moi", kieu="date")}
        {o("Link file phụ lục", "link_file", kieu="url")}
        <label class="rong">Nội dung thay đổi<textarea name="noi_dung" rows="2"></textarea></label>
        <p class="mo rong">Nếu phụ lục đổi số lượng hoặc đơn giá, hãy sửa trực tiếp ở mã hàng tương ứng.</p>
        <div class="hang-nut"><button class="nut">Thêm phụ lục</button></div></form></details>
      {xoa_hd}""", "hd")


def dong_hang_them(c, hid):
    lay_hd(c, hid)
    c.db.execute("INSERT INTO dong_hang (hop_dong_id, ma_hang, ten_hang, hang_sx, don_vi, so_luong, don_gia) VALUES (?,?,?,?,?,?,?)",
                 (hid,) + doc_dong_hang(c))
    c.db.commit()
    return Chuyen(f"/hop-dong/{hid}", "Đã thêm mã hàng.")


def lay_dong(c, did):
    d = c.db.execute("SELECT d.*, COALESCE((SELECT SUM(g.so_luong) FROM giao_hang g WHERE g.dong_hang_id = d.id), 0) AS da_giao "
                     "FROM dong_hang d WHERE d.id = ?", (did,)).fetchone()
    if not d:
        raise Loi(404, "Không tìm thấy mã hàng.")
    return d, lay_hd(c, d["hop_dong_id"])


def dong_hang_sua(c, did):
    d, h = lay_dong(c, did)
    if c.method == "POST":
        v = doc_dong_hang(c)
        if v[4] < d["da_giao"] - 1e-9:
            raise Loi(400, f"Số lượng không thể nhỏ hơn số đã giao ({sl(d['da_giao'])}).")
        c.db.execute("UPDATE dong_hang SET ma_hang=?, ten_hang=?, hang_sx=?, don_vi=?, so_luong=?, don_gia=? WHERE id=?", v + (did,))
        c.db.commit()
        return Chuyen(f"/hop-dong/{h['id']}", "Đã lưu mã hàng.")
    return trang(c, "Sửa mã hàng", f"""
      <h1>Sửa mã hàng</h1><p class="mo">Hợp đồng {e(h["so_hd"])} · đã giao {sl(d["da_giao"])} {e(d["don_vi"])}</p>
      <div class="the"><form method="post" class="luoi">{an_csrf(c)}{o_dong_hang(d)}
        <div class="hang-nut"><button class="nut">Lưu</button><a href="/hop-dong/{h["id"]}">Hủy</a></div></form></div>""", "hd")


def dong_hang_xoa(c, did):
    d, h = lay_dong(c, did)
    if d["da_giao"]:
        raise Loi(400, "Mã hàng đã có giao hàng nên không xóa được. Hãy xóa các dòng giao hàng trước.")
    c.db.execute("DELETE FROM dong_hang WHERE id = ?", (did,))
    c.db.commit()
    return Chuyen(f"/hop-dong/{h['id']}", "Đã xóa mã hàng.")


def giao_hang_them(c, hid):
    lay_hd(c, hid)
    ng = c.ngay("ngay", "Ngày giao", True)
    phieu, gc = c.chu("so_phieu", "Số phiếu", toi_da=100), c.chu("ghi_chu", "Ghi chú")
    them = []
    for d in dong_cua_hd(c, hid):
        n = c.so(f"sl_{d['id']}", f"Số lượng {d['ma_hang']}")
        if n > 0:
            con = d["so_luong"] - d["da_giao"]
            if n > con + 1e-9:
                raise Loi(400, f"Mã {d['ma_hang']} chỉ còn {sl(con)}, không thể giao {sl(n)}.")
            them.append((d["id"], ng, n, phieu, gc, c.user["id"]))
    if not them:
        raise Loi(400, "Chưa nhập số lượng giao cho mã hàng nào.")
    c.db.executemany("INSERT INTO giao_hang (dong_hang_id, ngay, so_luong, so_phieu, ghi_chu, nguoi_nhap_id) VALUES (?,?,?,?,?,?)", them)
    c.db.commit()
    return Chuyen(f"/hop-dong/{hid}", f"Đã ghi nhận giao {len(them)} mã hàng.")


def giao_hang_xoa(c, gid):
    g = c.db.execute("SELECT d.hop_dong_id FROM giao_hang g JOIN dong_hang d ON d.id = g.dong_hang_id WHERE g.id = ?", (gid,)).fetchone()
    if not g:
        raise Loi(404, "Không tìm thấy dòng giao hàng.")
    lay_hd(c, g["hop_dong_id"])
    c.db.execute("DELETE FROM giao_hang WHERE id = ?", (gid,))
    c.db.commit()
    return Chuyen(f"/hop-dong/{g['hop_dong_id']}", "Đã xóa dòng giao hàng.")


def phu_luc_them(c, hid):
    lay_hd(c, hid)
    c.db.execute("INSERT INTO phu_luc (hop_dong_id, so_pl, ngay_ky, noi_dung, ngay_het_han_moi, link_file) VALUES (?,?,?,?,?,?)",
                 (hid, c.chu("so_pl", "Số phụ lục", True, 100), c.ngay("ngay_ky", "Ngày ký"),
                  c.chu("noi_dung", "Nội dung", toi_da=2000), c.ngay("ngay_het_han_moi", "Ngày hết hạn mới"),
                  c.link("link_file", "Link file phụ lục")))
    c.db.commit()
    return Chuyen(f"/hop-dong/{hid}", "Đã thêm phụ lục.")


def phu_luc_xoa(c, pid):
    p = c.db.execute("SELECT hop_dong_id FROM phu_luc WHERE id = ?", (pid,)).fetchone()
    if not p:
        raise Loi(404, "Không tìm thấy phụ lục.")
    lay_hd(c, p["hop_dong_id"])
    c.db.execute("DELETE FROM phu_luc WHERE id = ?", (pid,))
    c.db.commit()
    return Chuyen(f"/hop-dong/{p['hop_dong_id']}", "Đã xóa phụ lục.")


# ───────────────────────── nhập danh sách khách hàng ─────────────────────────

# (cột trong app, các cụm chữ nhận diện tiêu đề cột — đã bỏ dấu, chữ thường)
TIEU_DE_NHAP = [
    ("nhan_vien_bh", ["nhan vien", "nvbh", "phu trach"]),
    ("ma_so_thue", ["ma so thue", "mst"]),
    ("dia_chi", ["dia chi"]),
    ("chuc_vu", ["chuc vu"]),
    ("dai_dien", ["nguoi dai dien", "dai dien", "ho ten nguoi dai dien"]),
    ("dien_thoai", ["dien thoai", "so dien thoai", "sdt", "so dt"]),
    ("email", ["email", "e-mail"]),
    ("lien_he", ["lien he"]),
    ("ten", ["ten khach hang", "ten cong ty", "ten don vi", "ten doanh nghiep", "khach hang", "ten"]),
]


def doc_xlsx(data):
    """Đọc trang tính đầu tiên của file .xlsx thành danh sách hàng (chỉ dùng thư viện có sẵn)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    chung = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(ns + "si"):
            t = si.find(ns + "t")                        # chữ thường, hoặc nhiều đoạn <r> có định dạng riêng
            chung.append(t.text or "" if t is not None else
                         "".join(r.find(ns + "t").text or "" for r in si.findall(ns + "r") if r.find(ns + "t") is not None))
    so = ET.fromstring(z.read("xl/workbook.xml"))
    dau = next(so.iter(ns + "sheet"))
    rid = dau.get(rns + "id")
    duong = "xl/worksheets/sheet1.xml"
    for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
        if r.get("Id") == rid:
            t = r.get("Target").lstrip("/")
            duong = t if t.startswith("xl/") else "xl/" + t
    hang = []
    for row in ET.fromstring(z.read(duong)).iter(ns + "row"):
        o = {}
        for cel in row.iter(ns + "c"):
            ref = re.match(r"([A-Z]+)", cel.get("r", "A"))
            cot = 0
            for ch in ref.group(1):
                cot = cot * 26 + ord(ch) - 64
            loai, v = cel.get("t"), cel.find(ns + "v")
            if loai == "s" and v is not None:
                gt = chung[int(v.text)]
            elif loai == "inlineStr":
                gt = "".join(t.text or "" for t in cel.iter(ns + "t"))
            else:
                gt = v.text if v is not None else ""
            o[cot - 1] = gt or ""
        if o:
            hang.append([o.get(i, "") for i in range(max(o) + 1)])
    return hang


def doc_csv(data):
    chu = data.decode("utf-8-sig", "replace")
    try:
        kieu = csv.Sniffer().sniff(chu[:4000], delimiters=",;\t")
    except csv.Error:
        kieu = csv.excel
    return list(csv.reader(io.StringIO(chu), kieu))


def nhan_cot(hang):
    """Tìm hàng tiêu đề trong 30 hàng đầu: hàng có cột tên và nhận ra nhiều cột nhất.
    Ô tiêu đề phải BẮT ĐẦU bằng cụm nhận diện, để dòng tựa "Danh sách khách hàng năm…" không bị nhầm."""
    tot = None
    for i, h in enumerate(hang[:30]):
        cot = {}
        for j, o in enumerate(h):
            g = gap(o)
            if not g or len(g) > 60:
                continue
            for ten, khoa in TIEU_DE_NHAP:
                if ten not in cot and any(g == k or g.startswith(k + " ") or g.startswith(k + "(") for k in khoa):
                    cot[ten] = j
                    break
        if "ten" in cot and (tot is None or len(cot) > len(tot[1])):
            tot = (i, cot)
    if tot:
        return tot
    raise Loi(400, "Không tìm thấy cột tên khách hàng. Hàng tiêu đề cần có ô \"Tên khách hàng\" (hoặc \"Tên công ty\").")


def nhap_khach(c):
    if c.method == "POST":
        ten_tep, dl = c.tep.get("tep", ("", b""))
        if not dl:
            raise Loi(400, "Chưa chọn file.")
        try:
            hang = doc_csv(dl) if ten_tep.lower().endswith(".csv") else doc_xlsx(dl)
        except (zipfile.BadZipFile, KeyError, ET.ParseError, StopIteration, ValueError, IndexError):
            raise Loi(400, "Không đọc được file. Hãy dùng file Excel .xlsx hoặc .csv.")
        dau, cot = nhan_cot(hang)
        co = {gap(k["ten"]): k for k in c.db.execute("SELECT * FROM khach_hang").fetchall()}
        da_thay, them, cap_nhat, trung = set(), [], 0, 0
        for h in hang[dau + 1:]:
            gt = {ten: gon(h[j]) if j < len(h) else "" for ten, j in cot.items()}
            ten = gt.pop("ten")
            k = gap(ten)
            if not k or k.startswith("tong cong"):
                continue
            if k in da_thay:
                trung += 1
                continue
            da_thay.add(k)
            if k in co:                                 # khách đã có: chỉ điền những ô đang trống
                sua = {f: v for f, v in gt.items() if v and not (co[k][f] or "").strip()}
                if sua:
                    c.db.execute(f"UPDATE khach_hang SET {', '.join(f + ' = ?' for f in sua)} WHERE id = ?",
                                 list(sua.values()) + [co[k]["id"]])
                    cap_nhat += 1
            else:
                them.append([ten[:300]] + [gt.get(f, "") for f in COT_KHACH[1:]])
        if them:
            c.db.executemany(f"INSERT INTO khach_hang ({', '.join(COT_KHACH)}) VALUES ({', '.join('?' * len(COT_KHACH))})", them)
        c.db.commit()
        tb = f"Đã nhập: thêm {len(them)} khách mới, bổ sung thông tin cho {cap_nhat} khách đã có"
        return Chuyen("/khach-hang", tb + (f", bỏ {trung} dòng trùng tên trong file." if trung else "."))
    return trang(c, "Nhập khách hàng", f"""
      <h1>Nhập danh sách khách hàng</h1>
      <div class="the"><form method="post" enctype="multipart/form-data" class="luoi-1">{an_csrf(c)}
        <label>File Excel (.xlsx) hoặc .csv<input type="file" name="tep" accept=".xlsx,.csv" required></label>
        <div class="hang-nut"><button class="nut">Nhập</button><a href="/khach-hang">Hủy</a></div></form></div>
      <div class="the"><h2>File cần có</h2>
        <p>Một hàng tiêu đề, trong đó có cột <b>Tên khách hàng</b> (hoặc Tên công ty). Các cột khác nếu có sẽ được nhận theo tiêu đề:
        Mã số thuế, Địa chỉ, Người đại diện, Chức vụ, Điện thoại, Email, Người liên hệ, Nhân viên BH. Cột khác bị bỏ qua.</p>
        <p class="mo">Khách trùng tên (không phân biệt hoa thường, dấu cách) với khách đã có thì không tạo mới,
        chỉ điền thêm các ô đang trống. Chỉ đọc trang tính đầu tiên của file Excel.</p></div>""", "kh")


# ───────────────────────── mẫu hợp đồng ─────────────────────────

O_DIEN_MO_TA = [("so_hd", "Số hợp đồng"), ("ngay", "Ngày ký (2 chữ số)"), ("thang", "Tháng ký"), ("nam", "Năm ký"),
                ("ten_kh", "Tên bên mua"), ("dia_chi", "Địa chỉ"), ("mst", "Mã số thuế"), ("dai_dien", "Người đại diện"),
                ("chuc_vu", "Chức vụ"), ("dien_thoai", "Điện thoại"), ("email", "Email")]


def lay_mau(c):
    r = c.db.execute("SELECT * FROM tep WHERE ma = 'hdnt'").fetchone()
    return (r, bytes(r["noi_dung"])) if r else (None, None)


def mau_hop_dong(c):
    if c.method == "POST":
        ten_tep, dl = c.tep.get("tep", ("", b""))
        if not ten_tep.lower().endswith(".docx"):
            raise Loi(400, "Hãy chọn file Word .docx.")
        try:
            co = docx_mau.kiem_tra(dl)
        except ValueError as loi:
            raise Loi(400, str(loi))
        if "ten_kh" not in co:
            raise Loi(400, "Mẫu chưa có ô {ten_kh} (tên bên mua). Xem danh sách ô điền ở cuối trang.")
        c.db.execute("DELETE FROM tep WHERE ma = 'hdnt'")
        c.db.execute("INSERT INTO tep (ma, ten_tep, noi_dung, cap_nhat, nguoi) VALUES ('hdnt', ?, ?, ?, ?)",
                     (os.path.basename(ten_tep)[:200], dl, datetime.now().isoformat(timespec="seconds"), c.user["ho_ten"]))
        c.db.commit()
        return Chuyen("/mau-hop-dong", f"Đã lưu mẫu. Mẫu có {len(co)}/{len(docx_mau.O_DIEN)} ô điền.")
    r, dl = lay_mau(c)
    if r:
        co = docx_mau.kiem_tra(dl)
        thieu = [x for x in docx_mau.O_DIEN if x not in co]
        hien = (f'<p>Đang dùng: <b>{e(r["ten_tep"])}</b> · cập nhật {e(r["cap_nhat"].replace("T", " "))} bởi {e(r["nguoi"])}'
                f' · <a href="/mau-hop-dong/tai">Tải mẫu về</a></p>'
                + (f'<p class="mo">Mẫu không có các ô: {", ".join("{" + x + "}" for x in thieu)}.</p>' if thieu else ""))
    else:
        hien = '<p><b>Chưa có mẫu.</b> Tải file mẫu .docx lên để làm được hợp đồng nguyên tắc.</p>'
    bang = "".join(f"<tr><td><code>{{{k}}}</code></td><td>{v}</td></tr>" for k, v in O_DIEN_MO_TA)
    return trang(c, "Mẫu hợp đồng", f"""
      <h1>Mẫu hợp đồng nguyên tắc</h1>
      <div class="the">{hien}
        <form method="post" enctype="multipart/form-data" class="luoi-1">{an_csrf(c)}
        <label>Tải mẫu mới (.docx)<input type="file" name="tep" accept=".docx" required></label>
        <div class="hang-nut"><button class="nut">Lưu mẫu</button></div></form></div>
      <div class="the"><h2>Ô điền trong mẫu</h2>
        <p class="mo">Gõ đúng các ô dưới đây (kể cả dấu ngoặc nhọn) vào chỗ cần điền trong file Word. App thay bằng thông tin
        bên mua và giữ nguyên định dạng của chữ chứa ô điền.</p>
        <div class="cuon"><table><thead><tr><th>Ô điền</th><th>Nội dung</th></tr></thead><tbody>{bang}</tbody></table></div></div>""",
                 "mau")


def mau_tai(c):
    r, dl = lay_mau(c)
    if not r:
        raise Loi(404, "Chưa có mẫu.")
    return Tep(r["ten_tep"], dl, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ───────────────────────── hợp đồng nguyên tắc ─────────────────────────

O_BEN_MUA = [("ten_kh", "ten", "Tên bên mua"), ("dia_chi", "dia_chi", "Địa chỉ"), ("mst", "ma_so_thue", "Mã số thuế"),
             ("dai_dien", "dai_dien", "Người đại diện"), ("chuc_vu", "chuc_vu", "Chức vụ"),
             ("dien_thoai", "dien_thoai", "Điện thoại"), ("email", "email", "Email")]


def so_hdnt_tiep(c, nam):
    """Số kế tiếp trong năm: 26001, 26002… (lấy số lớn nhất đang có + 1)."""
    yy = f"{nam % 100:02d}"
    lon = 0
    for r in c.db.execute("SELECT so_hd FROM hop_dong WHERE loai = 'nguyen_tac'").fetchall():
        m = re.match(r"\s*(\d+)", r["so_hd"])
        if m and m.group(1).startswith(yy) and len(m.group(1)) > 2:
            lon = max(lon, int(m.group(1)[2:]))
    return f"{yy}{lon + 1:03d}{HAU_TO_HDNT}"


def mot_nam_sau(d):
    try:
        return d.replace(year=d.year + 1) - timedelta(days=1)
    except ValueError:                                   # ký ngày 29/02
        return d.replace(year=d.year + 1, day=28)


def hdnt_moi(c):
    r_mau, _ = lay_mau(c)
    if c.method == "POST":
        if not r_mau:
            raise Loi(400, "Chưa có mẫu hợp đồng. Quản lý cần tải mẫu lên ở mục Mẫu HĐ.")
        gt = {o: c.chu(o, nhan, o == "ten_kh", 300) for o, _, nhan in O_BEN_MUA}
        if gt["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", gt["email"]):
            raise Loi(400, "Email bên mua không đúng định dạng.")
        so_hd = c.chu("so_hd", "Số hợp đồng", True, 100)
        ngay_ky = c.ngay("ngay_ky", "Ngày ký", True)
        pt = c.user["id"]
        if c.ql:
            v = c.form.get("phu_trach_id", "")
            if not (v.isdigit() and c.db.execute("SELECT 1 FROM nguoi_dung WHERE id = ?", (v,)).fetchone()):
                raise Loi(400, "Chưa chọn người phụ trách.")
            pt = int(v)
        if c.db.execute("SELECT 1 FROM hop_dong WHERE so_hd = ?", (so_hd,)).fetchone():
            raise Loi(400, f"Số hợp đồng {so_hd} đã có. Hãy đổi số khác.")
        # tìm khách theo tên (không phân biệt hoa thường, dấu cách); có thì cập nhật thông tin vừa nhập
        k = next((r for r in c.db.execute("SELECT * FROM khach_hang").fetchall() if gap(r["ten"]) == gap(gt["ten_kh"])), None)
        cot = {cot: gt[o] for o, cot, _ in O_BEN_MUA if o != "ten_kh"}
        if k:
            sua = {f: v for f, v in cot.items() if v}
            if sua:
                c.db.execute(f"UPDATE khach_hang SET {', '.join(f + ' = ?' for f in sua)} WHERE id = ?",
                             list(sua.values()) + [k["id"]])
            kid = k["id"]
        else:
            kid = c.db.them(f"INSERT INTO khach_hang (ten, {', '.join(cot)}) VALUES (?{', ?' * len(cot)})",
                            [gt["ten_kh"]] + list(cot.values()))
        d = date.fromisoformat(ngay_ky)
        try:
            hid = c.db.them(
                "INSERT INTO hop_dong (so_hd, khach_hang_id, ngay_ky, ngay_hieu_luc, ngay_het_han, phu_trach_id, trang_thai, "
                "ghi_chu, tao_luc, loai) VALUES (?,?,?,?,?,?,'dang_thuc_hien',?,?,'nguyen_tac')",
                (so_hd, kid, ngay_ky, ngay_ky, mot_nam_sau(d).isoformat(), pt,
                 "Hợp đồng nguyên tắc, tự gia hạn hằng năm", datetime.now().isoformat(timespec="seconds")))
        except LOI_TRUNG:
            c.db.rollback()
            raise Loi(400, f"Số hợp đồng {so_hd} đã có. Hãy đổi số khác.")
        c.db.commit()
        return Chuyen(f"/hop-dong/{hid}?tai=1", f"Đã tạo hợp đồng {so_hd}. File Word đang được tải xuống.")

    k = None
    if c.q.get("kh", "").isdigit():
        k = c.db.execute("SELECT * FROM khach_hang WHERE id = ?", (int(c.q["kh"]),)).fetchone()
    ds = c.db.execute("SELECT ten, ma_so_thue, dia_chi, dai_dien, chuc_vu, dien_thoai, email FROM khach_hang ORDER BY ten").fetchall()
    du_lieu = json.dumps([[r["ten"], r["dia_chi"], r["ma_so_thue"], r["dai_dien"], r["chuc_vu"], r["dien_thoai"], r["email"]]
                          for r in ds], ensure_ascii=False).replace("<", "\\u003c")
    canh_bao = "" if r_mau else ('<div class="thong-bao loi">Chưa có mẫu hợp đồng. '
                                 + ('<a href="/mau-hop-dong">Tải mẫu lên</a> trước.' if c.ql else "Báo quản lý tải mẫu lên.")
                                 + "</div>")
    o_bm = "".join(o(nhan, ten, k[cot] if k else "", kieu="email" if ten == "email" else "text", bat_buoc=ten == "ten_kh",
                     them='list="ds-khach" autocomplete="off"' if ten == "ten_kh" else "")
                   for ten, cot, nhan in O_BEN_MUA)
    o_pt = ""
    if c.ql:
        nd = c.db.execute("SELECT id, ho_ten FROM nguoi_dung WHERE hoat_dong = 1 ORDER BY ho_ten").fetchall()
        o_pt = f'<label>Người phụ trách{chon("phu_trach_id", [(u["id"], u["ho_ten"]) for u in nd], c.user["id"])}</label>'
    return trang(c, "Làm hợp đồng nguyên tắc", f"""
      <h1>Làm hợp đồng nguyên tắc</h1>
      <p class="mo">Nhập thông tin bên mua (Bên B). Chọn khách có sẵn thì app tự điền thông tin đã lưu.</p>{canh_bao}
      <script type="application/json" id="du-lieu-khach">{du_lieu}</script>
      <datalist id="ds-khach">{"".join(f'<option value="{e(r["ten"])}">' for r in ds)}</datalist>
      <details class="the"><summary>Dán thông tin bên mua để tự điền</summary>
        <p class="mo">Dán đoạn chữ có dạng "Mã số thuế: …", "Địa chỉ: …", "Người đại diện: …" (ví dụ chép từ tin nhắn Zalo
        hoặc trang tra cứu mã số thuế), rồi bấm Tự điền. Kiểm tra lại trước khi tạo.</p>
        <textarea id="o-dan" rows="6"></textarea>
        <div class="hang-nut cach-tren"><button type="button" class="nut phu" id="nut-tu-dien">Tự điền</button>
        <span class="mo" id="kq-tu-dien"></span></div></details>
      <div class="the"><form method="post" class="luoi" id="form-hdnt">{an_csrf(c)}
        <div class="rong"><b>Bên mua</b></div>{o_bm}
        <div class="rong"><b>Hợp đồng</b></div>
        {o("Số hợp đồng", "so_hd", so_hdnt_tiep(c, date.today().year), bat_buoc=True)}
        {o("Ngày ký", "ngay_ky", date.today().isoformat(), kieu="date", bat_buoc=True)}{o_pt}
        <p class="mo rong">Thông tin bên mua được lưu lại vào mục Khách hàng. Hợp đồng có hiệu lực 1 năm từ ngày ký, tự gia hạn.</p>
        <div class="hang-nut"><button class="nut"{"" if r_mau else " disabled"}>Tạo hợp đồng và tải file Word</button>
        <a href="/hop-dong?loai=nguyen_tac">Hủy</a></div></form></div>""", "hdnt")


def ten_tep_an_toan(s):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", s).strip(" .-")[:150] or "hop-dong"


def tai_hdnt(c, hid):
    h = lay_hd(c, hid)
    if h["loai"] != "nguyen_tac":
        raise Loi(400, "Chỉ hợp đồng nguyên tắc mới tạo được file từ mẫu.")
    _, mau = lay_mau(c)
    if not mau:
        raise Loi(400, "Chưa có mẫu hợp đồng. Quản lý cần tải mẫu lên ở mục Mẫu HĐ.")
    k = c.db.execute("SELECT * FROM khach_hang WHERE id = ?", (h["khach_hang_id"],)).fetchone()
    try:
        d = date.fromisoformat(h["ngay_ky"])
        ng = {"ngay": f"{d.day:02d}", "thang": f"{d.month:02d}", "nam": str(d.year)}
    except (TypeError, ValueError):
        ng = {}
    gt = {"so_hd": h["so_hd"], **ng, **{o: k[cot] for o, cot, _ in O_BEN_MUA}}
    ten = ten_tep_an_toan(f"HĐNT {h['so_hd'].split('-')[0]} - {k['ten']}") + ".docx"
    return Tep(ten, docx_mau.dien(mau, gt), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ───────────────────────── định tuyến ─────────────────────────
# quyền: "khach" = không cần đăng nhập, "nd" = đã đăng nhập, "ql" = chỉ quản lý

TUYEN = [
    ("GET|POST", r"/thiet-lap", thiet_lap, "khach"),
    ("GET|POST", r"/dang-nhap", dang_nhap, "khach"),
    ("POST", r"/dang-xuat", dang_xuat, "nd"),
    ("GET|POST", r"/doi-mat-khau", doi_mat_khau, "nd"),
    ("GET", r"/", tong_quan, "nd"),
    ("GET", r"/hop-dong", ds_hop_dong, "nd"),
    ("GET|POST", r"/hop-dong/moi", hd_moi, "nd"),
    ("GET", r"/hop-dong/(\d+)", hd_xem, "nd"),
    ("GET|POST", r"/hop-dong/(\d+)/sua", hd_sua, "nd"),
    ("POST", r"/hop-dong/(\d+)/xoa", hd_xoa, "ql"),
    ("POST", r"/hop-dong/(\d+)/dong-hang", dong_hang_them, "nd"),
    ("GET|POST", r"/dong-hang/(\d+)/sua", dong_hang_sua, "nd"),
    ("POST", r"/dong-hang/(\d+)/xoa", dong_hang_xoa, "nd"),
    ("POST", r"/hop-dong/(\d+)/giao-hang", giao_hang_them, "nd"),
    ("POST", r"/giao-hang/(\d+)/xoa", giao_hang_xoa, "nd"),
    ("POST", r"/hop-dong/(\d+)/phu-luc", phu_luc_them, "nd"),
    ("POST", r"/phu-luc/(\d+)/xoa", phu_luc_xoa, "nd"),
    ("GET|POST", r"/hdnt/moi", hdnt_moi, "nd"),
    ("GET", r"/hop-dong/(\d+)/tai-hdnt", tai_hdnt, "nd"),
    ("GET|POST", r"/mau-hop-dong", mau_hop_dong, "ql"),
    ("GET", r"/mau-hop-dong/tai", mau_tai, "ql"),
    ("GET|POST", r"/khach-hang/nhap", nhap_khach, "ql"),
    ("GET", r"/khach-hang", khach_hang, "nd"),
    ("POST", r"/khach-hang", khach_hang_them, "nd"),
    ("GET|POST", r"/khach-hang/(\d+)", khach_hang_sua, "nd"),
    ("POST", r"/khach-hang/(\d+)/xoa", khach_hang_xoa, "ql"),
    ("GET", r"/nguoi-dung", nguoi_dung, "ql"),
    ("POST", r"/nguoi-dung", nguoi_dung_them, "ql"),
    ("GET|POST", r"/nguoi-dung/(\d+)/sua", nguoi_dung_sua, "ql"),
    ("POST", r"/nguoi-dung/(\d+)/khoa", nguoi_dung_khoa, "ql"),
    ("GET|POST", r"/nguoi-dung/(\d+)/mat-khau", nguoi_dung_mat_khau, "ql"),
]


def dieu_huong(c):
    if c.path != "/thiet-lap" and not c.db.execute("SELECT 1 FROM nguoi_dung").fetchone():
        return Chuyen("/thiet-lap")
    for pp, mau, ham, quyen in TUYEN:
        m = re.fullmatch(mau, c.path)
        if not m or c.method not in pp.split("|"):
            continue
        if quyen != "khach":
            if not c.user:
                return Chuyen("/dang-nhap")
            if quyen == "ql" and not c.ql:
                raise Loi(403, "Chỉ quản lý mới dùng được chức năng này.")
            if c.method == "POST" and not hmac.compare_digest(c.form.get("csrf", ""), c.csrf):
                raise Loi(403, "Phiên làm việc đã hết hạn. Hãy tải lại trang rồi thử lại.")
        return ham(c, *[int(x) for x in m.groups()])
    raise Loi(404, "Không tìm thấy trang.")


class H(BaseHTTPRequestHandler):
    server_version = "HopDong"

    def do_GET(self):
        self.xu_ly("GET")

    def do_POST(self):
        self.xu_ly("POST")

    def xu_ly(self, method):
        u = urllib.parse.urlsplit(self.path)
        path = u.path.rstrip("/") or "/"
        if method == "GET" and path.startswith("/static/"):
            return self.tep_tinh(path[8:])
        c, ma = None, 200
        try:
            c = Ctx(self, method, path, u.query)
            kq = dieu_huong(c)
        except Loi as loi:
            ma = loi.ma
            if c:
                c.db.rollback()
                kq = trang(c, "Lỗi", f'<div class="the hep"><h1>Chưa thực hiện được</h1><p>{e(loi.tb)}</p>'
                                     f'<p><a href="/" data-quay-lai>← Quay lại</a></p></div>')
            else:
                kq = f"<p>{e(loi.tb)}</p>"
        finally:
            if c:
                c.db.close()
        self.gui(c, kq, ma)

    def gui(self, c, kq, ma):
        if isinstance(kq, Chuyen):
            self.send_response(303)
            self.send_header("Location", kq.url)
            if kq.tb:
                c.dat_cookie("hd_tb", urllib.parse.quote(kq.tb), 60)
            body = b""
        elif isinstance(kq, Tep):
            body = kq.du_lieu
            self.send_response(200)
            self.send_header("Content-Type", kq.kieu)
            self.send_header("Content-Disposition", "attachment; filename=\"hop-dong.docx\"; filename*=UTF-8''"
                             + urllib.parse.quote(kq.ten))
        else:
            body = kq.encode()
            self.send_response(ma)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        for ck in (c.cookies if c else []):
            self.send_header("Set-Cookie", ck)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; form-action 'self'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def tep_tinh(self, ten):
        goc = os.path.join(HERE, "public", "static")
        p = os.path.realpath(os.path.join(goc, ten))
        if not p.startswith(goc + os.sep) or not os.path.isfile(p):
            self.send_error(404)
            return
        with open(p, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(p)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    mo_db().close()
    print(f"Quản lý hợp đồng: http://{HOST}:{PORT}  (dữ liệu: {"PostgreSQL" if PG_URL else DB})", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
