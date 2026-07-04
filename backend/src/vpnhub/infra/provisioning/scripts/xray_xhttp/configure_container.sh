cd /opt/amnezia/xray
XRAY_CLIENT_ID=$(xray uuid) && echo $XRAY_CLIENT_ID > /opt/amnezia/xray/xray_uuid.key
XRAY_SHORT_ID=$(openssl rand -hex 8) && echo $XRAY_SHORT_ID > /opt/amnezia/xray/xray_short_id.key

# путь XHTTP — случайный, читается панелью для сборки vless://-ссылки
XRAY_XHTTP_PATH="/$(openssl rand -hex 6)" && echo $XRAY_XHTTP_PATH > /opt/amnezia/xray/xray_xhttp_path.key

KEYPAIR=$(xray x25519)
LINE_NUM=1
while IFS= read -r line; do
   if [[ $LINE_NUM -gt 1 ]]
      then
           IFS=":" read FIST XRAY_PUBLIC_KEY <<< "$line"
      else
      	   LINE_NUM=$((LINE_NUM + 1))
           IFS=":" read FIST XRAY_PRIVATE_KEY <<< "$line"
      fi
done <<< "$KEYPAIR"

XRAY_PRIVATE_KEY=$(echo $XRAY_PRIVATE_KEY | tr -d ' ')
XRAY_PUBLIC_KEY=$(echo $XRAY_PUBLIC_KEY | tr -d ' ')


echo $XRAY_PUBLIC_KEY > /opt/amnezia/xray/xray_public.key
echo $XRAY_PRIVATE_KEY > /opt/amnezia/xray/xray_private.key


# VLESS + Reality поверх XHTTP: транспорт xhttp (не tcp), поэтому у клиента НЕТ flow=vision
# (xtls-rprx-vision работает только с raw/tcp). Reality остаётся — маскировка под реальный сайт.
cat > /opt/amnezia/xray/server.json <<EOF
{
    "log": {
        "loglevel": "error"
    },
    "inbounds": [
        {
            "port": $XRAY_SERVER_PORT,
            "protocol": "vless",
            "settings": {
                "clients": [
                    {
                        "id": "$XRAY_CLIENT_ID"
                    }
                ],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "xhttp",
                "security": "reality",
                "realitySettings": {
                    "dest": "$XRAY_SITE_NAME:443",
                    "serverNames": [
                        "$XRAY_SITE_NAME"
                    ],
                    "privateKey": "$XRAY_PRIVATE_KEY",
                    "shortIds": [
                        "$XRAY_SHORT_ID"
                    ]
                },
                "xhttpSettings": {
                    "path": "$XRAY_XHTTP_PATH",
                    "mode": "auto"
                }
            }
        }
    ],
    "outbounds": [
        {
            "protocol": "freedom"
        }
    ]
}
EOF

