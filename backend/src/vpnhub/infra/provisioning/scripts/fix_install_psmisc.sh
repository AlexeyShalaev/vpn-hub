if pm=$(which apt-get 2>/dev/null || command -v apt-get 2>/dev/null); then inst="-yq install"; upd="-yq update"; dist="debian";\
elif pm=$(which dnf 2>/dev/null || command -v dnf 2>/dev/null); then inst="-yq install"; upd="-yq check-update"; dist="fedora";\
elif pm=$(which yum 2>/dev/null || command -v yum 2>/dev/null); then inst="-y -q install"; upd="-y -q check-update"; dist="centos";\
elif pm=$(which zypper 2>/dev/null || command -v zypper 2>/dev/null); then inst="-nq install"; upd="-nq refresh"; dist="suse";\
elif pm=$(which pacman 2>/dev/null || command -v pacman 2>/dev/null); then inst="-S --noconfirm --noprogressbar --quiet"; upd="-Sy"; dist="archlinux";\
else echo "FIX_PSMISC_NO_PM"; exit 1;\
fi;\
echo $LANG | grep -qE '^(en_US.UTF-8|C.UTF-8|C)$' || export LC_ALL=C;\
if [ "$dist" = "debian" ]; then export DEBIAN_FRONTEND=noninteractive; fi;\
if sudo -n sh -c 'command -v fuser > /dev/null 2>&1' || command -v fuser > /dev/null 2>&1; then echo "FIX_PSMISC_OK"; exit 0; fi;\
sudo -n $pm $upd 2>/dev/null || true;\
sudo -n $pm $inst psmisc 2>&1 || true;\
if sudo -n sh -c 'command -v fuser > /dev/null 2>&1' || command -v fuser > /dev/null 2>&1; then echo "FIX_PSMISC_OK"; else echo "FIX_PSMISC_FAILED"; fi
