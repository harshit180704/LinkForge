# LinkForge: five-service Docker Compose deployment

This is an additive overlay for your existing project. It intentionally **does not replace** `docker-compose.yml`, `compose.redis.yml`, or existing named volumes.

## Before starting

1. Ensure your latest analytics upgrade works locally and back up your PostgreSQL data.
2. Stop local FastAPI, worker, and Vite (`Ctrl+C`) so Docker can bind ports 8000 and 5173.
3. Extract the package into `D:\scalable-url-shortener`, retaining `docker/` and `compose.app.yml`.
4. Run from project root:

```powershell
.\.venv\Scripts\python.exe .\docker\prepare_env.py
```

The helper creates `.env.docker` based on your existing `.env`, using hostnames `db` and `redis` on the internal Compose network. Do not commit it.

## Build and run

```powershell
docker compose -f docker-compose.yml -f compose.redis.yml -f compose.app.yml config --services
docker compose -f docker-compose.yml -f compose.redis.yml -f compose.app.yml up -d --build
docker compose -f docker-compose.yml -f compose.redis.yml -f compose.app.yml ps
```

Dashboard: http://localhost:5173
API: http://localhost:8000/docs
Health: http://localhost:8000/health

Frontend Nginx proxies `/api/` and `/health` to `backend:8000`. Short links remain at `http://localhost:8000/<code>`.

## Validate

```powershell
docker compose -f docker-compose.yml -f compose.redis.yml -f compose.app.yml logs --tail=80 backend worker frontend
docker compose -f docker-compose.yml -f compose.redis.yml -f compose.app.yml exec db psql -U urluser -d urlshortener -c "SELECT COUNT(*) FROM click_events;"
```

Click an existing short link, wait a few seconds, then refresh the dashboard and confirm the chart increments. The backend startup creates the additive `click_events` table only if the installed app includes the analytics model and startup `create_all` logic.

## Stop without deleting data

```powershell
docker compose -f docker-compose.yml -f compose.redis.yml -f compose.app.yml stop
```

**Never use `down -v`**: it removes persistent volumes. To restart, run `up -d` with all three Compose files.

## Common issues

- `port is already allocated`: stop local Vite or Uvicorn and retry.
- Backend cannot connect to DB: check `.env.docker` uses `db:5432`, and existing Compose DB service is named `db`.
- Frontend build fails: run `cd frontend; npm run build` locally to inspect TypeScript errors.
- `npm ci` requires an existing package-lock; Dockerfile uses `npm install` if none exists.
- If your existing Compose service names differ from `db` and `redis`, adjust the overlay and helper before starting.
- If the existing `docker-compose.yml` defines a different DB user or DB name, preserve its settings; this overlay does not create a new DB.

## Git hygiene

Add to `.gitignore`:

```gitignore
.env.docker
analytics-backup/
frontend/node_modules/
frontend/dist/
```

Commit `compose.app.yml`, `docker/`, `.dockerignore`, and documentation, not `.env.docker`.

This is a **local containerized deployment**. Internet-facing production still needs HTTPS, managed secrets, migration tooling, operational monitoring, and a deployment environment.
