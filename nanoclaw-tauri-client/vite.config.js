import { defineConfig } from "vite";

// Vite config tuned for Tauri:
// - fixed dev port (must match tauri.conf.json -> build.devUrl)
// - don't clear the screen so Rust build errors stay visible
// - ignore src-tauri so file changes there don't trigger a frontend reload
export default defineConfig({
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    target: ["es2021", "chrome100", "safari13"],
    minify: "esbuild",
    sourcemap: !!process.env.TAURI_DEBUG,
  },
});
