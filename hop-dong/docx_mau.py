"""
Điền thông tin vào file Word (.docx) mẫu mà vẫn giữ nguyên định dạng.

Mẫu dùng các ô điền dạng {ten_kh}, {so_hd}... Word hay cắt một đoạn chữ thành nhiều "run"
(mỗi run một kiểu chữ), nên ô điền có thể bị cắt ngang. Hàm ở đây ghép chữ của cả đoạn,
tìm ô điền, rồi đặt giá trị vào run chứa ký tự đầu tiên của ô — các run khác giữ nguyên kiểu chữ.
Sửa thẳng trên chuỗi XML (không dựng lại cây XML) để Word không báo file hỏng.
"""
import io, re, zipfile
from xml.sax.saxutils import escape, unescape

O_DIEN = ["so_hd", "ngay", "thang", "nam", "ten_kh", "dia_chi", "mst", "dai_dien", "chuc_vu", "dien_thoai", "email"]
_DOAN = re.compile(r"<w:p[ >].*?</w:p>", re.S)
_CHU = re.compile(r"(<w:t(?: [^>]*)?>)([^<]*)(</w:t>)")
_KY_TU_XAU = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sua_doan(doan, cac_mau):
    """cac_mau: danh sách (regex đã biên dịch, hàm hoặc chuỗi thay)."""
    runs = list(_CHU.finditer(doan))
    if not runs:
        return doan
    chu = [unescape(m.group(2)) for m in runs]
    du = "".join(chu)
    if not any(p.search(du) for p, _ in cac_mau):
        return doan
    ky_tu = list(du)
    cua = [i for i, t in enumerate(chu) for _ in t]       # ký tự thứ k thuộc run nào
    for p, thay in cac_mau:
        hien = "".join(ky_tu)
        for m in reversed(list(p.finditer(hien))):         # thay từ phải sang trái để vị trí không lệch
            s, e = m.span()
            if s == e:
                continue
            moi = m.expand(thay) if isinstance(thay, str) else thay(m)
            ky_tu[s:e] = list(moi)
            cua[s:e] = [cua[s]] * len(moi)
    moi_run = ["".join(c for c, r in zip(ky_tu, cua) if r == i) for i in range(len(runs))]
    out, cuoi = [], 0
    for i, m in enumerate(runs):
        mo = m.group(1)
        if 'xml:space="preserve"' not in mo:
            mo = mo[:-1] + ' xml:space="preserve">'
        out += [doan[cuoi:m.start()], mo, escape(moi_run[i]), m.group(3)]
        cuoi = m.end()
    out.append(doan[cuoi:])
    return "".join(out)


def sua_xml(xml, cac_mau):
    return _DOAN.sub(lambda m: _sua_doan(m.group(0), cac_mau), xml)


def _phan_chu(z):
    return [n for n in z.namelist() if re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", n)]


def viet_lai(data, sua):
    """Chép lại file .docx, cho hàm sua(tên_phần, xml) -> xml đổi các phần chữ."""
    vao = zipfile.ZipFile(io.BytesIO(data))
    ra_buf = io.BytesIO()
    with zipfile.ZipFile(ra_buf, "w", zipfile.ZIP_DEFLATED) as ra:
        can_sua = set(_phan_chu(vao))
        for info in vao.infolist():
            b = vao.read(info.filename)
            if info.filename in can_sua:
                b = sua(info.filename, b.decode("utf-8")).encode("utf-8")
            ra.writestr(info, b)
    return ra_buf.getvalue()


def lam_sach(v):
    return _KY_TU_XAU.sub("", str(v or "")).replace("\r", "").replace("\n", " ").strip()


def dien(data, gia_tri):
    """Thay các ô {ten} trong mẫu bằng gia_tri[ten]. Ô không có giá trị thì để trống."""
    p = re.compile(r"\{(" + "|".join(O_DIEN) + r")\}")
    mau = [(p, lambda m: lam_sach(gia_tri.get(m.group(1), "")))]
    return viet_lai(data, lambda ten, xml: sua_xml(xml, mau))


# ───── chuẩn hóa file mẫu xuất từ Google Docs ─────

def dem_phan(data):
    """Số phần (section) của văn bản; Google Docs xuất mỗi tab thành một phần."""
    x = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
    return x.count("<w:sectPr")


def _cat_phan(xml, k):
    """Chỉ giữ phần thứ k (đếm từ 0) của thân văn bản."""
    dau = xml.index(">", xml.index("<w:body")) + 1
    cuoi = xml.rindex("</w:body>")
    than = xml[dau:cuoi]
    vt = [m.start() for m in re.finditer(r"<w:sectPr[ >]", than)]
    if k >= len(vt):
        raise ValueError("Không có phần số %d." % (k + 1))
    bat_dau = 0
    for i, s in enumerate(vt):
        e = than.index("</w:sectPr>", s) + len("</w:sectPr>")
        if i == len(vt) - 1:                              # phần cuối: sectPr nằm thẳng trong thân bài
            ket, giu = s, than[bat_dau:s]
        else:                                             # các phần khác: sectPr nằm trong đoạn cuối của phần
            ket = than.index("</w:p>", e) + len("</w:p>")
            giu = than[bat_dau:s] + than[e:ket]
        if i == k:
            return xml[:dau] + giu + than[s:e] + xml[cuoi:]
        bat_dau = ket


# chữ gợi ý sẵn trong mẫu ADM03901 -> ô điền (chỉ đổi phần Bên B, Bên A giữ nguyên)
_GOI_Y_BEN_B = [
    (r"\[\s*TÊN\s+CÔNG\s+TY\s*\]", "{ten_kh}"),
    (r"\[\s*Nhập\s+địa\s+chỉ(\s+công\s+ty)?\s*\]", "{dia_chi}"),
    (r"\[\s*Nhập\s+mã\s+số\s+thuế\s*\]", "{mst}"),
    (r"\[\s*Nhập\s+họ\s+tên\s+người\s+đại\s+diện\s*\]\s*", "{dai_dien}"),
    (r"\[\s*Nhập\s+chức\s+vụ\s*\]", "{chuc_vu}"),
    (r"\[\s*Nhập\s+số\s+điện\s+thoại(\s+liên\s+hệ)?\s*\]", "{dien_thoai}"),
    (r"\[\s*Nhập\s+(địa\s+chỉ\s+)?email\s*\]", "{email}"),
]
_GOI_Y_SO = re.compile(r"Số\s*:[ \t ]*(?:\[[^\]]*\])?[ \t .…_]*-?[ \t ]*HĐNT/(?:\[[^\]]*\]|[^\s<]+)", re.I)
_SO_HD_CO_DUOI = re.compile(r"\{so_hd\}[ \t ]*-?[ \t ]*HĐNT/(?:\[[^\]]*\]|[^\s<]+)", re.I)
_TRONG = r"(?:\d{1,4}|\[[^\]]*\]|[_.…]+|[ \t ]+)"
_GOI_Y_NGAY = re.compile(r"ngày\s*" + _TRONG + r"\s*tháng\s*" + _TRONG + r"\s*năm\s*" + _TRONG, re.I)


_RUN = re.compile(r"<w:r[ >](?:(?!<w:r[ >]).)*?</w:r>", re.S)
_MONO = re.compile(r'w:ascii="(Courier[^"]*|Consolas|Menlo|Monaco|Roboto Mono|Source Code Pro|Ubuntu Mono)"')


def _bo_kieu_code(doan):
    """Ô điền dán từ trang web hay mang kiểu chữ "code" (font Courier, nền xám).
    Trả run chứa ô điền về kiểu chữ của run có chữ đứng trước nó trong cùng đoạn."""
    if "{" not in doan:
        return doan
    truoc = [None]

    def mot_run(m):
        r = m.group(0)
        rpr = re.search(r"<w:rPr>.*?</w:rPr>", r, re.S)
        co_chu = re.search(r"<w:t(?: [^>]*)?>([^<]+)</w:t>", r)
        if co_chu and re.search(r"\{(" + "|".join(O_DIEN) + r")\}", unescape(co_chu.group(1))) and rpr \
                and (_MONO.search(rpr.group(0)) or "<w:shd " in rpr.group(0)) and truoc[0]:
            return r.replace(rpr.group(0), truoc[0], 1)
        if co_chu and co_chu.group(1).strip() and rpr and not _MONO.search(rpr.group(0)):
            truoc[0] = rpr.group(0)
        return r

    return _RUN.sub(mot_run, doan)


def doi_goi_y(xml):
    """Đổi chữ gợi ý của mẫu ADM03901 thành ô điền và bỏ màu chữ ở các đoạn đó (in ra chữ đen)."""
    trang_thai = {"ben_b": False}
    ben_b = [(re.compile(p, re.I), t) for p, t in _GOI_Y_BEN_B]

    def mot_doan(m):
        doan = m.group(0)
        chu = "".join(unescape(t) for t in re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", doan))
        mau = []
        if re.search(r"HĐNT", chu):
            mau.append((_GOI_Y_SO, "Số: {so_hd}"))
            # mẫu tự gõ "{so_hd}-HĐNT/PBH": số app điền đã có đuôi -HĐNT/PBH nên bỏ đuôi trong mẫu để khỏi lặp
            mau.append((_SO_HD_CO_DUOI, "{so_hd}"))
        if re.search(r"Hôm\s+nay", chu, re.I):
            mau.append((_GOI_Y_NGAY, "ngày {ngay} tháng {thang} năm {nam}"))
        if trang_thai["ben_b"]:
            mau += ben_b
        if re.search(r"Bên\s*B\b", chu):
            trang_thai["ben_b"] = True
        moi = _sua_doan(doan, mau) if mau else doan
        if moi != doan:
            moi = re.sub(r"<w:color [^>]*/>", "", moi)
        return _bo_kieu_code(moi)

    return _DOAN.sub(mot_doan, xml)


def chuan_hoa(data, phan=None):
    """Chuẩn bị file mẫu: giữ phần (tab) số `phan` nếu có, đổi chữ gợi ý thành ô điền."""
    def sua(ten, xml):
        if ten == "word/document.xml":
            if phan is not None:
                xml = _cat_phan(xml, phan)
            xml = doi_goi_y(xml)
        return xml
    return viet_lai(data, sua)


def kiem_tra(data):
    """Trả về danh sách ô điền có trong mẫu; báo lỗi nếu không phải file .docx."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        if "word/document.xml" not in z.namelist():
            raise ValueError
        chu = ""
        for n in _phan_chu(z):
            x = z.read(n).decode("utf-8")
            chu += "".join(unescape(t) for t in re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", x))
    except (zipfile.BadZipFile, ValueError, KeyError, UnicodeDecodeError):
        raise ValueError("File không phải Word .docx hợp lệ.")
    # chữ của ô điền có thể bị cắt run nên kiểm tra trên chữ đã ghép của cả phần
    return [o for o in O_DIEN if "{" + o + "}" in chu]
