import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

export default defineConfig({
  plugins: [react(), basicSsl()],
  server: {
    host: "0.0.0.0",
    port: 3000,
    strictPort: true,
    https: true,
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
