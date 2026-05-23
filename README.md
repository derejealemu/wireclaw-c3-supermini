# WireClaw on ESP32-C3 Super Mini 

**WireClaw** is an AI agent that lives on a microcontroller. It was designed for ESP32-C6, ESP32-S3, and full-size ESP32-C3 dev boards — chips with PSRAM.

**This repo is the story of running it on an ESP32-C3 Super Mini.**

The $2 board. 400KB of SRAM. No PSRAM. No second chance.

WireClaw already supports the big boards. **We wanted to make it run on the smallest one possible.**

---

---

## The Problem

The C3 Super Mini has ~400KB SRAM. The two things WireClaw needs to do simultaneously — polling Telegram (TLS) and calling an LLM (HTTP) — each need their own network connection. mbedTLS for Telegram alone eats ~55-70KB of heap with default buffers. Add a 20KB LLM request payload, the device registry, the rule engine, the web server, conversation history, and runtime allocations, and you hit the wall hard.

The stock WireClaw didn't even boot on C3. It would either crash during WiFi setup or OOM when Telegram tried to connect.

## The Solutions

### 1. Telegram Proxy (the big one)

The C3 can't sustain `WiFiClientSecure` to `api.telegram.org:443` alongside anything else. Full stop.

**What we did:** Deployed a Python HTTP proxy on a LAN server. The C3 talks to it over plain HTTP (zero TLS overhead). The proxy forwards requests to Telegram over TLS.

```
C3 (WiFiClient) → HTTP :9443 → Proxy Server → TLS :443 → api.telegram.org
```

The proxy script lives at `scripts/telegram-proxy.py` — 60 lines, no dependencies. Installable as a systemd service.

**Saved:** ~55KB of heap.

### 2. Lazy WiFiClientSecure

Stock WireClaw allocates `WiFiClientSecure` as a static object — it exists whether you use TLS or not. On C3, we made it a pointer, heap-allocated only when HTTPS is actually needed. Plain HTTP (proxy, Ollama) uses `WiFiClient` (zero heap overhead).

### 3. mbedTLS Buffer Trimming

Stock mbedTLS uses 16KB I/O buffers per direction. On C3, we capped them to 2KB via `platformio.ini`:

```ini
-DCONFIG_MBEDTLS_SSL_IN_CONTENT_LEN=2048
-DCONFIG_MBEDTLS_SSL_OUT_CONTENT_LEN=2048
```

**Saved:** ~28KB per direction.

### 4. Static Buffer Sizing

| Buffer | C3 Value |
|--------|----------|
| LLM request body | 20KB |
| LLM response content | 2KB |
| Tool calls JSON | 2KB |

### 5. Single-Buffer HTTP

Headers and body assembled in one buffer, sent in one `write()` call. Prevents the TCP framing issues where Ollama would RST connections mid-stream.

### 6. Explicit DNS

```cpp
WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE,
            IPAddress(8,8,8,8), IPAddress(1,1,1,1));
```

Fixed intermittent DNS failures that were killing the boot sequence.

### 7. TCP TIME_WAIT Delay

After closing the Telegram polling connection, the C3 waits 3 seconds before opening the LLM connection. Gives the LWIP stack time to settle.

---

## The Bug We Found

WireClaw's `TOOLS_JSON` is a C++ raw string literal wrapped in `R"JSON([...])JSON"` — the `[` and `]` are already part of the string. But `buildRequest()` wrapped it with `[%s]`, producing `"tools":[[...]]`. Double-wrapped arrays. Ollama's Go backend would reject this with:

```
cannot unmarshal array into Go struct field
ChatCompletionRequest.tools of type api.Tool
```

**Fix:** Changed `"tools":[%s]` to `"tools":%s`. The brackets were already there.

---

## The Gotchas

### Smart Quotes

macOS auto-converts straight quotes to curly Unicode quotes (`"` → `"`). JSON parsers refuse them. Use a heredoc:

```bash
cat > data/config.json << 'EOF'
{ "wifi_ssid": "YourNetwork" }
EOF
```

### uploadfs

Flashing firmware (`-t upload`) doesn't bake `data/config.json` onto the ESP32's LittleFS. You need a separate step:

```bash
pio run -e esp32-c3 -t upload
pio run -e esp32-c3 -t uploadfs
```

---

## The Code

The full source is right here in this repo.

---

## Quick Start

### Prerequisites

- ESP32-C3 Super Mini with 4MB flash
- PlatformIO (`pip install platformio`)
- A LAN server for the Telegram proxy (or skip Telegram and use serial)

### Setup

```bash
git clone https://github.com/derejealemu/wireclaw-c3-supermini
cd wireclaw-c3-supermini
```

**Config:**

```bash
cat > data/config.json << 'EOF'
{
  "wifi_ssid": "YourNetwork",
  "wifi_pass": "YourPassword",
  "model": "gemma4:e4b",
  "api_base_url": "http://192.168.1.100:11434/v1/chat/completions",
  "telegram_token": "your:bot_token",
  "telegram_chat_id": "your_chat_id",
  "telegram_cooldown": "3",
  "timezone": "CET-1CEST-2,M3.5.0/2,M10.5.0/3"
}
EOF
```

**Telegram proxy (on your LAN server):**

```bash
cp scripts/telegram-proxy.py /opt/telegram-proxy/
python3 /opt/telegram-proxy/telegram-proxy.py --port 9443
# Or systemd:
sudo cp scripts/telegram-proxy.service /etc/systemd/system/
sudo systemctl enable --now telegram-proxy
```

**Firewall:**

```bash
sudo ufw allow 9443
```

**Build and flash:**

```bash
pio run -e esp32-c3 -t upload --upload-port /dev/tty.usbmodem11401
pio run -e esp32-c3 -t uploadfs --upload-port /dev/tty.usbmodem11401
```

**Talk to it.** Open your serial monitor (115200 baud) or send a message to your Telegram bot. WireClaw responds with tool calls — reading sensors, flipping GPIOs, setting automation rules.

---

## License

MIT — same as WireClaw. See [LICENSE](LICENSE).

---

*WireClaw already runs on the big boards. Now it runs on the smallest one too.*
