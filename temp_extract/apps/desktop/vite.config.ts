import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Fixed port that matches the CORS allow-list in the backend
// (app/main.py) and src-tauri/tauri.conf.json's devUrl.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
});
