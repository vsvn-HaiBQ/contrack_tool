FROM node:22-alpine AS build

WORKDIR /app

ARG NODE_TLS_REJECT_UNAUTHORIZED=1
ARG NPM_CONFIG_STRICT_SSL=true
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    NODE_TLS_REJECT_UNAUTHORIZED=${NODE_TLS_REJECT_UNAUTHORIZED} \
    NPM_CONFIG_STRICT_SSL=${NPM_CONFIG_STRICT_SSL}

RUN apk add --no-cache ca-certificates \
    && update-ca-certificates

COPY package.json pnpm-lock.yaml tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
RUN corepack enable \
    && pnpm install --frozen-lockfile \
    && pnpm build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
