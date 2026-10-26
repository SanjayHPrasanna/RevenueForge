import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Let teammates open your running app through a tunnel link (VS Code port forwarding, Cloudflare).
    allowedHosts: [".devtunnels.ms", ".trycloudflare.com", "localhost", "127.0.0.1"],
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
});
