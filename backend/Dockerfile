FROM node:22-slim AS assets

WORKDIR /src

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV NODE_OPTIONS=--use-openssl-ca
RUN npm config set cafile /etc/ssl/certs/ca-certificates.crt

COPY package.json package-lock.json ./
RUN npm ci --omit=dev
ENV PATH=/src/node_modules/.bin:$PATH
RUN pnpm config set manage-package-manager-versions false

COPY frontend/package.json frontend/pnpm-lock.yaml ./frontend/
RUN pnpm --dir frontend install --frozen-lockfile

COPY frontend ./frontend
COPY local-server ./local-server
COPY build ./build
RUN pnpm --dir frontend build && node local-server/scripts/build.cjs

FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY sql ./sql
COPY --from=assets /src/build_output/web ./frontend_dist
COPY --from=assets /src/build_output/releases/local-server ./local_server_releases

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8009"]
