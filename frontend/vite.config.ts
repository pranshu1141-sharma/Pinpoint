import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: Number(process.env.PORT) || 5173,
    // PINPOINT_API_URL points the dev proxy at an API on another port when 8000 is taken
    proxy: { "/api": process.env.PINPOINT_API_URL || "http://127.0.0.1:8000" },
  },
});
