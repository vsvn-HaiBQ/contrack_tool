FROM node:22-alpine AS build

WORKDIR /app

COPY package.json pnpm-lock.yaml tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
RUN corepack enable && pnpm install --frozen-lockfile && pnpm build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
