# PO Approval System

Digital Purchase Order Approval System for Construction & Real Estate.

## Stack
- **Backend**: FastAPI + Python 3.12
- **Database**: PostgreSQL (asyncpg)
- **ORM**: SQLModel + Alembic
- **Auth**: fastapi-users (JWT)
- **State machine**: transitions
- **Async tasks**: ARQ + Redis
- **Frontend**: Jinja2 + HTMX + Tailwind CSS
- **Deploy**: Docker + Docker Compose → Railway/Render

## Quick Start

```bash
cp .env.example .env          # fill in your values
docker compose up --build     # starts app + postgres + redis
```

App: http://localhost:8000  
Swagger docs: http://localhost:8000/docs  
Admin: http://localhost:8000/admin

## Project Structure

```
app/
├── api/v1/endpoints/     # Route handlers
├── core/                 # Config, security, logging
├── db/                   # Database session
├── models/               # SQLModel table models
├── schemas/              # Pydantic request/response schemas
├── services/             # Business logic (PO, approval engine)
└── tasks/                # ARQ background tasks (email, notifications)
```

## Environment Variables

See `.env.example` for all required variables.

## Running Tests

```bash
docker compose run --rm app pytest tests/ -v
```
