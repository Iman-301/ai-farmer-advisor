FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade pip setuptools wheel

# 1) Install normal lightweight dependencies
RUN pip install \
    --no-cache-dir \
    --timeout 300 \
    --retries 10 \
    -r /app/requirements.txt

# 2) Install CPU-only PyTorch and Torchaudio from the PyTorch CPU index
RUN pip install \
    --no-cache-dir \
    --timeout 300 \
    --retries 10 \
    torch torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

# 3) Install silero-vad WITHOUT dependencies
# This prevents pip from trying to download another torch from PyPI
RUN pip install \
    --no-cache-dir \
    --timeout 300 \
    --retries 10 \
    silero-vad \
    --no-deps

COPY main.py /app/main.py
COPY vad_engine.py /app/vad_engine.py
COPY audio_utils.py /app/audio_utils.py

RUN mkdir -p /app/utterances

EXPOSE 8010

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]