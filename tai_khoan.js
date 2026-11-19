// Nút tài khoản trên mọi trang: tên + vai trò, đổi mật khẩu, quản trị (admin), đăng xuất.
// Ẩn các tab người dùng không có quyền. Việc chặn thật nằm ở middleware.js (máy chủ).
(() => {
  const TAB_OF = { '/goi-thau': 'goi-thau', '/bao-gia': 'bao-gia', '/co-so-y-te': 'co-so-y-te', '/trung-thau': 'trung-thau',
    '/duong-huyet': 'duong-huyet', '/so-sanh': 'so-sanh', '/so-sanh-duong-huyet': 'so-sanh' };
  const css = `.acct{position:relative;margin-left:auto}.acct>button{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,.16);color:#fff;
    border:1px solid rgba(255,255,255,.35);border-radius:10px;padding:7px 12px;font:inherit;font-size:14px;font-weight:500;cursor:pointer;white-space:nowrap}
    .acct .dot{background:#f97316;color:#fff;border-radius:999px;font-size:11px;padding:1px 6px;font-weight:700}
    .acct .menu{display:none;position:absolute;right:0;top:calc(100% + 6px);min-width:220px;background:var(--surface,#fff);color:var(--text,#14213d);
    border-radius:12px;box-shadow:0 8px 30px rgba(16,35,70,.18);padding:6px;z-index:80}.acct.open .menu{display:block}
    .acct .who{padding:8px 10px;border-bottom:1px solid var(--line,#e2e8f0);margin-bottom:4px;font-size:13px}.acct .who small{display:block;color:var(--muted,#5b6b82)}
    .acct .menu a,.acct .menu button{display:flex;justify-content:space-between;width:100%;text-align:left;padding:9px 10px;border:0;background:none;
    color:inherit;font:inherit;font-size:14px;border-radius:8px;text-decoration:none;cursor:pointer}.acct .menu a:hover,.acct .menu button:hover{background:var(--line-2,#eef2f7)}
    .acct-toast{position:fixed;left:50%;top:16px;transform:translateX(-50%);background:#14213d;color:#fff;padding:10px 16px;border-radius:10px;font-size:14px;z-index:90}`;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const toast = t => { const d = document.createElement('div'); d.className = 'acct-toast'; d.textContent = t; document.body.appendChild(d); setTimeout(() => d.remove(), 4000); };
  async function post(action, data) {
    const r = await fetch('/api/auth?action=' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data || {}) });
    const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.loi || 'Lỗi'); return d;
  }
  fetch('/api/auth?action=toi', { cache: 'no-store' }).then(async r => {
    if (r.status === 503) return;                       // chưa bật đăng nhập
    if (r.status === 401) { location.replace('/dang-nhap?tiep=' + encodeURIComponent(location.pathname + location.search)); return; }
    if (!r.ok) return;
    const { tai_khoan: u, cho_duyet: cho } = await r.json();
    const tab = TAB_OF[location.pathname.replace(/\.html$/, '')];
    if (tab && !u.tabs.includes(tab)) { location.replace('/'); return; }  // vai trò vừa bị đổi
    document.querySelectorAll('.nav a, .tabbar a').forEach(a => {
      const t = TAB_OF[a.getAttribute('href')]; if (t && !u.tabs.includes(t)) a.remove();
    });
    if (new URLSearchParams(location.search).get('khong-quyen')) toast('Tài khoản của bạn chưa được cấp quyền xem trang đó.');
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    const box = document.createElement('div'); box.className = 'acct notranslate'; box.setAttribute('translate', 'no');
    box.innerHTML = `<button type="button" aria-haspopup="true">👤 ${esc(u.ten.split(' ').slice(-1)[0])}${cho ? `<span class="dot">${cho}</span>` : ''}</button>
      <div class="menu"><div class="who"><b>${esc(u.ten)}</b><small>${esc(u.email)} · ${esc(u.ten_vai_tro)}</small></div>
      ${u.vai_tro === 'admin' ? `<a href="/quan-tri">Quản trị tài khoản${cho ? `<span class="dot">${cho} chờ duyệt</span>` : ''}</a>` : ''}
      <button type="button" data-a="mk">Đổi mật khẩu</button><button type="button" data-a="out">Đăng xuất</button></div>`;
    (document.querySelector('.hero .top') || document.querySelector('.hero') || document.body).appendChild(box);
    box.querySelector(':scope > button').onclick = e => { e.stopPropagation(); box.classList.toggle('open'); };
    document.addEventListener('click', e => { if (!box.contains(e.target)) box.classList.remove('open'); });
    box.querySelector('[data-a=out]').onclick = async () => {
      await post('dang-xuat').catch(() => {});
      try { for (const k of await caches.keys()) await caches.delete(k); } catch (e) {}
      location.replace('/dang-nhap');
    };
    box.querySelector('[data-a=mk]').onclick = async () => {
      const cu = prompt('Mật khẩu hiện tại:'); if (!cu) return;
      const moi = prompt('Mật khẩu mới (tối thiểu 8 ký tự):'); if (!moi) return;
      try { await post('doi-mat-khau', { cu, moi }); toast('Đã đổi mật khẩu.'); } catch (e) { toast(e.message); }
    };
  }).catch(() => {});
})();
