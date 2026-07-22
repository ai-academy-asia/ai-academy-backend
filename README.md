# AIAA Backend (Flask + PostgreSQL)

Flask REST backend with PostgreSQL, using the application-factory pattern,
SQLAlchemy ORM, and Flask-Migrate (Alembic) for schema migrations.

## Stack
- Flask 3
- Flask-SQLAlchemy 3 (SQLAlchemy 2)
- Flask-Migrate (Alembic)
- PostgreSQL 16 (via Docker Compose)
- psycopg2

## Layout
```
app/
  __init__.py      # create_app() application factory
  config.py        # config, builds DATABASE_URL from POSTGRES_* env vars
  extensions.py    # db, migrate singletons
  models/          # SQLAlchemy models (imported in __init__ for autodetect)
  routes/          # blueprints (health check included)
wsgi.py            # entrypoint, loads .env and creates the app
docker-compose.yml # local PostgreSQL
```

## First-time setup

```bash
# 1. Python virtualenv + deps
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Env file
cp .env.example .env        # edit SECRET_KEY / passwords as needed

# 3. Start PostgreSQL
docker compose up -d

# 4. Initialize migrations (first time only) and apply
flask db init
flask db migrate -m "initial"
flask db upgrade

# 5. Run the app
python wsgi.py                 # http://localhost:8000
# or: flask run --port 8000
```

> Notes for this machine:
> - Postgres is mapped to host port **5433** (5432 is taken by another project's container).
> - The app runs on **8000** — port 5000 is claimed by macOS AirPlay Receiver.

## Everyday commands
```bash
source .venv/bin/activate
docker compose up -d          # start db
flask db migrate -m "msg"     # after changing models
flask db upgrade              # apply migrations
python wsgi.py                # dev server on http://localhost:8000
docker compose down           # stop db (data persists in the pgdata volume)
```

## Endpoints
- `GET /`        → service banner
- `GET /health`  → liveness + DB connectivity (503 if DB down)
