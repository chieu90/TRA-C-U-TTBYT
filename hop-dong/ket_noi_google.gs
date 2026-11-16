/**
 * Kết nối Google Drive cho app Quản lý hợp đồng.
 * Chạy bằng tài khoản Google của bạn, nên:
 *  - đọc được file mẫu trong Drive của bạn mà KHÔNG cần chia sẻ công khai;
 *  - hợp đồng tạo ra là Google Docs nằm trong Drive của bạn (thư mục do app chỉ định).
 * App chỉ gọi được khi gửi đúng KHÓA bên dưới (app tự sinh khóa, đừng chia sẻ đoạn mã này).
 */
const KHOA = '__KHOA__';

function doPost(e) {
  let kq;
  try {
    const rq = JSON.parse(e.postData.contents);
    if (rq.khoa !== KHOA) throw new Error('Sai khóa kết nối. Hãy chép lại đoạn mã mới nhất từ trang Mẫu HĐ.');
    if (rq.viec === 'thu') kq = { ok: true, tai_khoan: Session.getEffectiveUser().getEmail() };
    else if (rq.viec === 'lay_mau') kq = layMau_(rq.url);
    else if (rq.viec === 'tao_doc') kq = taoDoc_(rq);
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
  } else {
    blob = f.getBlob();
  }
  return { ok: true, ten: f.getName(), loai: f.getMimeType(), tab: tab, tabs: tabs, docx: Utilities.base64Encode(blob.getBytes()) };
}

/** Tạo Google Docs từ file Word hợp đồng, đặt quyền link, trả về link. */
function taoDoc_(rq) {
  const thuMuc = layThuMuc_(rq.thu_muc || 'Hợp đồng nguyên tắc');
  const ranh = 'ranh-gioi-' + Date.now();
  const meta = { name: rq.ten, mimeType: 'application/vnd.google-apps.document', parents: [thuMuc.getId()] };
  const dau = Utilities.newBlob('--' + ranh + '\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n' + JSON.stringify(meta) +
    '\r\n--' + ranh + '\r\nContent-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\r\n\r\n').getBytes();
  const cuoi = Utilities.newBlob('\r\n--' + ranh + '--').getBytes();
  const r = UrlFetchApp.fetch('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id', {
    method: 'post', contentType: 'multipart/related; boundary=' + ranh,
    payload: dau.concat(Utilities.base64Decode(rq.docx)).concat(cuoi),
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }, muteHttpExceptions: true
  });
  if (r.getResponseCode() !== 200) throw new Error('Không tạo được Google Docs (mã ' + r.getResponseCode() + ').');
  const id = JSON.parse(r.getContentText()).id;
  const file = DriveApp.getFileById(id);
  if (rq.quyen === 'sua') file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.EDIT);
  else if (rq.quyen === 'xem') file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return { ok: true, id: id, url: 'https://docs.google.com/document/d/' + id + '/edit' };
}

function layThuMuc_(ten) {
  const it = DriveApp.getRootFolder().getFoldersByName(ten);
  return it.hasNext() ? it.next() : DriveApp.getRootFolder().createFolder(ten);
}
