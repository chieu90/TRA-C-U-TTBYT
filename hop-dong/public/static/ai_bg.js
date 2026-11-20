// Trợ lý AI báo giá: nút "Hỏi AI" nổi góc phải, hộp chat nhiều lượt; AI tra giá và soạn bản nháp, bấm Tạo báo giá để lưu.
(function () {
  var goc = document.getElementById("ai-bg");
  if (!goc) return;
  var CSRF = goc.getAttribute("data-csrf");
  var K_LS = "bg_ai_lich_su", K_NHAP = "bg_ai_nhap", K_BANG = "bg_ai_bang";
  var hist = [], nhap = {}, bang = null;
  try { hist = JSON.parse(sessionStorage.getItem(K_LS) || "[]"); nhap = JSON.parse(sessionStorage.getItem(K_NHAP) || "{}");
        bang = JSON.parse(sessionStorage.getItem(K_BANG) || "null"); } catch (e) {}
  function luu() {
    try { sessionStorage.setItem(K_LS, JSON.stringify(hist.slice(-20))); sessionStorage.setItem(K_NHAP, JSON.stringify(nhap));
          sessionStorage.setItem(K_BANG, JSON.stringify(bang)); } catch (e) {}
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function inl(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>"); }
  function md(t) {          // Markdown tối giản: đoạn, danh sách, bảng
    var L = String(t).split("\n"), out = [], i = 0;
    function o(r) { return r.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); }); }
    while (i < L.length) {
      var l = L[i];
      if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < L.length && /^\s*\|[\s:|-]+\|\s*$/.test(L[i + 1])) {
        var h = o(l), rows = []; i += 2;
        while (i < L.length && /^\s*\|.*\|\s*$/.test(L[i])) rows.push(o(L[i++]));
        out.push('<div class="ai-cuon"><table><thead><tr>' + h.map(function (c) { return "<th>" + inl(c) + "</th>"; }).join("") +
          "</tr></thead><tbody>" + rows.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + inl(c) + "</td>"; }).join("") + "</tr>"; }).join("") +
          "</tbody></table></div>");
        continue;
      }
      if (/^\s*([-*•]|\d+\.)\s+/.test(l)) {
        var it = [];
        while (i < L.length && /^\s*([-*•]|\d+\.)\s+/.test(L[i])) it.push(L[i++].replace(/^\s*([-*•]|\d+\.)\s+/, ""));
        out.push("<ul>" + it.map(function (x) { return "<li>" + inl(x) + "</li>"; }).join("") + "</ul>");
        continue;
      }
      if (l.trim()) out.push("<p>" + inl(l.replace(/^#+\s*/, "")) + "</p>");
      i++;
    }
    return out.join("");
  }

  // dựng nút và hộp chat
  var nut = document.createElement("button");
  nut.type = "button"; nut.className = "ai-nut"; nut.setAttribute("aria-haspopup", "dialog");
  nut.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M8.5 10h7M8.5 13.5h4.5"/></svg>Hỏi AI';
  var hop = document.createElement("section");
  hop.className = "ai-hop"; hop.setAttribute("role", "dialog"); hop.setAttribute("aria-label", "Trợ lý AI báo giá");
  hop.innerHTML = '<div class="ai-dau"><b>Trợ lý AI · Báo giá</b><button type="button" data-ai="moi" title="Cuộc chat mới">Mới</button>' +
    '<button type="button" data-ai="dong" aria-label="Đóng">✕</button></div><div class="ai-log" aria-live="polite"></div>' +
    '<form class="ai-go"><textarea placeholder="Hỏi giá, hoặc nhờ soạn báo giá…" aria-label="Tin nhắn"></textarea><button type="submit">Gửi</button></form>' +
    '<div class="ai-chu">AI có thể nhầm, hãy kiểm tra bản nháp trước khi tạo báo giá.</div>';
  document.body.appendChild(nut); document.body.appendChild(hop);
  var log = hop.querySelector(".ai-log"), q = hop.querySelector("textarea"), gui = hop.querySelector(".ai-go button");

  var GOI = ["Báo giá cho BV Thủ Đức: 50 hộp HIV OnSite, 20 hộp HBsAg que OnSite, giảm 3%",
             "Giá test Dengue NS1 các hãng bao nhiêu?", "Liệt kê hàng của Wondfo kèm giá bán",
             "Hàng nào đang có giá bán thấp hơn giá Min?"];
  function them(cls, html) { var d = document.createElement("div"); d.className = "ai-m " + cls; d.innerHTML = html; log.appendChild(d); log.scrollTop = log.scrollHeight; return d; }
  function veBang() {
    var cu = log.querySelector(".ai-nhap"); if (cu) cu.remove();
    if (!bang || !bang.dong || !bang.dong.length) return;
    var r = bang.dong.map(function (d, i) {
      return "<tr><td>" + (i + 1) + "</td><td><b>" + esc(d.ma) + "</b> " + esc(d.ten) + '<br><span class="mo">' + esc(d.nhan_hieu) + " · " + esc(d.quy_cach) + "</span></td>" +
        '<td class="so">' + esc(d.sl) + '</td><td class="so">' + esc(d.gia) + (d.canh ? '<br><span class="nhan ' + (d.canh.indexOf("Min") > 0 ? "do" : "vang") + '">' + esc(d.canh) + "</span>" : "") +
        '</td><td class="so">' + esc(d.tt) + "</td></tr>";
    }).join("");
    var d = document.createElement("div"); d.className = "ai-m a ai-nhap";
    d.innerHTML = "<p><b>Bản nháp báo giá</b> · Kính gửi: " + esc(bang.ten_kh) + "</p>" +
      '<p class="mo">Hiệu lực đến ' + esc(bang.hieu_luc) + (bang.giam && bang.giam !== "0" ? " · giảm " + esc(bang.giam) + "%" : "") +
      (bang.ghi_chu ? " · " + esc(bang.ghi_chu) : "") + "</p>" +
      '<div class="ai-cuon"><table><thead><tr><th>#</th><th>Hàng</th><th class="so">SL</th><th class="so">Đơn giá</th><th class="so">Thành tiền</th></tr></thead><tbody>' + r +
      (bang.tong ? '<tr><td colspan="4" class="so"><b>Tổng cộng</b></td><td class="so"><b>' + esc(bang.tong) + "</b></td></tr>" : "") + "</tbody></table></div>" +
      '<div class="ai-hang-nut"><button type="button" class="nut" data-ai="tao">Tạo báo giá</button></div>';
    log.appendChild(d); log.scrollTop = log.scrollHeight;
  }
  function ve() {
    log.innerHTML = "";
    if (!hist.length) {
      them("a", "<p>Chào anh/chị! Tôi tra <b>giá, mã hàng, quy cách</b> trong danh mục và <b>soạn báo giá</b> theo lời nhắn. " +
        "Cứ nhắn tự nhiên, sửa dần từng câu (thêm/bỏ hàng, đổi số lượng, giảm giá…), xong bấm <b>Tạo báo giá</b>.</p>");
      var g = document.createElement("div"); g.className = "ai-goi";
      GOI.forEach(function (t) { var b = document.createElement("button"); b.type = "button"; b.textContent = t; b.onclick = function () { hoi(t); }; g.appendChild(b); });
      log.appendChild(g);
    }
    hist.forEach(function (m) { m.role === "user" ? them("u", esc(m.content)) : them("a", md(m.content)); });
    veBang();
  }
  function loiTu(r, txt) {
    try { var p = new DOMParser().parseFromString(txt, "text/html").querySelector("main .the p"); if (p) return p.textContent; } catch (e) {}
    return "Lỗi kết nối (" + r.status + "), thử lại.";
  }
  function goi(url, du_lieu) {
    var f = new URLSearchParams(); f.append("csrf", CSRF);
    Object.keys(du_lieu).forEach(function (k) { f.append(k, JSON.stringify(du_lieu[k])); });
    return fetch(url, { method: "POST", body: f, credentials: "same-origin" }).then(function (r) {
      return r.text().then(function (t) {
        if (!r.ok) throw new Error(loiTu(r, t));
        try { return JSON.parse(t); } catch (e) { throw new Error("Phiên đăng nhập đã hết, hãy tải lại trang."); }
      });
    });
  }
  function hoi(text) {
    text = String(text || "").trim();
    if (!text || gui.disabled) return;
    if (!hist.length) log.innerHTML = "";
    hist.push({ role: "user", content: text }); luu();
    var cu = log.querySelector(".ai-nhap"); if (cu) cu.remove();
    them("u", esc(text)); q.value = "";
    gui.disabled = true;
    var cho = them("cho", "Đang soạn…");
    goi("/bao-gia/ai", { lich_su: hist, nhap: nhap }).then(function (d) {
      cho.remove();
      hist.push({ role: "assistant", content: d.tra_loi }); nhap = d.nhap || {}; bang = d.bang; luu();
      them("a", md(d.tra_loi)); veBang();
    }).catch(function (e) {
      cho.remove(); hist.pop(); luu(); them("loi", esc(e.message)); veBang();
    }).then(function () { gui.disabled = false; q.focus(); });
  }
  function tao(b) {
    b.disabled = true; b.textContent = "Đang tạo…";
    goi("/bao-gia/ai/tao", { nhap: nhap }).then(function (d) {
      hist = []; nhap = {}; bang = null; luu();
      try { sessionStorage.setItem("bg_ai_mo", "0"); } catch (e) {}
      window.location.href = d.url;
    }).catch(function (e) { b.disabled = false; b.textContent = "Tạo báo giá"; them("loi", esc(e.message)); });
  }
  function mo() { hop.classList.add("mo"); nut.hidden = true; ve(); q.focus(); try { sessionStorage.setItem("bg_ai_mo", "1"); } catch (e) {} }
  function dong() { hop.classList.remove("mo"); nut.hidden = false; try { sessionStorage.setItem("bg_ai_mo", "0"); } catch (e) {} }
  nut.onclick = mo;
  hop.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-ai]"); if (!b) return;
    var v = b.getAttribute("data-ai");
    if (v === "dong") dong();
    else if (v === "moi") { hist = []; nhap = {}; bang = null; luu(); ve(); q.focus(); }
    else if (v === "tao") tao(b);
  });
  hop.querySelector("form").onsubmit = function (ev) { ev.preventDefault(); hoi(q.value); };
  q.addEventListener("keydown", function (ev) { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); hoi(q.value); } });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && hop.classList.contains("mo")) dong(); });
  try { if (sessionStorage.getItem("bg_ai_mo") === "1") mo(); } catch (e) {}
})();
