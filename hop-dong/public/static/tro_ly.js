// Trợ lý AI chung: nút "Trợ lý AI" nổi góc phải, giao việc bằng câu thường; AI tự tra thông số, tạo file Excel, tra giá hàng.
(function () {
  var goc = document.getElementById("tro-ly");
  if (!goc) return;
  var CSRF = goc.getAttribute("data-csrf"), MO_SAN = goc.getAttribute("data-mo") === "1";
  var K_LS = "tl_lich_su", K_MO = "tl_mo";
  var hist = [];
  try { hist = JSON.parse(sessionStorage.getItem(K_LS) || "[]"); } catch (e) {}
  function luu() { try { sessionStorage.setItem(K_LS, JSON.stringify(hist.slice(-20))); } catch (e) {} }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function inl(s) {
    return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/(https:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
  }
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
  function chipTep(tep) {
    return (tep || []).map(function (f) {
      return f.loai === "sheet"
        ? '<p><a class="nut ai-tep" href="' + esc(f.url) + '" target="_blank" rel="noopener noreferrer">Mở Google Sheet: ' + esc(f.ten) + "</a></p>"
        : '<p><a class="nut phu ai-tep" href="' + esc(f.url) + '">⬇ Tải ' + esc(f.ten) + "</a></p>";
    }).join("");
  }

  var nut = document.createElement("button");
  nut.type = "button"; nut.className = "ai-nut"; nut.setAttribute("aria-haspopup", "dialog");
  nut.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M8.5 10h7M8.5 13.5h4.5"/></svg>Trợ lý AI';
  var hop = document.createElement("section");
  hop.className = "ai-hop"; hop.setAttribute("role", "dialog"); hop.setAttribute("aria-label", "Trợ lý AI");
  hop.innerHTML = '<div class="ai-dau"><b>Trợ lý AI</b><button type="button" data-ai="moi" title="Cuộc chat mới">Mới</button>' +
    '<button type="button" data-ai="dong" aria-label="Đóng">✕</button></div><div class="ai-log" aria-live="polite"></div>' +
    '<form class="ai-go"><textarea placeholder="Giao việc, ví dụ: cho tôi thông số mã R0090C…" aria-label="Tin nhắn"></textarea><button type="submit">Gửi</button></form>' +
    '<div class="ai-chu">AI có thể nhầm, hãy kiểm tra số liệu trước khi đưa vào hồ sơ.</div>';
  document.body.appendChild(nut); document.body.appendChild(hop);
  var log = hop.querySelector(".ai-log"), q = hop.querySelector("textarea"), gui = hop.querySelector(".ai-go button");

  var GOI = ["Cho tôi thông số kỹ thuật mã R0090C", "Độ nhạy, độ đặc hiệu của ITP03004-DS50 là bao nhiêu?",
             "Cho tôi file thông số R0090C, W072-C, ITP01023-DS50 (bỏ giá)", "Tìm các test HBsAg trong bảng thông số"];
  function them(cls, html) { var d = document.createElement("div"); d.className = "ai-m " + cls; d.innerHTML = html; log.appendChild(d); log.scrollTop = log.scrollHeight; return d; }
  function ve() {
    log.innerHTML = "";
    if (!hist.length) {
      them("a", "<p>Chào anh/chị! Giao việc cho tôi bằng câu thường: tôi <b>tra thông số kỹ thuật</b>, <b>tạo file Excel TSKT</b> cho các mã, " +
        "và <b>tra giá hàng</b>. Tôi chỉ tra cứu và tạo file tải về, không sửa dữ liệu.</p>");
      var g = document.createElement("div"); g.className = "ai-goi";
      GOI.forEach(function (t) { var b = document.createElement("button"); b.type = "button"; b.textContent = t; b.onclick = function () { hoi(t); }; g.appendChild(b); });
      log.appendChild(g);
    }
    hist.forEach(function (m) { m.role === "user" ? them("u", esc(m.content)) : them("a", md(m.content) + chipTep(m.tep)); });
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
    them("u", esc(text)); q.value = "";
    gui.disabled = true;
    var cho = them("cho", "Đang làm…");
    goi("/tro-ly/chat", { lich_su: hist.map(function (m) { return { role: m.role, content: m.content }; }) }).then(function (d) {
      cho.remove();
      hist.push({ role: "assistant", content: d.tra_loi, tep: d.tep || [] }); luu();
      them("a", md(d.tra_loi) + chipTep(d.tep));
    }).catch(function (e) {
      cho.remove(); hist.pop(); luu(); them("loi", esc(e.message));
    }).then(function () { gui.disabled = false; q.focus(); });
  }
  function mo() { hop.classList.add("mo"); nut.hidden = true; ve(); q.focus(); try { sessionStorage.setItem(K_MO, "1"); } catch (e) {} }
  function dong() { hop.classList.remove("mo"); nut.hidden = false; try { sessionStorage.setItem(K_MO, "0"); } catch (e) {} }
  nut.onclick = mo;
  hop.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-ai]"); if (!b) return;
    var v = b.getAttribute("data-ai");
    if (v === "dong") dong();
    else if (v === "moi") { hist = []; luu(); ve(); q.focus(); }
  });
  hop.querySelector("form").onsubmit = function (ev) { ev.preventDefault(); hoi(q.value); };
  q.addEventListener("keydown", function (ev) { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); hoi(q.value); } });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && hop.classList.contains("mo")) dong(); });
  try { if (MO_SAN || sessionStorage.getItem(K_MO) === "1") mo(); } catch (e) { if (MO_SAN) mo(); }
})();
