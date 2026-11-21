"""Create Docker-only environment from existing local .env without changing it."""
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

root = Path(__file__).resolve().parent.parent
src = root / '.env'
dst = root / '.env.docker'
if not src.is_file():
    raise SystemExit('Missing .env in project root. No changes made.')
if dst.exists():
    raise SystemExit('.env.docker already exists; refusing to overwrite. Inspect it first.')
values = {}
for line in src.read_text(encoding='utf-8-sig').splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or '=' not in stripped:
        continue
    key, val = stripped.split('=', 1)
    values[key.strip()] = val.strip().strip('"').strip("'")
for key in ('DATABASE_URL', 'JWT_SECRET'):
    if not values.get(key):
        raise SystemExit(f'Missing {key} in .env; no changes made.')
url = urlsplit(values['DATABASE_URL'])
if not url.scheme.startswith('postgres') or not url.hostname:
    raise SystemExit('DATABASE_URL must be a PostgreSQL URL; no changes made.')
userinfo = url.netloc.rsplit('@', 1)[0] + '@' if '@' in url.netloc else ''
values['DATABASE_URL'] = urlunsplit(url._replace(netloc=userinfo + 'db:5432'))
values['REDIS_URL'] = 'redis://redis:6379/0'
values['BASE_URL'] = 'http://localhost:8000'
# Restrict output to the known application settings; do not copy unrelated local secrets.
keys = ('DATABASE_URL', 'REDIS_URL', 'JWT_SECRET', 'BASE_URL')
dst.write_text(''.join(f'{key}={values[key]}\n' for key in keys), encoding='utf-8')
print('Created .env.docker using existing PostgreSQL credentials and JWT secret.')
print('Original .env was not modified. Do not commit .env.docker.')
