FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY om_apply ./om_apply
COPY om_apply.py ./
COPY resources ./resources

ENTRYPOINT ["python", "/app/om_apply.py"]
CMD ["--file", "/app/resources"]
