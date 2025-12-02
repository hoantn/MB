# kendz/database/__init__.py
"""Tầng truy cập dữ liệu (Database Layer) cho Kendz.

Giai đoạn này:
- Chỉ triển khai database local (SQLite) để lưu log, session, round, hand.
- License server và database server sẽ làm ở phase sau.

Toàn bộ tương tác DB nên đi qua các hàm tiện ích được định nghĩa ở đây
(thông qua db_session.py và models.py) để đảm bảo dễ bảo trì.
"""
