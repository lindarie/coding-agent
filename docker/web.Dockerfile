FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /repo
COPY package.json pnpm-workspace.yaml tsconfig.base.json pnpm-lock.yaml* ./
COPY packages/api-types packages/api-types
COPY apps/web apps/web
RUN pnpm install
RUN pnpm --filter @coding-agent/web build

FROM nginx:1.27-alpine
# Rendered with envsubst at container start (AGENT_API_TOKEN).
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
