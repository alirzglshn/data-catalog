FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends postfix \
    && rm -rf /var/lib/apt/lists/*

COPY main.cf /etc/postfix/main.cf

EXPOSE 25

CMD ["postfix", "start-fg"]
