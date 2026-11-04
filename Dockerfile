FROM node:22-alpine AS web-build

WORKDIR /app
RUN npm install --global pnpm@11.25.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY index.html tsconfig.json tsconfig.app.json tsconfig.node.json vite.config.ts ./
COPY src ./src
COPY public ./public
RUN pnpm build

FROM python:3.12-slim

WORKDIR /app
ENV MINGYAN_DATA_DIR=/data
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server ./server
COPY --from=web-build /app/dist ./dist
EXPOSE 4173
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4173/api/health')"
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "4173"]
