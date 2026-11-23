// Tab "Quản lý công việc": gói thầu được phân cho nhân viên theo Google Sheet phân công cơ sở y tế
// (cùng sheet dùng cho mail gói thầu: tab "Nhân viên" và "Cơ sở y tế"). Nhân viên ghi khách hàng, có tham gia không,
// mặt hàng tham gia, kết quả, ghi chú -> bảng mc_cong_viec (Neon). Không in dữ liệu ra log (repo công khai).
const SYNC_MIN = 15;  // phút: đọc lại sheet phân công khi cũ hơn mức này
const THAM_GIA = ["", "co", "khong"];
const KET_QUA = ["", "cho", "trung", "truot", "huy"];

const fold = s => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D")
  .toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const foldTinh = s => fold(s).replace(/^(thanh pho|tinh|tp)\s+/, "");
// độ giống 2 chuỗi (hệ số Dice trên cặp ký tự), 1 = giống hệt
function giong(a, b) {
  if (a === b) return 1;
  if (a.length < 2 || b.length < 2) return 0;
  const m = new Map();
  for (let i = 0; i < a.length - 1; i++) { const k = a.slice(i, i + 2); m.set(k, (m.get(k) || 0) + 1); }
  let n = 0;
  for (let i = 0; i < b.length - 1; i++) { const k = b.slice(i, i + 2), c = m.get(k); if (c) { n++; m.set(k, c - 1); } }
  return 2 * n / (a.length + b.length - 2);
}

function sheetId(link) {
  return (String(link).match(/\/d\/([a-zA-Z0-9_-]{20,})/) || String(link).match(/^([a-zA-Z0-9_-]{30,})$/) || [])[1] || "";
}
async function tab(id, name, parseCsv) {
  const r = await fetch(`https://docs.google.com/spreadsheets/d/${id}/gviz/tq?tqx=out:csv&sheet=${encodeURIComponent(name)}`);
  const t = await r.text();
  if (!r.ok || /^\s*<(!doctype|html)/i.test(t))
    throw new Error("Không đọc được sheet phân công. Mở chia sẻ \"Bất kỳ ai có đường liên kết – Người xem\".");
  return parseCsv(t).slice(1);
}
// đọc sheet -> {nv: [{ten, email:[...]}], cs: [[cdt đã gập, tỉnh đã gập, tên nhân viên]]}
async function docSheet(link, parseCsv) {
  const id = sheetId(link);
  if (!id) throw new Error("Link không phải Google Sheet.");
  const nv = (await tab(id, "Nhân viên", parseCsv)).filter(r => String(r[0] || "").trim())
    .map(r => ({ ten: String(r[0]).trim(), email: String(r[1] || "").split(/[,;\s]+/).map(e => e.trim().toLowerCase()).filter(e => e.includes("@")) }));
  const cs = (await tab(id, "Cơ sở y tế", parseCsv)).filter(r => String(r[0] || "").trim() && String(r[2] || "").trim())
    .map(r => [fold(r[0]), foldTinh(r[1]), String(r[2]).trim()]);
  if (!cs.length) throw new Error("Sheet phân công chưa có cơ sở nào có nhân viên phụ trách (tab \"Cơ sở y tế\").");
  return { nv, cs };
}

// chủ đầu tư + tỉnh -> tên nhân viên phụ trách ('' nếu chưa giao). Giống thong_bao_mail.py: tên lệch chút thì so gần đúng trong cùng tỉnh.
function phanCong(pc) {
  const exact = new Map(pc.cs.map(c => [c[0], c[2]]));
  return (cdt, tinh) => {
    const k = fold(cdt);
    if (exact.has(k)) return exact.get(k);
    const t = foldTinh(tinh);
    let best = 0, who = "";
    for (const c of pc.cs) if (c[1] === t) { const g = giong(k, c[0]); if (g > best) { best = g; who = c[2]; } }
    return best >= 0.9 ? who : "";
  };
}

const trimGoi = g => ({ ma: g.ma, ten: g.ten || "", cdt: g.cdt || "", tinh: g.tinh || "", han: g.han || "", dang: g.dang || "",
  gia_goi: g.gia_goi || null, link: g.link || "", hinh_thuc: g.hinh_thuc || "",
  hang: (g.hang_hoa || []).map(h => ({ ten: h.ten || "", nhom: h.nhom || "", sl: h.sl ?? null, dvt: h.dvt || "" })) });
const sach = (v, n) => String(v ?? "").trim().slice(0, n);

module.exports = function congViec({ sql, cfg, setCfg, parseCsv, docFile, me }) {
  const laQl = me.vai_tro === "admin" || me.vai_tro === "quan_ly";

  async function layPhanCong(ep = false) {
    const link = await cfg("phan_cong_link");
    if (!link) return { link: "", nv: [], cs: [], loi: "" };
    const luc = await cfg("phan_cong_luc");
    let loi = "";
    if (ep || !luc || Date.now() - Date.parse(luc) > SYNC_MIN * 60000) {
      try {
        const d = await docSheet(link, parseCsv);
        await setCfg("phan_cong_data", JSON.stringify(d));
        await setCfg("phan_cong_luc", new Date().toISOString());
      } catch (e) { if (ep) throw e; loi = e.message; }  // lỗi thì dùng bản đọc lần trước
    }
    let d = { nv: [], cs: [] };
    try { d = JSON.parse(await cfg("phan_cong_data") || "{}"); } catch (e) {}
    return { link, nv: d.nv || [], cs: d.cs || [], luc: await cfg("phan_cong_luc"), loi };
  }
  // tên nhân viên của người đang đăng nhập: admin chọn ở Quản trị (cv_nv) > nhân viên KQ > email trùng tab "Nhân viên"
  const kqMot = String(me.kq_nv || "").split(/\s*[,;]\s*/).filter(Boolean);  // chỉ dùng khi KQ gắn đúng 1 nhân viên
  const toiLa = pc => String(me.cv_nv || "").trim() || (kqMot.length === 1 ? kqMot[0] : "")
    || ((pc.nv || []).find(n => n.email.includes(String(me.email).toLowerCase())) || {}).ten || "";
  const coToi = (nv, toi) => !!toi && String(nv || "").split(/[,;]+/).map(x => x.trim()).includes(toi);

  return {
    async ds() {
      const pc = await layPhanCong();
      const toi = toiLa(pc), ai = phanCong(pc);
      const file = await docFile("/goi_thau.json").catch(() => null);
      const goi = new Map(((file && file.goi) || []).map(g => [g.ma, trimGoi(g)]));
      const luu = new Map((await sql("SELECT * FROM mc_cong_viec")).map(r => [r.ma, r]));
      const out = [];
      for (const ma of new Set([...goi.keys(), ...luu.keys()])) {
        const r = luu.get(ma), g = goi.get(ma) || (r && r.goi ? JSON.parse(r.goi) : null);
        if (!g) continue;
        const tu_dong = ai(g.cdt, g.tinh), nv = r ? r.nv : tu_dong;
        if (!laQl && !coToi(nv, toi)) continue;   // nhân viên chỉ thấy việc của mình
        if (!nv && !r && !laQl) continue;
        out.push({ ...g, nv, tu_dong, con_tren_web: goi.has(ma),
          khach: r ? r.khach : "", tham_gia: r ? r.tham_gia : "", ket_qua: r ? r.ket_qua : "", ghi_chu: r ? r.ghi_chu : "",
          san_pham: r && r.san_pham ? JSON.parse(r.san_pham) : [], sua_boi: r ? r.sua_boi : "", sua_luc: r ? r.sua_luc : null });
      }
      out.sort((a, b) => String(b.han).localeCompare(String(a.han)));
      const khach = (await sql("SELECT ten, nv FROM mc_khach_nv ORDER BY ten"));
      const nvTen = [...new Set([...pc.nv.map(n => n.ten), ...pc.cs.map(c => c[2])])].sort((a, b) => a.localeCompare(b, "vi"));
      return { toi, la_ql: laQl, nv: nvTen, khach, viec: out, cap_nhat: file && file.cap_nhat,
        phan_cong: { co_link: !!pc.link, link: me.vai_tro === "admin" ? pc.link : undefined, luc: pc.luc, loi: pc.loi || undefined } };
    },

    async luu(b) {
      const ma = sach(b.ma, 40);
      if (!ma) return [400, { loi: "Thiếu mã gói thầu." }];
      const pc = await layPhanCong(), toi = toiLa(pc);
      const file = await docFile("/goi_thau.json").catch(() => null);
      const g0 = ((file && file.goi) || []).find(g => g.ma === ma);
      const [cu] = await sql("SELECT * FROM mc_cong_viec WHERE ma=$1", [ma]);
      if (!g0 && !cu) return [404, { loi: "Không tìm thấy gói thầu." }];
      const g = g0 ? trimGoi(g0) : JSON.parse(cu.goi);
      const nvHienTai = cu ? cu.nv : phanCong(pc)(g.cdt, g.tinh);
      if (!laQl && !coToi(nvHienTai, toi)) return [403, { loi: "Gói này không phân cho bạn." }];
      const tham_gia = THAM_GIA.includes(b.tham_gia) ? b.tham_gia : "", ket_qua = KET_QUA.includes(b.ket_qua) ? b.ket_qua : "";
      const ten = new Set(g.hang.map(h => h.ten));
      const san_pham = (Array.isArray(b.san_pham) ? b.san_pham : []).filter(x => x && ten.has(x.ten))
        .map(x => ({ ten: sach(x.ten, 300), chao: sach(x.chao, 200) })).slice(0, 200);
      const v = [ma, sach(b.nv, 100), sach(b.khach, 200), tham_gia, JSON.stringify(san_pham), ket_qua, sach(b.ghi_chu, 3000),
        JSON.stringify(g), me.ten];
      await sql(`INSERT INTO mc_cong_viec (ma, nv, khach, tham_gia, san_pham, ket_qua, ghi_chu, goi, sua_boi, sua_luc)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,now()) ON CONFLICT (ma) DO UPDATE SET nv=EXCLUDED.nv, khach=EXCLUDED.khach,
        tham_gia=EXCLUDED.tham_gia, san_pham=EXCLUDED.san_pham, ket_qua=EXCLUDED.ket_qua, ghi_chu=EXCLUDED.ghi_chu,
        goi=EXCLUDED.goi, sua_boi=EXCLUDED.sua_boi, sua_luc=now()`, v);
      return [200, { ok: true }];
    },

    async ganLink(link) {  // admin: lưu link sheet phân công và đọc ngay
      link = sach(link, 500);
      if (!link) { await setCfg("phan_cong_link", ""); return [200, { ok: true, so: 0 }]; }
      const old = await cfg("phan_cong_link");
      await setCfg("phan_cong_link", link);
      try { const pc = await layPhanCong(true); return [200, { ok: true, so: pc.cs.length, nv: pc.nv.length }]; }
      catch (e) { await setCfg("phan_cong_link", old); return [400, { loi: e.message }]; }
    },
  };
};
