FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt
COPY dashboard/ dashboard/
COPY validation/config.py validation/config.py
COPY agents/ agents/
COPY eval/ eval/
EXPOSE 8888
CMD ["uvicorn", "dashboard.api.main:app", "--host", "0.0.0.0", "--port", "8888"]
