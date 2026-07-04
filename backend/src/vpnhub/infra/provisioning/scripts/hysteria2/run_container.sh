# Run container (Hysteria2 = QUIC/UDP, серверу не нужен tun — это прокси, а не туннель на хосте)
sudo docker run -d \
--log-driver none \
--restart always \
--cap-add=NET_ADMIN \
-p $HYSTERIA_PORT:$HYSTERIA_PORT/udp \
--name $CONTAINER_NAME $CONTAINER_NAME
