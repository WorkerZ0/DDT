FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
RUN useradd -r -u 1000 ddt && mkdir /data && chown ddt /data
USER ddt

EXPOSE 8000
# Un solo worker: el relay de pantallas vive en memoria del proceso
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--ws-max-size", "4194304", "--ws-ping-interval", "20", "--ws-ping-timeout", "20", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
