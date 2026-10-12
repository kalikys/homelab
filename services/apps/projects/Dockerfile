FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY projects_api/ projects_api/
COPY backup.py .
COPY --from=web /web/dist /app/static
ENV PROJECTS_DB=/data/projects.db STATIC_DIR=/app/static AUTH_MODE=none
EXPOSE 8790
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/api/health', timeout=3)"
CMD ["uvicorn", "--factory", "projects_api.main:create_app", "--host", "0.0.0.0", "--port", "8790"]
