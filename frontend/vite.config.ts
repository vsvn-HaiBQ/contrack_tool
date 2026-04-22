import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    port: 8888,
    host: "0.0.0.0",
    proxy: {
      "/api": {
        target: "http://localhost:8009",
        changeOrigin: true
      }
    }
  }
});
