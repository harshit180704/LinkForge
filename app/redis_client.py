
import redis

from app.database import settings

client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=10,
    health_check_interval=30,
)
