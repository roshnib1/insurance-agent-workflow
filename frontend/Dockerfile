# Underwriting Workflow frontend (Next.js 15 + React 19)
#
# Uses Next's "standalone" output (see next.config.ts) — the build stage traces
# exactly which node_modules the server actually needs and copies only those into
# the final image, instead of the full node_modules tree.
#
# NEXT_PUBLIC_API_BASE_URL is baked in at BUILD time, same as Vite's VITE_ vars —
# changing the backend's address later means rebuilding this image, not just
# restarting the container.
#
# Build:  docker build -t workflow-frontend --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8002 .
# Run:    docker run -p 3001:3000 workflow-frontend

FROM node:20-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8002
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

RUN npm run build

# --- Runtime stage ---
FROM node:20-slim AS run

WORKDIR /app
ENV NODE_ENV=production

# Standalone output includes a minimal server.js plus only the node_modules it needs.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
