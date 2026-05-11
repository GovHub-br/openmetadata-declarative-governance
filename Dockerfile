FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OPENMETADATA_RESOURCE_FILE=/data/resources

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY om_apply ./om_apply
COPY om_apply.py ./
ENTRYPOINT ["python", "/app/om_apply.py"]
CMD ["--file", "/data/resources"]
