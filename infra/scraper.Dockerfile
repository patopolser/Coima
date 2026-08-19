# Coima scraper — supervisor loop watching the shared control file
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY scraper/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY scraper/ ./

# Supervisor owns run_status.json and watches control.json in COIMA_OUTPUT_DIR.
CMD ["python", "supervisor.py"]
