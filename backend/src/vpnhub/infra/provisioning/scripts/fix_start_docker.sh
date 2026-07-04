echo $LANG | grep -qE '^(en_US.UTF-8|C.UTF-8|C)$' || export LC_ALL=C;\
if [ "$(sudo -n systemctl is-active docker 2>/dev/null)" = "active" ]; then echo "FIX_DOCKER_ACTIVE"; exit 0; fi;\
sudo -n systemctl enable --now docker 2>/dev/null || sudo -n systemctl start docker 2>/dev/null || true;\
sleep 3;\
if [ "$(sudo -n systemctl is-active docker 2>/dev/null)" = "active" ]; then echo "FIX_DOCKER_ACTIVE"; else echo "FIX_DOCKER_FAILED"; sudo -n journalctl -u docker --no-pager -n 20 2>/dev/null || true; fi
