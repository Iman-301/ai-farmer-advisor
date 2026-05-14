# syntax=docker/dockerfile:1
# CPU-only PyTorch: always use PyTorch's CPU wheel index, or pip pulls CUDA (~1.5GB+ nvidia-* wheels).
FROM python:3.10-slim
WORKDIR /app

ARG PYTORCH_CPU_INDEX=https://download.pytorch.org/whl/cpu

RUN apt-get update && apt-get install -y \
    build-essential python3-dev cmake \
    && rm -rf /var/lib/apt/lists/*

# Torch first from CPU index (small wheel vs default manylinux CUDA build).
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    pip install torch==2.2.2 --index-url ${PYTORCH_CPU_INDEX} && \
    pip install --default-timeout=300 \
        --extra-index-url ${PYTORCH_CPU_INDEX} \
        -r requirements.txt

COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
