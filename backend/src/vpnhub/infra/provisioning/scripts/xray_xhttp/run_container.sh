# Run container
sudo docker run -d \
--privileged \
--log-driver none \
--restart always \
--cap-add=NET_ADMIN \
-p $XRAY_SERVER_PORT:$XRAY_SERVER_PORT/tcp \
--name $CONTAINER_NAME $CONTAINER_NAME

sudo docker network connect amnezia-dns-net $CONTAINER_NAME

# Create tun device if not exist
sudo docker exec -i $CONTAINER_NAME bash -c 'mkdir -p /dev/net; if [ ! -c /dev/net/tun ]; then mknod /dev/net/tun c 10 200; fi'
