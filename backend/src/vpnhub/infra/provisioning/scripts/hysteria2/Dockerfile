FROM alpine:3.19
LABEL maintainer="vpn-hub"

ARG HYSTERIA_VERSION="app/v2.6.2"

RUN apk add --no-cache curl bash openssl ca-certificates iptables ip6tables dumb-init

RUN mkdir -p /opt/amnezia/hysteria2
RUN echo -e "#!/bin/bash\ntail -f /dev/null" > /opt/amnezia/start.sh
RUN chmod a+x /opt/amnezia/start.sh

RUN curl -L https://github.com/apernet/hysteria/releases/download/${HYSTERIA_VERSION}/hysteria-linux-amd64 \
      -o /usr/bin/hysteria; \
    chmod a+x /usr/bin/hysteria

# QUIC-тюнинг: увеличенные UDP-буферы (иначе hysteria логирует предупреждение и режет скорость)
RUN echo -e " \n\
  net.core.rmem_max = 16777216 \n\
  net.core.wmem_max = 16777216 \n\
  " | sed -e 's/^\s\+//g' | tee -a /etc/sysctl.conf

ENV TZ=UTC

ENTRYPOINT [ "dumb-init", "/opt/amnezia/start.sh" ]
