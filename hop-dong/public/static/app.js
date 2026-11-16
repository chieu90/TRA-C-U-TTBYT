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
