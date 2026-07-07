import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync, createReadStream } from "node:fs";
import { join, extname, normalize } from "node:path";
import { randomBytes, pbkdf2Sync, timingSafeEqual } from "node:crypto";

const PORT = Number(process.env.PORT || 3000);
const HOST = process.env.HOST || "127.0.0.1";
const LLAMA_URL = process.env.LLAMA_URL || "http://127.0.0.1:8080";
const MODEL = process.env.LLAMA_MODEL || "local-qwen3-8b";
const DATA_DIR = join(process.cwd(), "data");
const DB_PATH = join(DATA_DIR, "db.json");
const PUBLIC_DIR = join(process.cwd(), "public");

const jsonHeaders = { "content-type": "application/json; charset=utf-8" };
const sessions = new Map();
const MAX_TOKENS = Number(process.env.MAX_TOKENS || 256);
const FIRST_TOKEN_TIMEOUT_MS = Number(process.env.FIRST_TOKEN_TIMEOUT_MS || 180000);

async function ensureDb() {
  await mkdir(DATA_DIR, { recursive: true });
  if (!existsSync(DB_PATH)) {
    await writeFile(DB_PATH, JSON.stringify({ users: [], chats: [] }, null, 2));
  }
}

async function readDb() {
  await ensureDb();
  return JSON.parse(await readFile(DB_PATH, "utf8"));
}

async function writeDb(db) {
  await writeFile(DB_PATH, JSON.stringify(db, null, 2));
}

function send(res, status, body, headers = {}) {
  res.writeHead(status, { ...jsonHeaders, ...headers });
  res.end(JSON.stringify(body));
}

async function bodyJson(req) {
  let raw = "";
  for await (const chunk of req) raw += chunk;
  if (!raw) return {};
  return JSON.parse(raw);
}

function parseCookies(req) {
  return Object.fromEntries(
    (req.headers.cookie || "")
      .split(";")
      .map((cookie) => cookie.trim().split("="))
      .filter(([key, value]) => key && value)
  );
}

function hashPassword(password, salt = randomBytes(16).toString("hex")) {
  const hash = pbkdf2Sync(password, salt, 210000, 32, "sha256").toString("hex");
  return `${salt}:${hash}`;
}

function verifyPassword(password, stored) {
  const [salt, hash] = stored.split(":");
  const attempted = hashPassword(password, salt).split(":")[1];
  return timingSafeEqual(Buffer.from(hash, "hex"), Buffer.from(attempted, "hex"));
}

function currentUser(req) {
  const sid = parseCookies(req).sid;
  return sid ? sessions.get(sid) : null;
}

function requireUser(req, res) {
  const user = currentUser(req);
  if (!user) {
    send(res, 401, { error: "Not signed in" });
    return null;
  }
  return user;
}

function publicFile(pathname) {
  const requested = pathname === "/" ? "/index.html" : pathname;
  const fullPath = normalize(join(PUBLIC_DIR, requested));
  if (!fullPath.startsWith(PUBLIC_DIR)) return null;
  return fullPath;
}

function serveStatic(req, res, pathname) {
  const path = publicFile(pathname);
  if (!path || !existsSync(path)) return false;
  const types = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8"
  };
  res.writeHead(200, { "content-type": types[extname(path)] || "application/octet-stream" });
  createReadStream(path).pipe(res);
  return true;
}

function sanitizeMessages(messages) {
  return messages
    .filter((msg) => ["system", "user", "assistant"].includes(msg.role) && typeof msg.content === "string")
    .map((msg) => ({ role: msg.role, content: msg.content.slice(0, 12000) }));
}

async function streamLlama(messages, res) {
  res.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-cache, no-transform",
    connection: "keep-alive"
  });
  res.write(`data: ${JSON.stringify({ status: "Connected. Sending prompt to llama.cpp..." })}\n\n`);

  const controller = new AbortController();
  let firstTokenTimer = setTimeout(() => {
    controller.abort(new Error("Timed out waiting for the first token from llama.cpp."));
  }, FIRST_TOKEN_TIMEOUT_MS);

  let upstream;
  try {
    upstream = await fetch(`${LLAMA_URL}/v1/chat/completions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        model: MODEL,
        messages,
        stream: true,
        temperature: 0.7,
        top_p: 0.9,
        max_tokens: MAX_TOKENS
      })
    });
  } catch (error) {
    clearTimeout(firstTokenTimer);
    res.write(`data: ${JSON.stringify({ error: `Could not reach llama.cpp at ${LLAMA_URL}. ${error.message}` })}\n\n`);
    res.end();
    return "";
  }

  if (!upstream.ok || !upstream.body) {
    clearTimeout(firstTokenTimer);
    const text = await upstream.text();
    res.write(`data: ${JSON.stringify({ error: text || `llama.cpp returned ${upstream.status}` })}\n\n`);
    res.end();
    return "";
  }

  const reader = upstream.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let assistant = "";
  let sawFirstToken = false;
  let lastStatusAt = Date.now();

  res.write(`data: ${JSON.stringify({ status: "llama.cpp is processing the prompt. CPU-only can take a while..." })}\n\n`);

  while (true) {
    let result;
    try {
      result = await reader.read();
    } catch (error) {
      clearTimeout(firstTokenTimer);
      res.write(`data: ${JSON.stringify({ error: error.message || "llama.cpp stream stopped." })}\n\n`);
      res.end();
      return assistant;
    }
    const { done, value } = result;
    if (done) break;
    if (!sawFirstToken && Date.now() - lastStatusAt > 5000) {
      lastStatusAt = Date.now();
      res.write(`data: ${JSON.stringify({ status: "Still waiting for the first token from llama.cpp..." })}\n\n`);
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (!data || data === "[DONE]") continue;
      let json;
      try {
        json = JSON.parse(data);
      } catch {
        continue;
      }
      const choice = json.choices?.[0] || {};
      const delta =
        choice.delta?.content ||
        choice.delta?.reasoning_content ||
        choice.message?.content ||
        choice.content ||
        "";
      if (delta) {
        if (!sawFirstToken) clearTimeout(firstTokenTimer);
        sawFirstToken = true;
        assistant += delta;
        res.write(`data: ${JSON.stringify({ delta })}\n\n`);
      }
    }
  }

  clearTimeout(firstTokenTimer);
  if (!sawFirstToken) {
    res.write(`data: ${JSON.stringify({ error: "llama.cpp finished without sending text. Try a shorter prompt, lower -c, or restart llama-server." })}\n\n`);
  }
  res.write(`data: ${JSON.stringify({ done: true, assistant })}\n\n`);
  res.end();
  return assistant;
}

async function handleApi(req, res, pathname) {
  if (pathname === "/api/register" && req.method === "POST") {
    const { username, password } = await bodyJson(req);
    if (!username || !password || password.length < 6) {
      return send(res, 400, { error: "Use a username and password of at least 6 characters." });
    }
    const db = await readDb();
    const cleanName = username.trim().toLowerCase();
    if (db.users.some((user) => user.username === cleanName)) {
      return send(res, 409, { error: "That username already exists." });
    }
    const user = { id: randomBytes(12).toString("hex"), username: cleanName, passwordHash: hashPassword(password) };
    db.users.push(user);
    await writeDb(db);
    const sid = randomBytes(24).toString("hex");
    sessions.set(sid, { id: user.id, username: user.username });
    return send(res, 201, { user: { id: user.id, username: user.username } }, {
      "set-cookie": `sid=${sid}; HttpOnly; SameSite=Lax; Path=/`
    });
  }

  if (pathname === "/api/login" && req.method === "POST") {
    const { username, password } = await bodyJson(req);
    const db = await readDb();
    const user = db.users.find((item) => item.username === String(username || "").trim().toLowerCase());
    if (!user || !verifyPassword(password || "", user.passwordHash)) {
      return send(res, 401, { error: "Invalid username or password." });
    }
    const sid = randomBytes(24).toString("hex");
    sessions.set(sid, { id: user.id, username: user.username });
    return send(res, 200, { user: { id: user.id, username: user.username } }, {
      "set-cookie": `sid=${sid}; HttpOnly; SameSite=Lax; Path=/`
    });
  }

  if (pathname === "/api/logout" && req.method === "POST") {
    const sid = parseCookies(req).sid;
    if (sid) sessions.delete(sid);
    return send(res, 200, { ok: true }, { "set-cookie": "sid=; Max-Age=0; Path=/" });
  }

  if (pathname === "/api/me" && req.method === "GET") {
    return send(res, 200, { user: currentUser(req) });
  }

  const user = requireUser(req, res);
  if (!user) return;

  if (pathname === "/api/chats" && req.method === "GET") {
    const db = await readDb();
    const chats = db.chats
      .filter((chat) => chat.userId === user.id)
      .map(({ id, title, updatedAt }) => ({ id, title, updatedAt }))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    return send(res, 200, { chats });
  }

  if (pathname === "/api/chats" && req.method === "POST") {
    const db = await readDb();
    const chat = {
      id: randomBytes(12).toString("hex"),
      userId: user.id,
      title: "New chat",
      messages: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    db.chats.push(chat);
    await writeDb(db);
    return send(res, 201, { chat });
  }

  const chatMatch = pathname.match(/^\/api\/chats\/([^/]+)$/);
  if (chatMatch && req.method === "GET") {
    const db = await readDb();
    const chat = db.chats.find((item) => item.id === chatMatch[1] && item.userId === user.id);
    if (!chat) return send(res, 404, { error: "Chat not found." });
    return send(res, 200, { chat });
  }

  if (pathname === "/api/chat/stream" && req.method === "POST") {
    const { chatId, messages } = await bodyJson(req);
    const safeMessages = sanitizeMessages(messages || []);
    const assistant = await streamLlama(safeMessages, res);

    const db = await readDb();
    const chat = db.chats.find((item) => item.id === chatId && item.userId === user.id);
    if (chat) {
      chat.messages = [...safeMessages, { role: "assistant", content: assistant }];
      const firstUser = chat.messages.find((msg) => msg.role === "user");
      chat.title = firstUser ? firstUser.content.slice(0, 42) : "New chat";
      chat.updatedAt = new Date().toISOString();
      await writeDb(db);
    }
    return;
  }

  send(res, 404, { error: "Not found." });
}

createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (url.pathname.startsWith("/api/")) {
      await handleApi(req, res, url.pathname);
    } else if (!serveStatic(req, res, url.pathname)) {
      send(res, 404, { error: "Not found." });
    }
  } catch (error) {
    if (!res.headersSent) send(res, 500, { error: error.message || "Server error." });
    else res.end();
  }
}).listen(PORT, HOST, () => {
  console.log(`App running at http://${HOST}:${PORT}`);
  console.log(`Using llama.cpp server at ${LLAMA_URL}`);
});
