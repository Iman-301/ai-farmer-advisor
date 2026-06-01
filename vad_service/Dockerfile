FROM python:3.10-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Silero VAD needs PyTorch (CPU build keeps image smaller than CUDA).
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=600 \
    torch==2.5.1 torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cpu

COPY vad_service/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=100 --retries=10 -r /app/requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=100 --retries=10 silero-vad

COPY shared/ /app/shared/
COPY vad_service/*.py /app/

ENV PYTHONPATH=/app

RUN mkdir -p /app/utterances
EXPOSE 8010
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
