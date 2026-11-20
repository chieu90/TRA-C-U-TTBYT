#!/usr/bin/env python3
"""
Quản lý hợp đồng khách hàng — chạy trên máy:

    python3 app.py

rồi mở http://localhost:8770

Trên máy: chỉ dùng thư viện có sẵn của Python, dữ liệu nằm trong du-lieu/hop_dong.db (SQLite).
Trên Vercel: đặt biến môi trường DATABASE_URL (PostgreSQL) — xem api/index.py và vercel.json.
Lần chạy đầu tiên app sẽ hỏi tạo tài khoản quản lý.
"""
import base64, csv, hashlib, hmac, html, io, json, math, mimetypes, os, re, secrets, sqlite3, time, unicodedata, urllib.error, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
from email import policy as email_policy
from email.parser import BytesParser
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import docx_bao_gia, docx_mau, docx_uq

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
CREATE TABLE IF NOT EXISTS cai_dat (khoa TEXT PRIMARY KEY, gia_tri TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tep (
  ma TEXT PRIMARY KEY, ten_tep TEXT NOT NULL, noi_dung BLOB NOT NULL, cap_nhat TEXT NOT NULL, nguoi TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS hang_hoa (
  id INTEGER PRIMARY KEY, ten TEXT DEFAULT '', ten_tm TEXT DEFAULT '', ma TEXT DEFAULT '', nhan_hieu TEXT DEFAULT '',
  nuoc_sx TEXT DEFAULT '', phan_loai TEXT DEFAULT '', hsd TEXT DEFAULT '', quy_cach TEXT DEFAULT '',
  gia_ban REAL DEFAULT 0, gia_min REAL DEFAULT 0, gia_max REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS bao_gia (
  id INTEGER PRIMARY KEY, so_bg TEXT UNIQUE NOT NULL, ngay TEXT NOT NULL, ten_kh TEXT DEFAULT '',
  phu_trach_id INTEGER REFERENCES nguoi_dung(id), trang_thai TEXT NOT NULL DEFAULT 'nhap',
  hieu_luc_den TEXT DEFAULT '', ghi_chu TEXT DEFAULT '', link_file TEXT DEFAULT '', tao_luc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bao_gia_dong (
  id INTEGER PRIMARY KEY, bao_gia_id INTEGER NOT NULL REFERENCES bao_gia(id) ON DELETE CASCADE, tt INTEGER DEFAULT 0,
  ten TEXT DEFAULT '', ten_tm TEXT DEFAULT '', ma TEXT DEFAULT '', nhan_hieu TEXT DEFAULT '',
  nuoc_sx TEXT DEFAULT '', phan_loai TEXT DEFAULT '', hsd TEXT DEFAULT '', quy_cach TEXT DEFAULT '',
  so_luong REAL DEFAULT 0, don_gia REAL DEFAULT 0, gia_min REAL DEFAULT 0, gia_max REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS nha_cung_cap (
  id INTEGER PRIMARY KEY, ten TEXT UNIQUE NOT NULL, ma_so_thue TEXT DEFAULT '', dia_chi TEXT DEFAULT '',
  lien_he TEXT DEFAULT '', dien_thoai TEXT DEFAULT '', email TEXT DEFAULT '', ghi_chu TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS don_hang (
  id INTEGER PRIMARY KEY, so_dh TEXT UNIQUE NOT NULL, ngay TEXT NOT NULL,
  khach_hang_id INTEGER NOT NULL REFERENCES khach_hang(id), bao_gia_id INTEGER REFERENCES bao_gia(id),
  phu_trach_id INTEGER REFERENCES nguoi_dung(id), trang_thai TEXT NOT NULL DEFAULT 'mo',
  ghi_chu TEXT DEFAULT '', tao_luc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS don_hang_dong (
  id INTEGER PRIMARY KEY, don_hang_id INTEGER NOT NULL REFERENCES don_hang(id) ON DELETE CASCADE, tt INTEGER DEFAULT 0,
  hang_hoa_id INTEGER REFERENCES hang_hoa(id), ma TEXT DEFAULT '', ten TEXT DEFAULT '', quy_cach TEXT DEFAULT '',
  so_luong REAL DEFAULT 0, don_gia REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS phieu_xuat (
  id INTEGER PRIMARY KEY, so_px TEXT UNIQUE NOT NULL, don_hang_id INTEGER NOT NULL REFERENCES don_hang(id),
  ngay TEXT NOT NULL, han_tt TEXT NOT NULL, so_hoa_don TEXT DEFAULT '', ghi_chu TEXT DEFAULT '',
  nguoi_nhap_id INTEGER REFERENCES nguoi_dung(id));
CREATE TABLE IF NOT EXISTS phieu_xuat_dong (
  id INTEGER PRIMARY KEY, phieu_xuat_id INTEGER NOT NULL REFERENCES phieu_xuat(id) ON DELETE CASCADE,
  don_hang_dong_id INTEGER NOT NULL REFERENCES don_hang_dong(id), so_lo TEXT DEFAULT '', han_dung TEXT DEFAULT '',
  so_luong REAL NOT NULL);
CREATE TABLE IF NOT EXISTS thu_tien (
  id INTEGER PRIMARY KEY, so_pt TEXT UNIQUE NOT NULL, ngay TEXT NOT NULL,
  khach_hang_id INTEGER NOT NULL REFERENCES khach_hang(id), so_tien REAL NOT NULL, hinh_thuc TEXT DEFAULT '',
  ghi_chu TEXT DEFAULT '', nguoi_nhap_id INTEGER REFERENCES nguoi_dung(id));
CREATE TABLE IF NOT EXISTS phieu_nhap (
  id INTEGER PRIMARY KEY, so_pn TEXT UNIQUE NOT NULL, ngay TEXT NOT NULL,
  nha_cung_cap_id INTEGER REFERENCES nha_cung_cap(id), han_tt TEXT DEFAULT '', so_hoa_don TEXT DEFAULT '',
  ghi_chu TEXT DEFAULT '', nguoi_nhap_id INTEGER REFERENCES nguoi_dung(id));
CREATE TABLE IF NOT EXISTS phieu_nhap_dong (
  id INTEGER PRIMARY KEY, phieu_nhap_id INTEGER NOT NULL REFERENCES phieu_nhap(id) ON DELETE CASCADE,
  hang_hoa_id INTEGER NOT NULL REFERENCES hang_hoa(id), so_lo TEXT DEFAULT '', han_dung TEXT DEFAULT '',
  so_luong REAL NOT NULL, don_gia REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS uy_quyen (
  id INTEGER PRIMARY KEY, so_uq TEXT DEFAULT '', ngay TEXT NOT NULL, chu_dau_tu TEXT NOT NULL, nha_thau TEXT NOT NULL,
  dia_chi_nt TEXT DEFAULT '', goi_thau TEXT DEFAULT '', hieu_luc_den TEXT DEFAULT '', hang TEXT DEFAULT '',
  phu_trach_id INTEGER REFERENCES nguoi_dung(id), link_file TEXT DEFAULT '', ghi_chu TEXT DEFAULT '', tao_luc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS uy_quyen_dong (
  id INTEGER PRIMARY KEY, uy_quyen_id INTEGER NOT NULL REFERENCES uy_quyen(id) ON DELETE CASCADE, tt INTEGER DEFAULT 0,
  stt_mt TEXT DEFAULT '', ma TEXT DEFAULT '', ten_tm TEXT DEFAULT '', quy_cach TEXT DEFAULT '', nha_sx TEXT DEFAULT '',
  xuat_xu TEXT DEFAULT '', dvt TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS chi_tien (
  id INTEGER PRIMARY KEY, so_pc TEXT UNIQUE NOT NULL, ngay TEXT NOT NULL,
  nha_cung_cap_id INTEGER NOT NULL REFERENCES nha_cung_cap(id), so_tien REAL NOT NULL, hinh_thuc TEXT DEFAULT '',
  ghi_chu TEXT DEFAULT '', nguoi_nhap_id INTEGER REFERENCES nguoi_dung(id));
"""

# cột thêm sau khi database đã có dữ liệu: (bảng, cột, kiểu)
COT_THEM = [
    ("nguoi_dung", "email", "TEXT DEFAULT ''"),
    ("nguoi_dung", "duoc_xoa", "INTEGER DEFAULT 0"),
    ("khach_hang", "dai_dien", "TEXT DEFAULT ''"), ("khach_hang", "chuc_vu", "TEXT DEFAULT ''"),
    ("khach_hang", "email", "TEXT DEFAULT ''"), ("khach_hang", "nhan_vien_bh", "TEXT DEFAULT ''"),
    ("hop_dong", "loai", "TEXT DEFAULT 'thau'"),
    ("tep", "nguon", "TEXT DEFAULT ''"),
    ("khach_hang", "han_no", "INTEGER DEFAULT 30"),
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


class Json:
    """Trả về dữ liệu JSON cho script của trang."""
    def __init__(self, du_lieu):
        self.du_lieu = du_lieu


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
        # trên PostgreSQL chỉ chạy khi thiếu cột thêm gần đây nhất (đổi bảng / cột này mỗi lần thêm bảng / cột)
        if not PG_URL or not db.execute("SELECT 1 AS v FROM information_schema.columns WHERE table_name = ? "
                                        "AND column_name = ?", ("uy_quyen_dong", "dvt")).fetchone():
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

    @property
    def duoc_xoa(self):
        """Quản lý luôn được xóa hợp đồng; nhân viên chỉ khi được quản lý cấp quyền."""
        return self.ql or (bool(self.user) and bool(self.user["duoc_xoa"]))

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

def _svg(than):
    return f'<svg viewBox="0 0 48 48" aria-hidden="true">{than}</svg>'


_DONG = '<rect x="{x}" y="{y}" width="{w}" height="3" rx="1.5" fill="#fff"/>'
ICON = {k: _svg(v) for k, v in {
    "hop_dong": '<rect x="9" y="5" width="26" height="36" rx="4" fill="#8f4f86"/><path d="M27 5h4a4 4 0 0 1 4 4v4h-8z" fill="#1fc7b0"/>'
                + _DONG.format(x=14, y=18, w=16) + _DONG.format(x=14, y=25, w=11) + '<circle cx="33" cy="35" r="8" fill="#f58220"/>'
                '<path d="M29.5 35l2.5 2.5 4.5-5" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
    "bao_gia": '<path d="M6 22 22 6h16a4 4 0 0 1 4 4v16L26 42a4 4 0 0 1-5.6 0L6 27.6a4 4 0 0 1 0-5.6z" fill="#1fc7b0"/>'
               '<path d="M22 6h16a4 4 0 0 1 4 4v16z" fill="#fbb945"/><circle cx="33" cy="15" r="4" fill="#fff"/>'
               '<path d="M14 26l8 8M19 21l8 8" stroke="#1d5b79" stroke-width="3.2" stroke-linecap="round"/>',
    "tong_quan": '<rect x="6" y="6" width="20" height="20" rx="4" fill="#8f4f86"/><rect x="30" y="6" width="12" height="9" rx="3" fill="#f98b8b"/>'
                 '<rect x="30" y="18" width="12" height="8" rx="3" fill="#f58220"/><rect x="6" y="30" width="14" height="12" rx="3" fill="#2ea8f5"/>'
                 '<rect x="24" y="30" width="18" height="12" rx="3" fill="#1fc7b0"/>',
    "ds_hd": '<rect x="14" y="6" width="26" height="30" rx="4" fill="#fbb945"/><rect x="8" y="12" width="26" height="30" rx="4" fill="#2ea8f5"/>'
             + _DONG.format(x=13, y=20, w=16) + _DONG.format(x=13, y=27, w=16) + _DONG.format(x=13, y=34, w=9),
    "hdnt": '<rect x="7" y="8" width="28" height="34" rx="4" fill="#1fc7b0"/>' + _DONG.format(x=12, y=16, w=14) + _DONG.format(x=12, y=23, w=10)
            + '<path d="M22 36l3-9L38 8l6 4-13 19z" fill="#1d5b79"/><path d="M22 36l3-9 6 4z" fill="#fbb945"/>',
    "khach": '<rect x="10" y="12" width="34" height="30" rx="5" fill="#f98b8b"/><rect x="5" y="7" width="34" height="30" rx="5" fill="#1d7a6b"/>'
             '<circle cx="22" cy="18" r="5.5" fill="#fff"/><path d="M12 33a10 8 0 0 1 20 0z" fill="#fff"/>',
    "mau": '<rect x="6" y="6" width="36" height="36" rx="5" fill="#2ea8f5"/><rect x="11" y="11" width="26" height="8" rx="2" fill="#fff"/>'
           '<rect x="11" y="23" width="11" height="14" rx="2" fill="#fbb945"/><rect x="26" y="23" width="11" height="6" rx="2" fill="#fff"/>'
           '<rect x="26" y="31" width="11" height="6" rx="2" fill="#fff"/>',
    "ds_bg": '<rect x="6" y="7" width="36" height="34" rx="5" fill="#8f4f86"/>'
             + "".join(f'<circle cx="14" cy="{y + 1.5}" r="2.5" fill="{m}"/>' + _DONG.format(x=20, y=y, w=17)
                       for y, m in ((15, "#1fc7b0"), (22.5, "#fbb945"), (30, "#f98b8b"))),
    "soan": '<rect x="8" y="6" width="26" height="34" rx="4" fill="#fbb945"/>' + _DONG.format(x=13, y=14, w=16) + _DONG.format(x=13, y=21, w=11)
            + '<circle cx="33" cy="33" r="10" fill="#f58220"/><path d="M33 28v10M28 33h10" stroke="#fff" stroke-width="3" stroke-linecap="round"/>',
    "hang_hoa": '<path d="M24 5l17 9.5v19L24 43 7 33.5v-19z" fill="#f58220"/><path d="M24 24l17-9.5v19L24 43z" fill="#8f4f86"/>'
                '<path d="M24 24L7 14.5v19L24 43z" fill="#fbb945"/>',
    "nguoi_dung": '<circle cx="17" cy="16" r="7" fill="#f98b8b"/><path d="M5 40a12 12 0 0 1 24 0z" fill="#f98b8b"/>'
                  '<circle cx="32" cy="18" r="6" fill="#8f4f86"/><path d="M21 40a11 11 0 0 1 22 0z" fill="#8f4f86"/>',
}.items()}
ICON["chat"] = _svg('<path d="M6 10a5 5 0 0 1 5-5h20a5 5 0 0 1 5 5v13a5 5 0 0 1-5 5H17l-8 7v-7.5A5 5 0 0 1 6 23z" fill="#2ea8f5"/>'
                   '<path d="M24 20a4 4 0 0 1 4-4h11a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4v6l-7-6h-4a4 4 0 0 1-4-4z" fill="#1fc7b0"/>'
                   + "".join(f'<circle cx="{x}" cy="16.5" r="2.2" fill="#fff"/>' for x in (14, 21)))
ICON_LUOI = ('<svg viewBox="0 0 18 18" aria-hidden="true">'
             + "".join(f'<rect x="{x}" y="{y}" width="4" height="4" rx="1" fill="currentColor"/>' for y in (1, 7, 13) for x in (1, 7, 13)) + '</svg>')

# hai thư mục lớn và các mục con: (đường dẫn, tên, mã mục, icon, chỉ quản lý)
UNG_DUNG = [
    ("hop-dong", "Hợp đồng", "hop_dong", [
        ("/tong-quan", "Tổng quan", "tq", "tong_quan", False), ("/hop-dong", "Danh sách hợp đồng", "hd", "ds_hd", False),
        ("/hdnt/moi", "Làm HĐ nguyên tắc", "hdnt", "hdnt", False), ("/khach-hang", "Khách hàng", "kh", "khach", False),
        ("/mau-hop-dong", "Mẫu hợp đồng", "mau", "mau", True)]),
    ("bao-gia", "Báo giá", "bao_gia", [
        ("/bao-gia", "Danh sách báo giá", "bg", "ds_bg", False), ("/bao-gia/moi", "Soạn báo giá", "bgm", "soan", False),
        ("/bao-gia/nhanh", "Soạn bằng chat", "bgn", "chat", False),
        ("/hang-hoa", "Hàng hóa", "hh", "hang_hoa", False)]),
]


def o_icon(url, nhan, icon, lon=False):
    return (f'<a class="o-app{" lon" if lon else ""}" href="{url}"><span class="hinh">{ICON[icon]}</span>'
            f'<span class="ten">{e(nhan)}</span></a>')


def trang_chu(c):
    o_ = "".join(o_icon(f"/muc/{ma}", ten, icon, True) for ma, ten, icon, _ in UNG_DUNG)
    if c.ql:
        o_ += o_icon("/nguoi-dung", "Người dùng", "nguoi_dung", True)
    return trang(c, "Trang chủ", f'<div class="luoi-app">{o_}</div>')


def trang_muc(c, ma):
    ten, _, cac_muc = next((t, i, m) for k, t, i, m in UNG_DUNG if k == ma)
    o_ = "".join(o_icon(u, t, icon) for u, t, _, icon, chi_ql in cac_muc if c.ql or not chi_ql)
    return trang(c, ten, f'<h1>{e(ten)}</h1><div class="luoi-app">{o_}</div>', "muc:" + ma)


def trang(c, tieu_de, than, muc=""):
    nav = ""
    if c.user:
        ud = next((u for u in UNG_DUNG if muc == "muc:" + u[0] or any(m[2] == muc for m in u[3])), None)
        lk, ten_muc = "", ""
        if ud:
            ten_muc = f'<a class="ten-muc" href="/muc/{ud[0]}">{e(ud[1])}</a>'
            lk = "".join(f'<a href="{u}"{" class=chon" if m == muc else ""}>{t}</a>'
                         for u, t, m, _, chi_ql in ud[3] if c.ql or not chi_ql)
            if muc.startswith("muc:"):                   # trang thư mục đã có các ô icon, không lặp lại menu
                lk = ""
        elif muc == "nd":
            ten_muc = '<a class="ten-muc" href="/nguoi-dung">Người dùng</a>'
        nav = (f'<header><div class="khung dau"><a class="ten-app" href="/" title="Trang chủ" aria-label="Trang chủ">{ICON_LUOI}</a>'
               f'{ten_muc}<nav>{lk}</nav>'
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


QUYEN_XOA = [("0", "Không được xóa"), ("1", "Được xóa hợp đồng mình phụ trách")]


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
        uid = c.db.them("INSERT INTO nguoi_dung (ten_dang_nhap, ho_ten, mat_khau, muoi, vai_tro, email, duoc_xoa) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (ten, ho_ten, bam(mk, muoi), muoi, vai_tro, email, 1 if c.form.get("duoc_xoa") == "1" else 0))
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
                 f'<td>{e(dict(VAI_TRO)[u["vai_tro"]])}</td>'
                 f'<td>{"Có" if u["vai_tro"] == "quan_ly" or u["duoc_xoa"] else "<span class=mo>Không</span>"}</td>'
                 f'<td class="so">{u["n"]}</td>'
                 f'<td>{"Đang dùng" if u["hoat_dong"] else "<span class=mo>Đã khóa</span>"}</td>'
                 f'<td class="thao-tac"><a href="/nguoi-dung/{u["id"]}/sua">Sửa</a>'
                 f'<a href="/nguoi-dung/{u["id"]}/mat-khau">Đặt lại mật khẩu</a>{khoa}</td></tr>')
    return trang(c, "Người dùng", f"""
      <h1>Người dùng</h1>
      <div class="the cuon"><table><thead><tr><th>Họ tên</th><th>Tên đăng nhập</th><th>Email</th><th>Vai trò</th><th>Xóa hợp đồng</th>
        <th class="so">Hợp đồng</th><th>Tình trạng</th><th></th></tr></thead><tbody>{dong}</tbody></table></div>
      <div class="the"><h2>Thêm người dùng</h2>
      <p class="mo">Nhân viên chỉ thấy hợp đồng mình phụ trách. Quản lý thấy tất cả.
        Quản lý luôn xóa được hợp đồng; nhân viên chỉ xóa được hợp đồng mình phụ trách khi được cấp quyền (bấm Sửa).
        Mail cảnh báo hết hạn gửi cho người phụ trách và mọi quản lý có email.</p>
      <form method="post" action="/nguoi-dung" class="luoi">{an_csrf(c)}
        {o("Họ tên", "ho_ten", bat_buoc=True)}
        {o("Email", "email", kieu="email")}
        {o("Tên đăng nhập", "ten_dang_nhap", bat_buoc=True, them='autocomplete="off"')}
        <label>Vai trò{chon("vai_tro", VAI_TRO, "nhan_vien")}</label>
        <label>Quyền xóa hợp đồng{chon("duoc_xoa", QUYEN_XOA, "0")}</label>
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
        dx = u["duoc_xoa"] if chinh_minh else (1 if c.form.get("duoc_xoa") == "1" else 0)
        c.db.execute("UPDATE nguoi_dung SET ho_ten = ?, email = ?, vai_tro = ?, duoc_xoa = ? WHERE id = ?",
                     (c.chu("ho_ten", "Họ tên", True, 100), doc_email(c), vt, dx, uid))
        c.db.commit()
        return Chuyen("/nguoi-dung", "Đã lưu.")
    o_vt = "" if chinh_minh else (
        f'<label>Vai trò{chon("vai_tro", VAI_TRO, u["vai_tro"])}</label>'
        f'<label>Quyền xóa hợp đồng (quản lý thì luôn được xóa){chon("duoc_xoa", QUYEN_XOA, 1 if u["duoc_xoa"] else 0)}</label>')
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
            + o("Nhân viên bán hàng", "nhan_vien_bh", g("nhan_vien_bh"))
            + o("Số ngày được nợ", "han_no", 30 if not k or k["han_no"] is None else k["han_no"], "number", them='min="0" step="1"')
            + o("Ghi chú", "ghi_chu", g("ghi_chu")))


def luu_han_no(c, ten):
    """Số ngày được nợ lưu riêng (không nằm trong COT_KHACH vì file nhập khách không có cột này)."""
    hn = int(c.so("han_no", "Số ngày được nợ")) if (c.form.get("han_no") or "").strip() else 30
    c.db.execute("UPDATE khach_hang SET han_no = ? WHERE ten = ?", (hn, ten))


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
    luu_han_no(c, c.chu("ten", "Tên khách hàng", True, 300))
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
        luu_han_no(c, c.chu("ten", "Tên khách hàng", True, 300))
        c.db.commit()
        return Chuyen("/khach-hang", "Đã lưu.")
    n = c.db.execute("SELECT COUNT(*) AS n FROM hop_dong WHERE khach_hang_id = ?", (kid,)).fetchone()["n"]
    xoa = ""
    if c.ql and n == 0:
        xoa = nut_xoa(c, f"/khach-hang/{kid}/xoa", f"Xóa khách hàng {k['ten']}?", "Xóa khách hàng")
    return trang(c, k["ten"], f"""
      <div class="dau-trang"><h1>{e(k["ten"])}</h1><a class="nut" href="/hdnt/moi?kh={kid}">Làm HĐ nguyên tắc</a></div>
      <p class="mo"><a href="/hop-dong?kh={kid}">{n} hợp đồng</a> · <a href="/don-hang?kh={kid}">Đơn hàng</a>
        · <a href="/cong-no/{kid}">Công nợ</a></p>
      <div class="the"><form method="post" class="luoi">{an_csrf(c)}{o_khach(k)}
        <div class="hang-nut"><button class="nut">Lưu</button><a href="/khach-hang">Hủy</a></div></form></div>{xoa}""", "kh")


def khach_hang_xoa(c, kid):
    if c.db.execute("SELECT 1 FROM hop_dong WHERE khach_hang_id = ?", (kid,)).fetchone():
        raise Loi(400, "Khách hàng đã có hợp đồng nên không xóa được.")
    if (c.db.execute("SELECT 1 FROM don_hang WHERE khach_hang_id = ?", (kid,)).fetchone()
            or c.db.execute("SELECT 1 FROM thu_tien WHERE khach_hang_id = ?", (kid,)).fetchone()):
        raise Loi(400, "Khách hàng đã có đơn hàng hoặc phiếu thu nên không xóa được.")
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


def hoi_xoa_hd(h):
    if h["loai"] == "nguyen_tac":
        return f"Xóa hợp đồng nguyên tắc {h['so_hd']} của {h['khach']}? Không khôi phục được."
    return f"Xóa hợp đồng {h['so_hd']} cùng mọi mã hàng, phụ lục và lịch sử giao hàng? Không khôi phục được."


def bang_hd(ds, c=None):
    """c: truyền vào ở trang danh sách để có cột nút Xóa (chỉ hiện với người được xóa)."""
    co_xoa = bool(c) and c.duoc_xoa
    dong = ""
    for h in ds:
        xoa = (f'<td class="thao-tac">' + nut_xoa(c, f'/hop-dong/{h["id"]}/xoa', hoi_xoa_hd(h)) + '</td>') if co_xoa else ""
        pt = phan_tram(h)
        if h["loai"] == "nguyen_tac":
            gt_td = '<td class="so mo">—</td><td class="mo">theo đơn hàng</td>'
        else:
            gt_td = (f'<td class="so">{tien(h["gia_tri"])}</td>'
                     f'<td><progress max="100" value="{pt}"></progress> <span class="mo">{pt}%</span></td>')
        dong += (f'<tr><td><a href="/hop-dong/{h["id"]}"><b>{e(h["so_hd"])}</b></a></td><td>{e(h["khach"])}</td>'
                 f'<td>{ngay(h["het_han"])}</td>{gt_td}'
                 f'<td>{e(h["phu_trach"] or "—")}</td><td>{nhan_hd(h)}</td>{xoa}</tr>')
    return ('<div class="the cuon"><table><thead><tr><th>Số hợp đồng</th><th>Khách hàng</th><th>Hết hạn</th>'
            '<th class="so">Giá trị (đ)</th><th>Đã giao</th><th>Phụ trách</th><th>Tình trạng</th>' + ('<th></th>' if co_xoa else '') + '</tr></thead>'
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
    bang = bang_hd(ds, c) if ds else '<div class="the trong">Không có hợp đồng nào khớp.</div>'
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
    if not c.duoc_xoa:
        raise Loi(403, "Bạn chưa được cấp quyền xóa hợp đồng. Hãy nhờ quản lý cấp quyền ở mục Người dùng.")
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

    xoa_hd = nut_xoa(c, f"{url}/xoa", hoi_xoa_hd(h), "Xóa hợp đồng") if c.duoc_xoa else ""
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
        mo_gg = (f'<a class="nut" href="{e(h["link_file"])}" target="_blank" rel="noopener noreferrer">Mở Google Docs</a>'
                 if h["link_file"].startswith("https://docs.google.com/") else "")
        tao_gg = (f'<form method="post" action="{url}/google-doc" class="trong-dong">{an_csrf(c)}'
                  f'<button class="nut phu">{"Tạo lại link" if mo_gg else "Tạo link Google Docs"}</button></form>'
                  if da_ket_noi(c) else "")
        return trang(c, h["so_hd"], f"""
      <div class="dau-trang"><h1>{e(h["so_hd"])} {nhan_hd(h)}</h1><div class="hang-nut">{mo_gg}{tao_gg}
        <a class="nut phu" href="{url}/tai-hdnt"{tu_tai}>Tải file Word</a><a class="nut phu" href="{url}/sua">Sửa</a></div></div>
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


def doc_xlsx(data, moi_trang=False):
    """Đọc trang tính đầu tiên của file .xlsx thành danh sách hàng (chỉ dùng thư viện có sẵn).
    moi_trang=True: trả về danh sách (tên trang tính, các hàng) của mọi trang tính."""
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
    dich = {}
    for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
        t = r.get("Target").lstrip("/")
        dich[r.get("Id")] = t if t.startswith("xl/") else "xl/" + t
    cac_trang = [(sh.get("name") or "", dich.get(sh.get(rns + "id"), "xl/worksheets/sheet1.xml")) for sh in so.iter(ns + "sheet")]
    if not cac_trang:
        raise ValueError("file không có trang tính")
    if moi_trang:
        return [(ten, _doc_trang(z, duong, chung, ns)) for ten, duong in cac_trang]
    return _doc_trang(z, cac_trang[0][1], chung, ns)


def _doc_trang(z, duong, chung, ns):
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


def doc_cd(c, khoa, mac_dinh=""):
    r = c.db.execute("SELECT gia_tri FROM cai_dat WHERE khoa = ?", (khoa,)).fetchone()
    return r["gia_tri"] if r else mac_dinh


def ghi_cd(c, khoa, gia_tri):
    c.db.execute("DELETE FROM cai_dat WHERE khoa = ?", (khoa,))
    c.db.execute("INSERT INTO cai_dat (khoa, gia_tri) VALUES (?, ?)", (khoa, gia_tri))


def da_ket_noi(c):
    """Đã kết nối Google = đã lưu link Apps Script và lần thử kết nối thành công."""
    return bool(doc_cd(c, "gas_url") and doc_cd(c, "gas_tai_khoan"))


GAS_RE = re.compile(r"https://script\.google\.com/(?:a/macros/[\w.-]+/|macros/)s/[\w-]+/exec")
QUYEN_LINK = [("xem", "Ai có link đều xem được"), ("sua", "Ai có link đều sửa được"), ("rieng", "Chỉ tài khoản Google của tôi")]


def goi_google(c, viec, gas_url=None, **them):
    """Gọi Apps Script chạy bằng tài khoản Google của người dùng (xem ket_noi_google.gs).
    gas_url: link /exec cần thử (chưa lưu); các tham số khác (kể cả `url` của file mẫu) gửi nguyên cho script."""
    url, khoa = gas_url or doc_cd(c, "gas_url"), doc_cd(c, "gas_khoa")
    if not url:
        raise Loi(400, "Chưa kết nối Google. Quản lý vào mục Mẫu HĐ để kết nối.")
    rq = urllib.request.Request(url, data=json.dumps({"khoa": khoa, "viec": viec, **them}).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(rq, timeout=50) as r:
            raw = r.read()
    except urllib.error.HTTPError as loi:
        if loi.code in (401, 403):
            raise Loi(502, f"Google từ chối (lỗi {loi.code}): bản triển khai Apps Script chưa mở cho app gọi. Trong Apps Script "
                           "bấm Triển khai → Quản lý các lần triển khai → biểu tượng bút chì, chọn Người có quyền truy cập: "
                           "\"Bất kỳ ai\" (không phải \"Bất kỳ ai có Tài khoản Google\"), Phiên bản: Phiên bản mới, rồi bấm "
                           "Triển khai. Link /exec giữ nguyên, quay lại đây bấm Lưu và thử kết nối.")
        if loi.code == 404:
            raise Loi(502, "Google báo không tìm thấy (lỗi 404): link /exec sai hoặc bản triển khai đã bị lưu trữ.")
        raise Loi(502, f"Google trả lỗi {loi.code}. Kiểm tra lại link triển khai Apps Script.")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise Loi(502, "Không kết nối được Google Apps Script. Thử lại sau ít phút.")
    try:
        kq = json.loads(raw)
    except ValueError:
        # Google trả trang HTML báo lỗi: lấy câu báo lỗi để người dùng biết cần sửa gì
        chu = raw.decode("utf-8", "replace")
        chu = re.sub(r"<(script|style)\b.*?</\1>", " ", chu, flags=re.S | re.I)
        chu = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", chu))).strip()
        if "doPost" in chu:
            raise Loi(502, "Google báo: bản triển khai không có hàm doPost, tức là đoạn mã của app chưa được lưu trước khi "
                           "triển khai. Trong Apps Script: dán đoạn mã từ trang này, bấm Lưu (biểu tượng đĩa), rồi Triển khai → "
                           "Quản lý các lần triển khai → bút chì → Phiên bản: Phiên bản mới → Triển khai. Link /exec giữ nguyên.")
        if "accounts.google.com" in raw.decode("utf-8", "replace") or "Đăng nhập" in chu or "Sign in" in chu:
            raise Loi(502, "Google đòi đăng nhập: bản triển khai đang để Người có quyền truy cập là \"Bất cứ ai có Tài khoản "
                           "Google\". Hãy đổi thành \"Bất kỳ ai\" và triển khai Phiên bản mới.")
        raise Loi(502, "Apps Script không trả về đúng dữ liệu" + (f" (Google báo: {chu[:200]})" if chu else "") +
                       ". Khi triển khai cần chọn: Thực thi với tư cách = Tôi, Người có quyền truy cập = Bất kỳ ai.")
    if not kq.get("ok"):
        raise Loi(400, "Google: " + str(kq.get("loi") or "lỗi không rõ")[:300])
    return kq


def luu_mau(c, ten_tep, dl, nguon=""):
    try:
        co = docx_mau.kiem_tra(dl)
    except ValueError as loi:
        raise Loi(400, str(loi))
    if "ten_kh" not in co:
        raise Loi(400, "Mẫu chưa có chỗ điền tên bên mua: cần ô {ten_kh} hoặc chữ gợi ý [TÊN CÔNG TY] ở phần Bên B.")
    c.db.execute("DELETE FROM tep WHERE ma = 'hdnt'")
    c.db.execute("INSERT INTO tep (ma, ten_tep, noi_dung, cap_nhat, nguoi, nguon) VALUES ('hdnt', ?, ?, ?, ?, ?)",
                 (ten_tep[:200], dl, datetime.now().isoformat(timespec="seconds"), c.user["ho_ten"], nguon))
    c.db.commit()
    return co


def lay_mau_tu_link(c, url):
    if not re.match(r"https://(docs|drive)\.google\.com/", url):
        raise Loi(400, "Hãy dán link Google Docs hoặc Google Drive (bắt đầu bằng https://docs.google.com/ …).")
    kq = goi_google(c, "lay_mau", url=url)
    try:
        dl = base64.b64decode(kq["docx"])
        so_phan = docx_mau.dem_phan(dl)
    except (KeyError, ValueError, zipfile.BadZipFile):
        raise Loi(400, "File ở link không phải văn bản Word / Google Docs.")
    tabs, tab, phan, ten_tab = kq.get("tabs") or [], kq.get("tab") or "", None, ""
    if so_phan > 1:
        ids = [t["id"] for t in tabs]
        if len(ids) != so_phan:
            raise Loi(400, f"Văn bản có {so_phan} phần nhưng {len(ids)} tab nên app không biết lấy tab nào. "
                           "Hãy chép tab mẫu sang một Google Doc riêng rồi dán link Doc đó.")
        phan = ids.index(tab) if tab in ids else 0       # link không ghi tab thì lấy tab đầu như Google Docs
        ten_tab = tabs[phan]["ten"]
    dl = docx_mau.chuan_hoa(dl, phan)
    ten = re.sub(r"\.docx$", "", kq.get("ten") or "Mẫu") + (f" (tab {ten_tab})" if ten_tab else "") + ".docx"
    co = luu_mau(c, ten, dl, url)
    return f"Đã lấy mẫu từ Google{f' (tab {ten_tab})' if ten_tab else ''}. Mẫu có {len(co)}/{len(docx_mau.O_DIEN)} ô điền."


def ma_apps_script(c):
    khoa = doc_cd(c, "gas_khoa")
    if not khoa:
        khoa = secrets.token_urlsafe(24)
        ghi_cd(c, "gas_khoa", khoa)
        c.db.commit()
    with open(os.path.join(HERE, "ket_noi_google.gs"), encoding="utf-8") as f:
        return f.read().replace("__KHOA__", khoa)


def mau_hop_dong(c):
    if c.method == "POST":
        viec = c.form.get("viec", "")
        if viec == "tai_len":
            ten_tep, dl = c.tep.get("tep", ("", b""))
            if not ten_tep.lower().endswith(".docx"):
                raise Loi(400, "Hãy chọn file Word .docx.")
            try:
                phan = 0 if docx_mau.dem_phan(dl) > 1 else None
                dl = docx_mau.chuan_hoa(dl, phan)
            except (zipfile.BadZipFile, KeyError, ValueError):
                raise Loi(400, "File không phải Word .docx hợp lệ.")
            co = luu_mau(c, os.path.basename(ten_tep), dl)
            return Chuyen("/mau-hop-dong", f"Đã lưu mẫu{' (lấy phần đầu của file)' if phan == 0 else ''}. "
                                           f"Mẫu có {len(co)}/{len(docx_mau.O_DIEN)} ô điền.")
        if viec == "lay_link":
            return Chuyen("/mau-hop-dong", lay_mau_tu_link(c, c.chu("url", "Link mẫu", True, 1000)))
        if viec == "cap_nhat_link":
            r, _ = lay_mau(c)
            if not (r and r["nguon"]):
                raise Loi(400, "Mẫu hiện tại không lấy từ link.")
            return Chuyen("/mau-hop-dong", lay_mau_tu_link(c, r["nguon"]))
        if viec == "ket_noi":
            url = c.chu("gas_url", "Link Apps Script", True, 500)
            if not GAS_RE.fullmatch(url):
                raise Loi(400, "Link phải có dạng https://script.google.com/macros/s/…/exec (bước Triển khai → Ứng dụng web).")
            kq = goi_google(c, "thu", gas_url=url)                # thử trước, chạy được mới lưu
            ghi_cd(c, "gas_url", url)
            ghi_cd(c, "gas_tai_khoan", kq.get("tai_khoan") or "")
            c.db.commit()
            return Chuyen("/mau-hop-dong", f"Đã kết nối Google Drive của {kq.get('tai_khoan') or 'bạn'}.")
        if viec == "cai_dat_link":
            q = c.form.get("quyen_link", "")
            if q not in dict(QUYEN_LINK):
                raise Loi(400, "Quyền link không hợp lệ.")
            ghi_cd(c, "quyen_link", q)
            ghi_cd(c, "thu_muc", c.chu("thu_muc", "Thư mục", True, 200))
            c.db.commit()
            return Chuyen("/mau-hop-dong", "Đã lưu cài đặt link hợp đồng.")
        raise Loi(400, "Yêu cầu không hợp lệ.")

    r, dl = lay_mau(c)
    gas_url, tai_khoan = doc_cd(c, "gas_url"), doc_cd(c, "gas_tai_khoan")
    if gas_url and not tai_khoan:                         # link lưu từ bản cũ khi chưa thử được: coi như chưa kết nối
        gas_url = ""
    if r:
        co = docx_mau.kiem_tra(dl)
        thieu = [x for x in docx_mau.O_DIEN if x not in co]
        nguon = ""
        if r["nguon"]:
            nguon = (f'<p>Lấy từ <a href="{e(r["nguon"])}" target="_blank" rel="noopener noreferrer">link Google</a>. '
                     f'Sửa mẫu trên Google Docs xong thì bấm cập nhật.</p>'
                     f'<form method="post">{an_csrf(c)}<input type="hidden" name="viec" value="cap_nhat_link">'
                     f'<button class="nut">Cập nhật lại từ link</button></form>')
        hien = (f'<p>Đang dùng: <b>{e(r["ten_tep"])}</b> · cập nhật {e(r["cap_nhat"].replace("T", " "))} bởi {e(r["nguoi"])}'
                f' · <a href="/mau-hop-dong/tai">Tải mẫu về xem</a></p>' + nguon
                + (f'<p class="mo">Mẫu không có các ô: {", ".join("{" + x + "}" for x in thieu)}.</p>' if thieu else ""))
    else:
        hien = '<p><b>Chưa có mẫu.</b> Dán link Google Docs hoặc tải file .docx ở bên dưới.</p>'
    if gas_url:
        tt_gg = f'<p class="thong-bao">Đã kết nối Google Drive{f" của {e(tai_khoan)}" if tai_khoan else ""}.</p>'
    else:
        tt_gg = '<p class="thong-bao loi">Chưa kết nối Google. Làm 5 bước dưới đây một lần.</p>'
    bang = "".join(f"<tr><td><code>{{{k}}}</code></td><td>{v}</td></tr>" for k, v in O_DIEN_MO_TA)
    return trang(c, "Mẫu hợp đồng", f"""
      <h1>Mẫu hợp đồng nguyên tắc</h1>
      <div class="the"><h2>Mẫu đang dùng</h2>{hien}</div>

      <div class="the"><h2>Lấy mẫu từ link Google Docs</h2>
        <p class="mo">Dán link Google Docs (hoặc link file Word trên Drive). Link có chọn tab (…?tab=t.xxx) thì app lấy đúng tab đó,
        không có thì lấy tab đầu. Chữ gợi ý của mẫu ADM03901 ở phần Bên B ([TÊN CÔNG TY], [Nhập địa chỉ công ty]…), dòng
        "Số: …-HĐNT/…" và "Hôm nay, ngày … tháng … năm …" được tự đổi thành ô điền. Định dạng giữ nguyên. Doc không cần chia sẻ
        công khai.</p>
        <form method="post" class="luoi-1">{an_csrf(c)}<input type="hidden" name="viec" value="lay_link">
          <label>Link mẫu<input type="url" name="url" required placeholder="https://docs.google.com/document/d/…/edit?tab=…"></label>
          <div class="hang-nut"><button class="nut"{"" if gas_url else " disabled"}>Lấy mẫu</button>
          {"" if gas_url else '<span class="mo">Cần kết nối Google trước.</span>'}</div></form></div>

      <div class="the"><h2>Kết nối Google Drive</h2>{tt_gg}
        <p class="mo">Kết nối chạy bằng tài khoản Google của bạn: app đọc được mẫu trong Drive và tạo hợp đồng thành Google Docs
        trong Drive của bạn.</p>
        <ol>
          <li>Mở <a href="https://script.google.com/home/projects/create" target="_blank" rel="noopener noreferrer">script.google.com</a>
            (đăng nhập tài khoản Google chứa mẫu) để tạo dự án mới.</li>
          <li>Xóa hết mã có sẵn, dán đoạn mã dưới đây vào, bấm Lưu.</li>
          <li>Bấm <b>Triển khai → Tùy chọn triển khai mới</b>, loại <b>Ứng dụng web</b>.
            Chọn <b>Thực thi với tư cách: Tôi</b> và <b>Người có quyền truy cập: Bất kỳ ai</b>, bấm Triển khai.</li>
          <li>Google hỏi cấp quyền: chọn tài khoản → Nâng cao → Đi tới dự án → Cho phép.</li>
          <li>Chép <b>URL ứng dụng web</b> (đuôi /exec), dán vào ô dưới đây, bấm Lưu và thử.</li>
        </ol>
        <details><summary>Đoạn mã Apps Script (có khóa riêng của app, không gửi cho người khác)</summary>
          <div class="hang-nut cach-tren"><button type="button" class="nut phu" data-chep="#ma-gas">Chép đoạn mã</button>
          <span class="mo" id="kq-chep"></span></div>
          <pre id="ma-gas">{e(ma_apps_script(c))}</pre></details>
        <form method="post" class="luoi-1 cach-tren">{an_csrf(c)}<input type="hidden" name="viec" value="ket_noi">
          <label>URL ứng dụng web<input type="url" name="gas_url" value="{e(gas_url)}" required
            placeholder="https://script.google.com/macros/s/…/exec"></label>
          <div class="hang-nut"><button class="nut">Lưu và thử kết nối</button></div></form></div>

      <div class="the"><h2>Link hợp đồng tạo ra</h2>
        <form method="post" class="luoi">{an_csrf(c)}<input type="hidden" name="viec" value="cai_dat_link">
          <label>Ai mở được link{chon("quyen_link", QUYEN_LINK, doc_cd(c, "quyen_link", "xem"))}</label>
          {o("Thư mục trong Drive", "thu_muc", doc_cd(c, "thu_muc", "Hợp đồng nguyên tắc"), bat_buoc=True)}
          <div class="hang-nut"><button class="nut phu">Lưu</button></div></form></div>

      <div class="the"><h2>Hoặc tải file Word lên</h2>
        <form method="post" enctype="multipart/form-data" class="luoi-1">{an_csrf(c)}<input type="hidden" name="viec" value="tai_len">
        <label>File mẫu (.docx)<input type="file" name="tep" accept=".docx" required></label>
        <div class="hang-nut"><button class="nut phu">Lưu mẫu</button></div></form></div>

      <div class="the"><h2>Ô điền trong mẫu</h2>
        <p class="mo">Mẫu không theo dạng ADM03901 thì gõ đúng các ô dưới đây (kể cả dấu ngoặc nhọn) vào chỗ cần điền.</p>
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
        if da_ket_noi(c):
            try:
                tao_link_google(c, lay_hd(c, hid))
                return Chuyen(f"/hop-dong/{hid}", f"Đã tạo hợp đồng {so_hd} trên Google Docs.")
            except Loi as loi:                                 # Google lỗi: hợp đồng vẫn lưu, tải bản Word thay thế
                return Chuyen(f"/hop-dong/{hid}?tai=1", f"Đã tạo hợp đồng {so_hd} nhưng chưa tạo được link Google "
                                                        f"({loi.tb}). File Word đang được tải xuống.")
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
      <div class="the"><label for="o-tra-mst"><b>Tra theo mã số thuế</b></label>
        <div class="hang-nut cach-tren"><input type="text" id="o-tra-mst" inputmode="numeric" maxlength="20"
          placeholder="Ví dụ 0104670584" autocomplete="off"><button type="button" class="nut phu" id="nut-tra-mst">Tra cứu</button></div>
        <p class="mo cach-tren" id="kq-tra-mst">App lấy tên và địa chỉ đăng ký thuế rồi điền vào các ô bên dưới. Người đại diện,
        chức vụ, điện thoại, email không có trong dữ liệu thuế: nhập tay một lần, lần sau app nhớ.</p>
        <p class="cach-tren" id="goi-y-mst" hidden>Muốn lấy người đại diện, điện thoại:
        <a id="link-mst" href="https://masothue.com/" target="_blank" rel="noopener noreferrer">mở trang masothue.com của mã này</a>,
        bôi đen bảng thông tin, chép, rồi dán vào ô "Dán thông tin bên mua" ngay dưới và bấm Tự điền.</p></div>
      <details class="the" id="khung-dan"><summary>Dán thông tin bên mua để tự điền</summary>
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
        <div class="hang-nut"><button class="nut"{"" if r_mau else " disabled"}>{"Tạo hợp đồng (Google Docs)" if da_ket_noi(c)
                                                                              else "Tạo hợp đồng và tải file Word"}</button>
        <a href="/hop-dong?loai=nguyen_tac">Hủy</a></div></form></div>""", "hdnt")


MST_RE = re.compile(r"\d{10}(-\d{3})?")


def tra_mst(c):
    """Tra thông tin doanh nghiệp theo mã số thuế: khách đã lưu trong app trước, rồi tới dữ liệu công khai của Cục Thuế
    (qua api.vietqr.io; chỉ có tên, địa chỉ, tình trạng — không có người đại diện, điện thoại)."""
    mst = re.sub(r"[\s.]", "", c.q.get("mst", ""))
    if not MST_RE.fullmatch(mst):
        return Json({"ok": False, "loi": "Mã số thuế phải gồm 10 số, hoặc 10 số-3 số với chi nhánh."})
    kq = {"ok": True, "mst": mst}
    k = c.db.execute("SELECT * FROM khach_hang WHERE REPLACE(ma_so_thue, ' ', '') = ?", (mst,)).fetchone()
    if k:
        kq["khach"] = {ten: k[cot] or "" for ten, cot, _ in O_BEN_MUA}
    try:
        rq = urllib.request.Request("https://api.vietqr.io/v2/business/" + mst, headers={"User-Agent": "hop-dong-app"})
        with urllib.request.urlopen(rq, timeout=12) as r:
            d = json.loads(r.read())
        dn = d.get("data") if isinstance(d, dict) else None
        if isinstance(dn, dict) and dn.get("name"):
            kq["thue"] = {"ten_kh": gon(str(dn.get("name") or ""))[:300], "dia_chi": gon(str(dn.get("address") or ""))[:500],
                          "trang_thai": gon(str(dn.get("status") or ""))[:100]}
        elif not k:
            return Json({"ok": False, "loi": "Không tìm thấy mã số thuế này trong dữ liệu của Cục Thuế. Kiểm tra lại số."})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        if not k:
            return Json({"ok": False, "loi": "Chưa tra được (dịch vụ tra cứu không phản hồi). Thử lại sau hoặc nhập tay."})
    return Json(kq)


def ten_tep_an_toan(s):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", s).strip(" .-")[:150] or "hop-dong"


def tao_file_hdnt(c, h):
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
    return ten_tep_an_toan(f"HĐNT {h['so_hd'].split('-')[0]} - {k['ten']}"), docx_mau.dien(mau, gt)


def tai_hdnt(c, hid):
    ten, dl = tao_file_hdnt(c, lay_hd(c, hid))
    return Tep(ten + ".docx", dl, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def tao_link_google(c, h):
    """Tạo Google Docs của hợp đồng trong Drive, lưu link vào hợp đồng."""
    ten, dl = tao_file_hdnt(c, h)
    kq = goi_google(c, "tao_doc", ten=ten, docx=base64.b64encode(dl).decode(),
                    quyen=doc_cd(c, "quyen_link", "xem"), thu_muc=doc_cd(c, "thu_muc", "Hợp đồng nguyên tắc"))
    url = kq.get("url") or ""
    if not url.startswith("https://docs.google.com/"):
        raise Loi(502, "Google không trả về link hợp đồng.")
    c.db.execute("UPDATE hop_dong SET link_file = ? WHERE id = ?", (url, h["id"]))
    c.db.commit()
    return url


def hd_google(c, hid):
    h = lay_hd(c, hid)
    tao_link_google(c, h)
    return Chuyen(f"/hop-dong/{hid}", "Đã tạo link Google Docs mới cho hợp đồng.")



# ───────────────────────── hàng hóa (danh mục để soạn báo giá) ─────────────────────────

COT_HANG = [("ten", "Tên TTBYT"), ("ten_tm", "Tên thương mại"), ("ma", "Ký mã hiệu"), ("nhan_hieu", "Nhãn hiệu"),
            ("nuoc_sx", "Nước sản xuất"), ("phan_loai", "Phân loại TBYT"), ("hsd", "HSD"), ("quy_cach", "Quy cách")]
COT_GIA = ["gia_ban", "gia_min", "gia_max"]
TIEU_DE_HANG = [
    ("ten_tm", ["ten thuong mai"]),
    ("ten", ["ten ttbyt", "ten trang thiet bi", "ten hang", "ten san pham", "ten vat tu"]),
    ("ma", ["ky ma hieu", "model", "ma hang", "ma san pham", "ma hieu"]),
    ("nhan_hieu", ["nhan hieu"]),
    ("nuoc_sx", ["nuoc san xuat", "xuat xu"]),
    ("phan_loai", ["phan loai"]),
    ("hsd", ["hsd", "han su dung", "han dung", "tuoi tho"]),
    ("quy_cach", ["quy cach"]),
    ("gia_min", ["gia min", "gia thap nhat"]),
    ("gia_max", ["gia max", "gia cao nhat"]),
    ("gia_ban", ["gia ban", "don gia"]),
]


def doc_gia(v):
    """Đọc ô giá: 13230, 13230.0, hay chữ kiểu Việt '13.230' / '13.230,5'."""
    v = re.sub(r"[\s₫đ]", "", str(v or ""))
    if not v:
        return 0.0
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", v):
        v = v.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", v):
        v = v.replace(",", "")
    else:
        v = v.replace(",", ".")
    try:
        x = float(v)
    except ValueError:
        return 0.0
    return x if math.isfinite(x) and x >= 0 else 0.0


def tim_cot_hang(hang):
    """Hàng tiêu đề của bảng hàng hóa trong 30 hàng đầu: (chỉ số hàng, {cột: vị trí}) hoặc None."""
    tot = None
    for i, h in enumerate(hang[:30]):
        cot = {}
        for j, o_ in enumerate(h):
            g = gap(o_)
            if not g or len(g) > 60:
                continue
            for ten, khoa in TIEU_DE_HANG:
                if ten not in cot and any(g == k or g.startswith(k + " ") or g.startswith(k + "(") for k in khoa):
                    cot[ten] = j
                    break
        if ("ten_tm" in cot or "ten" in cot) and (tot is None or len(cot) > len(tot[1])):
            tot = (i, cot)
    return tot


def khoa_hang(h):
    return gap(h["ma"]) or gap(h["ten_tm"]) or gap(h["ten"])


ID_GOOGLE_RE = re.compile(r"/d/([\w-]{20,})|[?&]id=([\w-]{20,})")


def tai_bang_tu_link(c, url):
    """Lấy file Excel của một Google Sheet / file trên Drive: qua Apps Script (file riêng tư), không được thì thử link công khai."""
    m = ID_GOOGLE_RE.search(url)
    if not re.match(r"https://(docs|drive)\.google\.com/", url) or not m:
        raise Loi(400, "Hãy dán link Google Sheet hoặc Google Drive (bắt đầu bằng https://docs.google.com/ …).")
    fid, ban_cu = m.group(1) or m.group(2), False
    if da_ket_noi(c):
        kq = goi_google(c, "lay_mau", url=url)
        try:
            dl = base64.b64decode(kq.get("docx") or "")
        except ValueError:
            dl = b""
        if dl[:2] == b"PK":
            return dl
        ban_cu = kq.get("loai") == "application/vnd.google-apps.spreadsheet"
    for u in (f"https://docs.google.com/spreadsheets/d/{fid}/export?format=xlsx",
              f"https://drive.google.com/uc?export=download&id={fid}"):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "hop-dong-app"}), timeout=30) as r:
                dl = r.read(8_000_000)
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
        if dl[:2] == b"PK":
            return dl
    if ban_cu:
        raise Loi(400, "Đoạn mã Apps Script đang chạy là bản cũ, chưa đọc được Google Sheet. Vào mục Mẫu hợp đồng chép đoạn mã "
                       "mới, dán đè trong Apps Script, bấm Lưu, rồi Triển khai → Quản lý các lần triển khai → bút chì → "
                       "Phiên bản: Phiên bản mới → Triển khai. Link /exec giữ nguyên. Sau đó quay lại bấm Nhập từ link.")
    raise Loi(400, "Không đọc được file ở link. Link cần là Google Sheet hoặc file Excel trên Drive của tài khoản đã kết nối "
                   "với app (mục Mẫu hợp đồng), hoặc được chia sẻ \"Bất kỳ ai có đường liên kết\".")


def nhap_hang(c):
    link_cu = doc_cd(c, "hang_link")
    if c.method == "POST":
        ten_tep, dl = c.tep.get("tep", ("", b""))
        link = c.link("link", "Link Google Sheet")
        if not dl and not link:
            raise Loi(400, "Chưa dán link và chưa chọn file.")
        if not dl:
            dl, ten_tep = tai_bang_tu_link(c, link), "bang-gia.xlsx"
            ghi_cd(c, "hang_link", link)
        try:
            trang_tinh = [("", doc_csv(dl))] if ten_tep.lower().endswith(".csv") else doc_xlsx(dl, moi_trang=True)
        except (zipfile.BadZipFile, KeyError, ET.ParseError, StopIteration, ValueError, IndexError):
            raise Loi(400, "Không đọc được file. Hãy dùng file Excel .xlsx hoặc .csv.")
        # chọn trang tính có bảng giá: nhận ra nhiều cột nhất, ưu tiên trang có cột giá bán và tên "báo giá"
        ung = []
        for ten_trang, hang in trang_tinh:
            kq = tim_cot_hang(hang)
            if kq:
                ung.append((("gia_ban" in kq[1]), ("bao gia" in gap(ten_trang)), len(kq[1]), ten_trang, hang, kq))
        if not ung:
            raise Loi(400, "Không tìm thấy bảng hàng hóa. Hàng tiêu đề cần có cột \"Tên thương mại\" hoặc \"Tên TTBYT\".")
        _, _, _, ten_trang, hang, (dau, cot) = max(ung, key=lambda u: u[:3])
        moi, da_thay, trung = [], set(), 0
        for h in hang[dau + 1:]:
            gt = {ten: gon(h[j]) if j < len(h) else "" for ten, j in cot.items()}
            d = {ten: gt.get(ten, "")[:500] for ten, _ in COT_HANG}
            for g in COT_GIA:
                d[g] = doc_gia(gt.get(g))
            if not (d["ten"] or d["ten_tm"]) or not (d["ma"] or d["gia_ban"]):     # dòng trống, dòng tựa nhóm
                continue
            k = khoa_hang(d)
            if k in da_thay:
                trung += 1
                continue
            da_thay.add(k)
            moi.append(d)
        if not moi:
            raise Loi(400, "Bảng không có dòng hàng nào (mỗi dòng cần tên và ký mã hiệu hoặc giá bán).")
        ten_cot = [t for t, _ in COT_HANG] + COT_GIA
        if c.form.get("thay_het") == "1":
            c.db.execute("DELETE FROM hang_hoa WHERE id NOT IN (SELECT hang_hoa_id FROM don_hang_dong WHERE hang_hoa_id IS NOT NULL) "
                         "AND id NOT IN (SELECT hang_hoa_id FROM phieu_nhap_dong)")
        co = {khoa_hang(r): r["id"] for r in c.db.execute("SELECT * FROM hang_hoa").fetchall()}
        them = [[d[t] for t in ten_cot] for d in moi if khoa_hang(d) not in co]
        sua = [[d[t] for t in ten_cot] + [co[khoa_hang(d)]] for d in moi if khoa_hang(d) in co]
        if them:
            c.db.executemany(f"INSERT INTO hang_hoa ({', '.join(ten_cot)}) VALUES ({', '.join('?' * len(ten_cot))})", them)
        if sua:
            c.db.executemany(f"UPDATE hang_hoa SET {', '.join(t + ' = ?' for t in ten_cot)} WHERE id = ?", sua)
        c.db.commit()
        tb = f"Đã nhập{' từ trang tính ' + ten_trang.strip() if ten_trang.strip() else ''}: thêm {len(them)} hàng mới, cập nhật {len(sua)} hàng đã có"
        return Chuyen("/hang-hoa", tb + (f", bỏ {trung} dòng trùng ký mã hiệu trong file." if trung else "."))
    return trang(c, "Nhập hàng hóa", f"""
      <h1>Nhập danh mục hàng hóa</h1>
      <div class="the"><form method="post" enctype="multipart/form-data" class="luoi-1">{an_csrf(c)}
        <label>Link Google Sheet (hoặc file Excel trên Google Drive)<input type="url" name="link" value="{e(link_cu)}"
          placeholder="https://docs.google.com/spreadsheets/d/…"></label>
        <label>Hoặc chọn file Excel (.xlsx) / .csv từ máy<input type="file" name="tep" accept=".xlsx,.csv"></label>
        <label class="o-tich"><input type="checkbox" name="thay_het" value="1"> Thay toàn bộ danh mục bằng bảng này
          (xóa hàng không còn trong file; báo giá đã soạn không bị ảnh hưởng)</label>
        <div class="hang-nut"><button class="nut">Nhập</button><a href="/hang-hoa">Hủy</a></div></form></div>
      <div class="the"><h2>Bảng cần có</h2>
        <p>Dán link Google Sheet bảng giá rồi bấm Nhập. App đọc sheet bằng tài khoản Google đã kết nối ở mục Mẫu hợp đồng,
        nên sheet không cần chia sẻ công khai. App nhớ link này: khi giá đổi chỉ cần vào đây bấm Nhập lại.</p>
        <p>App tự tìm trang tính có bảng giá (ưu tiên trang tên "BÁO GIÁ") và hàng tiêu đề.</p>
        <p>Các cột nhận theo tiêu đề: Tên TTBYT, Tên thương mại, Ký mã hiệu, Nhãn hiệu, Nước sản xuất, Phân loại TBYT, HSD,
        Quy cách, Giá bán, Giá Min, Giá Max. Cột khác bị bỏ qua.</p>
        <p class="mo">Hàng trùng ký mã hiệu với hàng đã có thì được cập nhật thông tin và giá mới, không tạo dòng thứ hai.</p></div>""", "hh")


def dk_tim_hang(tu):
    """Mỗi từ gõ vào phải có ở tên, tên thương mại, ký mã hiệu hoặc nhãn hiệu."""
    dk, ts = "", []
    for w in tu.split()[:6]:
        dk += " AND (ten LIKE ? OR ten_tm LIKE ? OR ma LIKE ? OR nhan_hieu LIKE ?)"
        ts += [f"%{w}%"] * 4
    return dk, ts


def so_o(x):
    """Số để đặt vào ô nhập kiểu number (trống nếu bằng 0)."""
    if not x:
        return ""
    return str(round(x)) if abs(x - round(x)) < 1e-9 else repr(float(x))


def khoang_gia(h):
    if not (h["gia_min"] or h["gia_max"]):
        return ""
    return f'{tien(h["gia_min"])} – {tien(h["gia_max"])}'


def hang_hoa(c):
    tu, nh = c.q.get("q", ""), c.q.get("nh", "")
    dk, ts = dk_tim_hang(tu)
    if nh:
        dk += " AND nhan_hieu = ?"
        ts.append(nh)
    tong = c.db.execute("SELECT COUNT(*) AS n FROM hang_hoa").fetchone()["n"]
    ds = c.db.execute(f"SELECT * FROM hang_hoa WHERE 1=1{dk} ORDER BY id LIMIT 300", ts).fetchall()
    n = c.db.execute(f"SELECT COUNT(*) AS n FROM hang_hoa WHERE 1=1{dk}", ts).fetchone()["n"]
    cac_nh = [r["nhan_hieu"] for r in c.db.execute(
        "SELECT DISTINCT nhan_hieu FROM hang_hoa WHERE nhan_hieu <> '' ORDER BY nhan_hieu").fetchall()]
    dong = "".join(
        f'<tr><td>{e(h["ten"])}</td><td>{e(h["ten_tm"])}</td><td>{e(h["ma"])}</td><td>{e(h["nhan_hieu"])}</td>'
        f'<td>{e(h["nuoc_sx"])}</td><td>{e(h["phan_loai"])}</td><td>{e(h["hsd"])}</td><td>{e(h["quy_cach"])}</td>'
        f'<td class="so">{tien(h["gia_ban"]) if h["gia_ban"] else ""}</td><td class="so mo">{khoang_gia(h)}</td></tr>' for h in ds)
    if ds:
        bang = ('<div class="the cuon"><table><thead><tr><th>Tên TTBYT</th><th>Tên thương mại</th><th>Ký mã hiệu</th>'
                '<th>Nhãn hiệu</th><th>Nước SX</th><th>Loại</th><th>HSD</th><th>Quy cách</th><th class="so">Giá bán (đ)</th>'
                f'<th class="so">Min – Max</th></tr></thead><tbody>{dong}</tbody></table></div>')
        if n > len(ds):
            bang += f'<p class="mo">Đang hiện {len(ds)} / {n} hàng. Gõ thêm từ để thu hẹp.</p>'
    elif tong:
        bang = '<div class="the trong">Không có hàng nào khớp.</div>'
    else:
        bang = ('<div class="the trong">Chưa có danh mục hàng hóa. '
                + ('Bấm <b>Nhập từ link / Excel</b> để đưa bảng giá vào.' if c.ql else 'Quản lý cần nhập bảng giá.') + '</div>')
    nhap = '<a class="nut phu" href="/hang-hoa/nhap">Nhập từ link / Excel</a>' if c.ql else ""
    return trang(c, "Hàng hóa", f"""
      <div class="dau-trang"><h1>Hàng hóa <span class="dem">{n}</span></h1>{nhap}</div>
      <form class="bo-loc"><input type="search" name="q" value="{e(tu)}" placeholder="Tên, tên thương mại, ký mã hiệu…">
        {chon("nh", [(x, x) for x in cac_nh], nh, "Mọi nhãn hiệu")}
        <button class="nut phu">Lọc</button>{'<a href="/hang-hoa">Bỏ lọc</a>' if c.q else ""}</form>
      {bang}""", "hh")


# ───────────────────────── báo giá ─────────────────────────

TT_BG = [("nhap", "Đang soạn"), ("da_gui", "Đã gửi khách"), ("dong_y", "Khách đồng ý"), ("khong_thanh", "Không thành")]
HIEU_LUC_NGAY = 30           # hiệu lực mặc định của báo giá
SQL_BG = ("SELECT b.*, u.ho_ten AS phu_trach, "
          "(SELECT COUNT(*) FROM bao_gia_dong d WHERE d.bao_gia_id = b.id) AS so_dong, "
          "COALESCE((SELECT SUM(d.so_luong * d.don_gia) FROM bao_gia_dong d WHERE d.bao_gia_id = b.id), 0) AS gia_tri "
          "FROM bao_gia b LEFT JOIN nguoi_dung u ON u.id = b.phu_trach_id WHERE 1=1")


def lay_bg(c, bid):
    b = c.db.execute(SQL_BG + " AND b.id = ?", (bid,)).fetchone()
    if not b:
        raise Loi(404, "Không tìm thấy báo giá.")
    if not c.ql and b["phu_trach_id"] != c.user["id"]:
        raise Loi(403, "Bạn không phụ trách báo giá này.")
    return b


def dong_cua_bg(c, bid):
    return c.db.execute("SELECT * FROM bao_gia_dong WHERE bao_gia_id = ? ORDER BY tt, id", (bid,)).fetchall()


def so_bg_tiep(c, nam):
    """Số báo giá kế tiếp trong năm: BG26001, BG26002…"""
    dau = f"BG{nam % 100:02d}"
    lon = 0
    for r in c.db.execute("SELECT so_bg FROM bao_gia WHERE so_bg LIKE ?", (dau + "%",)).fetchall():
        m = re.fullmatch(re.escape(dau) + r"(\d{3,})", r["so_bg"], re.I)
        if m:
            lon = max(lon, int(m.group(1)))
    return f"{dau}{lon + 1:03d}"


def nhan_bg(b):
    tt = b["trang_thai"]
    if tt == "da_gui":
        if b["hieu_luc_den"] and b["hieu_luc_den"] < date.today().isoformat():
            return '<span class="nhan do">Hết hiệu lực</span>'
        return '<span class="nhan vang">Đã gửi khách</span>'
    mau = {"dong_y": "xanh"}.get(tt, "xam")
    return f'<span class="nhan {mau}">{e(dict(TT_BG).get(tt, ""))}</span>'


def ds_bao_gia(c):
    dk, ts = loc_quyen(c)
    tu, tt, pt = c.q.get("q", ""), c.q.get("tt", ""), c.q.get("pt", "")
    if tu:
        dk += (" AND (b.so_bg LIKE ? OR b.ten_kh LIKE ? OR b.id IN "
               "(SELECT bao_gia_id FROM bao_gia_dong WHERE ma LIKE ? OR ten_tm LIKE ? OR ten LIKE ?))")
        ts += [f"%{tu}%"] * 5
    if tt in dict(TT_BG):
        dk += " AND b.trang_thai = ?"
        ts.append(tt)
    if pt.isdigit() and c.ql:
        dk += " AND b.phu_trach_id = ?"
        ts.append(int(pt))
    ds = c.db.execute(SQL_BG + dk + " ORDER BY b.ngay DESC, b.id DESC", ts).fetchall()
    loc_pt = ""
    if c.ql:
        nd = c.db.execute("SELECT id, ho_ten FROM nguoi_dung ORDER BY ho_ten").fetchall()
        loc_pt = chon("pt", [(u["id"], u["ho_ten"]) for u in nd], pt, "Mọi người phụ trách")
    dong = ""
    for b in ds:
        xoa = ('<td class="thao-tac">' + nut_xoa(c, f'/bao-gia/{b["id"]}/xoa', f"Xóa báo giá {b['so_bg']}? Không khôi phục được.")
               + '</td>') if c.duoc_xoa else ""
        link = f' <a href="{e(b["link_file"])}" target="_blank" rel="noopener noreferrer">Docs</a>' if b["link_file"] else ""
        dong += (f'<tr><td><a href="/bao-gia/{b["id"]}"><b>{e(b["so_bg"])}</b></a>{link}</td><td>{ngay(b["ngay"])}</td>'
                 f'<td>{e(b["ten_kh"] or "—")}</td><td class="so">{b["so_dong"]}</td>'
                 f'<td class="so">{tien(b["gia_tri"]) if b["gia_tri"] else "—"}</td><td>{ngay(b["hieu_luc_den"])}</td>'
                 f'<td>{e(b["phu_trach"] or "—")}</td><td>{nhan_bg(b)}</td>{xoa}</tr>')
    if ds:
        bang = ('<div class="the cuon"><table><thead><tr><th>Số báo giá</th><th>Ngày</th><th>Khách hàng</th>'
                '<th class="so">Mặt hàng</th><th class="so">Giá trị (đ)</th><th>Hiệu lực đến</th><th>Phụ trách</th>'
                '<th>Tình trạng</th>' + ('<th></th>' if c.duoc_xoa else '') + f'</tr></thead><tbody>{dong}</tbody></table></div>')
    else:
        bang = f'<div class="the trong">{"Không có báo giá nào khớp." if c.q else "Chưa có báo giá nào. Bấm Soạn báo giá để bắt đầu."}</div>'
    return trang(c, "Báo giá", f"""
      <div class="dau-trang"><h1>Báo giá <span class="dem">{len(ds)}</span></h1><div class="hang-nut"><a class="nut" href="/bao-gia/nhanh">Soạn bằng chat</a><a class="nut phu" href="/bao-gia/moi">Soạn báo giá</a></div></div>
      <form class="bo-loc"><input type="search" name="q" value="{e(tu)}" placeholder="Số báo giá, khách, mã hàng…">
        {chon("tt", TT_BG, tt, "Mọi tình trạng")}{loc_pt}
        <button class="nut phu">Lọc</button>{'<a href="/bao-gia">Bỏ lọc</a>' if c.q else ""}</form>
      {bang}""", "bg")


def o_dau_bg(c, b=None):
    """Các ô thông tin chung của báo giá (dùng cho trang soạn mới và trang sửa)."""
    hom_nay = date.today()
    g = (lambda k, md="": b[k] if b else md)
    kh = "".join(f'<option value="{e(r["ten"])}">' for r in c.db.execute("SELECT ten FROM khach_hang ORDER BY ten").fetchall())
    pt = ""
    if c.ql:
        nd = c.db.execute("SELECT id, ho_ten FROM nguoi_dung WHERE hoat_dong = 1 ORDER BY ho_ten").fetchall()
        pt = f'<label>Người phụ trách{chon("phu_trach_id", [(u["id"], u["ho_ten"]) for u in nd], g("phu_trach_id", c.user["id"]))}</label>'
    tt = f'<label>Tình trạng{chon("trang_thai", TT_BG, b["trang_thai"])}</label>' if b else ""
    return f"""
      {o("Số báo giá", "so_bg", g("so_bg", so_bg_tiep(c, hom_nay.year)), bat_buoc=True)}
      {o("Ngày báo giá", "ngay", g("ngay", hom_nay.isoformat()), "date", True)}
      <label class="rong">Kính gửi (tên khách hàng)<input name="ten_kh" value="{e(g("ten_kh"))}" list="ds-khach"
        placeholder="Để trống thì ghi: Quý Khách hàng"></label><datalist id="ds-khach">{kh}</datalist>
      {o("Hiệu lực đến ngày", "hieu_luc_den", g("hieu_luc_den", (hom_nay + timedelta(days=HIEU_LUC_NGAY)).isoformat()), "date")}
      {pt}{tt}
      <label class="rong">Ghi chú in dưới bảng giá (thuế VAT, giao hàng, thanh toán…)
        <textarea name="ghi_chu" rows="2">{e(g("ghi_chu"))}</textarea></label>"""


def doc_dau_bg(c, b=None):
    gt = {"so_bg": c.chu("so_bg", "Số báo giá", True, 60), "ngay": c.ngay("ngay", "Ngày báo giá", True),
          "ten_kh": c.chu("ten_kh", "Tên khách hàng", toi_da=300), "hieu_luc_den": c.ngay("hieu_luc_den", "Hiệu lực đến ngày"),
          "ghi_chu": c.chu("ghi_chu", "Ghi chú", toi_da=1000)}
    if gt["hieu_luc_den"] and gt["hieu_luc_den"] < gt["ngay"]:
        raise Loi(400, "Ngày hết hiệu lực phải sau ngày báo giá.")
    gt["phu_trach_id"] = b["phu_trach_id"] if b else c.user["id"]
    if c.ql:
        v = c.form.get("phu_trach_id", "")
        if not (v.isdigit() and c.db.execute("SELECT 1 FROM nguoi_dung WHERE id = ?", (v,)).fetchone()):
            raise Loi(400, "Chưa chọn người phụ trách.")
        gt["phu_trach_id"] = int(v)
    if b:
        gt["trang_thai"] = c.form.get("trang_thai") if c.form.get("trang_thai") in dict(TT_BG) else b["trang_thai"]
    trung = c.db.execute("SELECT id FROM bao_gia WHERE so_bg = ?", (gt["so_bg"],)).fetchone()
    if trung and (not b or trung["id"] != b["id"]):
        raise Loi(400, f"Số báo giá {gt['so_bg']} đã có. Hãy đổi số khác.")
    return gt


def bg_moi(c):
    if c.method == "POST":
        gt = doc_dau_bg(c)
        try:
            bid = c.db.them(f"INSERT INTO bao_gia ({', '.join(gt)}, tao_luc) VALUES ({'?, ' * len(gt)}?)",
                            list(gt.values()) + [datetime.now().isoformat(timespec="seconds")])
        except LOI_TRUNG:
            c.db.rollback()
            raise Loi(400, f"Số báo giá {gt['so_bg']} đã có. Hãy đổi số khác.")
        c.db.commit()
        return Chuyen(f"/bao-gia/{bid}", "Đã tạo báo giá. Tìm và chọn hàng ở mục Thêm hàng bên dưới.")
    return trang(c, "Soạn báo giá", f"""
      <h1>Soạn báo giá</h1>
      <div class="the"><form method="post" class="luoi">{an_csrf(c)}{o_dau_bg(c)}
        <div class="hang-nut"><button class="nut">Tạo và chọn hàng</button><a href="/bao-gia">Hủy</a></div></form></div>""", "bgm")


def bg_sua(c, bid):
    b = lay_bg(c, bid)
    gt = doc_dau_bg(c, b)
    c.db.execute(f"UPDATE bao_gia SET {', '.join(k + ' = ?' for k in gt)} WHERE id = ?", list(gt.values()) + [bid])
    c.db.commit()
    return Chuyen(f"/bao-gia/{bid}", "Đã lưu thông tin báo giá.")


def bg_xoa(c, bid):
    b = lay_bg(c, bid)
    if not c.duoc_xoa:
        raise Loi(403, "Bạn chưa được cấp quyền xóa. Hãy nhờ quản lý.")
    c.db.execute("DELETE FROM bao_gia_dong WHERE bao_gia_id = ?", (bid,))
    c.db.execute("DELETE FROM bao_gia WHERE id = ?", (bid,))
    c.db.commit()
    return Chuyen("/bao-gia", f"Đã xóa báo giá {b['so_bg']}.")


def bg_xem(c, bid):
    b = lay_bg(c, bid)
    dong = dong_cua_bg(c, bid)
    tim = c.q.get("tim", "")
    # bảng các dòng hàng: sửa số lượng, đơn giá ngay trong bảng
    hang = ""
    for i, d in enumerate(dong, 1):
        canh = ""
        if d["gia_min"] and d["don_gia"] < d["gia_min"]:
            canh = ' <span class="nhan do">dưới giá Min</span>'
        elif d["gia_max"] and d["don_gia"] > d["gia_max"]:
            canh = ' <span class="nhan vang">trên giá Max</span>'
        tt_ = f'{tien(d["so_luong"] * d["don_gia"])}' if d["so_luong"] else ""
        hang += (f'<tr><td class="so">{i}</td><td>{e(d["ten"])}<br><span class="mo">{e(d["ten_tm"])}</span></td>'
                 f'<td>{e(d["ma"])}</td><td>{e(d["nhan_hieu"])}</td><td>{e(d["quy_cach"])}</td>'
                 f'<td class="so"><input class="o-nho" type="number" min="0" step="any" name="sl_{d["id"]}" '
                 f'value="{so_o(d["so_luong"])}" aria-label="Số lượng"></td>'
                 f'<td class="so"><input class="o-nho" type="number" min="0" step="any" name="gia_{d["id"]}" '
                 f'value="{so_o(d["don_gia"])}" aria-label="Đơn giá"></td>'
                 f'<td class="so">{tt_}</td><td class="mo">{khoang_gia(d)}{canh}</td>'
                 f'<td class="thao-tac"><button class="nut-chu nguy" name="xoa" value="{d["id"]}">Bỏ</button></td></tr>')
    if dong:
        tong = sum(d["so_luong"] * d["don_gia"] for d in dong)
        chan = (f'<tr><td colspan="7" class="so"><b>Tổng cộng</b></td><td class="so"><b>{tien(tong)}</b></td><td colspan="2"></td></tr>'
                if tong else "")
        bang = (f'<form method="post" action="/bao-gia/{bid}/dong">{an_csrf(c)}<button class="nut-an" tabindex="-1" aria-hidden="true"></button><div class="cuon"><table><thead><tr><th class="so">STT</th>'
                '<th>Tên TTBYT / tên thương mại</th><th>Ký mã hiệu</th><th>Nhãn hiệu</th><th>Quy cách</th><th class="so">Số lượng</th>'
                '<th class="so">Đơn giá (đ)</th><th class="so">Thành tiền</th><th>Giá Min – Max</th><th></th></tr></thead>'
                f'<tbody>{hang}{chan}</tbody></table></div>'
                '<div class="hang-nut"><button class="nut">Lưu số lượng và giá</button>'
                '<span class="mo">Số lượng để trống thì báo giá chỉ ghi đơn giá, không có cột thành tiền.</span></div></form>')
    else:
        bang = '<p class="mo">Chưa có hàng nào. Tìm hàng ở mục Thêm hàng bên dưới.</p>'
    # tìm hàng trong danh mục để thêm
    kq_tim = ""
    if tim:
        dk, ts = dk_tim_hang(tim)
        ds = c.db.execute(f"SELECT * FROM hang_hoa WHERE 1=1{dk} ORDER BY id LIMIT 80", ts).fetchall()
        da_co = {gap(d["ma"]) for d in dong if d["ma"]}
        if ds:
            dh = "".join(
                f'<tr><td><input type="checkbox" name="hh_{h["id"]}" value="1" aria-label="Chọn"></td><td>{e(h["ten"])}</td>'
                f'<td>{e(h["ten_tm"])}</td><td>{e(h["ma"])}{" <span class=mo>(đã có)</span>" if gap(h["ma"]) in da_co else ""}</td>'
                f'<td>{e(h["nhan_hieu"])}</td><td>{e(h["quy_cach"])}</td><td class="so">{tien(h["gia_ban"]) if h["gia_ban"] else ""}</td>'
                f'<td class="so mo">{khoang_gia(h)}</td></tr>' for h in ds)
            kq_tim = (f'<form method="post" action="/bao-gia/{bid}/them">{an_csrf(c)}<div class="cuon"><table><thead><tr><th></th>'
                      '<th>Tên TTBYT</th><th>Tên thương mại</th><th>Ký mã hiệu</th><th>Nhãn hiệu</th><th>Quy cách</th>'
                      f'<th class="so">Giá bán (đ)</th><th class="so">Min – Max</th></tr></thead><tbody>{dh}</tbody></table></div>'
                      '<div class="hang-nut"><button class="nut">Thêm các hàng đã chọn</button>'
                      '<button class="nut phu" name="tat_ca" value="1">Thêm tất cả kết quả</button></div>'
                      f'<input type="hidden" name="tim" value="{e(tim)}"></form>')
        else:
            kq_tim = '<p class="mo">Không có hàng nào khớp trong danh mục.</p>'
    co_hang = c.db.execute("SELECT 1 FROM hang_hoa").fetchone()
    chua_dm = "" if co_hang else '<p class="mo">Chưa có danh mục hàng hóa — quản lý nhập bảng giá ở mục Hàng hóa.</p>'
    nut_google = ""
    if da_ket_noi(c):
        nut_google = (f'<form method="post" action="/bao-gia/{bid}/google-doc" class="trong-dong">{an_csrf(c)}'
                      f'<button class="nut phu">{"Tạo lại" if b["link_file"] else "Tạo"} link Google Docs</button></form>')
    link = (f'<dt>Link Google Docs</dt><dd><a href="{e(b["link_file"])}" target="_blank" rel="noopener noreferrer">{e(b["link_file"])}</a></dd>'
            if b["link_file"] else "")
    xoa = nut_xoa(c, f"/bao-gia/{bid}/xoa", f"Xóa báo giá {b['so_bg']}? Không khôi phục được.", "Xóa báo giá") if c.duoc_xoa else ""
    tu_tay = "".join(o(nhan, ten, bat_buoc=(ten == "ten_tm")) for ten, nhan in COT_HANG)
    return trang(c, f"Báo giá {b['so_bg']}", f"""
      <div class="dau-trang"><h1>Báo giá {e(b["so_bg"])} {nhan_bg(b)}</h1>
        <div class="hang-nut">{'<a class="nut" href="/bao-gia/%d/tai">Tải file Word</a><a class="nut phu" href="/don-hang/moi?bg=%d">Lập đơn hàng</a>' % (bid, bid) if dong else ""}{nut_google}</div></div>
      <div class="the"><dl class="thong-tin"><dt>Kính gửi</dt><dd>{e(b["ten_kh"] or "Quý Khách hàng")}</dd>
        <dt>Ngày</dt><dd>{ngay(b["ngay"])}</dd><dt>Hiệu lực đến</dt><dd>{ngay(b["hieu_luc_den"]) or "—"}</dd>
        <dt>Phụ trách</dt><dd>{e(b["phu_trach"] or "—")}</dd>{link}
        {f'<dt>Ghi chú</dt><dd>{e(b["ghi_chu"])}</dd>' if b["ghi_chu"] else ""}</dl></div>
      <div class="the"><h2>Hàng trong báo giá <span class="dem">{len(dong)}</span></h2>{bang}</div>
      <div class="the"><h2>Thêm hàng</h2>{chua_dm}
        <form class="bo-loc"><input type="search" name="tim" value="{e(tim)}" placeholder="Gõ tên, ký mã hiệu, nhãn hiệu… ví dụ: HIV khay" {"autofocus" if tim else ""}>
          <button class="nut phu">Tìm</button></form>{kq_tim}</div>
      <details class="the"><summary>Thêm hàng không có trong danh mục</summary>
        <form method="post" action="/bao-gia/{bid}/them-tay" class="luoi">{an_csrf(c)}{tu_tay}
          {o("Số lượng", "so_luong", kieu="number", them='min="0" step="any"')}
          {o("Đơn giá (đ)", "don_gia", kieu="number", them='min="0" step="any"')}
          <div class="hang-nut"><button class="nut phu">Thêm dòng</button></div></form></details>
      <details class="the"><summary>Sửa thông tin, đổi tình trạng</summary>
        <form method="post" action="/bao-gia/{bid}/sua" class="luoi">{an_csrf(c)}{o_dau_bg(c, b)}
          <div class="hang-nut"><button class="nut">Lưu</button></div></form></details>
      {xoa}""", "bg")


def bg_dong_luu(c, bid):
    """Lưu số lượng, đơn giá của mọi dòng; hoặc bỏ một dòng khi bấm nút Bỏ."""
    lay_bg(c, bid)
    xoa = c.form.get("xoa", "")
    if xoa.isdigit():
        c.db.execute("DELETE FROM bao_gia_dong WHERE id = ? AND bao_gia_id = ?", (int(xoa), bid))
        c.db.commit()
        return Chuyen(f"/bao-gia/{bid}", "Đã bỏ một dòng hàng.")
    for d in dong_cua_bg(c, bid):
        c.db.execute("UPDATE bao_gia_dong SET so_luong = ?, don_gia = ? WHERE id = ?",
                     (c.so(f"sl_{d['id']}", "Số lượng"), c.so(f"gia_{d['id']}", "Đơn giá"), d["id"]))
    c.db.commit()
    return Chuyen(f"/bao-gia/{bid}", "Đã lưu số lượng và giá.")


def bg_them_dong(c, bid, cac_dong):
    cot = [t for t, _ in COT_HANG] + ["so_luong", "don_gia", "gia_min", "gia_max"]
    tt = (c.db.execute("SELECT COALESCE(MAX(tt), 0) AS m FROM bao_gia_dong WHERE bao_gia_id = ?", (bid,)).fetchone()["m"] or 0)
    c.db.executemany(f"INSERT INTO bao_gia_dong (bao_gia_id, tt, {', '.join(cot)}) VALUES (?, ?{', ?' * len(cot)})",
                     [[bid, tt + i] + [d[k] for k in cot] for i, d in enumerate(cac_dong, 1)])
    c.db.commit()


def bg_them(c, bid):
    lay_bg(c, bid)
    tim = c.form.get("tim", "")
    if c.form.get("tat_ca") == "1" and tim.strip():
        dk, ts = dk_tim_hang(tim)
        ds = c.db.execute(f"SELECT * FROM hang_hoa WHERE 1=1{dk} ORDER BY id LIMIT 80", ts).fetchall()
    else:
        ids = [int(k[3:]) for k in c.form if k.startswith("hh_") and k[3:].isdigit()][:200]
        if not ids:
            raise Loi(400, "Chưa tích chọn hàng nào.")
        ds = c.db.execute(f"SELECT * FROM hang_hoa WHERE id IN ({', '.join('?' * len(ids))}) ORDER BY id", ids).fetchall()
    if not ds:
        raise Loi(400, "Không tìm thấy hàng đã chọn trong danh mục.")
    bg_them_dong(c, bid, [dict({t: h[t] for t, _ in COT_HANG}, so_luong=0, don_gia=h["gia_ban"] or 0,
                               gia_min=h["gia_min"] or 0, gia_max=h["gia_max"] or 0) for h in ds])
    return Chuyen(f"/bao-gia/{bid}", f"Đã thêm {len(ds)} hàng vào báo giá, đơn giá lấy theo giá bán trong danh mục.")


def bg_them_tay(c, bid):
    lay_bg(c, bid)
    d = {t: c.chu(t, nhan, t == "ten_tm", 500) for t, nhan in COT_HANG}
    d.update(so_luong=c.so("so_luong", "Số lượng"), don_gia=c.so("don_gia", "Đơn giá"), gia_min=0, gia_max=0)
    bg_them_dong(c, bid, [d])
    return Chuyen(f"/bao-gia/{bid}", "Đã thêm một dòng hàng.")


def tao_file_bg(c, b):
    dong = dong_cua_bg(c, b["id"])
    if not dong:
        raise Loi(400, "Báo giá chưa có hàng nào.")
    ten = ten_tep_an_toan(f"Báo giá {b['so_bg']}" + (f" - {b['ten_kh']}" if b["ten_kh"] else ""))
    return ten, docx_bao_gia.tao(dict(b), [dict(d) for d in dong])


def bg_tai(c, bid):
    ten, dl = tao_file_bg(c, lay_bg(c, bid))
    return Tep(ten + ".docx", dl, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def bg_google(c, bid):
    b = lay_bg(c, bid)
    ten, dl = tao_file_bg(c, b)
    kq = goi_google(c, "tao_doc", ten=ten, docx=base64.b64encode(dl).decode(),
                    quyen=doc_cd(c, "quyen_link", "xem"), thu_muc="Báo giá")
    url = kq.get("url") or ""
    if not url.startswith("https://docs.google.com/"):
        raise Loi(502, "Google không trả về link báo giá.")
    c.db.execute("UPDATE bao_gia SET link_file = ? WHERE id = ?", (url, bid))
    c.db.commit()
    return Chuyen(f"/bao-gia/{bid}", "Đã tạo link Google Docs cho báo giá (thư mục Báo giá trong Drive).")


# ───────────────────────── soạn báo giá bằng chat (không dùng AI) ─────────────────────────
# Mỗi dòng (hoặc mỗi đoạn cách nhau bởi dấu ; ,) là một ý: khách hàng, một mặt hàng, giảm giá, hiệu lực, ghi chú.

DV_SL = r"(?:hop|test|que|khay|cai|bo|lo|kit|chiec|thung|tui|goi|vi)"
MAU_KHACH = re.compile(r"^(?:kh[aá]ch\s*h[aà]ng|kh[aá]ch|kh|k[ií]nh\s*g[uử]i|g[uử]i|b[aá]o\s*gi[aá]\s*cho|b[aá]o\s*gi[aá]|cho)"
                       r"(?:\s*[:\-]\s*|\s+)(.+)$", re.I)
MAU_GHI_CHU = re.compile(r"^(?:ghi\s*ch[uú]|gc|l[uư]u\s*[yý])\s*[:\-]?\s*(.+)$", re.I)
VI_DU_CHAT = """Khách: BV Thủ Đức
R0011C 50 hộp
HBsAg que x20
HCV khay 10 giá 11000
giảm 5%
hiệu lực 30 ngày
ghi chú: Giá đã gồm VAT, giao hàng tận nơi"""


VIET_TAT = {"bv": "benh vien", "bvdk": "benh vien da khoa", "ttyt": "trung tam y te", "tyt": "tram y te",
            "pk": "phong kham", "pkdk": "phong kham da khoa", "cty": "cong ty", "ct": "cong ty", "tnhh": "trach nhiem huu han"}


def viet_tat(s):
    """Bỏ dấu và mở các chữ viết tắt hay dùng (BV, TTYT, PK…) để so tên khách."""
    return " ".join(VIET_TAT.get(w, w) for w in re.sub(r"[^a-z0-9 ]", " ", gap(s)).split())


def _so_chat(s, k=""):
    x = doc_gia(s)
    return x * 1000 if k in ("k", "nghin", "ngan") else x


def _khop_hang(hang, q):
    """Tìm hàng theo câu đã bỏ dấu: trùng ký mã hiệu thì lấy luôn; không thì mỗi từ phải có trong tên/mã/nhãn hiệu."""
    tu = q.split()
    for t in tu:
        ex = [h for h in hang if h["_m"] and h["_m"] == t]
        if ex:
            return ex[:1]
    ung = [h for h in hang if all(re.search(r"(?<![a-z0-9])" + re.escape(t), h["_g"]) for t in tu)]
    if len(ung) > 1:
        for loc in (lambda h: h["_t"] == q, lambda h: all(re.search(r"(?<![a-z0-9])" + re.escape(t), h["_t"]) for t in tu)):
            hep = [h for h in ung if loc(h)]
            if len(hep) == 1:
                return hep
            if hep:
                ung = hep
    return ung


def doc_chat_bg(c, van_ban):
    """Hiểu yêu cầu gõ tự do -> thông tin báo giá và các dòng hàng (mỗi dòng có danh sách hàng khớp)."""
    kq = {"ten_kh": "", "giam": 0.0, "hieu_luc": None, "ghi_chu": "", "dong": [], "khong_hieu": []}
    hang = [dict(h) for h in c.db.execute("SELECT * FROM hang_hoa ORDER BY id").fetchall()]
    for h in hang:
        h["_g"] = gap(" ".join(str(h[k] or "") for k in ("ten", "ten_tm", "ma", "nhan_hieu")))
        h["_t"], h["_m"] = gap(h["ten"]), gap(h["ma"])
    khach = [r["ten"] for r in c.db.execute("SELECT ten FROM khach_hang").fetchall()]

    def dat_khach(ten):
        g = viet_tat(ten)
        trung = [k for k in khach if g and (g in viet_tat(k) or viet_tat(k) in g)]
        kq["ten_kh"] = trung[0] if len(trung) == 1 else ten.strip()

    cac_cau = []
    for dong in str(van_ban or "")[:5000].splitlines():
        m = MAU_GHI_CHU.match(dong.strip(" \t-•*+"))
        if m:                   # ghi chú lấy nguyên dòng, kể cả dấu phẩy
            kq["ghi_chu"] = (kq["ghi_chu"] + "; " if kq["ghi_chu"] else "") + m.group(1).strip()
        else:
            cac_cau += re.split(r";|,(?!\d)", dong)
    for cau in cac_cau:
        cau = cau.strip(" \t.-•*+")
        if not cau:
            continue
        g = gap(cau)
        con = g
        m = re.search(r"(?:giam|chiet khau|ck)\s*(?:gia\s*)?(\d+(?:[.,]\d+)?)\s*%", con)
        if m:
            kq["giam"] = min(float(m.group(1).replace(",", ".")), 100.0)
            con = (con[:m.start()] + " " + con[m.end():]).strip()
        m = re.search(r"hieu luc\s*(?:den|toi)?\s*(?:ngay\s*)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", con)
        if m:
            nam = int(m.group(3) or date.today().year)
            try:
                kq["hieu_luc"] = date(nam + 2000 if nam < 100 else nam, int(m.group(2)), int(m.group(1))).isoformat()
            except ValueError:
                kq["khong_hieu"].append(cau)
            con = (con[:m.start()] + " " + con[m.end():]).strip()
        else:
            m = re.search(r"hieu luc\s*(\d{1,3})\s*ngay", con)
            if m:
                kq["hieu_luc"] = (date.today() + timedelta(days=int(m.group(1)))).isoformat()
                con = (con[:m.start()] + " " + con[m.end():]).strip()
        if not con:
            continue
        m = MAU_KHACH.match(cau)
        if m and not re.search(r"\d", gap(m.group(1))[:3]) and not _khop_hang(hang, gap(cau)):
            dat_khach(m.group(1))
            continue
        # mặt hàng: tách giá, số lượng; phần còn lại để tìm hàng
        gia = 0.0
        m = re.search(r"(?:(?<![a-z])(?:don gia|gia)|@)\s*[:=]?\s*(\d[\d.,]*)\s*(k|nghin|ngan|d|vnd)?\b", con)
        if m:
            gia = _so_chat(m.group(1), m.group(2) or "")
            con = (con[:m.start()] + " " + con[m.end():]).strip()
        sl = 0.0
        for mau in (r"(?:^|\s)(?:x|sl|so luong)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\b", r"(?:^|\s)(\d+(?:[.,]\d+)?)\s*" + DV_SL + r"\b",
                    r"(?:^|\s)x?(\d+(?:[.,]\d+)?)$"):
            m = re.search(mau, con)
            if m:
                sl = float(m.group(1).replace(",", "."))
                con = (con[:m.start()] + " " + con[m.end():]).strip()
                break
        con = re.sub(r"\s+", " ", con).strip()
        ung = _khop_hang(hang, con) if con else []
        if not ung and not sl and not gia and not kq["ten_kh"] and not kq["dong"]:
            dat_khach(cau)          # dòng đầu không phải hàng -> coi là tên khách
            continue
        kq["dong"].append({"cau": cau, "sl": sl, "gia": gia, "ung": ung[:15], "nhieu": len(ung)})
    return kq


def _gia_chat(kq, d, h):
    if d["gia"]:
        return d["gia"]
    return round((h["gia_ban"] or 0) * (1 - kq["giam"] / 100))


GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
LENH_AI_BG = """Bạn là trợ lý soạn báo giá test nhanh / thiết bị y tế của công ty Avanta. Người dùng gõ yêu cầu báo giá bằng tiếng Việt tự do
(có thể không dấu, viết tắt, sai chính tả, nhiều hàng trên một dòng, hoặc là danh sách đã soạn rồi kèm câu bổ sung/sửa).
Nhiệm vụ: đọc yêu cầu và chọn đúng hàng trong DANH MỤC (chỉ dùng ký mã hiệu có trong danh mục, không bịa mã).
- Khi một tên khớp nhiều hàng mà người dùng không nói rõ hãng, chọn tất cả hàng khớp không được; hãy để ma rỗng và ghi tim = câu gốc ngắn gọn.
- so_luong: số lượng khách cần (0 nếu không nói). don_gia: chỉ điền khi người dùng tự nêu giá cho hàng đó (đơn vị đồng, "11k" = 11000), không thì 0.
- giam_pct: phần trăm giảm giá chung nếu có. hieu_luc_den: yyyy-mm-dd nếu người dùng nói ngày hết hiệu lực (hoặc tính từ "N ngày" kể từ hôm nay), không thì rỗng.
- ten_kh: BẮT BUỘC điền nếu người dùng nêu khách (thường sau "cho", "gửi", "khách", "kính gửi", hoặc tên bệnh viện/phòng khám/TTYT/công ty), kể cả khi không có trong DANH SÁCH KHÁCH. Nếu khớp một tên trong danh sách thì dùng đúng tên đó; không thì viết hoa chữ đầu, có dấu, mở viết tắt (bv → Bệnh viện, ttyt → Trung tâm Y tế, pk → Phòng khám). Chỉ để rỗng khi thật sự không có tên khách. ghi_chu: điều kiện thanh toán, giao hàng, VAT… nếu người dùng nêu.
- Nếu người dùng muốn bỏ/sửa một hàng trong danh sách cũ thì trả về danh sách sau khi sửa.
- tra_loi: một câu ngắn tiếng Việt cho người dùng biết đã hiểu gì, hoặc hỏi lại điều chưa rõ."""


def ai_soan_bg(c, van_ban):
    """Gemini đọc câu tự do -> các dòng theo cách gõ của trang chat (mã hàng, số lượng…) + câu trả lời ngắn."""
    khoa = os.environ.get("GEMINI_API_KEY", "")
    if not khoa:
        raise Loi(503, "Chưa cài khóa GEMINI_API_KEY cho app trên Vercel (project data.adc). Tạm thời dùng nút Gửi (không AI).")
    hang = c.db.execute("SELECT ma, ten, ten_tm, nhan_hieu, quy_cach, gia_ban FROM hang_hoa ORDER BY id LIMIT 1500").fetchall()
    if not hang:
        raise Loi(400, "Chưa có danh mục hàng hóa — quản lý nhập bảng giá ở mục Hàng hóa trước.")
    dm = "\n".join(" | ".join(str(h[k] or "") for k in ("ma", "ten", "ten_tm", "nhan_hieu", "quy_cach", "gia_ban")) for h in hang)
    kh = "\n".join(r["ten"] for r in c.db.execute("SELECT ten FROM khach_hang ORDER BY ten LIMIT 500").fetchall())
    than = {
        "systemInstruction": {"parts": [{"text": LENH_AI_BG + f"\nHôm nay: {date.today().isoformat()}"
                                         f"\n\nDANH MỤC (ký mã hiệu | tên | tên thương mại | nhãn hiệu | quy cách | giá bán):\n{dm}"
                                         f"\n\nDANH SÁCH KHÁCH:\n{kh or '(trống)'}"}]},
        "contents": [{"role": "user", "parts": [{"text": van_ban[:4000]}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": {
            "type": "OBJECT", "properties": {
                "ten_kh": {"type": "STRING"}, "giam_pct": {"type": "NUMBER"}, "hieu_luc_den": {"type": "STRING"},
                "ghi_chu": {"type": "STRING"}, "tra_loi": {"type": "STRING"},
                "hang": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                    "ma": {"type": "STRING"}, "tim": {"type": "STRING"}, "so_luong": {"type": "NUMBER"}, "don_gia": {"type": "NUMBER"}},
                    "required": ["ma", "so_luong", "don_gia"]}}},
            "required": ["ten_kh", "hang", "tra_loi"]}}}
    yc = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(GEMINI_MODEL)}:generateContent",
                                json.dumps(than).encode(), {"Content-Type": "application/json", "x-goog-api-key": khoa})
    try:
        with urllib.request.urlopen(yc, timeout=45) as r:
            j = json.loads(r.read())
    except urllib.error.HTTPError as ex:
        if ex.code == 429:
            raise Loi(429, "Đã hết lượt AI miễn phí trong lúc này (giới hạn của Google). Thử lại sau ít phút, hoặc dùng nút Gửi (không AI).")
        raise Loi(502, f"AI báo lỗi {ex.code}. Thử lại hoặc dùng nút Gửi (không AI).")
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise Loi(502, "Không gọi được AI. Thử lại hoặc dùng nút Gửi (không AI).")
    try:
        kq = json.loads(j["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise Loi(502, "AI trả lời không đúng dạng. Thử gõ lại rõ hơn.")
    dong = []
    if str(kq.get("ten_kh") or "").strip():
        dong.append("Khách: " + str(kq["ten_kh"]).replace(";", " ").replace(",", " ").strip())
    for h in kq.get("hang") or []:
        ten = str(h.get("ma") or h.get("tim") or "").strip().replace(";", " ").replace(",", " ")
        if not ten:
            continue
        sl, gia = h.get("so_luong") or 0, h.get("don_gia") or 0
        dong.append(ten + (f" x{so_o(sl)}" if sl else "") + (f" giá {so_o(gia)}" if gia else ""))
    if kq.get("giam_pct"):
        dong.append(f"giảm {so_o(kq['giam_pct'])}%")
    hl = date_or_none(kq.get("hieu_luc_den"))
    if hl:
        dong.append(f"hiệu lực đến {hl.day:02d}/{hl.month:02d}/{hl.year}")
    if str(kq.get("ghi_chu") or "").strip():
        dong.append("ghi chú: " + " ".join(str(kq["ghi_chu"]).split()))
    return "\n".join(dong), str(kq.get("tra_loi") or "").strip()[:500]


def date_or_none(s):
    try:
        return date.fromisoformat(str(s or "")[:10])
    except ValueError:
        return None


def bg_nhanh(c):
    van_ban = c.form.get("yeu_cau", "") if c.method == "POST" else ""
    ai_noi = ""
    if van_ban.strip() and c.form.get("buoc") == "ai":
        van_ban, ai_noi = ai_soan_bg(c, van_ban)
    kq = doc_chat_bg(c, van_ban) if van_ban.strip() else None
    if kq and c.form.get("buoc") == "tao":
        cac_dong, bo = [], 0
        for i, d in enumerate(kq["dong"]):
            h = None
            if len(d["ung"]) == 1:
                h = d["ung"][0]
            else:
                v = c.form.get(f"chon_{i}", "")
                h = next((x for x in d["ung"] if str(x["id"]) == v), None)
            if not h:
                bo += 1
                continue
            cac_dong.append(dict({t: h[t] for t, _ in COT_HANG}, so_luong=d["sl"], don_gia=_gia_chat(kq, d, h),
                                 gia_min=h["gia_min"] or 0, gia_max=h["gia_max"] or 0))
        if not cac_dong:
            raise Loi(400, "Chưa có mặt hàng nào khớp danh mục để đưa vào báo giá.")
        hom_nay = date.today()
        gt = {"so_bg": so_bg_tiep(c, hom_nay.year), "ngay": hom_nay.isoformat(), "ten_kh": kq["ten_kh"][:300],
              "hieu_luc_den": kq["hieu_luc"] or (hom_nay + timedelta(days=HIEU_LUC_NGAY)).isoformat(),
              "ghi_chu": kq["ghi_chu"][:1000], "phu_trach_id": c.user["id"]}
        try:
            bid = c.db.them(f"INSERT INTO bao_gia ({', '.join(gt)}, tao_luc) VALUES ({'?, ' * len(gt)}?)",
                            list(gt.values()) + [datetime.now().isoformat(timespec="seconds")])
        except LOI_TRUNG:
            c.db.rollback()
            raise Loi(400, "Số báo giá vừa bị trùng. Hãy bấm Tạo báo giá lần nữa.")
        bg_them_dong(c, bid, cac_dong)
        return Chuyen(f"/bao-gia/{bid}", f"Đã tạo báo giá {gt['so_bg']} với {len(cac_dong)} mặt hàng"
                      + (f", bỏ {bo} dòng không khớp hàng" if bo else "") + ". Kiểm tra lại rồi tải file Word.")
    tra_loi = ""
    if kq:
        hl = kq["hieu_luc"] or (date.today() + timedelta(days=HIEU_LUC_NGAY)).isoformat()
        y = [f'<dt>Kính gửi</dt><dd>{e(kq["ten_kh"] or "Quý Khách hàng")}</dd>', f'<dt>Hiệu lực đến</dt><dd>{ngay(hl)}</dd>']
        if kq["giam"]:
            y.append(f'<dt>Giảm giá</dt><dd>{so_o(kq["giam"])}% trên giá bán (dòng tự ghi giá thì giữ nguyên)</dd>')
        if kq["ghi_chu"]:
            y.append(f'<dt>Ghi chú</dt><dd>{e(kq["ghi_chu"])}</dd>')
        hang, tong, can_chon = "", 0, False
        for i, d in enumerate(kq["dong"]):
            sl = so_o(d["sl"]) or "—"
            if len(d["ung"]) == 1:
                h = d["ung"][0]
                gia = _gia_chat(kq, d, h)
                tong += gia * d["sl"]
                canh = ""
                if h["gia_min"] and gia < h["gia_min"]:
                    canh = ' <span class="nhan do">dưới giá Min</span>'
                elif h["gia_max"] and gia > h["gia_max"]:
                    canh = ' <span class="nhan vang">trên giá Max</span>'
                hang += (f'<tr><td class="mo">{e(d["cau"])}</td><td><span class="nhan xanh">Đã khớp</span> <b>{e(h["ma"])}</b> '
                         f'{e(h["ten"])}<br><span class="mo">{e(h["ten_tm"])} · {e(h["quy_cach"])}</span></td>'
                         f'<td class="so">{sl}</td><td class="so">{tien(gia) if gia else "—"}{canh}</td>'
                         f'<td class="so">{tien(gia * d["sl"]) if d["sl"] and gia else ""}</td></tr>')
            elif d["ung"]:
                can_chon = True
                lc = "".join(f'<option value="{h["id"]}">{e(h["ma"])} · {e(h["ten"])} · {e(h["ten_tm"])}'
                             f'{" · " + tien(h["gia_ban"]) if h["gia_ban"] else ""}</option>' for h in d["ung"])
                them = f' <span class="mo">(hiện 15/{d["nhieu"]}, gõ rõ hơn để thu hẹp)</span>' if d["nhieu"] > 15 else ""
                hang += (f'<tr><td class="mo">{e(d["cau"])}</td><td><span class="nhan vang">Chọn giúp</span> có {d["nhieu"]} hàng khớp{them}<br>'
                         f'<select name="chon_{i}" form="f-tao" required aria-label="Chọn hàng"><option value="">— chọn hàng —</option>'
                         f'{lc}<option value="bo">Bỏ qua dòng này</option></select></td>'
                         f'<td class="so">{sl}</td><td class="so">{tien(d["gia"]) if d["gia"] else "giá bán"}</td><td></td></tr>')
            else:
                hang += (f'<tr><td class="mo">{e(d["cau"])}</td><td><span class="nhan do">Không tìm thấy</span> '
                         'dòng này sẽ bị bỏ qua — gõ ký mã hiệu hoặc tên ngắn như trong danh mục</td><td></td><td></td><td></td></tr>')
        chan = f'<tr><td colspan="4" class="so"><b>Tổng cộng</b></td><td class="so"><b>{tien(tong)}</b></td></tr>' if tong else ""
        co_dong = any(d["ung"] for d in kq["dong"])
        bang = ('<div class="cuon"><table><thead><tr><th>Bạn gõ</th><th>App hiểu là</th><th class="so">Số lượng</th>'
                f'<th class="so">Đơn giá (đ)</th><th class="so">Thành tiền</th></tr></thead><tbody>{hang}{chan}</tbody></table></div>'
                if kq["dong"] else '<p class="mo">Chưa thấy mặt hàng nào. Mỗi mặt hàng gõ một dòng, ví dụ: R0011C 50 hộp.</p>')
        tao = (f'<form method="post" id="f-tao">{an_csrf(c)}<input type="hidden" name="buoc" value="tao">'
               f'<textarea name="yeu_cau" hidden>{e(van_ban)}</textarea><div class="hang-nut"><button class="nut">Tạo báo giá</button>'
               f'<span class="mo">{"Chọn hàng ở các dòng màu vàng trước khi tạo. " if can_chon else ""}'
               'Sau khi tạo vẫn sửa được số lượng, giá, thêm bớt hàng.</span></div></form>') if co_dong else ""
        tra_loi = f'<div class="the"><h2>App hiểu như sau</h2>{"<p><b>AI:</b> " + e(ai_noi) + "</p>" if ai_noi else ""}<dl class="thong-tin">{"".join(y)}</dl>{bang}{tao}</div>'
    chua_dm = "" if c.db.execute("SELECT 1 FROM hang_hoa").fetchone() else \
        '<p class="nhan do">Chưa có danh mục hàng hóa — quản lý nhập bảng giá ở mục Hàng hóa trước.</p>'
    return trang(c, "Soạn báo giá bằng chat", f"""
      <h1>Soạn báo giá bằng chat</h1>
      <div class="the">{chua_dm}<form method="post">{an_csrf(c)}<input type="hidden" name="buoc" value="xem">
        <label class="rong">Gõ yêu cầu, mỗi ý một dòng
          <textarea name="yeu_cau" rows="9" placeholder="{e(VI_DU_CHAT)}" {"" if kq else "autofocus"}>{e(van_ban)}</textarea></label>
        <div class="hang-nut"><button class="nut" name="buoc" value="ai">Gửi cho AI</button><button class="nut phu">Gửi (không AI)</button>
          {'<a href="/bao-gia/nhanh">Làm báo giá khác</a>' if kq else ""}</div>
        <p class="mo">AI hiểu câu gõ tự do. Sau khi AI đọc, ô trên đổi thành danh sách mã hàng — muốn sửa thì gõ thêm câu bổ sung (ví dụ "bỏ HCV, thêm 10 hộp HIV OnSite") rồi gửi lại.</p></form>
        <details><summary>Cách gõ</summary><ul class="mo">
          <li><b>Khách hàng:</b> <code>Khách: BV Thủ Đức</code> (hoặc <code>Kính gửi …</code>, <code>Báo giá cho …</code>). Dòng đầu không phải tên hàng cũng được hiểu là tên khách.</li>
          <li><b>Mặt hàng:</b> mỗi hàng một dòng — ký mã hiệu hoặc tên ngắn, rồi số lượng: <code>R0011C 50</code>, <code>HBsAg que x20</code>, <code>HIV khay 30 hộp</code>. Không ghi số lượng thì báo giá chỉ có đơn giá.</li>
          <li><b>Giá riêng:</b> thêm <code>giá 11000</code> (hoặc <code>@11k</code>) cuối dòng hàng. Không ghi thì lấy giá bán trong danh mục.</li>
          <li><b>Giảm giá cả báo giá:</b> <code>giảm 5%</code> · <b>Hiệu lực:</b> <code>hiệu lực 30 ngày</code> hoặc <code>hiệu lực đến 31/12</code> · <b>Ghi chú:</b> <code>ghi chú: Giá đã gồm VAT</code></li>
          <li>Gõ có dấu hay không dấu đều được. Nhiều hàng trên một dòng thì cách nhau bằng dấu <code>;</code></li></ul></details></div>
      {tra_loi}""", "bgn")


# ───────────────────────── bán hàng: phần dùng chung ─────────────────────────
# Đơn giá trong đơn hàng, phiếu nhập là giá đã gồm thuế VAT. Công nợ phát sinh khi giao hàng (phiếu xuất);
# tiền thu / chi trừ vào phiếu cũ nhất trước.

HINH_THUC = [("ck", "Chuyển khoản"), ("tm", "Tiền mặt"), ("khac", "Khác")]
CAN_DATE = 180               # cảnh báo lô còn hạn dùng ≤ 180 ngày
MOC_NO = ["Trong hạn", "Quá 1–30 ngày", "31–60 ngày", "61–90 ngày", "Trên 90 ngày"]

ICON.update({k: _svg(v) for k, v in {
    "ban_hang": '<path d="M5 8h6l5 22h20l5-15H14" fill="none" stroke="#1d5b79" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
                '<path d="M15 16h25l-4 13H18z" fill="#1fc7b0"/><circle cx="19" cy="38" r="4" fill="#f58220"/><circle cx="34" cy="38" r="4" fill="#f58220"/>',
    "tien": '<rect x="5" y="12" width="38" height="26" rx="5" fill="#1d7a6b"/><rect x="5" y="18" width="38" height="6" fill="#fbb945"/>'
            '<circle cx="34" cy="31" r="4" fill="#fff"/>' + _DONG.format(x=10, y=29, w=12),
    "bieu_do": '<rect x="6" y="26" width="9" height="16" rx="2" fill="#2ea8f5"/><rect x="19.5" y="16" width="9" height="26" rx="2" fill="#8f4f86"/>'
               '<rect x="33" y="6" width="9" height="36" rx="2" fill="#f58220"/>',
    "kho": '<path d="M4 20 24 6l20 14v22H4z" fill="#8f4f86"/><rect x="12" y="24" width="24" height="18" fill="#fbb945"/>'
           '<path d="M12 30h24M12 36h24" stroke="#fff" stroke-width="2.4"/>',
    "nhap": '<rect x="8" y="22" width="32" height="20" rx="4" fill="#2ea8f5"/><path d="M24 4v20m-8-8 8 8 8-8" fill="none" stroke="#f58220" '
            'stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>' + _DONG.format(x=15, y=33, w=18),
}.items()})
UNG_DUNG += [
    ("ban-hang", "Bán hàng", "ban_hang", [
        ("/don-hang", "Đơn hàng", "dh", "ds_hd", False), ("/don-hang/moi", "Lập đơn hàng", "dhm", "soan", False),
        ("/cong-no", "Công nợ phải thu", "cn", "tien", False), ("/doanh-so", "Báo cáo doanh số", "ds", "bieu_do", False)]),
    ("kho", "Kho – Mua hàng", "kho", [
        ("/kho", "Tồn kho", "tk", "hang_hoa", False), ("/nhap-kho", "Nhập kho / mua hàng", "pn", "nhap", True),
        ("/nha-cung-cap", "Nhà cung cấp", "ncc", "khach", True), ("/phai-tra", "Nợ nhà cung cấp", "pt", "tien", True)]),
]


def so_tiep(c, bang, cot, chu):
    """Số chứng từ kế tiếp trong năm: DH26001, PX26001…"""
    dau = f"{chu}{date.today().year % 100:02d}"
    lon = 0
    for r in c.db.execute(f"SELECT {cot} AS s FROM {bang} WHERE {cot} LIKE ?", (dau + "%",)).fetchall():
        m = re.fullmatch(re.escape(dau) + r"(\d{3,})", r["s"], re.I)
        if m:
            lon = max(lon, int(m.group(1)))
    return f"{dau}{lon + 1:03d}"


def goi_y_khach(c):
    return ('<datalist id="ds-khach">' + "".join(f'<option value="{e(r["ten"])}">' for r in c.db.execute(
        "SELECT ten FROM khach_hang ORDER BY ten").fetchall()) + '</datalist>')


def tim_khach(c):
    ten = c.chu("ten_kh", "Khách hàng", True, 300)
    for r in c.db.execute("SELECT * FROM khach_hang").fetchall():
        if gap(r["ten"]) == gap(ten):
            return r
    raise Loi(400, f"Chưa có khách hàng “{ten}”. Hãy chọn trong danh sách gợi ý, hoặc thêm khách ở mục Khách hàng trước.")


def cong(d, k, v):
    d[k] = d.get(k, 0) + v


def xep_no(nhom):
    """nhom = {id đối tác: {"phieu": [phiếu theo thứ tự ngày, có gia_tri / ngay / han_tt], "da_tra": số tiền}}.
    Trừ tiền đã trả vào phiếu cũ nhất trước, rồi chia phần còn nợ theo tuổi quá hạn."""
    hom_nay = date.today()
    for n in nhom.values():
        con = n["da_tra"]
        n["phat_sinh"], n["con_no"], n["tuoi"] = 0, 0, [0] * 5
        for p in n["phieu"]:
            tru = min(con, p["gia_tri"])
            con -= tru
            p["con_lai"] = p["gia_tri"] - tru if p["gia_tri"] - tru >= 0.5 else 0
            p["tre"] = (hom_nay - date.fromisoformat(p["han_tt"] or p["ngay"])).days
            n["phat_sinh"] += p["gia_tri"]
            n["con_no"] += p["con_lai"]
            n["tuoi"][0 if p["tre"] <= 0 else 1 if p["tre"] <= 30 else 2 if p["tre"] <= 60 else 3 if p["tre"] <= 90 else 4] += p["con_lai"]
        n["qua_han"] = sum(n["tuoi"][1:])
        n["tra_thua"] = con if con >= 0.5 else 0
    return nhom


def nhan_no(p):
    if not p["con_lai"]:
        return '<span class="nhan xanh">Đã trả đủ</span>'
    if p["tre"] > 0:
        return f'<span class="nhan do">Quá hạn {p["tre"]} ngày</span>'
    return f'<span class="nhan vang">Còn {-p["tre"]} ngày</span>'


def bang_no(nhom, ten, url):
    """Bảng công nợ theo đối tác kèm tuổi nợ. ten = {id: tên}."""
    ds = sorted(nhom.items(), key=lambda x: (-x[1]["con_no"], ten.get(x[0], "")))
    dong = "".join(
        f'<tr><td><a href="{url}/{i}">{e(ten.get(i, "?"))}</a></td><td class="so">{tien(n["phat_sinh"])}</td>'
        f'<td class="so">{tien(n["da_tra"])}</td><td class="so"><b>{tien(n["con_no"] - n["tra_thua"])}</b></td>'
        + "".join(f'<td class="so{" mo" if not v else ""}">{tien(v) if v else "—"}</td>' for v in n["tuoi"]) + '</tr>'
        for i, n in ds)
    tong = [sum(n["tuoi"][j] for n in nhom.values()) for j in range(5)]
    chan = ('<tr><td><b>Tổng cộng</b></td>'
            + "".join(f'<td class="so"><b>{tien(v)}</b></td>' for v in
                      [sum(n["phat_sinh"] for n in nhom.values()), sum(n["da_tra"] for n in nhom.values()),
                       sum(n["con_no"] - n["tra_thua"] for n in nhom.values())] + tong) + '</tr>')
    return ('<div class="the cuon"><table><thead><tr><th>Tên</th><th class="so">Phát sinh (đ)</th><th class="so">Đã trả</th>'
            '<th class="so">Còn nợ</th>' + "".join(f'<th class="so">{m}</th>' for m in MOC_NO)
            + f'</tr></thead><tbody>{dong}{chan}</tbody></table></div>')


def o_tien(c, chu, bang, cot):
    """Các ô của phiếu thu / phiếu chi."""
    return (o("Số phiếu", cot, so_tiep(c, bang, cot, chu), bat_buoc=True) + o("Ngày", "ngay", date.today().isoformat(), "date", True)
            + o("Số tiền (đ)", "so_tien", kieu="number", bat_buoc=True, them='min="1" step="any"')
            + f'<label>Hình thức{chon("hinh_thuc", HINH_THUC)}</label>' + o("Ghi chú", "ghi_chu"))


def luu_tien(c, bang, cot, cot_doi_tac, doi_tac_id):
    ht = c.form.get("hinh_thuc") if c.form.get("hinh_thuc") in dict(HINH_THUC) else "ck"
    tien_ = c.so("so_tien", "Số tiền", True)
    if tien_ <= 0:
        raise Loi(400, "Số tiền phải lớn hơn 0.")
    so = c.chu(cot, "Số phiếu", True, 60)
    try:
        c.db.execute(f"INSERT INTO {bang} ({cot}, ngay, {cot_doi_tac}, so_tien, hinh_thuc, ghi_chu, nguoi_nhap_id) VALUES (?,?,?,?,?,?,?)",
                     (so, c.ngay("ngay", "Ngày", True), doi_tac_id, tien_, ht, c.chu("ghi_chu", "Ghi chú"), c.user["id"]))
    except LOI_TRUNG:
        c.db.rollback()
        raise Loi(400, f"Số phiếu {so} đã có. Hãy đổi số khác.")
    c.db.commit()
    return so, tien_


def bang_tien(c, ds, cot, url_xoa):
    if not ds:
        return '<p class="mo">Chưa có phiếu nào.</p>'
    dong = "".join(
        f'<tr><td><b>{e(t[cot])}</b></td><td>{ngay(t["ngay"])}</td><td class="so">{tien(t["so_tien"])}</td>'
        f'<td>{e(dict(HINH_THUC).get(t["hinh_thuc"], ""))}</td><td>{e(t["ghi_chu"])}</td><td class="thao-tac">'
        + (nut_xoa(c, f'{url_xoa}/{t["id"]}/xoa', f"Xóa phiếu {t[cot]} số tiền {tien(t['so_tien'])} đ?") if c.ql else "") + '</td></tr>'
        for t in ds)
    return ('<div class="cuon"><table><thead><tr><th>Số phiếu</th><th>Ngày</th><th class="so">Số tiền (đ)</th><th>Hình thức</th>'
            f'<th>Ghi chú</th><th></th></tr></thead><tbody>{dong}</tbody></table></div>')


# ───────────────────────── kho: tồn theo lô ─────────────────────────

def ton_kho(c):
    """{(hàng hóa id, số lô, hạn dùng): tồn} = tổng nhập − tổng xuất."""
    ton = {}
    for r in c.db.execute("SELECT hang_hoa_id, so_lo, han_dung, so_luong FROM phieu_nhap_dong").fetchall():
        cong(ton, (r["hang_hoa_id"], r["so_lo"] or "", r["han_dung"] or ""), r["so_luong"])
    for r in c.db.execute("SELECT d.hang_hoa_id, x.so_lo, x.han_dung, x.so_luong FROM phieu_xuat_dong x "
                          "JOIN don_hang_dong d ON d.id = x.don_hang_dong_id WHERE d.hang_hoa_id IS NOT NULL").fetchall():
        cong(ton, (r["hang_hoa_id"], r["so_lo"] or "", r["han_dung"] or ""), -r["so_luong"])
    return ton


def ton_theo_hang(ton):
    kq = {}
    for (hh, _, _), q in ton.items():
        cong(kq, hh, q)
    return kq


def phan_lo(ton, hh, n, ngay_xuat):
    """Chia số lượng xuất vào các lô còn hàng, lô hết hạn trước xuất trước, bỏ qua lô đã hết hạn.
    Trả về ([(số lô, hạn dùng, số lượng)], số lượng kho không đủ). Phần thiếu ghi không lô."""
    lo_con = sorted((hd or "9999", lo, hd) for (h, lo, hd), q in ton.items()
                    if h == hh and q > 1e-9 and not (hd and hd < ngay_xuat))
    kq, con = {}, n
    for _, lo, hd in lo_con:
        if con <= 1e-9:
            break
        lay = min(con, ton[(hh, lo, hd)])
        ton[(hh, lo, hd)] -= lay
        kq[(lo, hd)] = lay
        con -= lay
    thieu = con if con > 1e-9 else 0
    if thieu:
        cong(kq, ("", ""), thieu)
        cong(ton, (hh, "", ""), -thieu)
    return [(lo, hd, q) for (lo, hd), q in kq.items()], thieu


def nhan_lo(hd):
    if not hd:
        return ""
    con = (date.fromisoformat(hd) - date.today()).days
    if con < 0:
        return ' <span class="nhan do">Hết hạn</span>'
    if con <= CAN_DATE:
        return f' <span class="nhan vang">Còn {con} ngày</span>'
    return ""


def kho(c):
    tu, canh = c.q.get("q", ""), c.q.get("canh", "")
    ton = {k: q for k, q in ton_kho(c).items() if abs(q) > 1e-9}
    dk, ts = dk_tim_hang(tu)
    hang = {h["id"]: h for h in c.db.execute(f"SELECT * FROM hang_hoa WHERE 1=1{dk}", ts).fetchall()}
    moc = (date.today() + timedelta(days=CAN_DATE)).isoformat()
    theo_hang, tong_gia_tri = {}, 0
    for (hh, lo, hd), q in ton.items():
        if hh in hang and not (canh and not (hd and hd <= moc and q > 0)):
            theo_hang.setdefault(hh, []).append((hd or "9999", lo, hd, q))
    dong = ""
    for hh in sorted(theo_hang, key=lambda i: gap(hang[i]["ten_tm"] or hang[i]["ten"])):
        h, cac_lo = hang[hh], sorted(theo_hang[hh])
        tong = sum(x[3] for x in cac_lo)
        am = ' <span class="nhan do">Xuất vượt tồn</span>' if tong < -1e-9 else ""
        dong += (f'<tr><td rowspan="{len(cac_lo)}">{e(h["ten_tm"] or h["ten"])}<br><span class="mo">{e(h["ma"])} · {e(h["quy_cach"])}</span></td>'
                 f'<td rowspan="{len(cac_lo)}" class="so"><b>{sl(tong)}</b>{am}</td>')
        for i, (_, lo, hd, q) in enumerate(cac_lo):
            dong += (("<tr>" if i else "") + f'<td>{e(lo) or "<span class=mo>không ghi lô</span>"}</td>'
                     f'<td>{ngay(hd) or "—"}{nhan_lo(hd) if q > 0 else ""}</td><td class="so">{sl(q)}</td></tr>')
    if dong:
        bang = ('<div class="the cuon"><table><thead><tr><th>Hàng hóa</th><th class="so">Tổng tồn</th><th>Số lô</th><th>Hạn dùng</th>'
                f'<th class="so">Tồn theo lô</th></tr></thead><tbody>{dong}</tbody></table></div>')
    elif ton:
        bang = '<div class="the trong">Không có hàng nào khớp.</div>'
    else:
        bang = ('<div class="the trong">Kho chưa có hàng. '
                + ('Lập phiếu ở mục <a href="/nhap-kho">Nhập kho / mua hàng</a> để ghi tồn đầu kỳ và hàng mua về.' if c.ql
                   else 'Quản lý cần lập phiếu nhập kho.') + '</div>')
    n_can = sum(1 for (_, _, hd), q in ton.items() if hd and hd <= moc and q > 0)
    return trang(c, "Tồn kho", f"""
      <div class="dau-trang"><h1>Tồn kho <span class="dem">{len(theo_hang)}</span></h1>
        {'<a class="nut" href="/nhap-kho/moi">Lập phiếu nhập</a>' if c.ql else ""}</div>
      <p class="mo">Tồn = tổng nhập − tổng đã giao theo đơn hàng. {n_can} lô còn hạn dùng từ {CAN_DATE} ngày trở xuống hoặc đã hết hạn.</p>
      <form class="bo-loc"><input type="search" name="q" value="{e(tu)}" placeholder="Tên, ký mã hiệu, nhãn hiệu…">
        {chon("canh", [("1", f"Chỉ lô cận hạn dùng (≤ {CAN_DATE} ngày)")], canh, "Mọi lô")}
        <button class="nut phu">Lọc</button>{'<a href="/kho">Bỏ lọc</a>' if c.q else ""}</form>
      {bang}""", "tk")


# ───────────────────────── đơn hàng bán ─────────────────────────

SQL_DH = ("SELECT o.*, k.ten AS khach, k.han_no, u.ho_ten AS phu_trach, "
          "COALESCE((SELECT SUM(d.so_luong * d.don_gia) FROM don_hang_dong d WHERE d.don_hang_id = o.id), 0) AS gia_tri, "
          "COALESCE((SELECT SUM(x.so_luong * d.don_gia) FROM phieu_xuat_dong x JOIN don_hang_dong d ON d.id = x.don_hang_dong_id "
          "WHERE d.don_hang_id = o.id), 0) AS da_giao "
          "FROM don_hang o JOIN khach_hang k ON k.id = o.khach_hang_id LEFT JOIN nguoi_dung u ON u.id = o.phu_trach_id WHERE 1=1")
TT_DH = [("chua", "Chưa giao"), ("mot_phan", "Giao một phần"), ("du", "Đã giao đủ"), ("huy", "Đã hủy")]


def tt_dh(o_):
    if o_["trang_thai"] == "huy":
        return "huy"
    if o_["da_giao"] < 0.5:
        return "chua"
    return "mot_phan" if o_["da_giao"] < o_["gia_tri"] - 0.5 else "du"


def nhan_dh(o_):
    tt = tt_dh(o_)
    return f'<span class="nhan {dict(huy="xam", chua="vang", mot_phan="vang", du="xanh")[tt]}">{dict(TT_DH)[tt]}</span>'


def lay_dh(c, did):
    o_ = c.db.execute(SQL_DH + " AND o.id = ?", (did,)).fetchone()
    if not o_:
        raise Loi(404, "Không tìm thấy đơn hàng.")
    if not c.ql and o_["phu_trach_id"] != c.user["id"]:
        raise Loi(403, "Bạn không phụ trách đơn hàng này.")
    return o_


def dong_cua_dh(c, did):
    return c.db.execute(
        "SELECT d.*, COALESCE((SELECT SUM(x.so_luong) FROM phieu_xuat_dong x WHERE x.don_hang_dong_id = d.id), 0) AS da_giao "
        "FROM don_hang_dong d WHERE d.don_hang_id = ? ORDER BY d.tt, d.id", (did,)).fetchall()


def ds_don_hang(c):
    dk, ts = loc_quyen(c)
    tu, tt, kh = c.q.get("q", ""), c.q.get("tt", ""), c.q.get("kh", "")
    if tu:
        dk += " AND (o.so_dh LIKE ? OR k.ten LIKE ? OR o.id IN (SELECT don_hang_id FROM don_hang_dong WHERE ma LIKE ? OR ten LIKE ?))"
        ts += [f"%{tu}%"] * 4
    if kh.isdigit():
        dk += " AND o.khach_hang_id = ?"
        ts.append(int(kh))
    ds = [o_ for o_ in c.db.execute(SQL_DH + dk + " ORDER BY o.ngay DESC, o.id DESC", ts).fetchall()
          if tt not in dict(TT_DH) or tt_dh(o_) == tt]
    dong = "".join(
        f'<tr><td><a href="/don-hang/{o_["id"]}"><b>{e(o_["so_dh"])}</b></a></td><td>{ngay(o_["ngay"])}</td><td>{e(o_["khach"])}</td>'
        f'<td class="so">{tien(o_["gia_tri"])}</td><td class="so">{tien(o_["da_giao"])}</td>'
        f'<td>{e(o_["phu_trach"] or "—")}</td><td>{nhan_dh(o_)}</td></tr>' for o_ in ds)
    if ds:
        bang = ('<div class="the cuon"><table><thead><tr><th>Số đơn</th><th>Ngày</th><th>Khách hàng</th><th class="so">Giá trị (đ)</th>'
                f'<th class="so">Đã giao (đ)</th><th>Phụ trách</th><th>Tình trạng</th></tr></thead><tbody>{dong}</tbody></table></div>')
    else:
        bang = f'<div class="the trong">{"Không có đơn hàng nào khớp." if c.q else "Chưa có đơn hàng nào. Bấm Lập đơn hàng để bắt đầu."}</div>'
    return trang(c, "Đơn hàng", f"""
      <div class="dau-trang"><h1>Đơn hàng <span class="dem">{len(ds)}</span></h1><a class="nut" href="/don-hang/moi">Lập đơn hàng</a></div>
      <form class="bo-loc"><input type="search" name="q" value="{e(tu)}" placeholder="Số đơn, khách, mã hàng…">
        {chon("tt", TT_DH, tt, "Mọi tình trạng")}
        <button class="nut phu">Lọc</button>{'<a href="/don-hang">Bỏ lọc</a>' if c.q else ""}</form>
      {bang}""", "dh")


def o_dau_dh(c, o_=None, ten_kh=""):
    g = (lambda k, md="": o_[k] if o_ else md)
    pt = ""
    if c.ql:
        nd = c.db.execute("SELECT id, ho_ten FROM nguoi_dung WHERE hoat_dong = 1 ORDER BY ho_ten").fetchall()
        pt = f'<label>Người phụ trách{chon("phu_trach_id", [(u["id"], u["ho_ten"]) for u in nd], g("phu_trach_id", c.user["id"]))}</label>'
    tt = (f'<label>Tình trạng{chon("trang_thai", [("mo", "Đang thực hiện"), ("huy", "Hủy đơn")], o_["trang_thai"])}</label>' if o_ else "")
    return f"""
      {o("Số đơn hàng", "so_dh", g("so_dh", so_tiep(c, "don_hang", "so_dh", "DH")), bat_buoc=True)}
      {o("Ngày đặt hàng", "ngay", g("ngay", date.today().isoformat()), "date", True)}
      <label class="rong">Khách hàng <b class="sao">*</b><input name="ten_kh" value="{e(g("khach", ten_kh))}" list="ds-khach" required
        placeholder="Gõ để tìm trong danh sách khách hàng"></label>{goi_y_khach(c)}
      {pt}{tt}
      <label class="rong">Ghi chú (địa chỉ giao, người nhận, điều kiện thanh toán…)
        <textarea name="ghi_chu" rows="2">{e(g("ghi_chu"))}</textarea></label>"""


def doc_dau_dh(c, o_=None):
    gt = {"so_dh": c.chu("so_dh", "Số đơn hàng", True, 60), "ngay": c.ngay("ngay", "Ngày đặt hàng", True),
          "khach_hang_id": tim_khach(c)["id"], "ghi_chu": c.chu("ghi_chu", "Ghi chú", toi_da=1000)}
    gt["phu_trach_id"] = o_["phu_trach_id"] if o_ else c.user["id"]
    if c.ql:
        v = c.form.get("phu_trach_id", "")
        if not (v.isdigit() and c.db.execute("SELECT 1 FROM nguoi_dung WHERE id = ?", (int(v),)).fetchone()):
            raise Loi(400, "Chưa chọn người phụ trách.")
        gt["phu_trach_id"] = int(v)
    if o_:
        gt["trang_thai"] = "huy" if c.form.get("trang_thai") == "huy" else "mo"
        if o_["da_giao"] >= 0.5 and (gt["trang_thai"] == "huy" or gt["khach_hang_id"] != o_["khach_hang_id"]):
            raise Loi(400, "Đơn đã có phiếu giao hàng nên không hủy hoặc đổi khách được. Hãy xóa phiếu giao trước.")
    trung = c.db.execute("SELECT id FROM don_hang WHERE so_dh = ?", (gt["so_dh"],)).fetchone()
    if trung and (not o_ or trung["id"] != o_["id"]):
        raise Loi(400, f"Số đơn hàng {gt['so_dh']} đã có. Hãy đổi số khác.")
    return gt


def dh_them_dong(c, did, cac_dong):
    tt = c.db.execute("SELECT COALESCE(MAX(tt), 0) AS m FROM don_hang_dong WHERE don_hang_id = ?", (did,)).fetchone()["m"] or 0
    c.db.executemany("INSERT INTO don_hang_dong (don_hang_id, tt, hang_hoa_id, ma, ten, quy_cach, so_luong, don_gia) VALUES (?,?,?,?,?,?,?,?)",
                     [(did, tt + i, d["hang_hoa_id"], d["ma"], d["ten"], d["quy_cach"], d["so_luong"], d["don_gia"])
                      for i, d in enumerate(cac_dong, 1)])


def dh_moi(c):
    bg = lay_bg(c, int(c.q["bg"])) if c.q.get("bg", "").isdigit() else None
    if c.method == "POST":
        gt = doc_dau_dh(c)
        bid = c.form.get("bao_gia_id", "")
        bg = lay_bg(c, int(bid)) if bid.isdigit() else None
        if bg:
            gt["bao_gia_id"] = bg["id"]
        try:
            did = c.db.them(f"INSERT INTO don_hang ({', '.join(gt)}, tao_luc) VALUES ({'?, ' * len(gt)}?)",
                            list(gt.values()) + [datetime.now().isoformat(timespec="seconds")])
        except LOI_TRUNG:
            c.db.rollback()
            raise Loi(400, f"Số đơn hàng {gt['so_dh']} đã có. Hãy đổi số khác.")
        tb = "Đã tạo đơn hàng. Tìm và chọn hàng ở mục Thêm hàng bên dưới."
        if bg:
            theo_ma = {}
            for h in c.db.execute("SELECT id, ma FROM hang_hoa WHERE ma <> '' ORDER BY id DESC").fetchall():
                theo_ma[gap(h["ma"])] = h["id"]
            dh_them_dong(c, did, [dict(hang_hoa_id=theo_ma.get(gap(d["ma"])) if d["ma"] else None, ma=d["ma"], ten=d["ten_tm"] or d["ten"],
                                       quy_cach=d["quy_cach"], so_luong=d["so_luong"], don_gia=d["don_gia"]) for d in dong_cua_bg(c, bg["id"])])
            if bg["trang_thai"] in ("nhap", "da_gui"):
                c.db.execute("UPDATE bao_gia SET trang_thai = 'dong_y' WHERE id = ?", (bg["id"],))
            tb = f"Đã tạo đơn hàng từ báo giá {bg['so_bg']}. Kiểm tra lại số lượng và đơn giá."
        c.db.commit()
        return Chuyen(f"/don-hang/{did}", tb)
    an = f'<input type="hidden" name="bao_gia_id" value="{bg["id"]}">' if bg else ""
    tu_bg = f'<p class="mo">Lấy hàng, số lượng và đơn giá từ báo giá <a href="/bao-gia/{bg["id"]}">{e(bg["so_bg"])}</a>.</p>' if bg else ""
    return trang(c, "Lập đơn hàng", f"""
      <h1>Lập đơn hàng</h1>{tu_bg}
      <div class="the"><form method="post" action="/don-hang/moi" class="luoi">{an_csrf(c)}{an}{o_dau_dh(c, ten_kh=bg["ten_kh"] if bg else "")}
        <div class="hang-nut"><button class="nut">{"Tạo đơn hàng" if bg else "Tạo và chọn hàng"}</button><a href="/don-hang">Hủy</a></div></form></div>
      <p class="mo">Đơn giá trong đơn hàng là giá đã gồm thuế VAT. Công nợ của khách được ghi nhận mỗi lần giao hàng.</p>""", "dhm")


def dh_sua(c, did):
    o_ = lay_dh(c, did)
    gt = doc_dau_dh(c, o_)
    c.db.execute(f"UPDATE don_hang SET {', '.join(k + ' = ?' for k in gt)} WHERE id = ?", list(gt.values()) + [did])
    c.db.commit()
    return Chuyen(f"/don-hang/{did}", "Đã lưu thông tin đơn hàng.")


def dh_xoa(c, did):
    o_ = lay_dh(c, did)
    if not c.duoc_xoa:
        raise Loi(403, "Bạn chưa được cấp quyền xóa. Hãy nhờ quản lý.")
    if c.db.execute("SELECT 1 FROM phieu_xuat WHERE don_hang_id = ?", (did,)).fetchone():
        raise Loi(400, "Đơn đã có phiếu giao hàng nên không xóa được. Hãy xóa phiếu giao trước.")
    c.db.execute("DELETE FROM don_hang_dong WHERE don_hang_id = ?", (did,))
    c.db.execute("DELETE FROM don_hang WHERE id = ?", (did,))
    c.db.commit()
    return Chuyen("/don-hang", f"Đã xóa đơn hàng {o_['so_dh']}.")


def dh_xem(c, did):
    o_ = lay_dh(c, did)
    dong = dong_cua_dh(c, did)
    tim = c.q.get("tim", "")
    mo = o_["trang_thai"] != "huy"
    ton = ton_theo_hang(ton_kho(c))
    co_kho = bool(ton)

    def o_ton(hh):
        if not hh or not co_kho:
            return '<td class="so mo">—</td>'
        return f'<td class="so">{sl(ton.get(hh, 0))}</td>'

    hang = ""
    for i, d in enumerate(dong, 1):
        khoa_gia = " readonly" if d["da_giao"] > 0 else ""
        bo = "" if d["da_giao"] > 0 else f'<button class="nut-chu nguy" name="xoa" value="{d["id"]}">Bỏ</button>'
        hang += (f'<tr><td class="so">{i}</td><td>{e(d["ten"])}<br><span class="mo">{e(d["ma"])} · {e(d["quy_cach"])}</span></td>'
                 f'<td class="so"><input class="o-nho" type="number" min="0" step="any" name="sl_{d["id"]}" value="{so_o(d["so_luong"])}" aria-label="Số lượng"></td>'
                 f'<td class="so"><input class="o-nho" type="number" min="0" step="any" name="gia_{d["id"]}" value="{so_o(d["don_gia"])}"{khoa_gia} aria-label="Đơn giá"></td>'
                 f'<td class="so">{tien(d["so_luong"] * d["don_gia"])}</td><td class="so">{sl(d["da_giao"])}</td>'
                 f'<td class="so">{sl(d["so_luong"] - d["da_giao"])}</td>{o_ton(d["hang_hoa_id"])}<td class="thao-tac">{bo}</td></tr>')
    if dong:
        bang = (f'<form method="post" action="/don-hang/{did}/dong">{an_csrf(c)}<button class="nut-an" tabindex="-1" aria-hidden="true"></button>'
                '<div class="cuon"><table><thead><tr><th class="so">STT</th><th>Hàng hóa</th><th class="so">Số lượng</th><th class="so">Đơn giá (đ)</th>'
                '<th class="so">Thành tiền</th><th class="so">Đã giao</th><th class="so">Còn lại</th><th class="so">Tồn kho</th><th></th></tr></thead>'
                f'<tbody>{hang}<tr><td colspan="4" class="so"><b>Tổng cộng</b></td><td class="so"><b>{tien(o_["gia_tri"])}</b></td>'
                '<td colspan="4"></td></tr></tbody></table></div>'
                '<div class="hang-nut"><button class="nut phu">Lưu số lượng và giá</button>'
                '<span class="mo">Dòng đã giao hàng thì không đổi được đơn giá.</span></div></form>')
    else:
        bang = '<p class="mo">Chưa có hàng nào. Tìm hàng ở mục Thêm hàng bên dưới.</p>'

    # giao hàng: mỗi lần giao là một phiếu xuất, sinh công nợ
    con_giao = [d for d in dong if d["so_luong"] - d["da_giao"] > 1e-9]
    giao = ""
    if mo and con_giao:
        dg = "".join(
            f'<tr><td>{e(d["ten"])}<br><span class="mo">{e(d["ma"])}</span></td><td class="so">{sl(d["so_luong"] - d["da_giao"])}</td>'
            f'{o_ton(d["hang_hoa_id"])}<td class="so"><input class="o-nho" type="number" min="0" step="any" max="{so_o(d["so_luong"] - d["da_giao"])}" '
            f'name="sl_{d["id"]}" value="{so_o(d["so_luong"] - d["da_giao"])}" aria-label="Số lượng giao"></td></tr>' for d in con_giao)
        han = o_["han_no"] if o_["han_no"] is not None else 30
        giao = f"""<div class="the"><h2>Giao hàng</h2>
          <form method="post" action="/don-hang/{did}/giao">{an_csrf(c)}<div class="luoi">
            {o("Số phiếu xuất", "so_px", so_tiep(c, "phieu_xuat", "so_px", "PX"), bat_buoc=True)}
            {o("Ngày giao", "ngay", date.today().isoformat(), "date", True)}
            {o("Số hóa đơn VAT (nếu đã xuất)", "so_hoa_don")}{o("Ghi chú", "ghi_chu")}</div>
            <div class="cuon cach-tren"><table><thead><tr><th>Hàng hóa</th><th class="so">Còn phải giao</th><th class="so">Tồn kho</th>
              <th class="so">Giao lần này</th></tr></thead><tbody>{dg}</tbody></table></div>
            <div class="hang-nut"><button class="nut">Lập phiếu giao hàng</button>
              <span class="mo">Khách được nợ {han} ngày kể từ ngày giao. Kho tự xuất lô có hạn dùng gần nhất trước.</span></div></form></div>"""

    # các phiếu đã giao
    ph = {}
    for r in dong_xuat(c, " AND o.id = ?", [did]):
        p = ph.setdefault(r["px_id"], dict(r, hang=[], gia_tri=0))
        p["gia_tri"] += r["so_luong"] * r["don_gia"]
        lo = f' (lô {e(r["so_lo"])}{", HSD " + ngay(r["han_dung"]) if r["han_dung"] else ""})' if r["so_lo"] or r["han_dung"] else ""
        p["hang"].append(f'{e(r["ma"] or r["ten"])} × {sl(r["so_luong"])}{lo}')
    da_giao = ""
    if ph:
        dp = "".join(
            f'<tr><td><b>{e(p["so_px"])}</b></td><td>{ngay(p["ngay"])}</td><td>{"<br>".join(p["hang"])}</td><td class="so">{tien(p["gia_tri"])}</td>'
            f'<td>{ngay(p["han_tt"])}</td><td>{e(p["so_hoa_don"]) or "—"}</td><td class="thao-tac">'
            + (nut_xoa(c, f'/phieu-xuat/{p["px_id"]}/xoa', f"Xóa phiếu giao {p['so_px']}? Công nợ và tồn kho của phiếu này sẽ được hoàn lại.")
               if c.duoc_xoa else "") + '</td></tr>' for p in ph.values())
        da_giao = ('<div class="the"><h2>Phiếu giao hàng <span class="dem">%d</span></h2><div class="cuon"><table><thead><tr><th>Số phiếu</th>'
                   '<th>Ngày giao</th><th>Hàng</th><th class="so">Giá trị (đ)</th><th>Hạn thanh toán</th><th>Hóa đơn</th><th></th></tr></thead>'
                   '<tbody>%s</tbody></table></div></div>' % (len(ph), dp))

    # tìm hàng trong danh mục để thêm
    kq_tim = ""
    if tim:
        dk, ts = dk_tim_hang(tim)
        ds = c.db.execute(f"SELECT * FROM hang_hoa WHERE 1=1{dk} ORDER BY id LIMIT 60", ts).fetchall()
        if ds:
            dh = "".join(
                f'<tr><td>{e(h["ten_tm"] or h["ten"])}</td><td>{e(h["ma"])}</td><td>{e(h["nhan_hieu"])}</td><td>{e(h["quy_cach"])}</td>'
                f'<td class="so">{tien(h["gia_ban"]) if h["gia_ban"] else ""}</td>{o_ton(h["id"])}'
                f'<td class="so"><input class="o-nho" type="number" min="0" step="any" name="sl_{h["id"]}" aria-label="Số lượng đặt"></td></tr>' for h in ds)
            kq_tim = (f'<form method="post" action="/don-hang/{did}/them">{an_csrf(c)}<div class="cuon"><table><thead><tr><th>Tên hàng</th>'
                      '<th>Ký mã hiệu</th><th>Nhãn hiệu</th><th>Quy cách</th><th class="so">Giá bán (đ)</th><th class="so">Tồn kho</th>'
                      f'<th class="so">Số lượng đặt</th></tr></thead><tbody>{dh}</tbody></table></div>'
                      '<div class="hang-nut"><button class="nut">Thêm các hàng đã nhập số lượng</button></div></form>')
        else:
            kq_tim = '<p class="mo">Không có hàng nào khớp trong danh mục.</p>'
    them = ""
    if mo:
        them = f"""<div class="the"><h2>Thêm hàng</h2>
        <form class="bo-loc"><input type="search" name="tim" value="{e(tim)}" placeholder="Gõ tên, ký mã hiệu, nhãn hiệu… ví dụ: HIV khay" {"autofocus" if tim else ""}>
          <button class="nut phu">Tìm</button></form>{kq_tim}</div>
      <details class="the"><summary>Thêm hàng không có trong danh mục (không theo dõi tồn kho)</summary>
        <form method="post" action="/don-hang/{did}/them-tay" class="luoi">{an_csrf(c)}
          {o("Tên hàng", "ten", bat_buoc=True)}{o("Ký mã hiệu", "ma")}{o("Quy cách", "quy_cach")}
          {o("Số lượng", "so_luong", kieu="number", bat_buoc=True, them='min="0" step="any"')}
          {o("Đơn giá (đ)", "don_gia", kieu="number", them='min="0" step="any"')}
          <div class="hang-nut"><button class="nut phu">Thêm dòng</button></div></form></details>"""
    tu_bg = ""
    if o_["bao_gia_id"]:
        b = c.db.execute("SELECT so_bg FROM bao_gia WHERE id = ?", (o_["bao_gia_id"],)).fetchone()
        tu_bg = f'<dt>Từ báo giá</dt><dd><a href="/bao-gia/{o_["bao_gia_id"]}">{e(b["so_bg"])}</a></dd>' if b else ""
    xoa = nut_xoa(c, f"/don-hang/{did}/xoa", f"Xóa đơn hàng {o_['so_dh']}? Không khôi phục được.", "Xóa đơn hàng") if c.duoc_xoa and not ph else ""
    return trang(c, f"Đơn hàng {o_['so_dh']}", f"""
      <div class="dau-trang"><h1>Đơn hàng {e(o_["so_dh"])} {nhan_dh(o_)}</h1>
        <a class="nut phu" href="/cong-no/{o_["khach_hang_id"]}">Công nợ của khách</a></div>
      <div class="the"><dl class="thong-tin"><dt>Khách hàng</dt><dd><a href="/khach-hang/{o_["khach_hang_id"]}">{e(o_["khach"])}</a></dd>
        <dt>Ngày đặt</dt><dd>{ngay(o_["ngay"])}</dd><dt>Phụ trách</dt><dd>{e(o_["phu_trach"] or "—")}</dd>
        <dt>Giá trị / đã giao</dt><dd>{tien(o_["gia_tri"])} / {tien(o_["da_giao"])} đ</dd>{tu_bg}
        {f'<dt>Ghi chú</dt><dd>{e(o_["ghi_chu"])}</dd>' if o_["ghi_chu"] else ""}</dl></div>
      <div class="the"><h2>Hàng trong đơn <span class="dem">{len(dong)}</span></h2>{bang}</div>
      {giao}{da_giao}{them}
      <details class="the"><summary>Sửa thông tin, hủy đơn</summary>
        <form method="post" action="/don-hang/{did}/sua" class="luoi">{an_csrf(c)}{o_dau_dh(c, o_)}
          <div class="hang-nut"><button class="nut">Lưu</button></div></form></details>
      {xoa}""", "dh")


def dh_dong_luu(c, did):
    lay_dh(c, did)
    dong = dong_cua_dh(c, did)
    xoa = c.form.get("xoa", "")
    if xoa.isdigit():
        if any(d["id"] == int(xoa) and d["da_giao"] > 0 for d in dong):
            raise Loi(400, "Dòng này đã giao hàng nên không bỏ được.")
        c.db.execute("DELETE FROM don_hang_dong WHERE id = ? AND don_hang_id = ?", (int(xoa), did))
        c.db.commit()
        return Chuyen(f"/don-hang/{did}", "Đã bỏ một dòng hàng.")
    for d in dong:
        n, gia = c.so(f"sl_{d['id']}", "Số lượng"), c.so(f"gia_{d['id']}", "Đơn giá")
        if n < d["da_giao"] - 1e-9:
            raise Loi(400, f"{d['ma'] or d['ten']}: đã giao {sl(d['da_giao'])}, số lượng đặt không thể nhỏ hơn.")
        if d["da_giao"] > 0:
            gia = d["don_gia"]
        c.db.execute("UPDATE don_hang_dong SET so_luong = ?, don_gia = ? WHERE id = ?", (n, gia, d["id"]))
    c.db.commit()
    return Chuyen(f"/don-hang/{did}", "Đã lưu số lượng và giá.")


def so_luong_theo_o(c, dau="sl_"):
    """{id: số lượng} từ các ô sl_<id> có nhập số lớn hơn 0."""
    kq = {}
    for k in c.form:
        if k.startswith(dau) and k[len(dau):].isdigit():
            n = c.so(k, "Số lượng")
            if n > 0:
                kq[int(k[len(dau):])] = n
    return kq


def dh_them(c, did):
    lay_dh(c, did)
    sl_ = so_luong_theo_o(c)
    if not sl_:
        raise Loi(400, "Chưa nhập số lượng cho hàng nào.")
    ids = list(sl_)[:200]
    ds = c.db.execute(f"SELECT * FROM hang_hoa WHERE id IN ({', '.join('?' * len(ids))}) ORDER BY id", ids).fetchall()
    dh_them_dong(c, did, [dict(hang_hoa_id=h["id"], ma=h["ma"], ten=h["ten_tm"] or h["ten"], quy_cach=h["quy_cach"],
                               so_luong=sl_[h["id"]], don_gia=h["gia_ban"] or 0) for h in ds])
    c.db.commit()
    return Chuyen(f"/don-hang/{did}", f"Đã thêm {len(ds)} hàng vào đơn, đơn giá lấy theo giá bán trong danh mục.")


def dh_them_tay(c, did):
    lay_dh(c, did)
    dh_them_dong(c, did, [dict(hang_hoa_id=None, ma=c.chu("ma", "Ký mã hiệu", toi_da=200), ten=c.chu("ten", "Tên hàng", True),
                               quy_cach=c.chu("quy_cach", "Quy cách", toi_da=200), so_luong=c.so("so_luong", "Số lượng", True),
                               don_gia=c.so("don_gia", "Đơn giá"))])
    c.db.commit()
    return Chuyen(f"/don-hang/{did}", "Đã thêm một dòng hàng.")


def dh_giao(c, did):
    o_ = lay_dh(c, did)
    if o_["trang_thai"] == "huy":
        raise Loi(400, "Đơn hàng đã hủy.")
    ng, so_px = c.ngay("ngay", "Ngày giao", True), c.chu("so_px", "Số phiếu xuất", True, 60)
    ton = ton_kho(c)
    co_kho = bool(ton)
    them, thieu = [], []
    for d in dong_cua_dh(c, did):
        n = c.so(f"sl_{d['id']}", f"Số lượng {d['ma']}")
        if n <= 0:
            continue
        con = d["so_luong"] - d["da_giao"]
        if n > con + 1e-9:
            raise Loi(400, f"{d['ma'] or d['ten']} chỉ còn {sl(con)} chưa giao, không thể giao {sl(n)}.")
        if d["hang_hoa_id"]:
            cac_lo, th = phan_lo(ton, d["hang_hoa_id"], n, ng)
            them += [(d["id"], lo, hd, q) for lo, hd, q in cac_lo]
            if th and co_kho:
                thieu.append(f"{d['ma'] or d['ten']} (thiếu {sl(th)})")
        else:
            them.append((d["id"], "", "", n))
    if not them:
        raise Loi(400, "Chưa nhập số lượng giao cho hàng nào.")
    han = o_["han_no"] if o_["han_no"] is not None else 30
    han_tt = (date.fromisoformat(ng) + timedelta(days=han)).isoformat()
    try:
        pid = c.db.them("INSERT INTO phieu_xuat (so_px, don_hang_id, ngay, han_tt, so_hoa_don, ghi_chu, nguoi_nhap_id) VALUES (?,?,?,?,?,?,?)",
                        (so_px, did, ng, han_tt, c.chu("so_hoa_don", "Số hóa đơn", toi_da=60), c.chu("ghi_chu", "Ghi chú"), c.user["id"]))
    except LOI_TRUNG:
        c.db.rollback()
        raise Loi(400, f"Số phiếu xuất {so_px} đã có. Hãy đổi số khác.")
    c.db.executemany("INSERT INTO phieu_xuat_dong (phieu_xuat_id, don_hang_dong_id, so_lo, han_dung, so_luong) VALUES (?,?,?,?,?)",
                     [(pid,) + t for t in them])
    c.db.commit()
    tb = f"Đã lập phiếu giao {so_px}, hạn thanh toán {ngay(han_tt)}."
    if thieu:
        tb += " Lưu ý kho không đủ hàng còn hạn dùng: " + ", ".join(thieu) + " — phần thiếu được xuất không ghi lô."
    return Chuyen(f"/don-hang/{did}", tb)


def px_xoa(c, pid):
    p = c.db.execute("SELECT * FROM phieu_xuat WHERE id = ?", (pid,)).fetchone()
    if not p:
        raise Loi(404, "Không tìm thấy phiếu giao hàng.")
    lay_dh(c, p["don_hang_id"])
    if not c.duoc_xoa:
        raise Loi(403, "Bạn chưa được cấp quyền xóa. Hãy nhờ quản lý.")
    c.db.execute("DELETE FROM phieu_xuat_dong WHERE phieu_xuat_id = ?", (pid,))
    c.db.execute("DELETE FROM phieu_xuat WHERE id = ?", (pid,))
    c.db.commit()
    return Chuyen(f"/don-hang/{p['don_hang_id']}", f"Đã xóa phiếu giao {p['so_px']}.")


# ───────────────────────── công nợ phải thu ─────────────────────────

def dong_xuat(c, dk="", ts=()):
    """Mọi dòng hàng đã giao kèm phiếu, đơn hàng — nền để tính công nợ và doanh số."""
    return c.db.execute(
        "SELECT x.so_luong, x.so_lo, x.han_dung, d.don_gia, d.hang_hoa_id, d.ma, d.ten, p.id AS px_id, p.so_px, p.ngay, p.han_tt, "
        "p.so_hoa_don, o.id AS dh_id, o.so_dh, o.khach_hang_id, o.phu_trach_id "
        "FROM phieu_xuat_dong x JOIN phieu_xuat p ON p.id = x.phieu_xuat_id JOIN don_hang_dong d ON d.id = x.don_hang_dong_id "
        f"JOIN don_hang o ON o.id = p.don_hang_id WHERE 1=1{dk} ORDER BY p.ngay, p.id, x.id", ts).fetchall()


def no_phai_thu(c, kid=None):
    dk, ts = ("", []) if kid is None else (" AND o.khach_hang_id = ?", [kid])
    nhom, ph = {}, {}
    for r in dong_xuat(c, dk, ts):
        if r["px_id"] not in ph:
            ph[r["px_id"]] = dict(r, gia_tri=0)
            nhom.setdefault(r["khach_hang_id"], {"phieu": [], "da_tra": 0})["phieu"].append(ph[r["px_id"]])
        ph[r["px_id"]]["gia_tri"] += r["so_luong"] * r["don_gia"]
    for t in c.db.execute("SELECT khach_hang_id, so_tien FROM thu_tien" + (" WHERE khach_hang_id = ?" if kid else ""), ts).fetchall():
        nhom.setdefault(t["khach_hang_id"], {"phieu": [], "da_tra": 0})["da_tra"] += t["so_tien"]
    return xep_no(nhom)


def o_so_no(n, tu_tra="Đã thu"):
    return f"""<div class="o-so">
        <div class="the"><span>Còn nợ (đ)</span><b>{tien(n["con_no"])}</b></div>
        <div class="the"><span>Trong đó quá hạn (đ)</span><b>{tien(n["qua_han"])}</b></div>
        <div class="the"><span>Phát sinh (đ)</span><b>{tien(n["phat_sinh"])}</b></div>
        <div class="the"><span>{tu_tra} (đ)</span><b>{tien(n["da_tra"])}</b></div></div>"""


def cong_no(c):
    nhom = no_phai_thu(c)
    ten = {k["id"]: k["ten"] for k in c.db.execute("SELECT id, ten FROM khach_hang").fetchall()}
    if not nhom:
        than = '<div class="the trong">Chưa có công nợ. Công nợ phát sinh khi lập phiếu giao hàng trong đơn hàng.</div>'
    else:
        tong = dict(con_no=sum(n["con_no"] - n["tra_thua"] for n in nhom.values()), qua_han=sum(n["qua_han"] for n in nhom.values()),
                    phat_sinh=sum(n["phat_sinh"] for n in nhom.values()), da_tra=sum(n["da_tra"] for n in nhom.values()))
        than = o_so_no(tong) + '<h2>Theo khách hàng và tuổi nợ</h2>' + bang_no(nhom, ten, "/cong-no")
    return trang(c, "Công nợ phải thu", f"""
      <h1>Công nợ phải thu</h1>
      <p class="mo">Bấm tên khách để xem từng phiếu giao và ghi phiếu thu. Tiền thu được trừ vào phiếu giao cũ nhất trước.</p>{than}""", "cn")


def cong_no_xem(c, kid):
    k = c.db.execute("SELECT * FROM khach_hang WHERE id = ?", (kid,)).fetchone()
    if not k:
        raise Loi(404, "Không tìm thấy khách hàng.")
    n = no_phai_thu(c, kid).get(kid) or xep_no({0: {"phieu": [], "da_tra": 0}})[0]
    dong = "".join(
        f'<tr><td><b>{e(p["so_px"])}</b></td><td><a href="/don-hang/{p["dh_id"]}">{e(p["so_dh"])}</a></td><td>{ngay(p["ngay"])}</td>'
        f'<td>{e(p["so_hoa_don"]) or "—"}</td><td class="so">{tien(p["gia_tri"])}</td><td class="so">{tien(p["con_lai"])}</td>'
        f'<td>{ngay(p["han_tt"])}</td><td>{nhan_no(p)}</td></tr>' for p in reversed(n["phieu"]))
    bang = ('<div class="cuon"><table><thead><tr><th>Phiếu giao</th><th>Đơn hàng</th><th>Ngày giao</th><th>Hóa đơn</th>'
            '<th class="so">Giá trị (đ)</th><th class="so">Còn nợ</th><th>Hạn thanh toán</th><th>Tình trạng</th></tr></thead>'
            f'<tbody>{dong}</tbody></table></div>') if n["phieu"] else '<p class="mo">Chưa có phiếu giao hàng nào.</p>'
    thu = c.db.execute("SELECT * FROM thu_tien WHERE khach_hang_id = ? ORDER BY ngay DESC, id DESC", (kid,)).fetchall()
    thua = f'<p class="thong-bao">Khách đang trả thừa {tien(n["tra_thua"])} đ, sẽ trừ vào lần giao hàng tới.</p>' if n["tra_thua"] else ""
    return trang(c, f"Công nợ {k['ten']}", f"""
      <div class="dau-trang"><h1>Công nợ: {e(k["ten"])}</h1><a class="nut phu" href="/don-hang?kh={kid}">Đơn hàng của khách</a></div>
      <p class="mo">Khách được nợ {k["han_no"] if k["han_no"] is not None else 30} ngày kể từ ngày giao
        (đổi ở <a href="/khach-hang/{kid}">thông tin khách hàng</a>).</p>
      {o_so_no(n)}{thua}
      <div class="the cach-tren"><h2>Ghi phiếu thu</h2><form method="post" action="/cong-no/{kid}/thu" class="luoi">{an_csrf(c)}
        {o_tien(c, "PT", "thu_tien", "so_pt")}<div class="hang-nut"><button class="nut">Ghi thu tiền</button></div></form></div>
      <div class="the"><h2>Phiếu giao hàng <span class="dem">{len(n["phieu"])}</span></h2>{bang}</div>
      <div class="the"><h2>Phiếu thu <span class="dem">{len(thu)}</span></h2>{bang_tien(c, thu, "so_pt", "/thu-tien")}</div>""", "cn")


def thu_tien_them(c, kid):
    if not c.db.execute("SELECT 1 FROM khach_hang WHERE id = ?", (kid,)).fetchone():
        raise Loi(404, "Không tìm thấy khách hàng.")
    so, tien_ = luu_tien(c, "thu_tien", "so_pt", "khach_hang_id", kid)
    return Chuyen(f"/cong-no/{kid}", f"Đã ghi phiếu thu {so}: {tien(tien_)} đ.")


def thu_tien_xoa(c, tid):
    t = c.db.execute("SELECT * FROM thu_tien WHERE id = ?", (tid,)).fetchone()
    if not t:
        raise Loi(404, "Không tìm thấy phiếu thu.")
    c.db.execute("DELETE FROM thu_tien WHERE id = ?", (tid,))
    c.db.commit()
    return Chuyen(f"/cong-no/{t['khach_hang_id']}", f"Đã xóa phiếu thu {t['so_pt']}.")


# ───────────────────────── nhà cung cấp, nhập kho, nợ phải trả ─────────────────────────

COT_NCC = [("ten", "Tên nhà cung cấp", 300), ("ma_so_thue", "Mã số thuế", 20), ("dia_chi", "Địa chỉ", 500), ("lien_he", "Người liên hệ", 100),
           ("dien_thoai", "Điện thoại", 50), ("email", "Email", 200), ("ghi_chu", "Ghi chú", 1000)]


def o_ncc(n=None):
    return "".join(o(nhan, t, n[t] if n else "", bat_buoc=(t == "ten")) for t, nhan, _ in COT_NCC)


def doc_ncc(c):
    return [c.chu(t, nhan, t == "ten", dai) for t, nhan, dai in COT_NCC]


def nha_cung_cap(c):
    if c.method == "POST":
        try:
            c.db.execute(f"INSERT INTO nha_cung_cap ({', '.join(t for t, _, _ in COT_NCC)}) VALUES ({', '.join('?' * len(COT_NCC))})", doc_ncc(c))
        except LOI_TRUNG:
            c.db.rollback()
            raise Loi(400, "Đã có nhà cung cấp trùng tên này.")
        c.db.commit()
        return Chuyen("/nha-cung-cap", "Đã thêm nhà cung cấp.")
    ds = c.db.execute("SELECT * FROM nha_cung_cap ORDER BY ten").fetchall()
    dong = "".join(f'<tr><td><a href="/nha-cung-cap/{n["id"]}">{e(n["ten"])}</a></td><td>{e(n["ma_so_thue"])}</td><td>{e(n["lien_he"])}</td>'
                   f'<td>{e(n["dien_thoai"])}</td><td class="thao-tac"><a href="/phai-tra/{n["id"]}">Công nợ</a></td></tr>' for n in ds)
    bang = ('<div class="the cuon"><table><thead><tr><th>Tên</th><th>Mã số thuế</th><th>Liên hệ</th><th>Điện thoại</th><th></th></tr></thead>'
            f'<tbody>{dong}</tbody></table></div>') if ds else '<div class="the trong">Chưa có nhà cung cấp nào. Thêm ở bên dưới.</div>'
    return trang(c, "Nhà cung cấp", f"""
      <h1>Nhà cung cấp <span class="dem">{len(ds)}</span></h1>{bang}
      <div class="the"><h2>Thêm nhà cung cấp</h2><form method="post" class="luoi">{an_csrf(c)}{o_ncc()}
        <div class="hang-nut"><button class="nut">Thêm</button></div></form></div>""", "ncc")


def lay_ncc(c, nid):
    n = c.db.execute("SELECT * FROM nha_cung_cap WHERE id = ?", (nid,)).fetchone()
    if not n:
        raise Loi(404, "Không tìm thấy nhà cung cấp.")
    return n


def ncc_sua(c, nid):
    n = lay_ncc(c, nid)
    if c.method == "POST":
        try:
            c.db.execute(f"UPDATE nha_cung_cap SET {', '.join(t + ' = ?' for t, _, _ in COT_NCC)} WHERE id = ?", doc_ncc(c) + [nid])
        except LOI_TRUNG:
            c.db.rollback()
            raise Loi(400, "Đã có nhà cung cấp trùng tên này.")
        c.db.commit()
        return Chuyen("/nha-cung-cap", "Đã lưu.")
    return trang(c, n["ten"], f"""
      <div class="dau-trang"><h1>{e(n["ten"])}</h1><a class="nut phu" href="/phai-tra/{nid}">Công nợ</a></div>
      <div class="the"><form method="post" class="luoi">{an_csrf(c)}{o_ncc(n)}
        <div class="hang-nut"><button class="nut">Lưu</button><a href="/nha-cung-cap">Hủy</a></div></form></div>""", "ncc")


SQL_PN = ("SELECT p.*, n.ten AS ncc, "
          "(SELECT COUNT(*) FROM phieu_nhap_dong d WHERE d.phieu_nhap_id = p.id) AS so_dong, "
          "COALESCE((SELECT SUM(d.so_luong * d.don_gia) FROM phieu_nhap_dong d WHERE d.phieu_nhap_id = p.id), 0) AS gia_tri "
          "FROM phieu_nhap p LEFT JOIN nha_cung_cap n ON n.id = p.nha_cung_cap_id WHERE 1=1")


def lay_pn(c, pid):
    p = c.db.execute(SQL_PN + " AND p.id = ?", (pid,)).fetchone()
    if not p:
        raise Loi(404, "Không tìm thấy phiếu nhập.")
    return p


def ds_nhap_kho(c):
    ds = c.db.execute(SQL_PN + " ORDER BY p.ngay DESC, p.id DESC").fetchall()
    dong = "".join(
        f'<tr><td><a href="/nhap-kho/{p["id"]}"><b>{e(p["so_pn"])}</b></a></td><td>{ngay(p["ngay"])}</td>'
        f'<td>{e(p["ncc"]) if p["ncc"] else "<span class=mo>Tồn đầu kỳ / nhập khác</span>"}</td><td>{e(p["so_hoa_don"]) or "—"}</td>'
        f'<td class="so">{p["so_dong"]}</td><td class="so">{tien(p["gia_tri"])}</td></tr>' for p in ds)
    bang = ('<div class="the cuon"><table><thead><tr><th>Số phiếu</th><th>Ngày nhập</th><th>Nhà cung cấp</th><th>Hóa đơn</th>'
            f'<th class="so">Mặt hàng</th><th class="so">Giá trị (đ)</th></tr></thead><tbody>{dong}</tbody></table></div>') if ds else (
        '<div class="the trong">Chưa có phiếu nhập nào. Lập phiếu đầu tiên để ghi tồn đầu kỳ hoặc hàng mua về.</div>')
    return trang(c, "Nhập kho", f"""
      <div class="dau-trang"><h1>Nhập kho / mua hàng <span class="dem">{len(ds)}</span></h1><a class="nut" href="/nhap-kho/moi">Lập phiếu nhập</a></div>
      {bang}""", "pn")


def o_dau_pn(c, p=None):
    g = (lambda k, md="": p[k] if p else md)
    ncc = c.db.execute("SELECT id, ten FROM nha_cung_cap ORDER BY ten").fetchall()
    return f"""
      {o("Số phiếu nhập", "so_pn", g("so_pn", so_tiep(c, "phieu_nhap", "so_pn", "PN")), bat_buoc=True)}
      {o("Ngày nhập", "ngay", g("ngay", date.today().isoformat()), "date", True)}
      <label>Nhà cung cấp{chon("nha_cung_cap_id", [(n["id"], n["ten"]) for n in ncc], g("nha_cung_cap_id") or "", "Không có (tồn đầu kỳ / nhập khác)")}</label>
      {o("Số hóa đơn mua", "so_hoa_don", g("so_hoa_don"))}{o("Hạn thanh toán", "han_tt", g("han_tt"), "date")}
      {o("Ghi chú", "ghi_chu", g("ghi_chu"))}"""


def doc_dau_pn(c, p=None):
    gt = {"so_pn": c.chu("so_pn", "Số phiếu nhập", True, 60), "ngay": c.ngay("ngay", "Ngày nhập", True),
          "so_hoa_don": c.chu("so_hoa_don", "Số hóa đơn", toi_da=60), "han_tt": c.ngay("han_tt", "Hạn thanh toán"),
          "ghi_chu": c.chu("ghi_chu", "Ghi chú", toi_da=1000), "nha_cung_cap_id": None}
    v = c.form.get("nha_cung_cap_id", "")
    if v.isdigit():
        gt["nha_cung_cap_id"] = lay_ncc(c, int(v))["id"]
    trung = c.db.execute("SELECT id FROM phieu_nhap WHERE so_pn = ?", (gt["so_pn"],)).fetchone()
    if trung and (not p or trung["id"] != p["id"]):
        raise Loi(400, f"Số phiếu nhập {gt['so_pn']} đã có. Hãy đổi số khác.")
    return gt


def pn_moi(c):
    if c.method == "POST":
        gt = doc_dau_pn(c)
        gt["nguoi_nhap_id"] = c.user["id"]
        try:
            pid = c.db.them(f"INSERT INTO phieu_nhap ({', '.join(gt)}) VALUES ({', '.join('?' * len(gt))})", list(gt.values()))
        except LOI_TRUNG:
            c.db.rollback()
            raise Loi(400, f"Số phiếu nhập {gt['so_pn']} đã có. Hãy đổi số khác.")
        c.db.commit()
        return Chuyen(f"/nhap-kho/{pid}", "Đã tạo phiếu nhập. Tìm hàng rồi nhập số lượng, số lô, hạn dùng bên dưới.")
    return trang(c, "Lập phiếu nhập", f"""
      <h1>Lập phiếu nhập kho</h1>
      <div class="the"><form method="post" class="luoi">{an_csrf(c)}{o_dau_pn(c)}
        <div class="hang-nut"><button class="nut">Tạo và chọn hàng</button><a href="/nhap-kho">Hủy</a></div></form></div>
      <p class="mo">Chọn nhà cung cấp thì giá trị phiếu được tính vào nợ phải trả. Để trống khi nhập tồn đầu kỳ.
        Chưa có nhà cung cấp trong danh sách? <a href="/nha-cung-cap">Thêm nhà cung cấp</a> trước.</p>""", "pn")


def pn_xem(c, pid):
    p = lay_pn(c, pid)
    tim = c.q.get("tim", "")
    dong = c.db.execute("SELECT d.*, h.ten, h.ten_tm, h.ma, h.quy_cach FROM phieu_nhap_dong d JOIN hang_hoa h ON h.id = d.hang_hoa_id "
                        "WHERE d.phieu_nhap_id = ? ORDER BY d.id", (pid,)).fetchall()
    hang = "".join(
        f'<tr><td class="so">{i}</td><td>{e(d["ten_tm"] or d["ten"])}<br><span class="mo">{e(d["ma"])} · {e(d["quy_cach"])}</span></td>'
        f'<td>{e(d["so_lo"]) or "—"}</td><td>{ngay(d["han_dung"]) or "—"}</td><td class="so">{sl(d["so_luong"])}</td>'
        f'<td class="so">{tien(d["don_gia"])}</td><td class="so">{tien(d["so_luong"] * d["don_gia"])}</td>'
        f'<td class="thao-tac"><button class="nut-chu nguy" name="xoa" value="{d["id"]}">Bỏ</button></td></tr>' for i, d in enumerate(dong, 1))
    bang = (f'<form method="post" action="/nhap-kho/{pid}/dong">{an_csrf(c)}<div class="cuon"><table><thead><tr><th class="so">STT</th><th>Hàng hóa</th>'
            '<th>Số lô</th><th>Hạn dùng</th><th class="so">Số lượng</th><th class="so">Giá nhập (đ)</th><th class="so">Thành tiền</th><th></th></tr></thead>'
            f'<tbody>{hang}<tr><td colspan="6" class="so"><b>Tổng cộng</b></td><td class="so"><b>{tien(p["gia_tri"])}</b></td><td></td></tr>'
            '</tbody></table></div></form>') if dong else '<p class="mo">Chưa có hàng nào. Tìm hàng ở mục Thêm hàng bên dưới.</p>'
    kq_tim = ""
    if tim:
        dk, ts = dk_tim_hang(tim)
        ds = c.db.execute(f"SELECT * FROM hang_hoa WHERE 1=1{dk} ORDER BY id LIMIT 40", ts).fetchall()
        if ds:
            dh = "".join(
                f'<tr><td>{e(h["ten_tm"] or h["ten"])}<br><span class="mo">{e(h["ma"])} · {e(h["quy_cach"])}</span></td>'
                f'<td class="so"><input class="o-nho" type="number" min="0" step="any" name="sl_{h["id"]}" aria-label="Số lượng"></td>'
                f'<td><input class="o-nho" name="lo_{h["id"]}" maxlength="60" aria-label="Số lô"></td>'
                f'<td><input type="date" name="hd_{h["id"]}" aria-label="Hạn dùng"></td>'
                f'<td class="so"><input class="o-nho" type="number" min="0" step="any" name="gia_{h["id"]}" aria-label="Giá nhập"></td></tr>' for h in ds)
            kq_tim = (f'<form method="post" action="/nhap-kho/{pid}/them">{an_csrf(c)}<div class="cuon"><table><thead><tr><th>Hàng hóa</th>'
                      '<th class="so">Số lượng</th><th>Số lô</th><th>Hạn dùng</th><th class="so">Giá nhập (đ)</th></tr></thead>'
                      f'<tbody>{dh}</tbody></table></div><div class="hang-nut"><button class="nut">Thêm các hàng đã nhập số lượng</button>'
                      '<span class="mo">Một hàng có nhiều lô: thêm lô thứ nhất, rồi tìm lại và thêm lô tiếp theo.</span></div></form>')
        else:
            kq_tim = '<p class="mo">Không có hàng nào khớp trong danh mục. Hàng mới cần được thêm vào mục Hàng hóa trước.</p>'
    return trang(c, f"Phiếu nhập {p['so_pn']}", f"""
      <h1>Phiếu nhập {e(p["so_pn"])}</h1>
      <div class="the"><dl class="thong-tin"><dt>Ngày nhập</dt><dd>{ngay(p["ngay"])}</dd>
        <dt>Nhà cung cấp</dt><dd>{f'<a href="/phai-tra/{p["nha_cung_cap_id"]}">{e(p["ncc"])}</a>' if p["ncc"] else "Không có (tồn đầu kỳ / nhập khác)"}</dd>
        <dt>Hóa đơn</dt><dd>{e(p["so_hoa_don"]) or "—"}</dd><dt>Hạn thanh toán</dt><dd>{ngay(p["han_tt"]) or "—"}</dd>
        {f'<dt>Ghi chú</dt><dd>{e(p["ghi_chu"])}</dd>' if p["ghi_chu"] else ""}</dl></div>
      <div class="the"><h2>Hàng nhập <span class="dem">{len(dong)}</span></h2>{bang}</div>
      <div class="the"><h2>Thêm hàng</h2>
        <form class="bo-loc"><input type="search" name="tim" value="{e(tim)}" placeholder="Gõ tên, ký mã hiệu, nhãn hiệu…" {"autofocus" if tim else ""}>
          <button class="nut phu">Tìm</button></form>{kq_tim}</div>
      <details class="the"><summary>Sửa thông tin phiếu</summary>
        <form method="post" action="/nhap-kho/{pid}/sua" class="luoi">{an_csrf(c)}{o_dau_pn(c, p)}
          <div class="hang-nut"><button class="nut">Lưu</button></div></form></details>
      {nut_xoa(c, f"/nhap-kho/{pid}/xoa", f"Xóa phiếu nhập {p['so_pn']} cùng mọi dòng hàng? Tồn kho và nợ nhà cung cấp sẽ giảm theo.", "Xóa phiếu nhập")}""", "pn")


def pn_them(c, pid):
    lay_pn(c, pid)
    sl_ = so_luong_theo_o(c)
    if not sl_:
        raise Loi(400, "Chưa nhập số lượng cho hàng nào.")
    ids = list(sl_)[:200]
    co = [h["id"] for h in c.db.execute(f"SELECT id FROM hang_hoa WHERE id IN ({', '.join('?' * len(ids))})", ids).fetchall()]
    c.db.executemany("INSERT INTO phieu_nhap_dong (phieu_nhap_id, hang_hoa_id, so_lo, han_dung, so_luong, don_gia) VALUES (?,?,?,?,?,?)",
                     [(pid, i, c.chu(f"lo_{i}", "Số lô", toi_da=60), c.ngay(f"hd_{i}", "Hạn dùng"), sl_[i], c.so(f"gia_{i}", "Giá nhập")) for i in co])
    c.db.commit()
    return Chuyen(f"/nhap-kho/{pid}", f"Đã thêm {len(co)} dòng hàng vào phiếu nhập.")


def pn_dong_xoa(c, pid):
    lay_pn(c, pid)
    xoa = c.form.get("xoa", "")
    if xoa.isdigit():
        c.db.execute("DELETE FROM phieu_nhap_dong WHERE id = ? AND phieu_nhap_id = ?", (int(xoa), pid))
        c.db.commit()
    return Chuyen(f"/nhap-kho/{pid}", "Đã bỏ một dòng hàng.")


def pn_sua(c, pid):
    p = lay_pn(c, pid)
    gt = doc_dau_pn(c, p)
    c.db.execute(f"UPDATE phieu_nhap SET {', '.join(k + ' = ?' for k in gt)} WHERE id = ?", list(gt.values()) + [pid])
    c.db.commit()
    return Chuyen(f"/nhap-kho/{pid}", "Đã lưu thông tin phiếu nhập.")


def pn_xoa(c, pid):
    p = lay_pn(c, pid)
    c.db.execute("DELETE FROM phieu_nhap_dong WHERE phieu_nhap_id = ?", (pid,))
    c.db.execute("DELETE FROM phieu_nhap WHERE id = ?", (pid,))
    c.db.commit()
    return Chuyen("/nhap-kho", f"Đã xóa phiếu nhập {p['so_pn']}.")


def no_phai_tra(c, nid=None):
    dk, ts = ("", []) if nid is None else (" AND p.nha_cung_cap_id = ?", [nid])
    nhom = {}
    for p in c.db.execute(SQL_PN + " AND p.nha_cung_cap_id IS NOT NULL" + dk + " ORDER BY p.ngay, p.id", ts).fetchall():
        nhom.setdefault(p["nha_cung_cap_id"], {"phieu": [], "da_tra": 0})["phieu"].append(dict(p))
    for t in c.db.execute("SELECT nha_cung_cap_id, so_tien FROM chi_tien" + (" WHERE nha_cung_cap_id = ?" if nid else ""), ts).fetchall():
        nhom.setdefault(t["nha_cung_cap_id"], {"phieu": [], "da_tra": 0})["da_tra"] += t["so_tien"]
    return xep_no(nhom)


def phai_tra(c):
    nhom = no_phai_tra(c)
    ten = {n["id"]: n["ten"] for n in c.db.execute("SELECT id, ten FROM nha_cung_cap").fetchall()}
    if not nhom:
        than = '<div class="the trong">Chưa có nợ nhà cung cấp. Nợ phát sinh khi lập phiếu nhập kho có chọn nhà cung cấp.</div>'
    else:
        tong = dict(con_no=sum(n["con_no"] - n["tra_thua"] for n in nhom.values()), qua_han=sum(n["qua_han"] for n in nhom.values()),
                    phat_sinh=sum(n["phat_sinh"] for n in nhom.values()), da_tra=sum(n["da_tra"] for n in nhom.values()))
        than = o_so_no(tong, "Đã trả") + '<h2>Theo nhà cung cấp và tuổi nợ</h2>' + bang_no(nhom, ten, "/phai-tra")
    return trang(c, "Nợ nhà cung cấp", f"""
      <h1>Nợ nhà cung cấp</h1>
      <p class="mo">Bấm tên nhà cung cấp để xem từng phiếu nhập và ghi phiếu chi. Phiếu không ghi hạn thanh toán thì tính hạn là ngày nhập.</p>{than}""", "pt")


def phai_tra_xem(c, nid):
    ncc = lay_ncc(c, nid)
    n = no_phai_tra(c, nid).get(nid) or xep_no({0: {"phieu": [], "da_tra": 0}})[0]
    dong = "".join(
        f'<tr><td><a href="/nhap-kho/{p["id"]}"><b>{e(p["so_pn"])}</b></a></td><td>{ngay(p["ngay"])}</td><td>{e(p["so_hoa_don"]) or "—"}</td>'
        f'<td class="so">{tien(p["gia_tri"])}</td><td class="so">{tien(p["con_lai"])}</td><td>{ngay(p["han_tt"] or p["ngay"])}</td>'
        f'<td>{nhan_no(p)}</td></tr>' for p in reversed(n["phieu"]))
    bang = ('<div class="cuon"><table><thead><tr><th>Phiếu nhập</th><th>Ngày nhập</th><th>Hóa đơn</th><th class="so">Giá trị (đ)</th>'
            f'<th class="so">Còn nợ</th><th>Hạn thanh toán</th><th>Tình trạng</th></tr></thead><tbody>{dong}</tbody></table></div>'
            ) if n["phieu"] else '<p class="mo">Chưa có phiếu nhập nào của nhà cung cấp này.</p>'
    chi = c.db.execute("SELECT * FROM chi_tien WHERE nha_cung_cap_id = ? ORDER BY ngay DESC, id DESC", (nid,)).fetchall()
    thua = f'<p class="thong-bao">Đang trả trước {tien(n["tra_thua"])} đ cho nhà cung cấp này.</p>' if n["tra_thua"] else ""
    return trang(c, f"Nợ {ncc['ten']}", f"""
      <div class="dau-trang"><h1>Nợ nhà cung cấp: {e(ncc["ten"])}</h1><a class="nut phu" href="/nha-cung-cap/{nid}">Thông tin</a></div>
      {o_so_no(n, "Đã trả")}{thua}
      <div class="the cach-tren"><h2>Ghi phiếu chi</h2><form method="post" action="/phai-tra/{nid}/chi" class="luoi">{an_csrf(c)}
        {o_tien(c, "PC", "chi_tien", "so_pc")}<div class="hang-nut"><button class="nut">Ghi chi tiền</button></div></form></div>
      <div class="the"><h2>Phiếu nhập <span class="dem">{len(n["phieu"])}</span></h2>{bang}</div>
      <div class="the"><h2>Phiếu chi <span class="dem">{len(chi)}</span></h2>{bang_tien(c, chi, "so_pc", "/chi-tien")}</div>""", "pt")


def chi_tien_them(c, nid):
    lay_ncc(c, nid)
    so, tien_ = luu_tien(c, "chi_tien", "so_pc", "nha_cung_cap_id", nid)
    return Chuyen(f"/phai-tra/{nid}", f"Đã ghi phiếu chi {so}: {tien(tien_)} đ.")


def chi_tien_xoa(c, tid):
    t = c.db.execute("SELECT * FROM chi_tien WHERE id = ?", (tid,)).fetchone()
    if not t:
        raise Loi(404, "Không tìm thấy phiếu chi.")
    c.db.execute("DELETE FROM chi_tien WHERE id = ?", (tid,))
    c.db.commit()
    return Chuyen(f"/phai-tra/{t['nha_cung_cap_id']}", f"Đã xóa phiếu chi {t['so_pc']}.")


# ───────────────────────── báo cáo doanh số ─────────────────────────

def bang_xep(tieu_de, cot, so_lieu, toi_da=None):
    """Bảng xếp hạng: so_lieu = [(nhãn đã escape, giá trị)]."""
    if not so_lieu:
        return ""
    lon = max(v for _, v in so_lieu) or 1
    dong = "".join(f'<tr><td>{nhan}</td><td class="so">{tien(v)}</td><td><progress max="100" value="{round(100 * v / lon)}"></progress></td></tr>'
                   for nhan, v in so_lieu[:toi_da])
    an = f'<p class="mo">Hiện {toi_da} / {len(so_lieu)} dòng lớn nhất.</p>' if toi_da and len(so_lieu) > toi_da else ""
    return (f'<div class="the"><h2>{tieu_de}</h2><div class="cuon"><table><thead><tr><th>{cot}</th><th class="so">Doanh số (đ)</th><th></th></tr></thead>'
            f'<tbody>{dong}</tbody></table></div>{an}</div>')


def doanh_so(c):
    hom_nay = date.today()
    try:
        tu = date.fromisoformat(c.q.get("tu", "")).isoformat()
    except ValueError:
        tu = hom_nay.replace(month=1, day=1).isoformat()
    try:
        den = date.fromisoformat(c.q.get("den", "")).isoformat()
    except ValueError:
        den = hom_nay.isoformat()
    dk, ts = " AND p.ngay >= ? AND p.ngay <= ?", [tu, den]
    if not c.ql:
        dk += " AND o.phu_trach_id = ?"
        ts.append(c.user["id"])
    ds = dong_xuat(c, dk, ts)
    thang, nv, kh, hh, phieu = {}, {}, {}, {}, set()
    for r in ds:
        v = r["so_luong"] * r["don_gia"]
        cong(thang, r["ngay"][:7], v)
        cong(nv, r["phu_trach_id"], v)
        cong(kh, r["khach_hang_id"], v)
        cong(hh, (r["ma"], r["ten"]), v)
        phieu.add(r["px_id"])
    tong = sum(thang.values())
    if not ds:
        than = '<div class="the trong">Không có phiếu giao hàng nào trong khoảng thời gian này.</div>'
    else:
        ten_nv = {u["id"]: u["ho_ten"] for u in c.db.execute("SELECT id, ho_ten FROM nguoi_dung").fetchall()}
        ten_kh = {k["id"]: k["ten"] for k in c.db.execute("SELECT id, ten FROM khach_hang").fetchall()}
        giam = (lambda d: sorted(d.items(), key=lambda x: -x[1]))
        than = f"""<div class="o-so">
            <div class="the"><span>Doanh số (đ)</span><b>{tien(tong)}</b></div>
            <div class="the"><span>Số phiếu giao</span><b>{len(phieu)}</b></div>
            <div class="the"><span>Số khách mua</span><b>{len(kh)}</b></div>
            <div class="the"><span>Bình quân mỗi phiếu (đ)</span><b>{tien(tong / len(phieu))}</b></div></div>
          <div class="cach-tren">{bang_xep("Theo tháng", "Tháng", [(f"{k[5:]}/{k[:4]}", v) for k, v in sorted(thang.items())])}
          {bang_xep("Theo nhân viên phụ trách", "Nhân viên", [(e(ten_nv.get(k, "Chưa phân công")), v) for k, v in giam(nv)]) if c.ql else ""}
          {bang_xep("Theo khách hàng", "Khách hàng", [(f'<a href="/don-hang?kh={k}">{e(ten_kh.get(k, "?"))}</a>', v) for k, v in giam(kh)], 20)}
          {bang_xep("Theo sản phẩm", "Sản phẩm", [(f'{e(k[1])} <span class="mo">{e(k[0])}</span>', v) for k, v in giam(hh)], 20)}</div>"""
    return trang(c, "Báo cáo doanh số", f"""
      <h1>Báo cáo doanh số</h1>
      <p class="mo">Doanh số tính theo hàng đã giao (phiếu giao hàng), giá đã gồm VAT.
        {"" if c.ql else "Bạn đang xem doanh số các đơn hàng mình phụ trách."}</p>
      <form class="bo-loc"><label>Từ ngày <input type="date" name="tu" value="{tu}"></label>
        <label>Đến ngày <input type="date" name="den" value="{den}"></label>
        <button class="nut phu">Xem</button></form>
      {than}""", "ds")


# ───────────────────────── ủy quyền bán hàng (UQ) ─────────────────────────
# Thư ủy quyền của nhà phân phối cho nhà thầu (khách mua lại) chào hàng vào gói thầu của chủ đầu tư, kèm danh mục hàng.

COT_UQ = [("stt_mt", "STT MT", 30), ("ma", "Ký mã hiệu", 200), ("ten_tm", "Tên thương mại", 500), ("quy_cach", "Quy cách", 200),
          ("nha_sx", "Nhà sản xuất", 200), ("xuat_xu", "Xuất xứ", 100), ("dvt", "ĐVT", 30)]
SQL_UQ = ("SELECT q.*, u.ho_ten AS phu_trach, (SELECT COUNT(*) FROM uy_quyen_dong d WHERE d.uy_quyen_id = q.id) AS so_dong "
          "FROM uy_quyen q LEFT JOIN nguoi_dung u ON u.id = q.phu_trach_id WHERE 1=1")

ICON["uq"] = _svg('<rect x="7" y="5" width="28" height="36" rx="4" fill="#2ea8f5"/>' + _DONG.format(x=12, y=13, w=18)
                  + _DONG.format(x=12, y=20, w=12) + '<circle cx="33" cy="33" r="10" fill="#1fc7b0"/>'
                  '<path d="M28.5 33.5l3 3 6-6.5" fill="none" stroke="#fff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>')
next(u for u in UNG_DUNG if u[0] == "hop-dong")[3].insert(3, ("/uy-quyen", "Ủy quyền bán hàng", "uq", "uq", False))


def nhan_uq(q):
    return f'{q["so_uq"]}{docx_uq.HAU_TO}' if q["so_uq"] else f'UQ chưa số · {ngay(q["ngay"])}'


def lay_uq(c, qid):
    q = c.db.execute(SQL_UQ + " AND q.id = ?", (qid,)).fetchone()
    if not q:
        raise Loi(404, "Không tìm thấy ủy quyền.")
    if not c.ql and q["phu_trach_id"] != c.user["id"]:
        raise Loi(403, "Bạn không phụ trách ủy quyền này.")
    return q


def dong_cua_uq(c, qid):
    return c.db.execute("SELECT * FROM uy_quyen_dong WHERE uy_quyen_id = ? ORDER BY tt, id", (qid,)).fetchall()


def ds_uy_quyen(c):
    dk, ts = loc_quyen(c)
    tu = c.q.get("q", "")
    if tu:
        dk += (" AND (q.so_uq LIKE ? OR q.chu_dau_tu LIKE ? OR q.nha_thau LIKE ? OR q.goi_thau LIKE ? OR q.id IN "
               "(SELECT uy_quyen_id FROM uy_quyen_dong WHERE ma LIKE ? OR ten_tm LIKE ?))")
        ts += [f"%{tu}%"] * 6
    ds = c.db.execute(SQL_UQ + dk + " ORDER BY q.ngay DESC, q.id DESC", ts).fetchall()
    dong = ""
    for q in ds:
        link = f' <a href="{e(q["link_file"])}" target="_blank" rel="noopener noreferrer">Docs</a>' if q["link_file"] else ""
        dong += (f'<tr><td><a href="/uy-quyen/{q["id"]}"><b>{e(nhan_uq(q))}</b></a>{link}</td><td>{ngay(q["ngay"])}</td>'
                 f'<td>{e(q["chu_dau_tu"])}</td><td>{e(q["nha_thau"])}</td><td>{e(q["goi_thau"] or "—")}</td>'
                 f'<td class="so">{q["so_dong"] or "—"}</td><td>{e(q["phu_trach"] or "—")}</td></tr>')
    if ds:
        bang = ('<div class="the cuon"><table><thead><tr><th>Số UQ</th><th>Ngày</th><th>Chủ đầu tư</th><th>Nhà thầu</th>'
                f'<th>Gói thầu</th><th class="so">Mặt hàng</th><th>Phụ trách</th></tr></thead><tbody>{dong}</tbody></table></div>')
    else:
        bang = f'<div class="the trong">{"Không có ủy quyền nào khớp." if tu else "Chưa có ủy quyền nào. Bấm Làm ủy quyền để bắt đầu."}</div>'
    return trang(c, "Ủy quyền bán hàng", f"""
      <div class="dau-trang"><h1>Ủy quyền bán hàng <span class="dem">{len(ds)}</span></h1><a class="nut" href="/uy-quyen/moi">Làm ủy quyền</a></div>
      <form class="bo-loc"><input type="search" name="q" value="{e(tu)}" placeholder="Số UQ, chủ đầu tư, nhà thầu, gói thầu, mã hàng…">
        <button class="nut phu">Lọc</button>{'<a href="/uy-quyen">Bỏ lọc</a>' if tu else ""}</form>
      {bang}""", "uq")


def o_dau_uq(c, q=None):
    g = (lambda k, md="": q[k] if q else md)
    chon_hang = [h for h in (g("hang") or "").split(",") if h] or docx_uq.HANG_MAC_DINH
    hang = "".join(f'<label class="o-tich"><input type="checkbox" name="hang_{ma}" value="1"{" checked" if ma in chon_hang else ""}> {e(ten)}</label>'
                   for ma, ten, _, _, _ in docx_uq.HANG)
    pt = ""
    if c.ql:
        nd = c.db.execute("SELECT id, ho_ten FROM nguoi_dung WHERE hoat_dong = 1 ORDER BY ho_ten").fetchall()
        pt = f'<label>Người phụ trách{chon("phu_trach_id", [(u["id"], u["ho_ten"]) for u in nd], g("phu_trach_id", c.user["id"]))}</label>'
    return f"""
      {o("Số UQ (phần trước /UQ-ADC)", "so_uq", g("so_uq"), them='placeholder="Để trống nếu văn thư cấp số sau"')}
      {o("Ngày", "ngay", g("ngay", date.today().isoformat()), "date", True)}
      <label class="rong">Kính gửi — chủ đầu tư <b class="sao">*</b><input name="chu_dau_tu" value="{e(g("chu_dau_tu"))}" list="ds-khach" required
        placeholder="Ví dụ: Bệnh viện đa khoa Phú Xuyên"></label>
      <label class="rong">Nhà thầu được ủy quyền <b class="sao">*</b><input name="nha_thau" value="{e(g("nha_thau"))}" list="ds-khach" required
        placeholder="Ví dụ: Công ty TNHH Phát triển công nghệ NDK"></label>{goi_y_khach(c)}
      <label class="rong">Địa chỉ nhà thầu (chỉ khi chủ đầu tư yêu cầu ghi)<input name="dia_chi_nt" value="{e(g("dia_chi_nt"))}"></label>
      <label class="rong">Tên gói thầu<textarea name="goi_thau" rows="2"
        placeholder="Để trống thì thư ghi: …chào giá cung cấp hàng hóa cho [chủ đầu tư].">{e(g("goi_thau"))}</textarea></label>
      {o("Hiệu lực đến ngày (nếu cần ghi)", "hieu_luc_den", g("hieu_luc_den"), "date")}{pt}
      <div class="rong"><b>Hãng nêu trong thư</b><div class="bo-loc">{hang}</div></div>
      <label class="rong">Ghi chú nội bộ (không in)<input name="ghi_chu" value="{e(g("ghi_chu"))}"></label>"""


def doc_dau_uq(c, q=None):
    so = re.sub(r"\s*/?\s*UQ-ADC\s*$", "", c.chu("so_uq", "Số UQ", toi_da=40), flags=re.I).strip()
    gt = {"so_uq": so, "ngay": c.ngay("ngay", "Ngày", True), "chu_dau_tu": c.chu("chu_dau_tu", "Chủ đầu tư", True, 300),
          "nha_thau": c.chu("nha_thau", "Nhà thầu", True, 300), "dia_chi_nt": c.chu("dia_chi_nt", "Địa chỉ nhà thầu"),
          "goi_thau": c.chu("goi_thau", "Tên gói thầu", toi_da=1000), "hieu_luc_den": c.ngay("hieu_luc_den", "Hiệu lực đến ngày"),
          "hang": ",".join(ma for ma, *_ in docx_uq.HANG if c.form.get(f"hang_{ma}") == "1"),
          "ghi_chu": c.chu("ghi_chu", "Ghi chú", toi_da=1000)}
    if not gt["hang"]:
        raise Loi(400, "Chưa chọn hãng nào để nêu trong thư ủy quyền.")
    gt["phu_trach_id"] = q["phu_trach_id"] if q else c.user["id"]
    if c.ql:
        v = c.form.get("phu_trach_id", "")
        if not (v.isdigit() and c.db.execute("SELECT 1 FROM nguoi_dung WHERE id = ?", (int(v),)).fetchone()):
            raise Loi(400, "Chưa chọn người phụ trách.")
        gt["phu_trach_id"] = int(v)
    if so:
        trung = c.db.execute("SELECT id FROM uy_quyen WHERE so_uq = ?", (so,)).fetchone()
        if trung and (not q or trung["id"] != q["id"]):
            raise Loi(400, f"Số UQ {so}{docx_uq.HAU_TO} đã dùng cho ủy quyền khác.")
    return gt


def uq_them_dong(c, qid, cac_dong):
    tt = c.db.execute("SELECT COALESCE(MAX(tt), 0) AS m FROM uy_quyen_dong WHERE uy_quyen_id = ?", (qid,)).fetchone()["m"] or 0
    c.db.executemany(f"INSERT INTO uy_quyen_dong (uy_quyen_id, tt, {', '.join(k for k, _, _ in COT_UQ)}) VALUES (?, ?{', ?' * len(COT_UQ)})",
                     [[qid, tt + i] + [(d.get(k) or "")[:dai] for k, _, dai in COT_UQ] for i, d in enumerate(cac_dong, 1)])


def dong_tu_hang(h, stt_mt=""):
    """Một dòng danh mục UQ lấy từ hàng hóa trong danh mục."""
    return {"stt_mt": stt_mt, "ma": h["ma"], "ten_tm": h["ten_tm"] or h["ten"], "quy_cach": h["quy_cach"],
            "nha_sx": docx_uq.nha_sx_mac_dinh(docx_uq.nhan_dien_hang(h["nhan_hieu"], h["ten_tm"])),
            "xuat_xu": h["nuoc_sx"], "dvt": docx_uq.dvt_tu_quy_cach(h["quy_cach"])}


def uq_moi(c):
    goc = lay_uq(c, int(c.q["tu"])) if c.q.get("tu", "").isdigit() else None
    if c.method == "POST":
        gt = doc_dau_uq(c)
        qid = c.db.them(f"INSERT INTO uy_quyen ({', '.join(gt)}, tao_luc) VALUES ({'?, ' * len(gt)}?)",
                        list(gt.values()) + [datetime.now().isoformat(timespec="seconds")])
        tu = c.form.get("tu", "")
        if tu.isdigit():
            uq_them_dong(c, qid, [dict(d) for d in dong_cua_uq(c, lay_uq(c, int(tu))["id"])])
        c.db.commit()
        return Chuyen(f"/uy-quyen/{qid}", "Đã tạo ủy quyền." + ("" if tu.isdigit() else " Thêm hàng vào danh mục đính kèm ở bên dưới."))
    mau = dict(goc, so_uq="", ngay=date.today().isoformat(), link_file="") if goc else None
    an = f'<input type="hidden" name="tu" value="{goc["id"]}">' if goc else ""
    ghi = (f'<p class="mo">Sao chép từ <a href="/uy-quyen/{goc["id"]}">{e(nhan_uq(goc))}</a> — gồm cả {goc["so_dong"]} dòng danh mục. '
           'Sửa chủ đầu tư, nhà thầu, gói thầu cho đúng trước khi tạo.</p>') if goc else ""
    return trang(c, "Làm ủy quyền", f"""
      <h1>Làm ủy quyền bán hàng</h1>{ghi}
      <div class="the"><form method="post" action="/uy-quyen/moi" class="luoi">{an_csrf(c)}{an}{o_dau_uq(c, mau)}
        <div class="hang-nut"><button class="nut">{"Tạo bản sao" if goc else "Tạo và thêm hàng"}</button><a href="/uy-quyen">Hủy</a></div></form></div>""", "uq")


def uq_sua(c, qid):
    q = lay_uq(c, qid)
    gt = doc_dau_uq(c, q)
    c.db.execute(f"UPDATE uy_quyen SET {', '.join(k + ' = ?' for k in gt)} WHERE id = ?", list(gt.values()) + [qid])
    c.db.commit()
    return Chuyen(f"/uy-quyen/{qid}", "Đã lưu thông tin ủy quyền.")


def uq_xoa(c, qid):
    q = lay_uq(c, qid)
    if not c.duoc_xoa:
        raise Loi(403, "Bạn chưa được cấp quyền xóa. Hãy nhờ quản lý.")
    c.db.execute("DELETE FROM uy_quyen_dong WHERE uy_quyen_id = ?", (qid,))
    c.db.execute("DELETE FROM uy_quyen WHERE id = ?", (qid,))
    c.db.commit()
    return Chuyen("/uy-quyen", f"Đã xóa {nhan_uq(q)}.")


def uq_xem(c, qid):
    q = lay_uq(c, qid)
    dong = dong_cua_uq(c, qid)
    tim = c.q.get("tim", "")
    hang = ""
    for i, d in enumerate(dong, 1):
        hang += (f'<tr><td class="so">{i}</td>'
                 + "".join(f'<td><input class="o-bang{" rong" if k == "ten_tm" else ""}" name="{k}_{d["id"]}" value="{e(d[k])}" '
                           f'maxlength="{dai}" aria-label="{nhan}"></td>' for k, nhan, dai in COT_UQ)
                 + f'<td class="thao-tac"><button class="nut-chu nguy" name="xoa" value="{d["id"]}">Bỏ</button></td></tr>')
    if dong:
        bang = (f'<form method="post" action="/uy-quyen/{qid}/dong">{an_csrf(c)}<button class="nut-an" tabindex="-1" aria-hidden="true"></button>'
                '<div class="cuon"><table class="bang-uq"><thead><tr><th class="so">STT</th>'
                + "".join(f'<th>{nhan}</th>' for _, nhan, _ in COT_UQ) + f'<th></th></tr></thead><tbody>{hang}</tbody></table></div>'
                '<div class="hang-nut"><button class="nut">Lưu danh mục</button>'
                '<span class="mo">Sửa thẳng trong bảng; STT MT là số thứ tự mặt hàng trong gói thầu của chủ đầu tư.</span></div></form>')
    else:
        bang = '<p class="mo">Chưa có hàng nào — thư sẽ không có trang danh mục đính kèm. Thêm hàng ở bên dưới.</p>'
    kq_tim = ""
    if tim:
        dk, ts = dk_tim_hang(tim)
        ds = c.db.execute(f"SELECT * FROM hang_hoa WHERE 1=1{dk} ORDER BY id LIMIT 80", ts).fetchall()
        da_co = {gap(d["ma"]) for d in dong if d["ma"]}
        if ds:
            dh = "".join(
                f'<tr><td><input type="checkbox" name="hh_{h["id"]}" value="1" aria-label="Chọn"></td>'
                f'<td><input class="o-nho" name="mt_{h["id"]}" maxlength="30" placeholder="STT MT" aria-label="STT MT"></td>'
                f'<td>{e(h["ten_tm"] or h["ten"])}</td><td>{e(h["ma"])}{" <span class=mo>(đã có)</span>" if gap(h["ma"]) in da_co else ""}</td>'
                f'<td>{e(h["nhan_hieu"])}</td><td>{e(h["quy_cach"])}</td></tr>' for h in ds)
            kq_tim = (f'<form method="post" action="/uy-quyen/{qid}/them">{an_csrf(c)}<div class="cuon"><table><thead><tr><th></th>'
                      '<th>STT MT</th><th>Tên thương mại</th><th>Ký mã hiệu</th><th>Nhãn hiệu</th><th>Quy cách</th></tr></thead>'
                      f'<tbody>{dh}</tbody></table></div><div class="hang-nut"><button class="nut">Thêm các hàng đã chọn</button>'
                      '<span class="mo">Nhập STT MT thì không cần tích chọn.</span></div></form>')
        else:
            kq_tim = '<p class="mo">Không có hàng nào khớp trong danh mục.</p>'
    nut_google = ""
    if da_ket_noi(c):
        nut_google = (f'<form method="post" action="/uy-quyen/{qid}/google-doc" class="trong-dong">{an_csrf(c)}'
                      f'<button class="nut phu">{"Tạo lại" if q["link_file"] else "Tạo"} link Google Docs</button></form>')
    link = (f'<dt>Link Google Docs</dt><dd><a href="{e(q["link_file"])}" target="_blank" rel="noopener noreferrer">{e(q["link_file"])}</a></dd>'
            if q["link_file"] else "")
    ten_hang = ", ".join(t for m, t, *_ in docx_uq.HANG if m in (q["hang"] or "").split(","))
    xoa = nut_xoa(c, f"/uy-quyen/{qid}/xoa", f"Xóa {nhan_uq(q)}? Không khôi phục được.", "Xóa ủy quyền") if c.duoc_xoa else ""
    tay = "".join(o(nhan, k, bat_buoc=(k == "ten_tm")) for k, nhan, _ in COT_UQ)
    return trang(c, nhan_uq(q), f"""
      <div class="dau-trang"><h1>Ủy quyền {e(nhan_uq(q))}</h1>
        <div class="hang-nut"><a class="nut" href="/uy-quyen/{qid}/tai">Tải file Word</a>{nut_google}
          <a class="nut phu" href="/uy-quyen/moi?tu={qid}">Sao chép thành UQ mới</a></div></div>
      <div class="the"><dl class="thong-tin"><dt>Kính gửi (chủ đầu tư)</dt><dd>{e(q["chu_dau_tu"])}</dd>
        <dt>Nhà thầu</dt><dd>{e(q["nha_thau"])}{" — " + e(q["dia_chi_nt"]) if q["dia_chi_nt"] else ""}</dd>
        <dt>Gói thầu</dt><dd>{e(q["goi_thau"]) or "<span class=mo>Không ghi — thư ghi chào giá cho chủ đầu tư</span>"}</dd>
        <dt>Ngày</dt><dd>{ngay(q["ngay"])}</dd><dt>Hiệu lực đến</dt><dd>{ngay(q["hieu_luc_den"]) or "Không ghi"}</dd>
        <dt>Hãng</dt><dd>{e(ten_hang)}</dd><dt>Phụ trách</dt><dd>{e(q["phu_trach"] or "—")}</dd>{link}
        {f'<dt>Ghi chú</dt><dd>{e(q["ghi_chu"])}</dd>' if q["ghi_chu"] else ""}</dl></div>
      <div class="the"><h2>Danh mục đính kèm <span class="dem">{len(dong)}</span></h2>{bang}</div>
      <div class="the"><h2>Thêm hàng</h2>
        <form class="bo-loc"><input type="search" name="tim" value="{e(tim)}" placeholder="Gõ tên, ký mã hiệu, nhãn hiệu… ví dụ: HBsAg" {"autofocus" if tim else ""}>
          <button class="nut phu">Tìm</button></form>{kq_tim}</div>
      <details class="the"><summary>Dán danh mục từ Excel (STT MT và ký mã hiệu)</summary>
        <form method="post" action="/uy-quyen/{qid}/dan" class="luoi-1">{an_csrf(c)}
          <p class="mo">Chép các dòng từ bảng của chủ đầu tư rồi dán vào đây, mỗi dòng một mặt hàng, có cột STT MT và cột ký mã hiệu
            (các cột khác bỏ qua). App tìm ký mã hiệu trong danh mục hàng hóa để điền tên, quy cách, nhà sản xuất, xuất xứ.</p>
          <textarea name="dan" rows="6" placeholder="1.3&#9;ITP01003-DS50&#10;1.4&#9;ITP01102-DS50"></textarea>
          <div class="hang-nut"><button class="nut phu">Thêm vào danh mục</button></div></form></details>
      <details class="the"><summary>Thêm hàng không có trong danh mục</summary>
        <form method="post" action="/uy-quyen/{qid}/them-tay" class="luoi">{an_csrf(c)}{tay}
          <div class="hang-nut"><button class="nut phu">Thêm dòng</button></div></form></details>
      <details class="the"><summary>Sửa thông tin thư ủy quyền</summary>
        <form method="post" action="/uy-quyen/{qid}/sua" class="luoi">{an_csrf(c)}{o_dau_uq(c, q)}
          <div class="hang-nut"><button class="nut">Lưu</button></div></form></details>
      {xoa}""", "uq")


def uq_dong_luu(c, qid):
    lay_uq(c, qid)
    xoa = c.form.get("xoa", "")
    if xoa.isdigit():
        c.db.execute("DELETE FROM uy_quyen_dong WHERE id = ? AND uy_quyen_id = ?", (int(xoa), qid))
        c.db.commit()
        return Chuyen(f"/uy-quyen/{qid}", "Đã bỏ một dòng hàng.")
    for d in dong_cua_uq(c, qid):
        c.db.execute(f"UPDATE uy_quyen_dong SET {', '.join(k + ' = ?' for k, _, _ in COT_UQ)} WHERE id = ?",
                     [c.chu(f"{k}_{d['id']}", nhan, toi_da=dai) for k, nhan, dai in COT_UQ] + [d["id"]])
    c.db.commit()
    return Chuyen(f"/uy-quyen/{qid}", "Đã lưu danh mục.")


def uq_them(c, qid):
    lay_uq(c, qid)
    ids = sorted({int(k[3:]) for k, v in c.form.items() if k[:3] in ("hh_", "mt_") and k[3:].isdigit() and v.strip()})[:200]
    if not ids:
        raise Loi(400, "Chưa tích chọn hoặc nhập STT MT cho hàng nào.")
    ds = c.db.execute(f"SELECT * FROM hang_hoa WHERE id IN ({', '.join('?' * len(ids))}) ORDER BY id", ids).fetchall()
    uq_them_dong(c, qid, [dong_tu_hang(h, c.chu(f"mt_{h['id']}", "STT MT", toi_da=30)) for h in ds])
    c.db.commit()
    return Chuyen(f"/uy-quyen/{qid}", f"Đã thêm {len(ds)} hàng vào danh mục. Kiểm tra lại nhà sản xuất, xuất xứ, ĐVT.")


def uq_dan(c, qid):
    lay_uq(c, qid)
    theo_ma = {}
    for h in c.db.execute("SELECT * FROM hang_hoa WHERE ma <> '' ORDER BY id DESC").fetchall():
        theo_ma[re.sub(r"\s+", "", gap(h["ma"]))] = h
    them, la = [], []
    for dong in (c.form.get("dan") or "").splitlines()[:300]:
        o_ = [gon(x) for x in dong.split("\t")] if "\t" in dong else [gon(x) for x in re.split(r"\s{2,}|;", dong)]
        o_ = [x for x in o_ if x]
        if not o_:
            continue
        vi_tri = next((i for i, x in enumerate(o_) if re.sub(r"\s+", "", gap(x)) in theo_ma), None)
        if vi_tri is not None:
            h = theo_ma[re.sub(r"\s+", "", gap(o_[vi_tri]))]
            stt = o_[0] if vi_tri > 0 and re.fullmatch(r"[\d.,\-a-zA-Z]{1,12}", o_[0]) else ""
            them.append(dong_tu_hang(h, stt))
        else:
            la.append(o_[1] if len(o_) > 1 and re.fullmatch(r"[\d.,]{1,12}", o_[0]) else o_[0])
            stt = o_[0] if len(o_) > 1 and re.fullmatch(r"[\d.,]{1,12}", o_[0]) else ""
            them.append({"stt_mt": stt, "ma": la[-1], "ten_tm": " ".join(o_[2:]) if stt else " ".join(o_[1:]), "dvt": ""})
    if not them:
        raise Loi(400, "Chưa dán dòng nào.")
    uq_them_dong(c, qid, them)
    c.db.commit()
    tb = f"Đã thêm {len(them)} dòng."
    if la:
        tb += f" {len(la)} mã không có trong danh mục hàng hóa ({', '.join(la[:5])}{'…' if len(la) > 5 else ''}) — cần điền tay tên, quy cách, nhà sản xuất."
    return Chuyen(f"/uy-quyen/{qid}", tb)


def uq_them_tay(c, qid):
    lay_uq(c, qid)
    uq_them_dong(c, qid, [{k: c.chu(k, nhan, k == "ten_tm", dai) for k, nhan, dai in COT_UQ}])
    c.db.commit()
    return Chuyen(f"/uy-quyen/{qid}", "Đã thêm một dòng hàng.")


def tao_file_uq(c, q):
    ten = ten_tep_an_toan(f"UQ {q['so_uq'] or 'chua so'} - {q['chu_dau_tu']} - {q['nha_thau']}")
    return ten, docx_uq.tao(dict(q), [dict(d) for d in dong_cua_uq(c, q["id"])])


def uq_tai(c, qid):
    ten, dl = tao_file_uq(c, lay_uq(c, qid))
    return Tep(ten + ".docx", dl, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def uq_google(c, qid):
    q = lay_uq(c, qid)
    ten, dl = tao_file_uq(c, q)
    kq = goi_google(c, "tao_doc", ten=ten, docx=base64.b64encode(dl).decode(),
                    quyen=doc_cd(c, "quyen_link", "xem"), thu_muc="Ủy quyền bán hàng")
    url = kq.get("url") or ""
    if not url.startswith("https://docs.google.com/"):
        raise Loi(502, "Google không trả về link ủy quyền.")
    c.db.execute("UPDATE uy_quyen SET link_file = ? WHERE id = ?", (url, qid))
    c.db.commit()
    return Chuyen(f"/uy-quyen/{qid}", "Đã tạo link Google Docs (thư mục Ủy quyền bán hàng trong Drive).")


# ───────────────────────── định tuyến ─────────────────────────
# quyền: "khach" = không cần đăng nhập, "nd" = đã đăng nhập, "ql" = chỉ quản lý

TUYEN = [
    ("GET|POST", r"/thiet-lap", thiet_lap, "khach"),
    ("GET|POST", r"/dang-nhap", dang_nhap, "khach"),
    ("POST", r"/dang-xuat", dang_xuat, "nd"),
    ("GET|POST", r"/doi-mat-khau", doi_mat_khau, "nd"),
    ("GET", r"/", trang_chu, "nd"),
    ("GET", r"/tong-quan", tong_quan, "nd"),
    ("GET", r"/muc/(hop-dong|bao-gia|ban-hang|kho)", trang_muc, "nd"),
    ("GET", r"/hop-dong", ds_hop_dong, "nd"),
    ("GET|POST", r"/hop-dong/moi", hd_moi, "nd"),
    ("GET", r"/hop-dong/(\d+)", hd_xem, "nd"),
    ("GET|POST", r"/hop-dong/(\d+)/sua", hd_sua, "nd"),
    ("POST", r"/hop-dong/(\d+)/xoa", hd_xoa, "nd"),
    ("POST", r"/hop-dong/(\d+)/dong-hang", dong_hang_them, "nd"),
    ("GET|POST", r"/dong-hang/(\d+)/sua", dong_hang_sua, "nd"),
    ("POST", r"/dong-hang/(\d+)/xoa", dong_hang_xoa, "nd"),
    ("POST", r"/hop-dong/(\d+)/giao-hang", giao_hang_them, "nd"),
    ("POST", r"/giao-hang/(\d+)/xoa", giao_hang_xoa, "nd"),
    ("POST", r"/hop-dong/(\d+)/phu-luc", phu_luc_them, "nd"),
    ("POST", r"/phu-luc/(\d+)/xoa", phu_luc_xoa, "nd"),
    ("GET|POST", r"/hdnt/moi", hdnt_moi, "nd"),
    ("GET", r"/tra-mst", tra_mst, "nd"),
    ("GET", r"/hop-dong/(\d+)/tai-hdnt", tai_hdnt, "nd"),
    ("POST", r"/hop-dong/(\d+)/google-doc", hd_google, "nd"),
    ("GET", r"/bao-gia", ds_bao_gia, "nd"),
    ("GET|POST", r"/bao-gia/moi", bg_moi, "nd"),
    ("GET|POST", r"/bao-gia/nhanh", bg_nhanh, "nd"),
    ("GET", r"/bao-gia/(\d+)", bg_xem, "nd"),
    ("POST", r"/bao-gia/(\d+)/sua", bg_sua, "nd"),
    ("POST", r"/bao-gia/(\d+)/xoa", bg_xoa, "nd"),
    ("POST", r"/bao-gia/(\d+)/dong", bg_dong_luu, "nd"),
    ("POST", r"/bao-gia/(\d+)/them", bg_them, "nd"),
    ("POST", r"/bao-gia/(\d+)/them-tay", bg_them_tay, "nd"),
    ("GET", r"/bao-gia/(\d+)/tai", bg_tai, "nd"),
    ("POST", r"/bao-gia/(\d+)/google-doc", bg_google, "nd"),
    ("GET", r"/hang-hoa", hang_hoa, "nd"),
    ("GET", r"/uy-quyen", ds_uy_quyen, "nd"),
    ("GET|POST", r"/uy-quyen/moi", uq_moi, "nd"),
    ("GET", r"/uy-quyen/(\d+)", uq_xem, "nd"),
    ("POST", r"/uy-quyen/(\d+)/sua", uq_sua, "nd"),
    ("POST", r"/uy-quyen/(\d+)/xoa", uq_xoa, "nd"),
    ("POST", r"/uy-quyen/(\d+)/dong", uq_dong_luu, "nd"),
    ("POST", r"/uy-quyen/(\d+)/them", uq_them, "nd"),
    ("POST", r"/uy-quyen/(\d+)/dan", uq_dan, "nd"),
    ("POST", r"/uy-quyen/(\d+)/them-tay", uq_them_tay, "nd"),
    ("GET", r"/uy-quyen/(\d+)/tai", uq_tai, "nd"),
    ("POST", r"/uy-quyen/(\d+)/google-doc", uq_google, "nd"),
    ("GET", r"/don-hang", ds_don_hang, "nd"),
    ("GET|POST", r"/don-hang/moi", dh_moi, "nd"),
    ("GET", r"/don-hang/(\d+)", dh_xem, "nd"),
    ("POST", r"/don-hang/(\d+)/sua", dh_sua, "nd"),
    ("POST", r"/don-hang/(\d+)/xoa", dh_xoa, "nd"),
    ("POST", r"/don-hang/(\d+)/dong", dh_dong_luu, "nd"),
    ("POST", r"/don-hang/(\d+)/them", dh_them, "nd"),
    ("POST", r"/don-hang/(\d+)/them-tay", dh_them_tay, "nd"),
    ("POST", r"/don-hang/(\d+)/giao", dh_giao, "nd"),
    ("POST", r"/phieu-xuat/(\d+)/xoa", px_xoa, "nd"),
    ("GET", r"/cong-no", cong_no, "nd"),
    ("GET", r"/cong-no/(\d+)", cong_no_xem, "nd"),
    ("POST", r"/cong-no/(\d+)/thu", thu_tien_them, "nd"),
    ("POST", r"/thu-tien/(\d+)/xoa", thu_tien_xoa, "ql"),
    ("GET", r"/doanh-so", doanh_so, "nd"),
    ("GET", r"/kho", kho, "nd"),
    ("GET", r"/nhap-kho", ds_nhap_kho, "ql"),
    ("GET|POST", r"/nhap-kho/moi", pn_moi, "ql"),
    ("GET", r"/nhap-kho/(\d+)", pn_xem, "ql"),
    ("POST", r"/nhap-kho/(\d+)/sua", pn_sua, "ql"),
    ("POST", r"/nhap-kho/(\d+)/xoa", pn_xoa, "ql"),
    ("POST", r"/nhap-kho/(\d+)/them", pn_them, "ql"),
    ("POST", r"/nhap-kho/(\d+)/dong", pn_dong_xoa, "ql"),
    ("GET|POST", r"/nha-cung-cap", nha_cung_cap, "ql"),
    ("GET|POST", r"/nha-cung-cap/(\d+)", ncc_sua, "ql"),
    ("GET", r"/phai-tra", phai_tra, "ql"),
    ("GET", r"/phai-tra/(\d+)", phai_tra_xem, "ql"),
    ("POST", r"/phai-tra/(\d+)/chi", chi_tien_them, "ql"),
    ("POST", r"/chi-tien/(\d+)/xoa", chi_tien_xoa, "ql"),
    ("GET|POST", r"/hang-hoa/nhap", nhap_hang, "ql"),
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
        return ham(c, *[int(x) if x.isdigit() else x for x in m.groups()])
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
        elif isinstance(kq, Json):
            body = json.dumps(kq.du_lieu, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
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
