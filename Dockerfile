# Duas imagens a partir da mesma base, escolhidas por --target:
#   receptor  servico do webhook de sugestoes (receptor/), publicado no ghcr
#   apply     o om_apply, rodado pelo run.sh (alvo padrao)

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app


FROM base AS receptor

COPY receptor/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY receptor/receptor.py ./
# numerico, e nao `nobody`: com runAsNonRoot o kubelet so aceita usuario
# que ele consiga provar que nao e root
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["python", "/app/receptor.py"]


FROM base AS apply

ENV OPENMETADATA_RESOURCE_FILE=/data/resources

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY om_apply ./om_apply
COPY om_apply.py ./
ENTRYPOINT ["python", "/app/om_apply.py"]
CMD ["--file", "/data/resources"]
