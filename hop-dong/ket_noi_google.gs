/**
 * Kết nối Google Drive cho app Quản lý hợp đồng.
 * Chạy bằng tài khoản Google của bạn, nên:
 *  - đọc được file mẫu trong Drive của bạn mà KHÔNG cần chia sẻ công khai;
 *  - hợp đồng tạo ra là Google Docs nằm trong Drive của bạn (thư mục do app chỉ định).
 * App chỉ gọi được khi gửi đúng KHÓA bên dưới (app tự sinh khóa, đừng chia sẻ đoạn mã này).
 */
const KHOA = '__KHOA__';

/** Mở link /exec trên trình duyệt (cửa sổ ẩn danh) để kiểm tra bản triển khai đã đúng chưa. */
function doGet() {
  return ContentService.createTextOutput('Kết nối Apps Script cho app Quản lý hợp đồng đang chạy đúng. ' +
    'Hãy dán link này vào trang Mẫu HĐ của app.');
}

function doPost(e) {
  let kq;
  try {
    const rq = JSON.parse(e.postData.contents);
    if (rq.khoa !== KHOA) throw new Error('Sai khóa kết nối. Hãy chép lại đoạn mã mới nhất từ trang Mẫu HĐ.');
    if (rq.viec === 'thu') kq = { ok: true, tai_khoan: Session.getEffectiveUser().getEmail() };
    else if (rq.viec === 'lay_mau') kq = layMau_(rq.url);
    else if (rq.viec === 'tao_doc') kq = taoDoc_(rq);
    else if (rq.viec === 'tao_sheet') kq = taoSheet_(rq);
    else if (rq.viec === 'liet_ke') kq = lietKe_(rq);
    else throw new Error('Yêu cầu không hợp lệ.');
  } catch (err) {
    kq = { ok: false, loi: String((err && err.message) || err) };
  }
  return ContentService.createTextOutput(JSON.stringify(kq)).setMimeType(ContentService.MimeType.JSON);
}

function layId_(url) {
  const m = String(url).match(/\/d\/([\w-]{20,})/) || String(url).match(/[?&]id=([\w-]{20,})/);
  if (!m) throw new Error('Link không phải link Google Docs / Google Drive.');
  return m[1];
}

/** Lấy file mẫu dạng Word (.docx), giữ nguyên định dạng. */
function layMau_(url) {
  const id = layId_(url);
  const f = DriveApp.getFileById(id);
  const tab = (String(url).match(/[?&#]tab=([\w.-]+)/) || [])[1] || '';
  let blob, tabs = [];
  if (f.getMimeType() === MimeType.GOOGLE_DOCS) {
    try {
      tabs = DocumentApp.openById(id).getTabs().map(function (t) { return { id: t.getId(), ten: t.getTitle() }; });
    } catch (e) { tabs = []; }
    const r = UrlFetchApp.fetch('https://docs.google.com/document/d/' + id + '/export?format=docx', {
      headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }, muteHttpExceptions: true
    });
    if (r.getResponseCode() !== 200) throw new Error('Không xuất được file Word từ Google Docs (mã ' + r.getResponseCode() + ').');
    blob = r.getBlob();
  } else if (f.getMimeType() === MimeType.GOOGLE_SHEETS) {      // bảng giá: xuất cả file ra Excel
    const r = UrlFetchApp.fetch('https://docs.google.com/spreadsheets/d/' + id + '/export?format=xlsx', {
      headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }, muteHttpExceptions: true
    });
    if (r.getResponseCode() !== 200) throw new Error('Không xuất được file Excel từ Google Sheet (mã ' + r.getResponseCode() + ').');
    blob = r.getBlob();
  } else {
    blob = f.getBlob();
  }
  return { ok: true, ten: f.getName(), loai: f.getMimeType(), tab: tab, tabs: tabs, docx: Utilities.base64Encode(blob.getBytes()) };
}

/** Tạo Google Docs từ file Word hợp đồng, đặt quyền link, trả về link. */
function taoDoc_(rq) {
  return taoTep_(rq, rq.docx, 'application/vnd.google-apps.document',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'https://docs.google.com/document/d/', 'Google Docs');
}

/** Tạo Google Sheet từ file Excel (bảng thông số kỹ thuật), đặt quyền link, trả về link. */
function taoSheet_(rq) {
  return taoTep_(rq, rq.xlsx, 'application/vnd.google-apps.spreadsheet',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'https://docs.google.com/spreadsheets/d/', 'Google Sheet');
}

function taoTep_(rq, noiDungB64, loaiDich, loaiNguon, tienTo, tenLoai) {
  const thuMuc = layThuMuc_(rq.thu_muc || 'Hợp đồng nguyên tắc');
  const ranh = 'ranh-gioi-' + Date.now();
  const meta = { name: rq.ten, mimeType: loaiDich, parents: [thuMuc.getId()] };
  const dau = Utilities.newBlob('--' + ranh + '\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n' + JSON.stringify(meta) +
    '\r\n--' + ranh + '\r\nContent-Type: ' + loaiNguon + '\r\n\r\n').getBytes();
  const cuoi = Utilities.newBlob('\r\n--' + ranh + '--').getBytes();
  const r = UrlFetchApp.fetch('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id', {
    method: 'post', contentType: 'multipart/related; boundary=' + ranh,
    payload: dau.concat(Utilities.base64Decode(noiDungB64)).concat(cuoi),
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }, muteHttpExceptions: true
  });
  if (r.getResponseCode() !== 200) throw new Error('Không tạo được ' + tenLoai + ' (mã ' + r.getResponseCode() + ').');
  const id = JSON.parse(r.getContentText()).id;
  const file = DriveApp.getFileById(id);
  if (rq.quyen === 'sua') file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.EDIT);
  else if (rq.quyen === 'xem') file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return { ok: true, id: id, url: tienTo + id + '/edit' };
}

function layThuMuc_(ten) {
  const it = DriveApp.getRootFolder().getFoldersByName(ten);
  return it.hasNext() ? it.next() : DriveApp.getRootFolder().createFolder(ten);
}

/** Liệt kê file trong một thư mục Drive (kể cả thư mục con, tối đa 4 tầng, 800 file) để app nhập tài liệu hàng hóa. */
function lietKe_(rq) {
  const url = String(rq.url || '');
  const m = url.match(/\/folders\/([\w-]{20,})/) || url.match(/\/d\/([\w-]{20,})/) || url.match(/[?&]id=([\w-]{20,})/);
  if (!m) throw new Error('Link không phải link thư mục / file Google Drive.');
  const ds = [];
  let ten;
  try {
    const goc = DriveApp.getFolderById(m[1]);
    ten = goc.getName();
    duyetThuMuc_(goc, [], ds, 0, rq.mo_quyen);
  } catch (err) {
    if (ds.length) throw err;
    const f = DriveApp.getFileById(m[1]);                     // link một file lẻ
    ten = f.getName();
    themTep_(f, [], ds, rq.mo_quyen);
  }
  return { ok: true, ten: ten, tep: ds };
}

function duyetThuMuc_(tm, duong, ds, sau, moQuyen) {
  const it = tm.getFiles();
  while (it.hasNext() && ds.length < 800) themTep_(it.next(), duong, ds, moQuyen);
  if (sau >= 4) return;
  const con = tm.getFolders();
  while (con.hasNext() && ds.length < 800) {
    const s = con.next();
    duyetThuMuc_(s, duong.concat([s.getName()]), ds, sau + 1, moQuyen);
  }
}

function themTep_(f, duong, ds, moQuyen) {
  if (f.getMimeType() === 'application/vnd.google-apps.shortcut') return;
  if (moQuyen) {
    try { f.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW); } catch (e) { /* file của người khác */ }
  }
  ds.push({ id: f.getId(), ten: f.getName(), loai: f.getMimeType(), co: f.getSize(), url: f.getUrl(),
            thu_muc: duong.join(' / '), sua: f.getLastUpdated().toISOString() });
}
