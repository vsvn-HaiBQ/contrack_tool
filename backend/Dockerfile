FROM node:22-alpine AS frontend-build

WORKDIR /frontend

ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/tsconfig.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/public ./public
COPY frontend/src ./src
RUN corepack enable \
    && pnpm install --frozen-lockfile \
    && pnpm build

FROM node:22-alpine AS local-server-release

WORKDIR /repo

COPY package.json ./
COPY frontend/package.json ./frontend/package.json
COPY local-server ./local-server
COPY build ./build
RUN node local-server/scripts/build.cjs

FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY sql ./sql
COPY --from=frontend-build /frontend/dist ./frontend_dist
COPY --from=local-server-release /repo/build_output/releases/local-server ./local_server_releases

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8009"]
