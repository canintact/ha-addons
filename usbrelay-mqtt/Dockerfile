# ===== Stage 1: Build usbrelay binary =====
FROM alpine:3.20 AS build
RUN apk add --no-cache build-base git coreutils hidapi-dev libusb-dev argp-standalone
WORKDIR /src
RUN git clone --depth=1 https://github.com/darrylb123/usbrelay.git .
RUN make LDFLAGS="-largp" && strip usbrelay

# ===== Stage 2: Runtime =====
FROM alpine:3.20
RUN apk add --no-cache python3 py3-pip hidapi libusb tini
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN python3 -m venv /venv
ENV PATH="/venv/bin:${PATH}"
RUN pip install --no-cache-dir fastapi uvicorn paho-mqtt

COPY --from=build /src/usbrelay /usr/local/bin/usbrelay
COPY --from=build /src/libusbrelay.so.1.2 /usr/lib/libusbrelay.so.1.2
RUN ln -s /usr/lib/libusbrelay.so.1.2 /usr/lib/libusbrelay.so.1 && \
    ln -s /usr/lib/libusbrelay.so.1   /usr/lib/libusbrelay.so

WORKDIR /opt/app
COPY app.py /opt/app/app.py
COPY run.sh /run.sh
RUN chmod +x /run.sh

VOLUME ["/data"]
EXPOSE 8000
ENTRYPOINT ["/sbin/tini","-g","--"]
CMD ["/run.sh"]
