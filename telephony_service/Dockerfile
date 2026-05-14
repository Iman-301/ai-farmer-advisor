# syntax=docker/dockerfile:1
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# --retries 5: auto-retries on network failures / partial downloads
RUN pip install --retries 5 --default-timeout=300 -r requirements.txt

COPY . .

CMD ["python", "main.py"]
