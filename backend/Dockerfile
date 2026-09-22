FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/backend
WORKDIR /srv
COPY backend/requirements.txt /srv/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /srv/.data/documents /srv/.data/beat \
    && chown -R app:app /srv/.data
COPY backend /srv/backend
USER app
CMD ["celery", "-A", "app.worker.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=2", "-Q", "ingestion,documents,ai,default"]
