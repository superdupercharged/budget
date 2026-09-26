# Budget dashboard — local OCR + web UI
FROM python:3.12-slim-bookworm

ENV TZ=Europe/Berlin \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code only — no sample screenshots, secrets, or local data/
COPY budget_dict.json budget_categories.py budget_functions.py budget.py \
     classify_unknown.py run_dashboard.py ./
COPY dashboard/ ./dashboard/

RUN mkdir -p /app/data /app/statements

EXPOSE 8000

# Bind all interfaces so phones on the LAN can reach the dashboard
CMD ["python3", "run_dashboard.py", "--host", "0.0.0.0", "--port", "8000"]
