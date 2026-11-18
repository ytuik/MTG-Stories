import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  // In CI, VITE_BASE is "/<repository-name>/". Locally it is "/".
  base: process.env.VITE_BASE ?? "/",
  plugins: [react(), tailwindcss()],
});