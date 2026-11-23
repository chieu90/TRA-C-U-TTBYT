// Hỏi lại trước khi xóa, và nút "Quay lại" ở trang báo lỗi (giữ nguyên dữ liệu đã nhập).
document.addEventListener("submit", function (ev) {
  var hoi = ev.target.getAttribute("data-xac-nhan");
  if (hoi && !window.confirm(hoi)) ev.preventDefault();
});
document.addEventListener("click", function (ev) {
  var a = ev.target.closest("[data-quay-lai]");
  if (a && window.history.length > 1) {
    ev.preventDefault();
    window.history.back();
  }
});

// Nút chép đoạn mã (trang Mẫu HĐ)
document.addEventListener("click", function (ev) {
  var nut = ev.target.closest("[data-chep]");
  if (!nut) return;
  var nguon = document.querySelector(nut.getAttribute("data-chep"));
  var kq = document.getElementById("kq-chep");
  navigator.clipboard.writeText(nguon.textContent).then(function () {
    if (kq) kq.textContent = "Đã chép. Dán vào trình soạn thảo Apps Script.";
  }, function () {
    if (kq) kq.textContent = "Không chép tự động được, hãy bôi đen đoạn mã rồi chép tay.";
  });
});

// Vừa tạo hợp đồng nguyên tắc: tự tải file Word một lần.
document.addEventListener("DOMContentLoaded", function () {
  var tai = document.querySelector("[data-tu-tai]");
  if (tai) {
    window.location.href = tai.getAttribute("href");
    if (window.history.replaceState) window.history.replaceState(null, "", window.location.pathname);
  }
});

// ── Trang làm hợp đồng nguyên tắc ──
(function () {
  var form = document.getElementById("form-hdnt");
  if (!form) return;
  var O = ["ten_kh", "dia_chi", "mst", "dai_dien", "chuc_vu", "dien_thoai", "email"];
  function gap(s) {
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D")
      .replace(/\s+/g, " ").trim().toLowerCase();
  }
  function o(ten) { return form.elements[ten]; }

  // Chọn khách có sẵn -> điền thông tin đã lưu (chỉ những ô khách có dữ liệu)
  var ds = [];
  try { ds = JSON.parse(document.getElementById("du-lieu-khach").textContent); } catch (e) { ds = []; }
  var theoTen = {};
  ds.forEach(function (k) { theoTen[gap(k[0])] = k; });
  o("ten_kh").addEventListener("change", function () {
    var k = theoTen[gap(this.value)];
    if (!k) return;
    for (var i = 1; i < O.length; i++) if (k[i]) o(O[i]).value = k[i];
  });

  // Tra theo mã số thuế: khách đã lưu thì lấy đủ thông tin, tên và địa chỉ lấy theo đăng ký thuế mới nhất
  var oMst = document.getElementById("o-tra-mst"), kqMst = document.getElementById("kq-tra-mst");
  function traMst() {
    var mst = oMst.value.replace(/[\s.]/g, "");
    if (!mst) return;
    kqMst.textContent = "Đang tra…";
    fetch("/tra-mst?mst=" + encodeURIComponent(mst), { credentials: "same-origin" }).then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) { kqMst.textContent = d.loi; return; }
        var cu = d.khach || {}, thue = d.thue || {}, loi = [];
        O.forEach(function (ten) { if (cu[ten]) o(ten).value = cu[ten]; });
        if (thue.ten_kh && !cu.ten_kh) o("ten_kh").value = thue.ten_kh;
        if (thue.dia_chi) {
          if (cu.dia_chi && gap(cu.dia_chi) !== gap(thue.dia_chi)) loi.push("Địa chỉ đã đổi theo đăng ký thuế mới (trước đây: " + cu.dia_chi + ").");
          o("dia_chi").value = thue.dia_chi;
        }
        o("mst").value = d.mst;
        if (!d.khach) {                                  // khách mới theo MST nhưng có thể đã lưu theo tên
          var k = theoTen[gap(o("ten_kh").value)];
          if (k) for (var i = 3; i < O.length; i++) if (k[i]) o(O[i]).value = k[i];
        }
        var thieu = ["dai_dien", "chuc_vu"].filter(function (t) { return !o(t).value.trim(); });
        var tb = (d.thue ? "Đã điền theo dữ liệu Cục Thuế" + (thue.trang_thai ? " (" + thue.trang_thai + ")" : "") + "."
          : "Chưa tra được dữ liệu thuế, đã điền thông tin khách đã lưu.");
        if (d.khach) tb += " Khách này đã có trong danh sách.";
        if (thieu.length) tb += " Còn thiếu người đại diện, chức vụ: nhập tay bên dưới.";
        if (thue.trang_thai && !/đang hoạt động/i.test(thue.trang_thai)) tb = "LƯU Ý: " + thue.trang_thai + ". " + tb;
        kqMst.textContent = tb + (loi.length ? " " + loi.join(" ") : "");
        var goiY = document.getElementById("goi-y-mst");   // dữ liệu thuế không có người đại diện: chỉ đường lấy nhanh
        goiY.hidden = !thieu.length;
        if (thieu.length) {
          document.getElementById("link-mst").href = "https://masothue.com/Search/?q=" + encodeURIComponent(d.mst) + "&type=auto";
          document.getElementById("khung-dan").open = true;
        }
      }, function () { kqMst.textContent = "Chưa tra được. Kiểm tra mạng rồi thử lại."; });
  }
  document.getElementById("nut-tra-mst").addEventListener("click", traMst);
  oMst.addEventListener("keydown", function (ev) { if (ev.key === "Enter") { ev.preventDefault(); traMst(); } });

  // Dán đoạn chữ -> tự nhận các trường
  var KHOA = [
    ["mst", /^(ma so thue|mst|ma so doanh nghiep|ma doanh nghiep)/],
    ["dia_chi", /^(dia chi|tru so|dia chi tru so)/],
    ["chuc_vu", /^chuc vu/],
    ["dai_dien", /^(nguoi dai dien|dai dien|giam doc|chu ho|chu doanh nghiep)/],
    ["dien_thoai", /^(dien thoai|so dien thoai|sdt|so dt|dt|tel|mobile|hotline)/],
    ["email", /^(e-?mail|thu dien tu)/],
    ["ten_kh", /^(ten (cong ty|doanh nghiep|don vi|khach hang|giao dich|ho kinh doanh)|ben mua|ben b|ten)/]
  ];
  document.getElementById("nut-tu-dien").addEventListener("click", function () {
    var kq = {};
    document.getElementById("o-dan").value.split(/\r?\n/).forEach(function (dong) {
      dong = dong.trim();
      if (!dong) return;
      var m = dong.match(/^([^:\t]{2,40})[:\t]\s*(.+)$/);
      if (m) {
        var khoa = gap(m[1]), gt = m[2].trim();
        if (/^ten (quoc te|viet tat|tieng anh)/.test(khoa)) return;   // không phải tên dùng trong hợp đồng
        for (var i = 0; i < KHOA.length; i++) {
          if (KHOA[i][1].test(khoa)) {
            var ten = KHOA[i][0];
            if (!kq[ten]) kq[ten] = gt;
            if (ten === "dai_dien" && /^giam doc/.test(khoa) && !kq.chuc_vu) kq.chuc_vu = "Giám đốc";
            return;
          }
        }
      }
      var g = gap(dong);
      if (!kq.email && /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(dong)) kq.email = dong;
      else if (!kq.mst && /^\d{10}(-\d{3})?$/.test(dong.replace(/\s/g, ""))) kq.mst = dong.replace(/\s/g, "");
      else if (!kq.ten_kh && /^(cong ty|cty|ctcp|ho kinh doanh|hkd|chi nhanh|benh vien|phong kham|nha thuoc)/.test(g)) kq.ten_kh = dong;
    });
    if (kq.mst) kq.mst = kq.mst.replace(/\s+/g, "");
    var n = 0;
    O.forEach(function (ten) { if (kq[ten]) { o(ten).value = kq[ten]; n++; } });
    if (kq.ten_kh) o("ten_kh").dispatchEvent(new Event("change"));
    O.forEach(function (ten) { if (kq[ten]) o(ten).value = kq[ten]; });  // giữ chữ vừa dán nếu khác thông tin cũ
    document.getElementById("kq-tu-dien").textContent = n ? "Đã điền " + n + " ô. Kiểm tra lại trước khi tạo." :
      "Không nhận ra thông tin nào. Hãy viết theo dạng \"Mã số thuế: …\" mỗi dòng.";
  });
})();

// ô "chọn hết" ở đầu bảng: tích / bỏ tích mọi ô chọn trong cùng bảng
document.querySelectorAll("[data-chon-het]").forEach((o) => {
  o.addEventListener("change", () => {
    o.closest("table").querySelectorAll("tbody input[type=checkbox]").forEach((x) => { x.checked = o.checked; });
  });
});
