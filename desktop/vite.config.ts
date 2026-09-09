import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { readFileSync } from "node:fs";

const cargoManifest = readFileSync(new URL("./src-tauri/Cargo.toml", import.meta.url), "utf8");
const packageSection = cargoManifest.split(/^\[package\]\s*$/m)[1]?.split(/^\[/m)[0];
const appVersion = packageSection?.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
if (!appVersion) throw new Error("Cannot read desktop version from Cargo.toml");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(appVersion) },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: "127.0.0.1"
  },
  envPrefix: ["VITE_", "TAURI_"]
});
