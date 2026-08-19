# Coima backend — FastAPI served by uvicorn
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

# Seed a clean schema-only SQLite DB. On first run the empty backend_data volume
# is initialized from the image's /app/data, so the app starts with this clean DB.
# Existing volumes keep their data (cp only runs at build, into the image layer).
RUN cp data/coima.seed.db data/coima.db

EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
