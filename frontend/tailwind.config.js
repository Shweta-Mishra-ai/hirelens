/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        bg:     "#060F1A",
        surf:   "#0A1525",
        card:   "#0E1C2E",
        border: "#172840",
        blue:   "#1D6AFF",
        bluel:  "#4B8DFF",
        cyan:   "#06B6D4",
        cyanl:  "#22D3EE",
      },
      fontFamily: {
        mono: ["'JetBrains Mono'", "'Fira Code'", "monospace"],
      },
    },
  },
  plugins: [],
};
