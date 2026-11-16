"""
Tạo file Word (.docx) bảng báo giá, khổ A4 ngang, phông Roboto Condensed — chỉ dùng thư viện có sẵn.

    tao(bg, dong) -> bytes
      bg:   so_bg, ngay (yyyy-mm-dd), ten_kh, hieu_luc_den, ghi_chu, phu_trach
      dong: danh sách dòng hàng (ten, ten_tm, ma, nhan_hieu, nuoc_sx, phan_loai, hsd, quy_cach, so_luong, don_gia)
Có dòng nào nhập số lượng thì bảng thêm cột Số lượng, Thành tiền và hàng Tổng cộng.
"""
import io, zipfile
from datetime import date
from xml.sax.saxutils import escape

FONT = "Roboto Condensed"
RONG = 15138                 # bề rộng vùng in (twip): A4 ngang, lề trái phải 1,5 cm

GIOI_THIEU = ("Avanta Diagnostics là đơn vị nhập khẩu và phân phối chính thức các sản phẩm test nhanh chất lượng cao từ những "
              "thương hiệu uy tín hàng đầu thế giới như CTK Biotech, Intec, Wondfo, Orient Gene, Taidoc và Rapidlabs.... "
              "Với cam kết cung cấp sản phẩm đạt tiêu chuẩn quốc tế, nguồn gốc rõ ràng, đầy đủ chứng từ (CE, ISO, FDA, WHO PQ...). "
              "Avanta Diagnostics cam kết mang đến cho cộng đồng y tế các giải pháp đột phá, hiệu quả trong lĩnh vực xét nghiệm "
              "và chẩn đoán.")
MO_DAU = "Công ty Avanta trân trọng gửi đến Quý khách hàng báo giá với thông tin sau:"

# (tiêu đề, khóa, tỉ lệ rộng, canh lề)
COT = [("STT", "stt", 4, "center"), ("TÊN TTBYT", "ten", 11, "left"), ("TÊN THƯƠNG MẠI", "ten_tm", 21, "left"),
       ("KÝ MÃ HIỆU", "ma", 10, "center"), ("NHÃN HIỆU", "nhan_hieu", 9, "center"),
       ("NƯỚC SẢN XUẤT", "nuoc_sx", 8, "center"), ("PHÂN LOẠI TBYT", "phan_loai", 6, "center"),
       ("HSD", "hsd", 7, "center"), ("QUY CÁCH", "quy_cach", 9, "center")]
COT_GIA = ("ĐƠN GIÁ (VNĐ)", "don_gia", 8, "right")
COT_SL = [("SỐ LƯỢNG", "so_luong", 7, "right"), COT_GIA, ("THÀNH TIỀN (VNĐ)", "thanh_tien", 10, "right")]


def _so(n):
    n = n or 0
    if abs(n - round(n)) < 1e-9:
        return f"{round(n):,}".replace(",", ".")
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _ngay(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _doan(chu, canh="left", dam=False, nghieng=False, co=24, sau=80, truoc=0):
    """Một đoạn văn; chu có thể nhiều dòng (xuống dòng trong cùng đoạn)."""
    kieu = ("<w:b/><w:bCs/>" if dam else "") + ("<w:i/><w:iCs/>" if nghieng else "") + f'<w:sz w:val="{co}"/><w:szCs w:val="{co}"/>'
    dong = str(chu or "").split("\n")
    than = "<w:br/>".join(f'<w:t xml:space="preserve">{escape(d)}</w:t>' for d in dong)
    return (f'<w:p><w:pPr><w:spacing w:before="{truoc}" w:after="{sau}"/><w:jc w:val="{canh}"/></w:pPr>'
            f'<w:r><w:rPr>{kieu}</w:rPr>{than}</w:r></w:p>')


def _o(chu, rong, canh, dam=False, nen="", gop=1):
    tc = f'<w:tcW w:w="{rong}" w:type="dxa"/>' + (f'<w:gridSpan w:val="{gop}"/>' if gop > 1 else "")
    if nen:
        tc += f'<w:shd w:val="clear" w:color="auto" w:fill="{nen}"/>'
    return f'<w:tc><w:tcPr>{tc}<w:vAlign w:val="center"/></w:tcPr>{_doan(chu, canh, dam, co=20, sau=0)}</w:tc>'


def _bang(dong):
    co_sl = any((d.get("so_luong") or 0) > 0 for d in dong)
    cot = COT + (COT_SL if co_sl else [COT_GIA])
    tong_tl = sum(c[2] for c in cot)
    rong = [RONG * c[2] // tong_tl for c in cot]
    rong[2] += RONG - sum(rong)
    vien = "".join(f'<w:{v} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                   for v in ("top", "left", "bottom", "right", "insideH", "insideV"))
    x = (f'<w:tbl><w:tblPr><w:tblW w:w="{RONG}" w:type="dxa"/><w:tblBorders>{vien}</w:tblBorders>'
         '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="70" w:type="dxa"/>'
         '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar></w:tblPr>'
         f'<w:tblGrid>{"".join(f"<w:gridCol w:w=\"{r}\"/>" for r in rong)}</w:tblGrid>')
    x += ('<w:tr><w:trPr><w:tblHeader/></w:trPr>'
          + "".join(_o(c[0], r, "center", True, "D9E2F3") for c, r in zip(cot, rong)) + '</w:tr>')
    tong = 0
    for i, d in enumerate(dong, 1):
        sl, gia = d.get("so_luong") or 0, d.get("don_gia") or 0
        tong += sl * gia
        gt = dict(d, stt=str(i), don_gia=_so(gia) if gia else "", so_luong=_so(sl) if sl else "",
                  thanh_tien=_so(sl * gia) if sl else "")
        x += ('<w:tr><w:trPr><w:cantSplit/></w:trPr>'
              + "".join(_o(gt.get(c[1]) or "", r, c[3]) for c, r in zip(cot, rong)) + '</w:tr>')
    if co_sl:
        x += ('<w:tr>' + _o("TỔNG CỘNG", sum(rong[:-1]), "right", True, gop=len(cot) - 1)
              + _o(_so(tong), rong[-1], "right", True) + '</w:tr>')
    return x + '</w:tbl>'


def tao(bg, dong):
    d = _ngay(bg.get("ngay"))
    hl = _ngay(bg.get("hieu_luc_den"))
    than = _doan("BẢNG BÁO GIÁ", "center", True, co=32, sau=40)
    than += _doan(f"Số: {bg.get('so_bg') or ''}" + (f"   ·   Ngày {d.day:02d} tháng {d.month:02d} năm {d.year}" if d else ""),
                  "center", nghieng=True, sau=160)
    than += _doan(f"Kính gửi: {bg.get('ten_kh') or 'Quý Khách hàng'}", dam=True)
    than += _doan(GIOI_THIEU, "both")
    than += _doan(MO_DAU, sau=120)
    than += _bang(dong)
    if hl:
        than += _doan(f"Báo giá có hiệu lực đến hết ngày {hl.day:02d}/{hl.month:02d}/{hl.year}.", truoc=160)
    if (bg.get("ghi_chu") or "").strip():
        than += _doan("Ghi chú: " + bg["ghi_chu"].strip(), truoc=0 if hl else 160)
    if bg.get("phu_trach"):
        than += _doan(f"Người báo giá: {bg['phu_trach']}", truoc=120)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + than +
           '<w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>'
           '<w:pgMar w:top="850" w:right="850" w:bottom="850" w:left="850" w:header="400" w:footer="400" w:gutter="0"/>'
           '</w:sectPr></w:body></w:document>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr>'
              f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}" w:cs="{FONT}"/>'
              '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="vi-VN"/></w:rPr></w:rPrDefault>'
              '<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
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
