FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .

# sqlite3 is part of python standard library but needed to satisfy pip requirements files easily if someone left it, actual installation avoids it.
RUN sed -i '/sqlite3/d' requirements.txt
RUN pip install --default-timeout=1000 --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
