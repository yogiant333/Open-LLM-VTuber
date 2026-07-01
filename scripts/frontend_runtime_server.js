const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");

const host = process.env.FRONTEND_HOST || "0.0.0.0";
const port = Number(process.env.FRONTEND_PORT || "3000");
const distDir = path.resolve(process.env.FRONTEND_DIST || path.join(__dirname, "dist"));
const backendHost = process.env.BACKEND_HOST || "127.0.0.1";
const backendPort = Number(process.env.BACKEND_PORT || "18080");
const livetalkingHost = process.env.LIVETALKING_HOST || "127.0.0.1";
const livetalkingPort = Number(process.env.LIVETALKING_PORT || "18010");

const mimeTypes = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".wasm": "application/wasm",
  ".wav": "audio/wav",
  ".mp3": "audio/mpeg",
};

function stripPrefix(url, prefix) {
  const next = url.slice(prefix.length) || "/";
  return next.startsWith("/") ? next : `/${next}`;
}

function proxyHttp(req, res, targetHost, targetPort, rewritePath) {
  const headers = { ...req.headers, host: `${targetHost}:${targetPort}` };
  const proxyReq = http.request(
    {
      host: targetHost,
      port: targetPort,
      method: req.method,
      path: rewritePath,
      headers,
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
      proxyRes.pipe(res);
    },
  );

  proxyReq.on("error", (error) => {
    res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end(`Proxy request failed: ${error.message}`);
  });

  req.pipe(proxyReq);
}

function serveStatic(req, res) {
  const requestUrl = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  let pathname = decodeURIComponent(requestUrl.pathname);
  if (pathname.includes("\0")) {
    res.writeHead(400);
    res.end("Bad request");
    return;
  }

  let filePath = path.resolve(distDir, `.${pathname}`);
  if (!filePath.startsWith(distDir)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    filePath = path.join(distDir, "index.html");
  }

  fs.readFile(filePath, (error, data) => {
    if (error) {
      res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      res.end("Not found");
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { "content-type": mimeTypes[ext] || "application/octet-stream" });
    res.end(data);
  });
}

function rewriteUpgradeRequest(raw, pathOverride, targetHost, targetPort) {
  const text = raw.toString("latin1");
  const lines = text.split("\r\n");
  const first = lines[0].split(" ");
  first[1] = pathOverride;
  lines[0] = first.join(" ");

  for (let i = 1; i < lines.length; i += 1) {
    if (lines[i].toLowerCase().startsWith("host:")) {
      lines[i] = `Host: ${targetHost}:${targetPort}`;
      break;
    }
  }

  return Buffer.from(lines.join("\r\n"), "latin1");
}

function proxyWebSocket(req, socket, head, targetHost, targetPort, targetPath) {
  const upstream = net.connect(targetPort, targetHost, () => {
    const rawRequest = `${req.method} ${req.url} HTTP/${req.httpVersion}\r\n${
      Object.entries(req.headers)
        .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join("; ") : value}`)
        .join("\r\n")
    }\r\n\r\n`;
    upstream.write(rewriteUpgradeRequest(Buffer.from(rawRequest, "latin1"), targetPath, targetHost, targetPort));
    if (head.length) {
      upstream.write(head);
    }
    socket.pipe(upstream);
    upstream.pipe(socket);
  });

  upstream.on("error", () => socket.destroy());
  socket.on("error", () => upstream.destroy());
}

const server = http.createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify({ ok: true }));
    return;
  }

  if (req.url.startsWith("/livetalking/") || req.url === "/livetalking") {
    proxyHttp(req, res, livetalkingHost, livetalkingPort, stripPrefix(req.url, "/livetalking"));
    return;
  }

  if (req.url.startsWith("/client-ws")) {
    proxyHttp(req, res, backendHost, backendPort, req.url);
    return;
  }

  serveStatic(req, res);
});

server.on("upgrade", (req, socket, head) => {
  if (req.url.startsWith("/client-ws")) {
    proxyWebSocket(req, socket, head, backendHost, backendPort, req.url);
    return;
  }

  if (req.url.startsWith("/livetalking/") || req.url === "/livetalking") {
    proxyWebSocket(req, socket, head, livetalkingHost, livetalkingPort, stripPrefix(req.url, "/livetalking"));
    return;
  }

  socket.destroy();
});

if (!fs.existsSync(path.join(distDir, "index.html"))) {
  console.error(`Missing frontend dist: ${distDir}`);
  process.exit(1);
}

server.listen(port, host, () => {
  console.log(`Frontend runtime ready: http://${host}:${port}`);
  console.log(`Static dist: ${distDir}`);
  console.log(`Backend proxy: /client-ws -> ${backendHost}:${backendPort}`);
  console.log(`LiveTalking proxy: /livetalking -> ${livetalkingHost}:${livetalkingPort}`);
});
