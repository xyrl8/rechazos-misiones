import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // En dev el backend corre en :8000; el frontend usa rutas /api/*.
      "/api": "http://127.0.0.1:8000",
    },
  },
});
