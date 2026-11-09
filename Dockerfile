FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FINN_DATA_DIR=/data

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 finn \
    && mkdir /data && chown finn:finn /data

COPY finn/ ./finn/
COPY tests/ ./tests/
USER finn
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "finn.app:app", "--host", "0.0.0.0", "--port", "8080"]
