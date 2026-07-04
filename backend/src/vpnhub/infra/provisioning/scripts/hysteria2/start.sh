#!/bin/bash

# Launched every time the container starts (uploaded by the panel to /opt/amnezia/start.sh)

echo "Container startup"

iptables -A INPUT -i lo -j ACCEPT
iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -p icmp -j ACCEPT
# Hysteria2 слушает QUIC на UDP; TCP того же порта держим открытым для masquerade-фолбэка
iptables -A INPUT -p udp --dport $HYSTERIA_PORT -j ACCEPT
iptables -A INPUT -p tcp --dport $HYSTERIA_PORT -j ACCEPT
iptables -P INPUT DROP

ip6tables -A INPUT -i lo -j ACCEPT
ip6tables -A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
ip6tables -A INPUT -p ipv6-icmp -j ACCEPT
ip6tables -A INPUT -p udp --dport $HYSTERIA_PORT -j ACCEPT
ip6tables -P INPUT DROP

# kill daemon in case of restart
killall -KILL hysteria 2>/dev/null

# start daemon if configured
if [ -f /opt/amnezia/hysteria2/config.yaml ]; then (hysteria server -c /opt/amnezia/hysteria2/config.yaml &); fi

tail -f /dev/null
