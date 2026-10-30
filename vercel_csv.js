// Xuất data/bao_gia.json ra 2 file CSV (public/bao-gia-dang-nhan.csv, public/gia-da-bao.csv)
// để Google Sheet đọc bằng =IMPORTDATA("https://muasamcongadc.vercel.app/...csv"):
// mỗi lần web cập nhật dữ liệu, Sheet tự lấy bản mới (Google làm mới IMPORTDATA khoảng 1 giờ/lần).
const fs = require('fs');

const data = JSON.parse(fs.readFileSync('data/bao_gia.json', 'utf8'));
const now = data.cap_nhat || '';
const cut = s => String(s ?? '').replace(/\s+/g, ' ').slice(0, 300);
const num = v => (typeof v === 'number' ? Math.round(v) : v ?? '');
const write = (path, rows) => fs.writeFileSync(path,
  rows.map(r => r.map(c => '"' + String(c ?? '').replace(/"/g, '""') + '"').join(',')).join('\r\n') + '\r\n');

const open = [['Mã YCBG', 'Trạng thái', 'Tên YCBG', 'Đơn vị yêu cầu', 'Tỉnh/TP', 'Ngày đăng', 'Hạn nhận báo giá',
  'Nhóm', 'Mặt hàng', 'Mô tả', 'ĐVT', 'Số lượng', 'Lần đầu thấy', 'Link']];
[...data.ycbg].sort((a, b) => (b.han || '').localeCompare(a.han || '')).forEach(r => r.items.forEach(h => open.push([
  r.ma, (r.han || '') >= now ? 'Đang nhận' : 'Hết hạn', r.ten, r.cdt, r.tinh, r.dang, r.han,
  h.nhom, h.ten, cut(h.mo_ta), h.dvt, num(h.sl), r.lan_dau, r.link])));

const done = [['Mã YCBG', 'Nơi yêu cầu', 'Tỉnh/TP', 'Hiệu lực từ', 'Hạn nhận báo giá', 'Nhóm', 'Mặt hàng', 'Mô tả',
  'ĐVT', 'Số lượng', 'Số báo giá', 'Giá thấp nhất', 'Giá trung vị', 'Giá cao nhất', 'Tất cả giá báo', 'Lần đầu thấy']];
data.items.forEach(h => done.push([h.ma, h.noi, h.tinh, h.hieu_luc, h.han, h.nhom, h.ten, cut(h.mo_ta), h.dvt,
  num(h.sl), h.so_bg, num(h.min), num(h.tv), num(h.max), (h.gia || []).map(Math.round).join('; '), h.lan_dau]));

write('public/bao-gia-dang-nhan.csv', open);
write('public/gia-da-bao.csv', done);
console.log(`CSV: ${open.length - 1} dòng YCBG, ${done.length - 1} dòng giá đã báo`);
