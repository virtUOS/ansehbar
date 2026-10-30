# Production image: builds the SPA and bakes it into the Django image, so one
# versioned artifact per release. On start (see docker-compose.prod.yml) the
# app copies /app/frontend_dist into a volume that Caddy serves directly.

FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ .
# Same-origin API in production: VITE_API_BASE_URL stays unset (api.ts → "").
RUN npm run build

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# gettext for compilemessages (add `RUN python manage.py compilemessages` once
# the tool ships a locale/ directory). No compiler needed — wheels only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY --from=frontend-build /frontend/dist /app/frontend_dist

EXPOSE 8000

# --proxy-headers: trust Caddy's X-Forwarded-* so https is detected.
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
