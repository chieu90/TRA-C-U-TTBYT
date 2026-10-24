// Nút "Cập nhật ngay" trên bản Vercel: chạy workflow GitHub Actions cap-nhat-bao-gia.yml
// (lấy báo giá + làm mới gói thầu), sau đó Vercel tự triển khai dữ liệu mới.
//   GET  /api/cap-nhat -> trạng thái lần chạy gần nhất
//   POST /api/cap-nhat -> chạy ngay (bỏ qua nếu đang chạy hoặc vừa chạy < 5 phút)
// Cần biến môi trường GH_TOKEN trên Vercel: token GitHub chỉ cấp quyền "Actions: Read and write" cho repo này.
const REPO = "chieu90/TRA-C-U-TTBYT";
const WORKFLOW = "cap-nhat-bao-gia.yml";
const GH = `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}`;

async function gh(path, opts = {}) {
  const r = await fetch(GH + path, {
    ...opts,
    headers: {
      Accept: "application/vnd.github+json",
      "User-Agent": "muasamcong-vercel",
      ...(process.env.GH_TOKEN ? { Authorization: `Bearer ${process.env.GH_TOKEN}` } : {}),
      ...(opts.headers || {}),
    },
  });
  return r;
}

async function latestRun() {
  const r = await gh("/runs?per_page=1");
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  const run = (await r.json()).workflow_runs?.[0];
  return run ? { id: run.id, status: run.status, conclusion: run.conclusion, created_at: run.created_at,
                 updated_at: run.updated_at, url: run.html_url } : null;
}

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  try {
    if (req.method === "GET") return res.status(200).json({ ok: true, run: await latestRun(), ready: !!process.env.GH_TOKEN });
    if (req.method !== "POST") return res.status(405).json({ ok: false, error: "Chỉ hỗ trợ GET/POST" });
    if (!process.env.GH_TOKEN) return res.status(500).json({ ok: false, error: "Chưa cài GH_TOKEN trên Vercel" });
    const run = await latestRun();
    if (run && run.status !== "completed") return res.status(200).json({ ok: true, started: false, reason: "dang-chay", run });
    if (run && Date.now() - Date.parse(run.created_at) < 5 * 60 * 1000)
      return res.status(200).json({ ok: true, started: false, reason: "vua-chay", run });
    const r = await gh("/dispatches", { method: "POST", body: JSON.stringify({ ref: "main" }),
                                        headers: { "Content-Type": "application/json" } });
    if (r.status !== 204) return res.status(502).json({ ok: false, error: `GitHub từ chối (${r.status}): ${await r.text()}` });
    return res.status(200).json({ ok: true, started: true });
  } catch (e) {
    return res.status(502).json({ ok: false, error: String(e.message || e) });
  }
};
