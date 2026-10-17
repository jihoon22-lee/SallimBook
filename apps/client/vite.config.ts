import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 18742,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:18741" },
  },
  build: { sourcemap: false },
});
