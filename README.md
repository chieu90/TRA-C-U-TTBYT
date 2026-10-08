# Tra cứu thiết bị y tế (vimda.moh.gov.vn)

Trang web tìm theo từ khóa trên [vimda.moh.gov.vn](https://vimda.moh.gov.vn/web/guest/van-ban-cong-bo):
công ty công bố, số lưu hành, tên sản phẩm, hãng sản xuất, chủ sở hữu. Xuất CSV / Google Sheets.

- Chạy trên máy: `python3 app.py` rồi mở http://localhost:8765
- Đưa lên Render.com: file `render.yaml` đã cấu hình sẵn (máy chủ Singapore, gói miễn phí).
- `vimda_scraper.py`: script lấy dữ liệu hàng loạt ra Excel/CSV.
- `google_apps_script.gs`: code dán vào Apps Script để gửi thẳng vào Google Sheet.

Chỉ dùng thư viện chuẩn của Python, không cần cài thêm gì.
