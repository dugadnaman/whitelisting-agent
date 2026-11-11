import type { Config } from "tailwindcss";

const accent = {
  50: "#fff7ed", 100: "#ffedd5", 200: "#fed7aa", 300: "#f3b77c",
  400: "#dc8e53", 500: "#bd612d", 600: "#a64c24", 700: "#8e3d20",
  800: "#73331e", 900: "#5f2c1d", 950: "#32160f",
};

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        blue: accent,
        indigo: accent,
        purple: accent,
        gray: {
          50: "#fafafa", 100: "#f4f4f5", 200: "#e4e4e7", 300: "#d4d4d8",
          400: "#a1a1aa", 500: "#71717a", 600: "#52525b", 700: "#3f3f46",
          800: "#27272a", 900: "#18181b", 950: "#09090b",
        },
      }
    },
  },
};

export default config;
