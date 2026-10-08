/**
 * Nhận dữ liệu từ trang "Tra cứu thiết bị y tế" (app.py) và ghi vào Google Sheet này.
 *
 * Cài đặt (làm 1 lần):
 *  1. Mở Google Sheet muốn lưu dữ liệu → Tiện ích mở rộng → Apps Script.
 *  2. Xoá code mẫu, dán toàn bộ file này vào, bấm Lưu.
 *  3. Triển khai → Tùy chọn triển khai mới → Loại: Ứng dụng web.
 *       Thực thi với tư cách: Tôi      Người có quyền truy cập: Bất kỳ ai
 *  4. Bấm Triển khai, cấp quyền, rồi sao chép "URL ứng dụng web" (…/exec)
 *     dán vào ô "URL Apps Script" trên trang tra cứu.
 *
 * Dữ liệu được ghi thêm vào trang tính "vimda"; hồ sơ đã có (trùng Mã hồ sơ + Số lưu hành) sẽ bỏ qua.
 */
const SHEET_NAME = 'vimda';

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const data = JSON.parse(e.postData.contents);
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
    const header = data.header;

    if (sh.getLastRow() === 0) {
      sh.appendRow(header);
      sh.getRange(1, 1, 1, header.length).setFontWeight('bold');
      sh.setFrozenRows(1);
    }

    // Khoá chống trùng: cột "Mã hồ sơ" + "Số công bố / số lưu hành"
    const cols = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
    const iMa = cols.indexOf('Mã hồ sơ'), iSo = cols.indexOf('Số công bố / số lưu hành');
    const seen = new Set();
    if (sh.getLastRow() > 1 && iMa >= 0 && iSo >= 0) {
      sh.getRange(2, 1, sh.getLastRow() - 1, cols.length).getValues()
        .forEach(r => seen.add(r[iMa] + '|' + r[iSo]));
    }
    const hMa = header.indexOf('Mã hồ sơ'), hSo = header.indexOf('Số công bố / số lưu hành');
    const rows = data.rows.filter(r => {
      const k = r[hMa] + '|' + r[hSo];
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });

    if (rows.length) {
      // Ghi dạng chữ để Sheets không tự đổi số lưu hành / ngày
      const range = sh.getRange(sh.getLastRow() + 1, 1, rows.length, header.length);
      range.setNumberFormat('@').setValues(rows);
    }
    return json({ ok: true, url: ss.getUrl() + '#gid=' + sh.getSheetId(), added: rows.length,
                  skipped: data.rows.length - rows.length });
  } catch (err) {
    return json({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function json(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
