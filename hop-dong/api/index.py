"""Điểm vào trên Vercel: mọi đường dẫn được vercel.json chuyển về đây, app.py xử lý như khi chạy trên máy."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import H  # noqa: E402


class handler(H):
    pass
