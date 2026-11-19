// ESLint flat config. `next lint` was removed in Next.js 16, so linting runs
// through the ESLint CLI (`npm run lint`), using Next's own rule set.
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const config = [
  { ignores: [".next/**", "out/**", "node_modules/**", "coverage/**", "next-env.d.ts"] },
  ...nextCoreWebVitals,
];

export default config;
