# admin_dashboard_frontend

**Microservice:** Admin Dashboard — Next.js 16 / TypeScript  
**Port:** `3000`  
**Depends on:** `logic_service`

---

## Overview

React/Next.js web dashboard for the Voice-to-Voice Farmer Advisory System.  
Communicates exclusively through the `logic_service` Admin REST API (`/admin/*`).

## Features

| Page | Route | Role |
|---|---|---|
| Dashboard | `/` | All |
| Farmer Profiles | `/farmers` | All |
| Call Logs + Audio Playback | `/calls` | All |
| Helpdesk / Escalations | `/helpdesk` | All |
| Knowledge Base (ChromaDB) | `/knowledge-base` | Admin write, All read |
| Market Prices | `/market-prices` | Admin write, All read |
| Alerts & Forecasts | `/alerts` | Admin write, All read |

## Authentication

Backed by the `logic_service` `/admin/login` endpoint (bcrypt + Bearer token).  
Session expires after **1 hour** (matches backend timeout). Role badge shown in header.

## Dependencies (`package.json`)

> For Node.js microservices, `package.json` is the equivalent of `requirements.txt`.  
> Run `npm ci` (not `npm install`) in production/Docker to get exact locked versions.

| Package | Purpose |
|---|---|
| `next` | App framework / SSR |
| `react`, `react-dom` | UI rendering |
| `lucide-react` | Icons |
| `tailwindcss` | Styling (v4) |
| `typescript` | Type safety |

## Environment Variables

| Variable | Default (local) | Docker value |
|---|---|---|
| `LOGIC_SERVICE_URL` | `http://localhost:8002` | `http://logic_service:8000` |
| `DATA_DIR` | `/data` | `/data` |
| `NODE_ENV` | `development` | `production` |

## Development

```bash
npm ci          # install exact locked dependencies
npm run dev     # start dev server on :3000
```

Login with any credentials registered in the `admin_users` table (default: `admin` / `admin`).

## Docker

Built and managed via the root `docker-compose.yml`:

```bash
docker compose up --build admin_dashboard_frontend
```

The container mounts `./data:/data:ro` (read-only) to stream call recordings via `/api/audio`.
