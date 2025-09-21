FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY . /app

ENV DATABASE_URL=sqlite:////data/wallettaser.db \
    WALLETTASER_DATA_ROOT=/data/reports \
    CELERY_BROKER_URL=redis://redis:6379/0 \
    CELERY_RESULT_BACKEND=redis://redis:6379/0

VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "wallettaser.api:app", "--host", "0.0.0.0", "--port", "8000"]
