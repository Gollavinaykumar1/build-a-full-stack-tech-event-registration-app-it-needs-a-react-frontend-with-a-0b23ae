import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: "/build-a-full-stack-tech-event-registration-app-it-needs-a-react-frontend-with-a-0b23ae/",
  build: { outDir: "dist", assetsDir: "assets" },
  server: { port: 3000 },
});
