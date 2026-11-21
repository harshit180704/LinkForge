"""Wait for database and Redis TCP sockets, then exec the requested command."""
import os
import socket
import sys
import time
from urllib.parse import urlsplit

services = [os.environ['DATABASE_URL'], os.environ['REDIS_URL']]
for url in services:
    parsed = urlsplit(url)
    host = parsed.hostname
    port = parsed.port or (5432 if parsed.scheme.startswith('postgres') else 6379)
    if not host:
        raise SystemExit(f'Invalid service URL: {parsed.scheme}')
    for attempt in range(60):
        try:
            with socket.create_connection((host, port), timeout=2):
                break
        except OSError:
            if attempt == 59:
                raise SystemExit(f'Service unavailable: {host}:{port}')
            time.sleep(2)
    print(f'Service ready: {host}:{port}', flush=True)
if len(sys.argv) < 2:
    raise SystemExit('Usage: wait_for_services.py command [args...]')
os.execvp(sys.argv[1], sys.argv[1:])
