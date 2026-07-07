# Local AI Chat App

A dependency-free Node.js web app for chatting with a local llama.cpp server.

## 1. Start llama.cpp

Run your Qwen3 8B model with llama.cpp's OpenAI-compatible server:

```powershell
.\llama-server.exe -m C:\path\to\qwen3-8b-q4_k_m.gguf -c 4096 -t 8 --host 127.0.0.1 --port 8080
```

For CPU-only machines, use a smaller quant such as `Q4_K_M`, keep context modest, and set `-t` near your physical CPU core count.

## 2. Start this app

```powershell
cd C:\Users\User\Documents\Codex\2026-07-07\i\outputs\llama-chat-app
npm start
```

Open:

```text
http://127.0.0.1:3000
```

## Configuration

```powershell
$env:PORT="3000"
$env:LLAMA_URL="http://127.0.0.1:8080"
$env:LLAMA_MODEL="local-qwen3-8b"
npm start
```

## What is included

- Local username/password registration and login
- Secure password hashing with PBKDF2
- Cookie-based sessions
- Per-user chat list
- Per-user chat history saved in `data/db.json`
- Token-by-token streaming from llama.cpp to the browser

This is good for local development. Before exposing it on the internet, move storage to a real database, add HTTPS, rate limits, CSRF protection, and a persistent session store.
