"""
Tạo file Word (.docx) Ủy quyền bán hàng của nhà phân phối, theo tab "UQ MẪU" của Google Doc mẫu
(A4 đứng, phông Roboto Condensed) — chỉ dùng thư viện có sẵn.

    tao(uq, dong) -> bytes
      uq:   so_uq, ngay (yyyy-mm-dd), chu_dau_tu, nha_thau, dia_chi_nt, goi_thau, hieu_luc_den, hang ("intec,ctk,…")
      dong: danh mục đính kèm (stt_mt, ma, ten_tm, quy_cach, nha_sx, xuat_xu, dvt); không có dòng nào thì bỏ trang danh mục
"""
import io, re, unicodedata, zipfile
from datetime import date
from xml.sax.saxutils import escape

FONT = "Roboto Condensed"
RONG = 9404                  # bề rộng vùng in (twip): A4 đứng, lề trái 1350, phải 1152
HAU_TO = "/UQ-ADC"
CONG_TY = "Công ty TNHH Avanta Diagnostics"
GIOI_THIEU = ("được thành lập từ ngày 31 tháng 05 năm 2010 có địa chỉ tại: 286 đường Giải Phóng, phường Phương Liệt, TP Hà Nội. "
              "Đơn vị chúng tôi là nhà nhập khẩu và phân phối độc quyền tại Việt Nam các sản phẩm: ")
CAM_DOAN = ("Chúng tôi xin cam đoan sẽ cung cấp đầy đủ các sản phẩm cho nhà thầu để cung cấp cho chủ đầu tư và đảm bảo cho "
            "việc bảo hành sản phẩm theo hợp đồng cung cấp được ký kết giữa chủ đầu tư và nhà thầu.")

# hãng phân phối: (mã, tên ngắn, câu giới thiệu trong thư, nhà sản xuất mặc định trong danh mục, từ nhận diện nhãn hiệu)
HANG = [
    ("intec", "InTec (Advanced Quality)",
     "Test thử nhanh ADVANCED QUALITY của hãng INTEC PRODUCTS có địa chỉ tại 332 Xinguang Road, Xinyang Industry Area, "
     "Haicang, Xiamen 361022 P.R China.", "InTec Products, Inc", ["intec", "advanced quality"]),
    ("ctk", "CTK Biotech (OnSite)",
     "Test thử nhanh thương hiệu ONSITE của hãng CTK BIOTECH có địa chỉ tại 13855 Stowe Dr.Poway, CA92064, USA.",
     "Beijing Genesee Biotech, Inc", ["ctk", "onsite", "genesee"]),
    ("wondfo", "Wondfo",
     "Test thử nhanh của hãng WONDFO có địa chỉ tại No.8, Lizhishan Road, Science City, Luogang District, 510663, "
     "Guangzhou, P.R.China.", "Guangzhou Wondfo Biotech Co., Ltd.", ["wondfo"]),
    ("orient", "Orient Gene",
     "Test thử nhanh ORIENT GENE của hãng ZHEJIANG ORIENT GENE BIOTECH có địa chỉ tại 3787#, East Yangguang Avenue, "
     "Dipu Street, Anji 313300, Huzhou, Zhejiang, China.", "Zhejiang Orient Gene Biotech Co., Ltd", ["orient"]),
    ("taidoc", "TaiDoc (Uright)",
     "Thiết bị chăm sóc sức khỏe thương hiệu URIGHT của hãng TAIDOC có địa chỉ tại 6F., No. 127, Wugong 2nd Road, "
     "24888 Wugu Dist., New Taipei City, Taiwan.", "TaiDoc Technology Corporation", ["taidoc", "uright"]),
]
HANG_MAC_DINH = ["intec", "ctk", "wondfo", "orient"]

# danh mục: (tiêu đề, khóa, bề rộng theo mẫu)
COT = [("STT", "stt", 510), ("STT MT", "stt_mt", 600), ("Ký mã hiệu", "ma", 1300), ("Tên thương mại", "ten_tm", 2700),
       ("Quy cách\nđóng gói", "quy_cach", 1160), ("Nhà sản xuất", "nha_sx", 1830), ("Xuất xứ", "xuat_xu", 860), ("ĐVT", "dvt", 640)]


def _gap(s):
    s = unicodedata.normalize("NFD", str(s or "")).replace("đ", "d").replace("Đ", "D")
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()


def nhan_dien_hang(*chu):
    """Mã hãng theo nhãn hiệu / tên hàng, '' nếu không nhận ra."""
    s = " ".join(_gap(x) for x in chu)
    for ma, _, _, _, tu in HANG:
        if any(t in s for t in tu):
            return ma
    return ""


def nha_sx_mac_dinh(ma_hang):
    return next((h[3] for h in HANG if h[0] == ma_hang), "")


def dvt_tu_quy_cach(qc):
    """'50Test/Hộp' → 'Test'; 'Hộp 25 test' → 'Test'."""
    m = re.search(r"\d+\s*([^\d\s/]+)\s*/", qc or "")
    if m:
        return m.group(1).capitalize()
    return "Test" if "test" in _gap(qc) else ""


def so_day_du(so):
    """Số UQ in ra: '125' → '125/UQ-ADC'; trống → chừa chỗ để văn thư ghi tay."""
    so = (so or "").strip()
    return f"{so}{HAU_TO}" if so else f"{' ' * 14}{HAU_TO}"


def _ngay(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _r(chu, dam=False, nghieng=False, co=25):
    kieu = ("<w:b/><w:bCs/>" if dam else "") + ("<w:i/><w:iCs/>" if nghieng else "") + f'<w:sz w:val="{co}"/><w:szCs w:val="{co}"/>'
    than = "<w:br/>".join(f'<w:t xml:space="preserve">{escape(d)}</w:t>' for d in str(chu or "").split("\n"))
    return f'<w:r><w:rPr>{kieu}</w:rPr>{than}</w:r>'


def _p(chay, canh="both", truoc=0, sau=0, dong=240, dau=0, trai=0, treo=0, them=""):
    """Một đoạn từ các run đã dựng; dau = thụt dòng đầu, treo = thụt treo (twip)."""
    ind = ""
    if dau or trai or treo:
        ind = f'<w:ind w:left="{trai}"' + (f' w:hanging="{treo}"' if treo else f' w:firstLine="{dau}"') + '/>'
    return (f'<w:p><w:pPr>{them}<w:spacing w:before="{truoc}" w:after="{sau}" w:line="{dong}" w:lineRule="auto"/>{ind}'
            f'<w:jc w:val="{canh}"/></w:pPr>{"".join(chay) if isinstance(chay, list) else chay}</w:p>')


def _gach(trai, phai):
    """Đường kẻ ngắn dưới tên công ty / quốc hiệu."""
    return (f'<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="000000"/></w:pBdr>'
            f'<w:spacing w:before="0" w:after="60" w:line="120" w:lineRule="exact"/><w:ind w:left="{trai}" w:right="{phai}"/></w:pPr></w:p>')


def _o(noi_dung, rong, vien=False, gop=1, nen=""):
    tc = f'<w:tcW w:w="{rong}" w:type="dxa"/>' + (f'<w:gridSpan w:val="{gop}"/>' if gop > 1 else "")
    if not vien:
        tc += '<w:tcBorders>' + "".join(f'<w:{v} w:val="nil"/>' for v in ("top", "left", "bottom", "right")) + '</w:tcBorders>'
    if nen:
        tc += f'<w:shd w:val="clear" w:color="auto" w:fill="{nen}"/>'
    return f'<w:tc><w:tcPr>{tc}<w:vAlign w:val="center"/></w:tcPr>{noi_dung}</w:tc>'


def _bang(rong, hang, vien=False, dau_lap=False):
    v = ("".join(f'<w:{x} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                 for x in ("top", "left", "bottom", "right", "insideH", "insideV")) if vien else "")
    x = (f'<w:tbl><w:tblPr><w:tblW w:w="{sum(rong)}" w:type="dxa"/><w:jc w:val="center"/>'
         + (f'<w:tblBorders>{v}</w:tblBorders>' if vien else "") +
         '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="30" w:type="dxa"/><w:left w:w="60" w:type="dxa"/>'
         '<w:bottom w:w="30" w:type="dxa"/><w:right w:w="60" w:type="dxa"/></w:tblCellMar></w:tblPr>'
         f'<w:tblGrid>{"".join(f"<w:gridCol w:w=\"{r}\"/>" for r in rong)}</w:tblGrid>')
    for i, h in enumerate(hang):
        tr = '<w:trPr><w:tblHeader/></w:trPr>' if dau_lap and i == 0 else ('<w:trPr><w:cantSplit/></w:trPr>' if vien else "")
        x += f'<w:tr>{tr}{"".join(h)}</w:tr>'
    return x + '</w:tbl>'


def _phan_dau(uq):
    d = _ngay(uq.get("ngay"))
    ngay_chu = f"Hà Nội, ngày {d.day:02d} tháng {d.month:02d} năm {d.year}" if d else "Hà Nội, ngày      tháng      năm"
    trai = (_p(_r("CÔNG TY TNHH", True, co=24), "center") + _p(_r("AVANTA DIAGNOSTICS", True, co=24), "center")
            + _gach(1100, 1100) + _p(_r(f"Số: {so_day_du(uq.get('so_uq'))}", nghieng=True, co=24), "center"))
    phai = (_p(_r("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", True, co=24), "center")
            + _p(_r("Độc lập – Tự do – Hạnh phúc", True, co=24), "center") + _gach(1500, 1500)
            + _p(_r(ngay_chu, nghieng=True, co=26), "center", truoc=60, sau=60))
    return _bang([3800, RONG - 3800], [[_o(trai, 3800), _o(phai, RONG - 3800)]])


def _than_thu(uq, co_danh_muc):
    goi = (uq.get("goi_thau") or "").strip()
    dia_chi = (uq.get("dia_chi_nt") or "").strip()
    cdt = (uq.get("chu_dau_tu") or "").strip()
    x = _p(_r("ỦY QUYỀN BÁN HÀNG CỦA NHÀ PHÂN PHỐI", True, co=34), "center", truoc=240, sau=60, dong=360)
    x += _p([_r("Kính gửi: ", True, co=26), _r(cdt.upper(), True, co=26)], "center", truoc=120, dong=324)
    x += _p(_r("(Sau đây gọi là chủ đầu tư)", nghieng=True, co=26), "center", sau=120, dong=360)
    de_nghi = [_r("Theo đề nghị của "), _r((uq.get("nha_thau") or "").strip(), True), _r(" (sau đây gọi là “nhà thầu”)")]
    if dia_chi:
        de_nghi.append(_r(f" có địa chỉ tại: {dia_chi},"))
    if goi:
        de_nghi += [_r(" sẽ tham gia chào giá cung cấp hàng hóa cho gói thầu: "), _r(f"“{goi}”", nghieng=True), _r(".")]
    else:
        de_nghi.append(_r(f" sẽ tham gia chào giá cung cấp hàng hóa cho {cdt}."))
    x += _p(de_nghi, dau=709, sau=40, dong=324)
    x += _p([_r("Chúng tôi, "), _r(CONG_TY, True), _r(" " + GIOI_THIEU)], dau=720, truoc=40, sau=40, dong=360)
    chon = [h for h in (uq.get("hang") or "").split(",") if h]
    for ma, _, cau, _, _ in HANG:
        if ma in (chon or HANG_MAC_DINH):
            x += _p([_r("-"), '<w:r><w:tab/></w:r>', _r(cau)], trai=714, treo=357, dong=324,
                    them='<w:tabs><w:tab w:val="left" w:pos="714"/></w:tabs>')
    cho_phep = [_r("Bằng văn bản này, chúng tôi cho phép nhà thầu được sử dụng các sản phẩm")]
    if co_danh_muc:
        cho_phep += [_r(": "), _r("(Theo danh mục đính kèm)", True, True)]
    cho_phep.append(_r(" của các hãng nêu trên để chào trong HSDT của nhà thầu."))
    x += _p(cho_phep, dau=709, truoc=40, sau=40, dong=324)
    x += _p(_r(CAM_DOAN), dau=720, truoc=40, sau=40, dong=360)
    hl = _ngay(uq.get("hieu_luc_den"))
    if hl:
        x += _p(_r(f"Uỷ quyền bán hàng này có hiệu lực đến ngày {hl.day:02d}/{hl.month:02d}/{hl.year}."), dau=720, sau=40, dong=360)
    ky = _p(_r("ĐẠI DIỆN NHÀ PHÂN PHỐI", True, co=26), "center", truoc=120, sau=60, dong=360)
    x += _bang([RONG // 2, RONG - RONG // 2], [[_o(_p(""), RONG // 2), _o(ky, RONG - RONG // 2)]])
    return x


def _danh_muc(uq, dong):
    d = _ngay(uq.get("ngay"))
    x = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    x += _p(_r("DANH MỤC UỶ QUYỀN BÁN HÀNG", True, co=24), "center")
    x += _p(_r(f"(Theo UQ số : {so_day_du(uq.get('so_uq'))}" + (f" ngày {d.day:02d}/{d.month:02d}/{d.year}" if d else "") + " )",
               nghieng=True, co=20), "center", sau=120)
    if (uq.get("goi_thau") or "").strip():
        x += _p(_r(uq["goi_thau"].strip(), True, co=20), "left", sau=80)
    tong = sum(c[2] for c in COT)
    rong = [RONG * c[2] // tong for c in COT]
    rong[3] += RONG - sum(rong)
    hang = [[_o(_p(_r(t, True, co=20), "center"), r, True, nen="F2F2F2") for (t, _, _), r in zip(COT, rong)]]
    for i, dg in enumerate(dong, 1):
        gt = dict(dg, stt=str(i))
        hang.append([_o(_p(_r(gt.get(k) or "", co=18), "left" if k == "ten_tm" else "center"), r, True)
                     for (_, k, _), r in zip(COT, rong)])
    return x + _bang(rong, hang, vien=True, dau_lap=True)


def tao(uq, dong):
    dong = [d for d in dong if any((d.get(k) or "").strip() for k in ("ma", "ten_tm"))]
    than = _phan_dau(uq) + _than_thu(uq, bool(dong)) + (_danh_muc(uq, dong) if dong else "")
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + than +
           '<w:p/><w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
           '<w:pgMar w:top="850" w:right="1152" w:bottom="850" w:left="1350" w:header="400" w:footer="400" w:gutter="0"/>'
           '</w:sectPr></w:body></w:document>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr>'
              f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}" w:cs="{FONT}"/>'
              '<w:sz w:val="25"/><w:szCs w:val="25"/><w:lang w:val="vi-VN"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style></w:styles>')
    kieu = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>')
    rels_doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                '</Relationships>')
    ra = io.BytesIO()
    with zipfile.ZipFile(ra, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", kieu)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", rels_doc)
    return ra.getvalue()
