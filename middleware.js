// Chặn truy cập trang muasamcongadc khi chưa đăng nhập, và phân quyền theo vai trò.
// Chạy ở Vercel Routing Middleware (trước khi trả file tĩnh). Không cần thư viện ngoài.
// Phiên đăng nhập: cookie "mc_phien" = base64url(JSON) + "." + HMAC-SHA256, khóa suy ra từ DATABASE_URL.
// Chưa nối database (thiếu DATABASE_URL) thì để trang mở như cũ, tránh khóa nhầm mọi người.

export const config = { matcher: "/((?!_vercel).*)" };

// tab -> các đường dẫn trang + dữ liệu của tab đó (so khớp tiền tố)
const TABS = {
  "goi-thau": ["/goi-thau", "/goi_thau", "/api/goi-thau"],
  "bao-gia": ["/bao-gia", "/bao_gia", "/api/bao-gia"],
  "co-so-y-te": ["/co-so-y-te", "/co_so_y_te", "/api/co-so-y-te"],
  "trung-thau": ["/trung-thau", "/trung_thau", "/api/trung-thau"],
  "duong-huyet": ["/duong-huyet", "/duong_huyet", "/api/duong-huyet"],
  "so-sanh": ["/so-sanh"],
};
// vai trò mẫu -> tab mặc định (khi admin chưa tick riêng). Sửa cùng ROLES trong api/auth.js.
const ROLES = {
  admin: Object.keys(TABS),
  quan_ly: Object.keys(TABS),
  nhan_vien: ["goi-thau", "bao-gia", "co-so-y-te"],
};
// Không cần đăng nhập. 2 file CSV giữ công khai cho Google Sheet báo giá (=IMPORTDATA).
const PUBLIC = ["/dang-nhap", "/api/auth", "/static/", "/tai-khoan.js", "/manifest.webmanifest", "/sw.js",
  "/favicon", "/bao-gia-dang-nhan.csv", "/gia-da-bao.csv", "/robots.txt"];

const dbUrl = () => process.env.DATABASE_URL || process.env.POSTGRES_URL || process.env.NEON_DATABASE_URL || "";
const b64u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const pass = () => new Response(null, { headers: { "x-middleware-next": "1" } });

async function readSession(req) {
  const m = (req.headers.get("cookie") || "").match(/(?:^|;\s*)mc_phien=([^;]+)/);
  if (!m) return null;
  const [body, sig] = m[1].split(".");
  if (!body || !sig) return null;
  const enc = new TextEncoder();
  const keyRaw = await crypto.subtle.digest("SHA-256", enc.encode("muasamcong-auth|" + dbUrl()));
  const key = await crypto.subtle.importKey("raw", keyRaw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const want = b64u(await crypto.subtle.sign("HMAC", key, enc.encode(body)));
  if (want !== sig) return null;
  try {
    const s = JSON.parse(atob(body.replace(/-/g, "+").replace(/_/g, "/")));
    return s.exp > Date.now() / 1000 ? s : null;
  } catch (e) { return null; }
}

// file dữ liệu KQ (lọc theo khách của nhân viên nếu tài khoản bị giới hạn)
const KQ_FILE = { "/api/trung-thau": "/trung_thau.json", "/api/duong-huyet": "/duong_huyet.json" };
const kqFile = path => KQ_FILE[path] || (/^\/(trung_thau|duong_huyet)(_\d{4})?\.json$/.test(path) ? path : "");
async function internalKey() {
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("muasamcong-noibo|" + dbUrl()));
  return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, "0")).join("");
}
const tabOf = path => Object.keys(TABS).find(t => TABS[t].some(p => path === p || path.startsWith(p)));
const isData = path => path.startsWith("/api/") || /\.(json|csv)$/.test(path);

export default async function middleware(req) {
  if (!dbUrl()) return pass();
  const url = new URL(req.url);
  const path = url.pathname;
  if (PUBLIC.some(p => path === p || path.startsWith(p))) return pass();
  if (req.headers.get("x-mc-noi-bo") && req.headers.get("x-mc-noi-bo") === await internalKey()) return pass();
  const s = await readSession(req);
  if (!s) {
    if (isData(path)) return new Response(JSON.stringify({ loi: "Chưa đăng nhập" }), { status: 401, headers: { "content-type": "application/json" } });
    return Response.redirect(new URL("/dang-nhap?tiep=" + encodeURIComponent(path + url.search), url), 302);
  }
  // quyền từng tab nằm trong phiên (s.t, admin tick ở /quan-tri); admin luôn xem tất cả
  const allowed = s.r === "admin" ? ROLES.admin : (Array.isArray(s.t) ? s.t.filter(x => TABS[x]) : ROLES[s.r] || []);
  const home = allowed.length ? "/" + allowed[0] : "/dang-nhap?chua-co-tab=1";  // chưa được tick tab nào
  if (path === "/") return Response.redirect(new URL(home, url), 302);
  if (path === "/quan-tri") return s.r === "admin" ? pass() : Response.redirect(new URL(home, url), 302);
  const tab = tabOf(path);
  if (tab && !allowed.includes(tab)) {
    if (isData(path)) return new Response(JSON.stringify({ loi: "Không có quyền" }), { status: 403, headers: { "content-type": "application/json" } });
    return Response.redirect(new URL(home + (allowed.length ? "?khong-quyen=1" : ""), url), 302);
  }
  // tài khoản chỉ xem KQ khách của mình: chuyển file KQ sang /api/auth?action=kq để máy chủ lọc
  const kf = s.k && s.r !== "admin" ? kqFile(path) : "";
  if (kf) return new Response(null, { headers: { "x-middleware-rewrite": new URL("/api/auth?action=kq&f=" + encodeURIComponent(kf), url).toString() } });
  return pass();
}
