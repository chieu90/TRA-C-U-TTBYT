// Trợ lý AI cho tab Kết quả trúng thầu: Claude tự gọi 2 công cụ (thống kê / tìm dòng) trên dữ liệu KQ
// mà người hỏi được xem (đã lọc theo tab và theo "chỉ khách của nhân viên"). Dữ liệu không rời máy chủ ngoài
// các kết quả công cụ gửi cho Claude. Khóa API đặt ở biến môi trường ANTHROPIC_API_KEY trên Vercel.
// File bắt đầu bằng "_" nên Vercel không coi là một API riêng.
const Anthropic = require("@anthropic-ai/sdk");
const { betaTool } = require("@anthropic-ai/sdk/helpers/beta/json-schema");

const MODEL = process.env.KQ_AI_MODEL || "claude-opus-5-5";
const fold = s => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase().replace(/\s+/g, " ").trim();
const NHOM_THEO = { cdt: "cdt", tinh: "tinh", nhom: "nhom", hang: "hang_chuan", nha_thau: "nha_thau", xuat_xu: "xuat_xu", ten: "ten", thang: "_thang", nam: "_nam", hinh_thuc: "hinh_thuc" };

// ds: [{loai: "test"|"duong_huyet", nam, cot, rows}] -> bảng phẳng các đối tượng
function phang(ds) {
  const out = [];
  for (const d of ds) {
    const ix = Object.fromEntries(d.cot.map((c, i) => [c, i]));
    for (const r of d.rows) {
      const o = { loai: d.loai };
      for (const c of d.cot) o[c] = r[ix[c]];
      o._nam = String(o.ngay || "").slice(0, 4) || String(d.nam);
      o._thang = String(o.ngay || "").slice(0, 7);
      o._gt = (Number(o.sl) || 0) * (Number(o.don_gia) || 0);
      out.push(o);
    }
  }
  return out;
}

const CHUA = ["cdt", "tinh", "nhom", "hang", "nha_thau", "ten", "xuat_xu", "ma"];
function loc(rows, f = {}) {
  const can = CHUA.filter(k => f[k]).map(k => [k === "hang" ? "_hang" : k, fold(f[k])]);
  return rows.filter(r => {
    if (f.loai && r.loai !== f.loai) return false;
    if (f.nam && r._nam !== String(f.nam)) return false;
    if (f.tu_ngay && String(r.ngay) < f.tu_ngay) return false;
    if (f.den_ngay && String(r.ngay) > f.den_ngay) return false;
    for (const [k, v] of can) {
      const s = k === "_hang" ? fold(`${r.hang} ${r.hang_chuan} ${r.nhan}`) : fold(r[k]);
      if (!s.includes(v)) return false;
    }
    return true;
  });
}

const BO_LOC = {
  loai: { type: "string", enum: ["test", "duong_huyet"], description: "test = KQ Test nhanh; duong_huyet = KQ que/máy đường huyết. Bỏ trống = cả hai." },
  nam: { type: "string", description: "Năm trúng thầu, ví dụ 2026" },
  tu_ngay: { type: "string", description: "YYYY-MM-DD" },
  den_ngay: { type: "string", description: "YYYY-MM-DD" },
  cdt: { type: "string", description: "Một phần tên cơ sở y tế / chủ đầu tư (không dấu cũng được)" },
  tinh: { type: "string", description: "Một phần tên tỉnh" },
  nhom: { type: "string", description: "Một phần tên nhóm hàng, ví dụ 'HIV', 'Cúm', 'Dengue'" },
  hang: { type: "string", description: "Một phần tên hãng sản xuất hoặc nhãn hiệu" },
  nha_thau: { type: "string", description: "Một phần tên nhà thầu trúng" },
  ten: { type: "string", description: "Một phần tên hàng hóa" },
  xuat_xu: { type: "string", description: "Nước xuất xứ" },
  ma: { type: "string", description: "Mã TBMT, ví dụ IB2600607981" },
};
const sach = (input, keys) => Object.fromEntries(Object.entries(input || {}).filter(([k, v]) => keys.includes(k) && typeof v === "string" && v.trim()).map(([k, v]) => [k, v.trim().slice(0, 120)]));
const tron = n => Math.round(n);

function thongKe(rows, input) {
  const f = sach(input, Object.keys(BO_LOC));
  const by = NHOM_THEO[input?.nhom_theo] ? input.nhom_theo : "";
  const top = Math.min(Math.max(parseInt(input?.so_nhom) || 15, 1), 50);
  const sel = loc(rows, f);
  const tong = { so_dong: sel.length, so_goi: new Set(sel.map(r => r.ma)).size, gia_tri_vnd: tron(sel.reduce((a, r) => a + r._gt, 0)),
    so_luong: tron(sel.reduce((a, r) => a + (Number(r.sl) || 0), 0)), so_test: tron(sel.reduce((a, r) => a + (Number(r.sl_test) || 0), 0)) };
  if (!by) return { bo_loc: f, tong };
  const g = new Map(), col = NHOM_THEO[by];
  for (const r of sel) for (const k of (by === "nha_thau" ? String(r.nha_thau || "").split("; ") : [r[col]])) {
    const key = k || "(trống)";
    const x = g.get(key) || { ten: key, so_dong: 0, goi: new Set(), gia_tri_vnd: 0, so_luong: 0, so_test: 0, gia: [] };
    x.so_dong++; x.goi.add(r.ma); x.gia_tri_vnd += r._gt; x.so_luong += Number(r.sl) || 0; x.so_test += Number(r.sl_test) || 0;
    if (Number(r.don_gia)) x.gia.push(Number(r.don_gia));
    g.set(key, x);
  }
  const sap = input?.sap_xep === "so_dong" ? "so_dong" : input?.sap_xep === "so_test" ? "so_test" : by === "thang" || by === "nam" ? "ten" : "gia_tri_vnd";
  const ds = [...g.values()].sort((a, b) => sap === "ten" ? String(a.ten).localeCompare(b.ten) : b[sap] - a[sap]);
  return { bo_loc: f, nhom_theo: by, tong, so_nhom: ds.length, nhom: ds.slice(0, top).map(x => ({ ten: x.ten, so_dong: x.so_dong, so_goi: x.goi.size,
    gia_tri_vnd: tron(x.gia_tri_vnd), so_luong: tron(x.so_luong), so_test: tron(x.so_test),
    don_gia_min: x.gia.length ? Math.min(...x.gia) : null, don_gia_max: x.gia.length ? Math.max(...x.gia) : null })) };
}

function timDong(rows, input) {
  const f = sach(input, Object.keys(BO_LOC));
  const n = Math.min(Math.max(parseInt(input?.so_dong) || 20, 1), 40);
  const sel = loc(rows, f);
  const s = input?.sap_xep;
  sel.sort(s === "don_gia_tang" ? (a, b) => (a.don_gia || 0) - (b.don_gia || 0) : s === "don_gia_giam" ? (a, b) => (b.don_gia || 0) - (a.don_gia || 0)
    : s === "gia_tri_giam" ? (a, b) => b._gt - a._gt : (a, b) => String(b.ngay).localeCompare(String(a.ngay)));
  return { bo_loc: f, tong_so_dong: sel.length, dong: sel.slice(0, n).map(r => ({ ma: r.ma, ngay: r.ngay, cdt: r.cdt, tinh: r.tinh, nhom: r.nhom, ten: String(r.ten || "").slice(0, 160),
    hang: r.hang_chuan || r.hang, nhan: r.nhan, xuat_xu: r.xuat_xu, dvt: r.dvt, sl: r.sl, don_gia: r.don_gia, gia_tri_vnd: tron(r._gt), nha_thau: r.nha_thau, hinh_thuc: r.hinh_thuc })) };
}

// messages: [{role:"user"|"assistant", content:string}] (lịch sử ngắn do trình duyệt gửi lên)
async function hoi({ ds, messages, pham_vi, nhom_hang }) {
  if (!process.env.ANTHROPIC_API_KEY) { const e = new Error("Chưa cài khóa ANTHROPIC_API_KEY trên Vercel."); e.code = 503; throw e; }
  const rows = phang(ds);
  const nams = [...new Set(rows.map(r => r._nam))].sort();
  const client = new Anthropic();
  const tools = [
    betaTool({ name: "thong_ke", description: "Tổng hợp kết quả trúng thầu theo bộ lọc: tổng số dòng, số gói, giá trị (VNĐ = số lượng × đơn giá), số lượng, số test; nếu có nhom_theo thì chia nhóm (cơ sở y tế, tỉnh, nhóm hàng, hãng, nhà thầu, xuất xứ, tên hàng, tháng, năm, hình thức). Dùng cho câu hỏi tổng số, xếp hạng, thị phần, so sánh năm.",
      inputSchema: { type: "object", additionalProperties: false, properties: { ...BO_LOC,
        nhom_theo: { type: "string", enum: Object.keys(NHOM_THEO) },
        sap_xep: { type: "string", enum: ["gia_tri_vnd", "so_dong", "so_test"], description: "Mặc định gia_tri_vnd (theo tháng/năm thì theo thời gian)" },
        so_nhom: { type: "integer", description: "Số nhóm trả về, tối đa 50, mặc định 15" } } },
      run: async input => JSON.stringify(thongKe(rows, input)) }),
    betaTool({ name: "tim_dong", description: "Liệt kê từng dòng kết quả trúng thầu (gói, ngày, cơ sở y tế, hàng, hãng, đơn giá, nhà thầu) theo bộ lọc. Dùng khi cần chi tiết hoặc đơn giá cụ thể.",
      inputSchema: { type: "object", additionalProperties: false, properties: { ...BO_LOC,
        sap_xep: { type: "string", enum: ["moi_nhat", "don_gia_tang", "don_gia_giam", "gia_tri_giam"] },
        so_dong: { type: "integer", description: "Tối đa 40, mặc định 20" } } },
      run: async input => JSON.stringify(timDong(rows, input)) }),
  ];
  const system = `Bạn là trợ lý phân tích kết quả trúng thầu test nhanh và đường huyết (dữ liệu muasamcong) cho công ty kinh doanh thiết bị y tế.
Luôn trả lời bằng tiếng Việt, ngắn gọn, đúng trọng tâm; số liệu lấy từ công cụ, không bịa. Mỗi câu hỏi có số liệu phải gọi công cụ trước khi trả lời.
Tiền viết dạng 1.234.567 đ (hoặc "x,y tỷ" / "x triệu" khi lớn). Khi liệt kê nhiều mục dùng bảng Markdown ngắn (tối đa ~15 dòng).
Nếu công cụ trả về 0 dòng, thử nới bộ lọc (bỏ dấu, rút ngắn từ khóa) trước khi kết luận không có.
Dữ liệu có các năm: ${nams.join(", ")}. Hôm nay: ${new Date().toISOString().slice(0, 10)}.
Nhóm hàng Test: ${(nhom_hang || []).join("; ")}.
${pham_vi ? `Phạm vi của người hỏi: chỉ các kết quả mà nhà thầu trúng là khách do ${pham_vi} phụ trách. Nói rõ điều này khi trả lời về tổng thị trường.` : "Người hỏi xem được toàn bộ dữ liệu."}
Không trả lời các việc ngoài dữ liệu kết quả trúng thầu này.`;
  const msgs = (messages || []).filter(m => (m.role === "user" || m.role === "assistant") && typeof m.content === "string" && m.content.trim())
    .slice(-12).map(m => ({ role: m.role, content: m.content.slice(0, 4000) }));
  while (msgs.length && msgs[0].role !== "user") msgs.shift();
  if (!msgs.length || msgs[msgs.length - 1].role !== "user") { const e = new Error("Thiếu câu hỏi."); e.code = 400; throw e; }

  const runner = client.beta.messages.toolRunner({
    model: MODEL, max_tokens: 8000, max_iterations: 8,
    betas: ["server-side-fallback-2026-07-01"], fallbacks: "default",
    output_config: { effort: "low" },
    system, tools, messages: msgs,
  });
  const final = await runner.runUntilDone();
  if (final.stop_reason === "refusal") return { tra_loi: "Xin lỗi, tôi không trả lời được câu hỏi này." };
  const text = final.content.filter(b => b.type === "text").map(b => b.text).join("\n").trim();
  return { tra_loi: text || "Chưa có câu trả lời, anh/chị hỏi lại giúp tôi." };
}

module.exports = { hoi };
