FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run check \
    && npm run test \
    && npm run build

FROM caddy:2.11.4-alpine@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648

COPY frontend/Caddyfile /etc/caddy/Caddyfile
COPY --from=builder /app/frontend/dist /srv

RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

EXPOSE 80 443
