// Nút "Lên đầu trang" + Trợ lý AI (hỏi đáp kết quả trúng thầu) dùng chung cho mọi trang.
// tai-khoan.js nạp tệp này sau khi đăng nhập; trang đã có sẵn (KQ Test) thì bỏ qua phần đã có.
// Máy chủ: /api/auth?action=hoi-kq — chỉ trả lời trên dữ liệu người hỏi được xem.
window.TroLy = function (u) {
  const coKq = !!u && (u.tabs || []).some(t => t === 'trung-thau' || t === 'duong-huyet' || t === 'so-sanh');
  const canTop = !document.getElementById('toTop'), canAi = coKq && !document.getElementById('aiBtn');
  if (!canTop && !canAi) return;
  const st = document.createElement('style'); st.textContent = "\n.to-top { position: fixed; right: 18px; bottom: 18px; z-index: 45; width: 44px; height: 44px; border-radius: 50%;\n  border: 1px solid var(--line, #e2e8f0); background: var(--surface, #fff); color: var(--accent, var(--brand, #0b5cad)); box-shadow: 0 4px 14px rgba(16,35,70,.18);\n  display: flex; align-items: center; justify-content: center; cursor: pointer; padding: 0;\n  opacity: 0; visibility: hidden; transform: translateY(8px); transition: opacity .2s, transform .2s, visibility .2s; }\n.to-top.show { opacity: 1; visibility: visible; transform: none; }\n.to-top:hover { background: var(--accent, var(--brand, #0b5cad)); color: #fff; border-color: var(--accent, var(--brand, #0b5cad)); }\n.to-top:focus-visible { outline: 2px solid var(--accent, var(--brand, #0b5cad)); outline-offset: 2px; }\n.to-top svg { width: 22px; height: 22px; }\n@media (max-width: 760px) { .to-top { right: 14px; bottom: calc(78px + env(safe-area-inset-bottom)); } }\n@media print { .to-top { display: none; } }\n\n\n.ai-btn { position: fixed; right: 20px; bottom: 78px; z-index: 45; display: flex; align-items: center; gap: 8px; border: 0; border-radius: 999px;\n  padding: 11px 16px; font: inherit; font-weight: 600; font-size: 14px; color: #fff; cursor: pointer;\n  background: linear-gradient(135deg, var(--brand, #0b5cad), var(--brand-2, #0e9f9a)); box-shadow: 0 6px 20px rgba(16,35,70,.25); }\n.ai-btn svg { width: 18px; height: 18px; }\n.ai-btn[hidden] { display: none; }\n.ai-box { position: fixed; right: 20px; bottom: 20px; z-index: 60; width: min(440px, calc(100vw - 32px)); height: min(620px, calc(100vh - 40px));\n  display: none; flex-direction: column; background: var(--surface, #fff); color: var(--text, #14213d); border: 1px solid var(--line, #e2e8f0); border-radius: 16px;\n  box-shadow: 0 12px 40px rgba(16,35,70,.25); overflow: hidden; }\n.ai-box.open { display: flex; }\n.ai-head { display: flex; align-items: center; gap: 8px; padding: 12px 14px; color: #fff; background: linear-gradient(120deg, var(--brand, #0b5cad), var(--brand-2, #0e9f9a)); }\n.ai-head b { flex: 1; font-size: 15px; }\n.ai-head button { background: rgba(255,255,255,.18); border: 0; color: #fff; border-radius: 8px; padding: 5px 9px; font: inherit; font-size: 13px; cursor: pointer; }\n.ai-log { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; background: var(--bg, #f3f6fa); }\n.ai-m { max-width: 92%; padding: 9px 12px; border-radius: 12px; font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }\n.ai-m.u { align-self: flex-end; background: var(--brand, #0b5cad); color: #fff; border-bottom-right-radius: 4px; white-space: pre-wrap; }\n.ai-m.a { align-self: flex-start; background: var(--surface, #fff); border: 1px solid var(--line, #e2e8f0); border-bottom-left-radius: 4px; }\n.ai-m.a p { margin: 0 0 6px; } .ai-m.a p:last-child { margin: 0; }\n.ai-m.a ul { margin: 4px 0 6px; padding-left: 18px; }\n.ai-m.a .tw { overflow-x: auto; margin: 6px 0; }\n.ai-m.a table { border-collapse: collapse; font-size: 12.5px; }\n.ai-m.a th, .ai-m.a td { border: 1px solid var(--line, #e2e8f0); padding: 4px 6px; text-align: left; vertical-align: top; }\n.ai-m.a th { background: var(--line-2, #eef2f7); }\n.ai-m.a td.n { text-align: right; white-space: nowrap; }\n.ai-m.err { align-self: flex-start; color: #c2410c; background: #fdeee6; }\n.ai-m.wait { align-self: flex-start; color: var(--muted, #5b6b82); font-style: italic; }\n.ai-goi { display: flex; flex-wrap: wrap; gap: 6px; }\n.ai-goi button { border: 1px solid var(--line, #e2e8f0); background: var(--surface, #fff); color: var(--text, #14213d); border-radius: 999px; padding: 6px 10px; font: inherit; font-size: 12.5px; cursor: pointer; text-align: left; }\n.ai-goi button:hover { border-color: var(--brand, #0b5cad); }\n.ai-in { display: flex; gap: 8px; padding: 10px; border-top: 1px solid var(--line, #e2e8f0); background: var(--surface, #fff); }\n.ai-in textarea { flex: 1; resize: none; height: 42px; max-height: 120px; padding: 10px; border: 1.5px solid var(--line, #e2e8f0); border-radius: 10px;\n  background: var(--bg, #f3f6fa); color: var(--text, #14213d); font: inherit; font-size: 14px; outline: none; }\n.ai-in textarea:focus { border-color: var(--brand, #0b5cad); }\n.ai-in button { border: 0; border-radius: 10px; padding: 0 14px; color: #fff; font: inherit; font-weight: 600; cursor: pointer; background: var(--brand, #0b5cad); }\n.ai-in button:disabled { opacity: .5; cursor: default; }\n.ai-note { font-size: 11.5px; color: var(--muted, #5b6b82); padding: 0 12px 8px; background: var(--surface, #fff); }\n@media (max-width: 760px) { .ai-btn { right: 14px; bottom: calc(136px + env(safe-area-inset-bottom)); padding: 10px 14px; }\n  .ai-box { left: 8px; right: 8px; width: auto; bottom: 8px; top: 8px; height: auto; } }\n@media print { .ai-btn, .ai-box { display: none !important; } }\n";
  document.head.appendChild(st);
  const wrap = document.createElement('div'); wrap.innerHTML = "<button type=\"button\" class=\"to-top\" id=\"toTop\" aria-label=\"Lên đầu trang\" title=\"Lên đầu trang\">\n  <svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.4\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\"><path d=\"M12 19V5M5 12l7-7 7 7\"/></svg>\n</button>\n\n\n\n<button type=\"button\" class=\"ai-btn notranslate\" id=\"aiBtn\" translate=\"no\" aria-haspopup=\"dialog\">\n  <svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2.2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" aria-hidden=\"true\"><path d=\"M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z\"/><path d=\"M8.5 10h7M8.5 13.5h4.5\"/></svg>\n  Hỏi AI\n</button>\n<section class=\"ai-box notranslate\" id=\"aiBox\" translate=\"no\" role=\"dialog\" aria-label=\"Trợ lý AI kết quả trúng thầu\">\n  <div class=\"ai-head\"><b>Trợ lý AI · Kết quả trúng thầu</b><button type=\"button\" id=\"aiNew\" title=\"Cuộc hỏi mới\">Mới</button><button type=\"button\" id=\"aiClose\" aria-label=\"Đóng\">✕</button></div>\n  <div class=\"ai-log\" id=\"aiLog\" aria-live=\"polite\"></div>\n  <form class=\"ai-in\" id=\"aiForm\"><textarea id=\"aiQ\" placeholder=\"Hỏi về kết quả trúng thầu…\" aria-label=\"Câu hỏi\"></textarea><button type=\"submit\" id=\"aiSend\">Gửi</button></form>\n  <div class=\"ai-note\">AI có thể sai, nên đối chiếu lại số liệu trên bảng trước khi dùng.</div>\n</section>";
  if (!canTop) wrap.querySelector('#toTop').remove();
  if (!canAi) { wrap.querySelector('#aiBtn').remove(); wrap.querySelector('#aiBox').remove(); }
  while (wrap.firstChild) document.body.appendChild(wrap.firstChild);
  if (canTop) (() => {
  const b = document.getElementById('toTop');
  const tab = document.querySelector('.tabbar');
  // trên điện thoại: đặt nút ngay trên thanh menu dưới (chiều cao thanh menu khác nhau giữa các trang)
  const place = () => { const h = tab && getComputedStyle(tab).display !== 'none' && getComputedStyle(tab).position === 'fixed' ? tab.offsetHeight : 0;
    b.style.bottom = h ? (h + 12) + 'px' : ''; };
  const on = () => b.classList.toggle('show', window.scrollY > 400);
  place(); window.addEventListener('resize', place);
  window.addEventListener('scroll', on, { passive: true }); on();
  b.addEventListener('click', () => window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }));
})();
  if (canAi) (() => {
  const $ = id => document.getElementById(id);
  const btn = $('aiBtn'), box = $('aiBox'), log = $('aiLog'), q = $('aiQ'), send = $('aiSend');
  const KEY = 'kq_ai_hoi';
  let hist = [];
  try { hist = JSON.parse(sessionStorage.getItem(KEY) || '[]'); } catch (e) {}
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(hist.slice(-20))); } catch (e) {} };
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const inl = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
  // Markdown tối giản: đoạn, danh sách, bảng
  function md(t) {
    const L = String(t).split('\n'), out = []; let i = 0;
    while (i < L.length) {
      const l = L[i];
      if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < L.length && /^\s*\|[\s:|-]+\|\s*$/.test(L[i + 1])) {
        const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
        const h = cells(l); i += 2; const rows = [];
        while (i < L.length && /^\s*\|.*\|\s*$/.test(L[i])) rows.push(cells(L[i++]));
        out.push('<div class="tw"><table><thead><tr>' + h.map(c => `<th>${inl(c)}</th>`).join('') + '</tr></thead><tbody>' +
          rows.map(r => '<tr>' + r.map(c => `<td${/^[\d.,\s%đ+-]+(tỷ|triệu)?\s*đ?$/.test(c) ? ' class="n"' : ''}>${inl(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>');
        continue;
      }
      if (/^\s*([-*•]|\d+\.)\s+/.test(l)) {
        const it = []; while (i < L.length && /^\s*([-*•]|\d+\.)\s+/.test(L[i])) it.push(L[i++].replace(/^\s*([-*•]|\d+\.)\s+/, ''));
        out.push('<ul>' + it.map(x => `<li>${inl(x)}</li>`).join('') + '</ul>'); continue;
      }
      if (l.trim()) out.push(`<p>${inl(l.replace(/^#+\s*/, ''))}</p>`);
      i++;
    }
    return out.join('');
  }
  const Y = new Date().getFullYear();
  const GOI = [`Top 10 nhà thầu trúng nhiều nhất năm ${Y}`, 'Hãng nào chiếm thị phần lớn nhất nhóm HIV?', 'Giá trúng thấp nhất của test Cúm A/B năm nay',
    `So sánh giá trị trúng thầu ${Y - 1} và ${Y} theo nhóm hàng`, '10 gói trúng thầu mới nhất'];
  function add(cls, html) { const d = document.createElement('div'); d.className = 'ai-m ' + cls; d.innerHTML = html; log.appendChild(d); log.scrollTop = log.scrollHeight; return d; }
  function render() {
    log.innerHTML = '';
    if (!hist.length) {
      add('a', `<p>Chào anh/chị, tôi trả lời các câu hỏi về <b>kết quả trúng thầu Test và Đường huyết</b> (${Y - 2}–${Y}): nhà thầu, hãng, cơ sở y tế, tỉnh, đơn giá, giá trị…</p>`);
      const g = document.createElement('div'); g.className = 'ai-goi';
      GOI.forEach(t => { const b = document.createElement('button'); b.type = 'button'; b.textContent = t; b.onclick = () => ask(t); g.appendChild(b); });
      log.appendChild(g);
    }
    hist.forEach(m => m.role === 'user' ? add('u', esc(m.content)) : add('a', md(m.content)));
  }
  async function ask(text) {
    text = String(text || '').trim(); if (!text || send.disabled) return;
    if (!hist.length) log.innerHTML = '';
    hist.push({ role: 'user', content: text }); save(); add('u', esc(text)); q.value = '';
    send.disabled = true; const w = add('wait', 'Đang tra dữ liệu…');
    try {
      const r = await fetch('/api/auth?action=hoi-kq', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: hist }) });
      const d = await r.json().catch(() => ({}));
      w.remove();
      if (!r.ok) { hist.pop(); save(); add('err', esc(d.loi || 'Lỗi kết nối, thử lại.')); return; }
      hist.push({ role: 'assistant', content: d.tra_loi }); save(); add('a', md(d.tra_loi));
    } catch (e) { w.remove(); hist.pop(); save(); add('err', 'Lỗi kết nối, thử lại.'); }
    finally { send.disabled = false; q.focus(); }
  }
  btn.onclick = () => { box.classList.add('open'); btn.hidden = true; render(); q.focus(); };
  $('aiClose').onclick = () => { box.classList.remove('open'); btn.hidden = false; };
  $('aiNew').onclick = () => { hist = []; save(); render(); q.focus(); };
  $('aiForm').onsubmit = e => { e.preventDefault(); ask(q.value); };
  q.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(q.value); } });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && box.classList.contains('open')) $('aiClose').click(); });
})();
};
