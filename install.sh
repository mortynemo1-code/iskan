#!/usr/bin/env sh
set -eu

command -v docker >/dev/null 2>&1 || { echo "Docker Engine is required" >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required" >&2; exit 1; }
command -v openssl >/dev/null 2>&1 || { echo "OpenSSL is required" >&2; exit 1; }
tls_name="${WORKFORCE_TLS_NAME:-workforce.local}"

if [ ! -f .env ]; then
  cp .env.example .env
  postgres_password="$(openssl rand -hex 24)"
  installation_token="$(openssl rand -hex 32)"
  device_pepper="$(openssl rand -hex 32)"
  jwt_secret="$(openssl rand -hex 48)"
  minio_password="$(openssl rand -hex 24)"
  admin_password="$(openssl rand -base64 24 | tr -d '/+=')Aa1!"
  grafana_password="$(openssl rand -base64 24 | tr -d '/+=')Aa1!"
  sed -i "s/POSTGRES_PASSWORD=change-me/POSTGRES_PASSWORD=$postgres_password/" .env
  sed -i "s/workforce:change-me@postgres/workforce:$postgres_password@postgres/" .env
  sed -i "s/replace-with-a-long-random-token/$installation_token/" .env
  sed -i "s/replace-with-a-different-long-random-secret/$device_pepper/" .env
  sed -i "s/replace-with-at-least-32-random-bytes/$jwt_secret/" .env
  sed -i "s/replace-with-a-strong-minio-password/$minio_password/" .env
  sed -i "s/replace-with-a-strong-password/$admin_password/" .env
  sed -i "s/replace-with-a-strong-grafana-password/$grafana_password/" .env
  sed -i "s/workforce.local/$tls_name/g" .env
  chmod 600 .env
  echo "Generated .env. Bootstrap admin password: $admin_password"
  echo "Save it now; remove BOOTSTRAP_ADMIN_PASSWORD from .env after the first successful login."
fi

mkdir -p infra/tls
if [ ! -s infra/tls/fullchain.pem ] || [ ! -s infra/tls/privkey.pem ]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
    -subj "/CN=$tls_name" \
    -addext "subjectAltName=DNS:$tls_name" \
    -keyout infra/tls/privkey.pem -out infra/tls/fullchain.pem
  chmod 600 infra/tls/privkey.pem
  echo "Created a self-signed TLS certificate for $tls_name. Replace it with your CA certificate in production."
fi

docker compose -f compose.yaml -f compose.production.yaml up --build -d
docker compose -f compose.yaml -f compose.production.yaml ps
echo "Workforce Monitoring is starting at https://$tls_name/"
