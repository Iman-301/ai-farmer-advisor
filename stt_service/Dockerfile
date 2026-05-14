# syntax=docker/dockerfile:1
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
# BuildKit cache: pip wheel cache is reused across rebuilds
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=300 -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
