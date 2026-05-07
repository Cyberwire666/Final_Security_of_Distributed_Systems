#!/usr/bin/env bash
set -e
mkdir -p nginx/certs
MSYS_NO_PATHCONV=1 openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/localhost.key \
  -out nginx/certs/localhost.crt \
  -subj "/C=EG/ST=Alexandria/L=Alexandria/O=HospitalSecure/OU=Dev/CN=localhost"
echo "Generated nginx/certs/localhost.crt and nginx/certs/localhost.key"
