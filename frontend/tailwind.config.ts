import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        blue: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#1E90FF", // Vibrant Dodger Blue
          600: "#0078F2", // Deep Vibrant Dodger Blue
          700: "#005BC4",
          800: "#00479E",
          900: "#00387D",
          950: "#002354",
        },
        indigo: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#1E90FF",
          600: "#0078F2",
          700: "#005BC4",
          800: "#00479E",
          900: "#00387D",
          950: "#002354",
        },
        purple: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#1E90FF",
          600: "#0078F2",
          700: "#005BC4",
          800: "#00479E",
          900: "#00387D",
        }
      }
    },
  },
};

export default config;
