# ESP32-C3 Super Mini Optimization Guide

WireClaw was designed for ESP32-C6 and ESP32-S3 (with PSRAM). Running on the
ESP32-C3 Super Mini (~400KB SRAM, no PSRAM) requires specific optimizations.

## The Problem

The C3 cannot sustain two network connections simultaneously when one uses TLS:

- **WiFiClientSecure** to `api.telegram.org:443` consumes ~55-70KB of heap
  (mbedTLS buffers, certificate store, SSL handshake state)
- The LLM HTTP request body is ~20KB (system prompt + tools + conversation)
- Combined: ~90KB + runtime allocations = heap exhaustion

## Architecture: Telegram Proxy

The solution is a plain-HTTP proxy on your LAN server:

```
C3 (WiFiClient) -> [HTTP :9443] -> Proxy Server -> [TLS :443] -> api.telegram.org
```

The C3 connects to the proxy using `WiFiClient` (no TLS, ~0KB overhead) instead of
`WiFiClientSecure` (~55KB saved). The proxy handles TLS to Telegram.

### Setup

1. Copy `scripts/telegram-proxy.py` to your server:

```bash
sudo mkdir -p /opt/telegram-proxy
sudo cp scripts/telegram-proxy.py /opt/telegram-proxy/
```

2. Install systemd service (optional):

```bash
sudo cp scripts/telegram-proxy.service /etc/systemd/system/
sudo systemctl enable telegram-proxy
sudo systemctl start telegram-proxy
```

3. Open firewall port:

```bash
sudo ufw allow 9443 comment "Telegram proxy for WireClaw C3"
```

4. Configure the C3 to point to the proxy instead of `api.telegram.org`:

```json
{
  "telegram_token": "your-bot-token",
  "telegram_chat_id": "your-chat-id"
}
```

The firmware automatically routes Telegram requests to the proxy host/port
(configured in `src/main.cpp` — edit `TG_HOST` and `TG_PORT` for your network).

## Memory Optimizations

These are applied in `platformio.ini` and source code:

### 1. Lazy WiFiClientSecure

`WiFiClientSecure` is heap-allocated only when HTTPS is needed (pointer +
`new`/`delete`). Plain HTTP uses `WiFiClient` (stack-allocated, ~0KB).

**Saves:** ~55KB when not using HTTPS

### 2. mbedTLS Buffer Sizes

```ini
-DCONFIG_MBEDTLS_SSL_IN_CONTENT_LEN=2048
-DCONFIG_MBEDTLS_SSL_OUT_CONTENT_LEN=2048
```

Reduces mbedTLS I/O buffers from 16KB to 2KB each.

**Saves:** ~28KB per direction

### 3. Static Buffer Sizing

| Buffer | Stock | C3 Optimized |
|--------|-------|-------------|
| LLM request body | 20KB | 20KB |
| LLM response content | 4KB | 2KB |
| Tool calls JSON | 4KB | 2KB |
| HTTP wire buffer | 24.5KB | 24.5KB |

### 4. Single-Buffer HTTP Request

Headers + body are assembled into one buffer and sent in a single `write()` call.
Prevents TCP framing issues that caused Ollama to RST connections.

### 5. Explicit DNS

```cpp
WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE,
            IPAddress(8,8,8,8), IPAddress(1,1,1,1));
```

Fixes intermittent DNS failures on some networks.

### 6. TCP TIME_WAIT Delay

A 3-second delay between closing the Telegram connection and opening the LLM
connection lets the LWIP stack settle.

## Known Issues

- **Config file must be valid JSON.** macOS/iOS often auto-convert straight
  quotes to smart/curly quotes (`"` → `"`). Use a heredoc:
  ```bash
  cat > data/config.json << 'EOF'
  { "wifi_ssid": "YourNetwork" }
  EOF
  ```
- **Always run `uploadfs` after `upload`** to bake config.json and
  system_prompt.txt onto LittleFS. Firmware-only upload leaves stale config.

## Partition Table

The C3 needs a 4MB flash chip. The default partition table includes:
- Factory app: ~1.2MB
- LittleFS: ~1.5MB (for config, system prompt, memory, history)

## Build Commands

```bash
pio run -e esp32-c3 -t upload --upload-port /dev/tty.usbmodem11401
pio run -e esp32-c3 -t uploadfs --upload-port /dev/tty.usbmodem11401
```

Adjust the upload port to match your system (`/dev/ttyACM0` on Linux,
`/dev/tty.usbmodem*` on macOS).