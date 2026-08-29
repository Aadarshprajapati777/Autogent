import type { Config } from "tailwindcss";
export default {
  darkMode: ["class"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#09090b",
        panel: "#121216",
        line: "#28282e",
        mint: "#75e0bd",
        ink: "#f5f4f8",
      },
      boxShadow: { glow: "0 0 32px rgba(117,224,189,.12)" },
    },
  },
  plugins: [],
} satisfies Config;
