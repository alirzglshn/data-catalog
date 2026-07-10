# a small postfix relay that django can talk to over smtp, this
# exists to satisfy the "send a notification email via postfix"
# requirement without depending on an external mail provider
#
# note: when EMAIL_HOST in .env is pointed at an external provider
# such as smtp.gmail.com instead of this container, django bypasses
# this relay entirely and talks to that provider directly, this
# container still builds and starts in that case, it is just unused
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends postfix \
    && rm -rf /var/lib/apt/lists/*

COPY main.cf /etc/postfix/main.cf

EXPOSE 25

CMD ["postfix", "start-fg"]
