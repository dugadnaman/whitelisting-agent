import type { Config } from "tailwindcss";

const accent = {
  50: "#f3f2fc", 100: "#e9e7f9", 200: "#d5d1f2", 300: "#b5aee8",
  400: "#9286db", 500: "#7162ca", 600: "#5948b2", 700: "#493994",
  800: "#3d3179", 900: "#332b62", 950: "#201a40",
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
          50: "#f7f7f5", 100: "#f0f0ed", 200: "#e2e2dc", 300: "#cecec7",
          400: "#95958b", 500: "#6c6d64", 600: "#53564e", 700: "#41443d",
          800: "#2f332d", 900: "#20251f", 950: "#111510",
        },
      }
    },
  },
};

export default config;
