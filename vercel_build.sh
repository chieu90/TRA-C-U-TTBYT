#!/bin/sh
# Dựng bản tĩnh các trang Gói thầu, Báo giá, Cơ sở y tế, Trúng thầu cho Vercel (thư mục public/).
# Trang Tra cứu TBYT vẫn chạy trên Render (app.py), Vercel chỉ phục vụ file tĩnh nên không bị ngủ/khởi động lại.
set -e
rm -rf public && mkdir -p public/static
cp data/goi_thau.json public/goi_thau.json
cp data/bao_gia.json public/bao_gia.json
cp data/co_so_y_te.json public/co_so_y_te.json
cp data/trung_thau.json public/trung_thau.json
cp data/duong_huyet.json public/duong_huyet.json
cp static/*.png static/*.json public/static/
cp pwa/manifest.webmanifest pwa/sw.js public/
# CSV báo giá cho Google Sheet (=IMPORTDATA) tự cập nhật theo web
node vercel_csv.js
# bản Vercel không có trang Tra cứu TBYT -> bỏ nút đó khỏi thanh điều hướng
sed 's#<a href="/">Tra cứu TBYT</a>##' goi_thau.html > public/goi-thau.html
sed 's#<a href="/">Tra cứu TBYT</a>##' bao_gia.html > public/bao-gia.html
sed 's#<a href="/">Tra cứu TBYT</a>##' co_so_y_te.html > public/co-so-y-te.html
sed 's#<a href="/">Tra cứu TBYT</a>##' trung_thau.html > public/trung-thau.html
# KQ Đường Huyết dùng chung giao diện với KQ Test (trang tự nhận theo đường dẫn)
cp public/trung-thau.html public/duong-huyet.html
echo "Xong: $(ls public | tr '\n' ' ')"
