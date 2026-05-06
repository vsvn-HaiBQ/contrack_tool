FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY sql ./sql
COPY build_output/web ./frontend_dist
COPY build_output/releases/local-server ./local_server_releases

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8009"]
