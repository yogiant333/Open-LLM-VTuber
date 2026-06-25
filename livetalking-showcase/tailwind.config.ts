import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cyanStage: "#20D6C7",
        goldStage: "#FFD84A",
        inkStage: "#030405",
      },
      borderRadius: {
        stage: "8px",
      },
    },
  },
  plugins: [],
} satisfies Config;
