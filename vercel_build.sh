#!/bin/sh
# Dựng bản tĩnh của 2 trang Gói thầu + Báo giá cho Vercel (thư mục public/).
# Trang Tra cứu TBYT vẫn chạy trên Render (app.py), Vercel chỉ phục vụ file tĩnh nên không bị ngủ/khởi động lại.
set -e
rm -rf public && mkdir -p public/static
cp data/goi_thau.json public/goi_thau.json
cp data/bao_gia.json public/bao_gia.json
cp static/*.png public/static/
cp pwa/manifest.webmanifest pwa/sw.js public/
# CSV báo giá cho Google Sheet (=IMPORTDATA) tự cập nhật theo web
node vercel_csv.js
# bản Vercel không có trang Tra cứu TBYT -> bỏ nút đó khỏi thanh điều hướng
sed 's#<a href="/">Tra cứu TBYT</a>##' goi_thau.html > public/goi-thau.html
sed 's#<a href="/">Tra cứu TBYT</a>##' bao_gia.html > public/bao-gia.html
echo "Xong: $(ls public | tr '\n' ' ')"
