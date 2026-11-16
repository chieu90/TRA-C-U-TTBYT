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
