import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";

const certDir = new URL("./certs/", import.meta.url);
const keyPath = new URL("dev-key.pem", certDir);
const certPath = new URL("dev-cert.pem", certDir);

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3001,
    strictPort: true,
    https: {
      key: fs.readFileSync(keyPath),
      cert: fs.readFileSync(certPath),
    },
    proxy: {
      "/client-ws": {
        target: "ws://127.0.0.1:18080",
        ws: true,
      },
      "/livetalking": {
        target: "http://127.0.0.1:18010",
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/livetalking/, ""),
      },
    },
  },
});
