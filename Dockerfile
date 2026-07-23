# ---- hnetwork multi-arch Docker image ----
# Desteklenen platformlar: linux/amd64 (x86_64 Proxmox), linux/arm64 (Raspberry Pi / CasaOS)
FROM --platform=$BUILDPLATFORM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Sistem bağımlılıkları: nmap (gerçek tarama için, opsiyonel ama önerilen),
# ping için CAP_NET_RAW gerekmez çünkü uygulama subprocess ile ping çağırır.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nmap iproute2 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Çalışma zamanı veritabanı (OUI) diske yazılabilir olmalı
RUN mkdir -p /app/data && chmod 777 /app/data

# Uygulama tüm arayüzleri dinler
EXPOSE 5883

# host network modunda port otomatik paylaşılır; burada sadece belirtiyoruz.
CMD ["sh", "-c", "python -m hnetwork.web --host 0.0.0.0 --port 5883"]
