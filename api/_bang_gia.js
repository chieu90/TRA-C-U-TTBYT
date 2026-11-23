// Bảng giá đại lý kênh ETC: admin dán link Google Sheet ở Quản trị, máy chủ đọc (gviz CSV) và lưu bản sao vào mc_cau_hinh.
// Giá là thông tin nội bộ: KHÔNG ghi vào repo công khai, chỉ trả qua /api/auth cho người đã đăng nhập. Không in dữ liệu ra log.
const SYNC_MIN = 15;  // phút: đọc lại sheet khi bản lưu cũ hơn mức này
const MAX_ROWS = 5000;

const fold = s => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
function sheetRef(link) {
  link = String(link || "");
  const id = (link.match(/\/d\/([a-zA-Z0-9_-]{20,})/) || link.match(/^([a-zA-Z0-9_-]{30,})$/) || [])[1] || "";
  const gid = (link.match(/[#&?]gid=(\d+)/) || [])[1] || "";
  return { id, gid };
}
// dòng tiêu đề: dòng đầu (trong 15 dòng) có ít nhất 2 ô giống tên cột bảng giá
const HEAD_RE = [/ten|san pham|mat hang|hang hoa/, /\bma\b|ky ma|ma hang|ma sp|code|ref|cat/, /hang sx|hang|nha san xuat|brand/, /gia/, /dvt|don vi/, /quy cach|dong goi/];
function headerRow(rows) {
  let best = 0, at = 0;
  rows.slice(0, 15).forEach((r, i) => {
    const n = HEAD_RE.filter(re => r.some(c => c && String(c).length < 60 && re.test(fold(c)))).length;
    if (n > best) { best = n; at = i; }
  });
  return best >= 2 ? at : 0;
}

async function docSheet(link, parseCsv) {
  const { id, gid } = sheetRef(link);
  if (!id) throw new Error("Link không phải Google Sheet.");
  const r = await fetch(`https://docs.google.com/spreadsheets/d/${id}/gviz/tq?tqx=out:csv${gid ? "&gid=" + gid : ""}`);
  const t = await r.text();
  if (!r.ok || /^\s*<(!doctype|html)/i.test(t))
    throw new Error("Không đọc được bảng giá. Mở chia sẻ \"Bất kỳ ai có đường liên kết – Người xem\".");
  const rows = parseCsv(t).map(r => r.map(c => String(c ?? "").trim()));
  const h = headerRow(rows);
  const cot = rows[h] || [];
  const ds = rows.slice(h + 1).filter(r => r.some(Boolean)).slice(0, MAX_ROWS);
  if (!ds.length) throw new Error("Bảng giá trống.");
  // cột giá: tiêu đề có chữ "giá" (có thể nhiều cột: giá đại lý, giá bán lẻ...)
  const gia = cot.map((c, i) => /gia/.test(fold(c)) ? i : -1).filter(i => i >= 0);
  return { cot, rows: ds, cot_gia: gia };
}

module.exports = function bangGia({ cfg, setCfg, parseCsv, me }) {
  async function lay(ep = false) {
    const link = await cfg("bang_gia_link");
    if (!link) return { link: "", cot: [], rows: [], cot_gia: [] };
    const luc = await cfg("bang_gia_luc");
    let loi = "";
    if (ep || !luc || Date.now() - Date.parse(luc) > SYNC_MIN * 60000) {
      try {
        const d = await docSheet(link, parseCsv);
        await setCfg("bang_gia_data", JSON.stringify(d));
        await setCfg("bang_gia_luc", new Date().toISOString());
      } catch (e) { if (ep) throw e; loi = e.message; }  // lỗi thì dùng bản đọc lần trước
    }
    let d = {};
    try { d = JSON.parse(await cfg("bang_gia_data") || "{}"); } catch (e) {}
    return { link, cot: d.cot || [], rows: d.rows || [], cot_gia: d.cot_gia || [], luc: await cfg("bang_gia_luc"), loi };
  }
  return {
    async xem() {  // người đã đăng nhập có quyền KQ Test
      const d = await lay();
      return { co_link: !!d.link, link: me.vai_tro === "admin" ? d.link : undefined, cot: d.cot, cot_gia: d.cot_gia, rows: d.rows,
        luc: d.luc, loi: d.loi || undefined };
    },
    async ganLink(link) {  // admin: lưu link và đọc ngay; lỗi thì giữ link cũ
      link = String(link || "").trim().slice(0, 500);
      if (!link) { await setCfg("bang_gia_link", ""); await setCfg("bang_gia_data", ""); return [200, { ok: true, so: 0 }]; }
      const old = await cfg("bang_gia_link");
      await setCfg("bang_gia_link", link);
      try { const d = await lay(true); return [200, { ok: true, so: d.rows.length, cot: d.cot, cot_gia: d.cot_gia.map(i => d.cot[i]) }]; }
      catch (e) { await setCfg("bang_gia_link", old); return [400, { loi: e.message }]; }
    },
  };
};
