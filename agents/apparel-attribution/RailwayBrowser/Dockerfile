FROM lscr.io/linuxserver/chromium:latest

# Loopback DevTools is forwarded only onto private interface addresses below.
ENV RESTART_APP=true \
    CHROME_CLI="--remote-debugging-address=127.0.0.1 --remote-debugging-port=9223 --disable-dev-shm-usage about:blank" \
    HARDEN_DESKTOP=true \
    SELKIES_ENABLE_SHARING="false|locked" \
    SELKIES_ENABLE_COLLAB="false|locked"

RUN apt-get update \
    && apt-get install -y --no-install-recommends socat python3 iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Root build context; do not copy old environment files or browser profiles.
COPY agents/apparel-attribution/RailwayBrowser/browser-start.py /usr/local/bin/browser-start
COPY agents/apparel-attribution/RailwayBrowser/cdp-forward /custom-services.d/cdp-forward
RUN chmod 0755 /usr/local/bin/browser-start /custom-services.d/cdp-forward

VOLUME ["/config"]
# A live socat listener is not proof Chromium has started or survived a crash.
HEALTHCHECK --interval=15s --timeout=10s --start-period=90s --retries=3 \
    CMD ["/usr/local/bin/browser-start", "--healthcheck"]
# No EXPOSE for 9222/9223. Never configure a public TCP proxy for either port.
# Start the guard BEFORE /init so failed validation cannot leave GUI services running.
ENTRYPOINT ["/usr/local/bin/browser-start"]
