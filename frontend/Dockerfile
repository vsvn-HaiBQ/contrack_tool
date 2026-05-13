FROM node:22-slim AS build

WORKDIR /app

RUN apt-get update \
	&& apt-get install -y --no-install-recommends ca-certificates \
	&& rm -rf /var/lib/apt/lists/*
ENV NODE_OPTIONS=--use-openssl-ca
RUN npm config set cafile /etc/ssl/certs/ca-certificates.crt \
	&& npm config set strict-ssl false

COPY package.json package-lock.json ./
RUN npm ci

COPY . ./
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
