FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY receptor.py ./
# numerico, e nao `nobody`: com runAsNonRoot o kubelet so aceita usuario
# que ele consiga provar que nao e root
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["python", "/app/receptor.py"]
