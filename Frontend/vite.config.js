import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/login": "http://127.0.0.1:5000",
      "/register": "http://127.0.0.1:5000",
      "/logout": "http://127.0.0.1:5000",
      "/me": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
      },
      "/lobbies": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
      },
      "/socket.io": {
        target: "http://127.0.0.1:5000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
