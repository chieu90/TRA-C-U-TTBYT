// Tài khoản đăng nhập trang muasamcongadc: đăng ký (chờ admin duyệt), đăng nhập, phân quyền theo vai trò.
// Lưu ở Neon Postgres (bảng mc_tai_khoan, dùng chung database với app hợp đồng) qua HTTP, không cần thư viện.
// Người đăng ký đầu tiên tự thành admin. Mật khẩu băm scrypt. Không in dữ liệu tài khoản ra log.
//   GET  /api/auth?action=toi              -> thông tin người đang đăng nhập (làm mới phiên)
//   POST /api/auth?action=dang-ky          {ten, email, sdt, mat_khau}
//   POST /api/auth?action=dang-nhap        {email, mat_khau}
//   POST /api/auth?action=dang-xuat
//   POST /api/auth?action=doi-mat-khau     {cu, moi}
//   Admin: GET ds | POST sua {id, vai_tro, trang_thai, tabs: ["goi-thau",...]} | POST xoa {id} | POST dat-mat-khau {id, mat_khau}
const crypto = require("crypto");

const ROLES = {
  admin: { ten: "Admin", tabs: ["goi-thau", "bao-gia", "co-so-y-te", "trung-thau", "duong-huyet", "so-sanh"] },
  quan_ly: { ten: "Quản lý", tabs: ["goi-thau", "bao-gia", "co-so-y-te", "trung-thau", "duong-huyet", "so-sanh"] },
  nhan_vien: { ten: "Nhân viên", tabs: ["goi-thau", "bao-gia", "co-so-y-te"] },
};
const ALL_TABS = ROLES.admin.tabs;
const STATUS = ["cho_duyet", "hoat_dong", "khoa"];
// quyền xem thực tế: admin xem tất cả; người khác theo cột tabs (admin tick từng tab), chưa tick thì theo vai trò mẫu
const tabsOf = u => u.vai_tro === "admin" ? ALL_TABS
  : (u.tabs != null ? String(u.tabs).split(",").filter(t => ALL_TABS.includes(t)) : (ROLES[u.vai_tro] || {}).tabs || []);
const SESSION_DAYS = 7;

const dbUrl = () => process.env.DATABASE_URL || process.env.POSTGRES_URL || process.env.NEON_DATABASE_URL || "";

async function sql(query, params = []) {
  const u = new URL(dbUrl().replace(/^postgres(ql)?:/, "https:"));
  const r = await fetch(`https://${u.hostname}/sql`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Neon-Connection-String": dbUrl() },
    body: JSON.stringify({ query, params }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error("db " + r.status + " " + (j.message || ""));
  return j.rows || [];
}

let ready = false;
async function ensure() {
  if (ready) return;
  await sql(`CREATE TABLE IF NOT EXISTS mc_tai_khoan (
    id SERIAL PRIMARY KEY, ten TEXT NOT NULL, email TEXT UNIQUE NOT NULL, sdt TEXT DEFAULT '',
    mat_khau TEXT NOT NULL, vai_tro TEXT NOT NULL DEFAULT 'nhan_vien', trang_thai TEXT NOT NULL DEFAULT 'cho_duyet',
    tao_luc TIMESTAMPTZ DEFAULT now(), duyet_luc TIMESTAMPTZ, dang_nhap_cuoi TIMESTAMPTZ)`);
  await sql("ALTER TABLE mc_tai_khoan ADD COLUMN IF NOT EXISTS tabs TEXT");
  ready = true;
}

const b64u = b => Buffer.from(b).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const sessionKey = () => crypto.createHash("sha256").update("muasamcong-auth|" + dbUrl()).digest();
function makeToken(u) {
  const body = b64u(JSON.stringify({ i: u.id, r: u.vai_tro, t: tabsOf(u), exp: Math.floor(Date.now() / 1000) + SESSION_DAYS * 86400 }));
  return body + "." + b64u(crypto.createHmac("sha256", sessionKey()).update(body).digest());
}
function readToken(req) {
  const m = (req.headers.cookie || "").match(/(?:^|;\s*)mc_phien=([^;]+)/);
  if (!m) return null;
  const [body, sig] = m[1].split(".");
  if (!body || !sig || b64u(crypto.createHmac("sha256", sessionKey()).update(body).digest()) !== sig) return null;
  try {
    const s = JSON.parse(Buffer.from(body.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString());
    return s.exp > Date.now() / 1000 ? s : null;
  } catch (e) { return null; }
}
const setCookie = (res, v, maxAge) => res.setHeader("Set-Cookie",
  `mc_phien=${v}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`);

function hashPw(pw) {
  const salt = crypto.randomBytes(16);
  return "s1$" + salt.toString("hex") + "$" + crypto.scryptSync(pw, salt, 32).toString("hex");
}
function checkPw(pw, stored) {
  const [v, salt, hash] = String(stored).split("$");
  if (v !== "s1") return false;
  const h = crypto.scryptSync(pw, Buffer.from(salt, "hex"), 32);
  return crypto.timingSafeEqual(h, Buffer.from(hash, "hex"));
}

const pub = u => ({ id: u.id, ten: u.ten, email: u.email, sdt: u.sdt, vai_tro: u.vai_tro,
  ten_vai_tro: (ROLES[u.vai_tro] || {}).ten || u.vai_tro, trang_thai: u.trang_thai, tabs: tabsOf(u),
  tao_luc: u.tao_luc, duyet_luc: u.duyet_luc, dang_nhap_cuoi: u.dang_nhap_cuoi });

function body(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try { return JSON.parse(req.body || "{}"); } catch (e) { return {}; }
}
const send = (res, code, data) => { res.statusCode = code; res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store"); res.end(JSON.stringify(data)); };
const cleanEmail = e => String(e || "").trim().toLowerCase();

module.exports = async (req, res) => {
  if (!dbUrl()) return send(res, 503, { loi: "Chưa nối database cho trang này (thiếu DATABASE_URL trên Vercel)." });
  const action = new URL(req.url, "http://x").searchParams.get("action") || "";
  try {
    await ensure();
    const b = body(req);

    if (action === "vai-tro") return send(res, 200, { vai_tro: ROLES });

    if (action === "dang-ky" && req.method === "POST") {
      const ten = String(b.ten || "").trim(), email = cleanEmail(b.email), pw = String(b.mat_khau || "");
      if (!ten || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return send(res, 400, { loi: "Nhập họ tên và email hợp lệ." });
      if (pw.length < 8) return send(res, 400, { loi: "Mật khẩu tối thiểu 8 ký tự." });
      if ((await sql("SELECT 1 FROM mc_tai_khoan WHERE email=$1", [email])).length)
        return send(res, 409, { loi: "Email này đã đăng ký. Nếu chưa vào được, chờ admin duyệt." });
      const first = !(await sql("SELECT 1 FROM mc_tai_khoan LIMIT 1")).length;
      await sql(`INSERT INTO mc_tai_khoan (ten, email, sdt, mat_khau, vai_tro, trang_thai, duyet_luc)
                 VALUES ($1,$2,$3,$4,$5,$6,$7)`,
        [ten, email, String(b.sdt || "").trim(), hashPw(pw), first ? "admin" : "nhan_vien",
         first ? "hoat_dong" : "cho_duyet", first ? new Date().toISOString() : null]);
      return send(res, 200, { ok: true, admin: first,
        thong_bao: first ? "Tài khoản admin đầu tiên đã tạo, mời đăng nhập." : "Đã gửi đăng ký. Admin duyệt xong thì đăng nhập được." });
    }

    if (action === "dang-nhap" && req.method === "POST") {
      const [u] = await sql("SELECT * FROM mc_tai_khoan WHERE email=$1", [cleanEmail(b.email)]);
      if (!u || !checkPw(String(b.mat_khau || ""), u.mat_khau)) {
        await new Promise(r => setTimeout(r, 600));
        return send(res, 401, { loi: "Sai email hoặc mật khẩu." });
      }
      if (u.trang_thai === "cho_duyet") return send(res, 403, { loi: "Tài khoản đang chờ admin duyệt." });
      if (u.trang_thai !== "hoat_dong") return send(res, 403, { loi: "Tài khoản đã bị khóa. Liên hệ admin." });
      await sql("UPDATE mc_tai_khoan SET dang_nhap_cuoi=now() WHERE id=$1", [u.id]);
      setCookie(res, makeToken(u), SESSION_DAYS * 86400);
      return send(res, 200, { ok: true, tai_khoan: pub(u) });
    }

    if (action === "dang-xuat") { setCookie(res, "", 0); return send(res, 200, { ok: true }); }

    // các thao tác dưới đây cần đăng nhập; luôn đọc lại tài khoản từ database
    const s = readToken(req);
    const [me] = s ? await sql("SELECT * FROM mc_tai_khoan WHERE id=$1", [s.i]) : [];
    if (!me || me.trang_thai !== "hoat_dong") { if (s) setCookie(res, "", 0); return send(res, 401, { loi: "Chưa đăng nhập." }); }
    if (me.vai_tro !== s.r || tabsOf(me).join(",") !== (s.t || []).join(","))  // vai trò / quyền tab vừa đổi -> cấp phiên mới
      setCookie(res, makeToken(me), SESSION_DAYS * 86400);

    if (action === "toi") {
      const cho = me.vai_tro === "admin" ? (await sql("SELECT count(*)::int AS n FROM mc_tai_khoan WHERE trang_thai='cho_duyet'"))[0].n : 0;
      return send(res, 200, { tai_khoan: pub(me), cho_duyet: cho });
    }

    if (action === "doi-mat-khau" && req.method === "POST") {
      if (!checkPw(String(b.cu || ""), me.mat_khau)) return send(res, 400, { loi: "Mật khẩu hiện tại không đúng." });
      if (String(b.moi || "").length < 8) return send(res, 400, { loi: "Mật khẩu mới tối thiểu 8 ký tự." });
      await sql("UPDATE mc_tai_khoan SET mat_khau=$1 WHERE id=$2", [hashPw(String(b.moi)), me.id]);
      return send(res, 200, { ok: true });
    }

    if (me.vai_tro !== "admin") return send(res, 403, { loi: "Chỉ admin được làm việc này." });

    if (action === "ds") {
      const rows = await sql("SELECT * FROM mc_tai_khoan ORDER BY (trang_thai='cho_duyet') DESC, tao_luc DESC");
      return send(res, 200, { ds: rows.map(pub), vai_tro: ROLES });
    }
    const id = parseInt(b.id, 10);
    const [u] = id ? await sql("SELECT * FROM mc_tai_khoan WHERE id=$1", [id]) : [];
    if (!u) return send(res, 404, { loi: "Không tìm thấy tài khoản." });
    const admins = async () => (await sql("SELECT count(*)::int AS n FROM mc_tai_khoan WHERE vai_tro='admin' AND trang_thai='hoat_dong'"))[0].n;

    if (action === "sua" && req.method === "POST") {
      const vt = ROLES[b.vai_tro] ? b.vai_tro : u.vai_tro, tt = STATUS.includes(b.trang_thai) ? b.trang_thai : u.trang_thai;
      if (u.vai_tro === "admin" && u.trang_thai === "hoat_dong" && (vt !== "admin" || tt !== "hoat_dong") && (await admins()) <= 1)
        return send(res, 400, { loi: "Phải còn ít nhất 1 admin đang hoạt động." });
      const tabs = Array.isArray(b.tabs) ? b.tabs.filter(t => ALL_TABS.includes(t)).join(",") : u.tabs;
      await sql(`UPDATE mc_tai_khoan SET vai_tro=$1, trang_thai=$2, tabs=$4,
                 duyet_luc = CASE WHEN $2='hoat_dong' AND duyet_luc IS NULL THEN now() ELSE duyet_luc END WHERE id=$3`, [vt, tt, id, tabs]);
      return send(res, 200, { ok: true });
    }
    if (action === "xoa" && req.method === "POST") {
      if (u.id === me.id) return send(res, 400, { loi: "Không tự xóa tài khoản của mình." });
      if (u.vai_tro === "admin" && (await admins()) <= 1) return send(res, 400, { loi: "Phải còn ít nhất 1 admin." });
      await sql("DELETE FROM mc_tai_khoan WHERE id=$1", [id]);
      return send(res, 200, { ok: true });
    }
    if (action === "dat-mat-khau" && req.method === "POST") {
      if (String(b.mat_khau || "").length < 8) return send(res, 400, { loi: "Mật khẩu tối thiểu 8 ký tự." });
      await sql("UPDATE mc_tai_khoan SET mat_khau=$1 WHERE id=$2", [hashPw(String(b.mat_khau)), id]);
      return send(res, 200, { ok: true });
    }
    return send(res, 404, { loi: "Không rõ thao tác." });
  } catch (e) {
    console.error("auth", action, e.message);
    return send(res, 500, { loi: "Lỗi máy chủ, thử lại sau." });
  }
};
