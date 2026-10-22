FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY receptor.py ./
USER nobody
EXPOSE 8080
ENTRYPOINT ["python", "/app/receptor.py"]
