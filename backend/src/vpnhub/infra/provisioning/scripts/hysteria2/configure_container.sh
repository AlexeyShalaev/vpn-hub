cd /opt/amnezia/hysteria2

# self-signed серт для маскировочного SNI: публичного CA нет, клиент доверяет по pinSHA256.
openssl ecparam -genkey -name prime256v1 -out /opt/amnezia/hysteria2/cert.key
openssl req -new -x509 -days 3650 -key /opt/amnezia/hysteria2/cert.key \
  -out /opt/amnezia/hysteria2/cert.crt -subj "/CN=$HYSTERIA_SNI" \
  -addext "subjectAltName=DNS:$HYSTERIA_SNI"

# отпечаток серта для клиентского pinSHA256 (hex с двоеточиями — формат, который ждёт hysteria)
openssl x509 -in /opt/amnezia/hysteria2/cert.crt -noout -fingerprint -sha256 \
  | sed 's/^.*Fingerprint=//' > /opt/amnezia/hysteria2/cert_sha256.key

# пароль salamander-обфускации (прячет QUIC-хендшейк от DPI)
openssl rand -hex 16 > /opt/amnezia/hysteria2/obfs.key
HYSTERIA_OBFS=$(cat /opt/amnezia/hysteria2/obfs.key)

# файл токенов клиентов (строки "<client_id> <password>", пусто на старте) + внешняя аутентификация.
# auth.type=command вызывается на каждое подключение и грепает этот файл — add/revoke клиента
# = правка файла БЕЗ рестарта демона (как revoke у openvpn через crl).
: > /opt/amnezia/hysteria2/users
cat > /opt/amnezia/hysteria2/auth.sh <<'AUTH'
#!/bin/sh
# hysteria command-auth: $1=адрес клиента, $2=auth-строка (пароль). Печатаем client_id при совпадении.
id=$(awk -v p="$2" '$2==p{print $1; exit}' /opt/amnezia/hysteria2/users)
[ -n "$id" ] && { printf '%s' "$id"; exit 0; }
exit 1
AUTH
chmod +x /opt/amnezia/hysteria2/auth.sh

# masquerade: на любой неаутентифицированный запрос сервер отвечает как реальный HTTPS-сайт
# (проксирует $HYSTERIA_SNI) — активное зондирование видит обычный веб-хост.
cat > /opt/amnezia/hysteria2/config.yaml <<EOF
listen: :$HYSTERIA_PORT
tls:
  cert: /opt/amnezia/hysteria2/cert.crt
  key: /opt/amnezia/hysteria2/cert.key
obfs:
  type: salamander
  salamander:
    password: $HYSTERIA_OBFS
auth:
  type: command
  command: /opt/amnezia/hysteria2/auth.sh
masquerade:
  type: proxy
  proxy:
    url: https://$HYSTERIA_SNI/
    rewriteHost: true
EOF
