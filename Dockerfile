FROM node:20-alpine AS frontend
WORKDIR /ui
COPY dashboard/frontend/package.json dashboard/frontend/package-lock.json ./
RUN npm ci
COPY dashboard/frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt
COPY agents/ agents/
COPY ingestion/ ingestion/
COPY validation/ validation/
COPY dashboard/ dashboard/
COPY scripts/ scripts/
COPY eval/ eval/
COPY --from=frontend /ui/dist dashboard/frontend/dist
EXPOSE 8888
CMD ["python", "-m", "validation.streaming_validator"]
