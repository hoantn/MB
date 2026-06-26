from datetime import datetime, timedelta

# Quy ước toàn hệ thống:
# Giờ VN (UTC+7), naive datetime (để không vỡ SQLite)
def now() -> datetime:
    return datetime.utcnow() + timedelta(hours=7)
