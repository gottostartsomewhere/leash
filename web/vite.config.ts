import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API is proxied rather than called cross-origin, so the browser sees one
// origin and the demo never depends on CORS behaving.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
