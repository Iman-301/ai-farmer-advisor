# syntax=docker/dockerfile:1
FROM python:3.10-slim
WORKDIR /app

# ── CPU-only PyTorch (matches current transformers; avoids NumPy 2 / torch 2.2 mismatch) ──
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=600 \
    torch==2.5.1 torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cpu

# ── Everything else (requirements.txt must not reinstall torch) ─────────────
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --default-timeout=300 -r requirements.txt

COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
