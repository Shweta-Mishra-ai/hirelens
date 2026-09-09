import nextPlugin from "eslint-config-next";

const eslintConfig = [
  ...nextPlugin,
  {
    rules: {
      // eslint-plugin-react-hooks v6 (pulled in by the Next 16 upgrade)
      // adds this new, more opinionated rule aimed at React Compiler-style
      // code. It flags the standard "useCallback-wrapped async fetch,
      // invoked from a mount effect" pattern used throughout this app
      // (dashboard/teams/report/etc. loading their data) — even though the
      // actual setState calls happen after an `await`, not synchronously
      // during the effect's commit phase, which is what the rule is
      // actually meant to catch. Downgraded to a warning rather than
      // silenced entirely or force-restructuring ~10 legitimate call
      // sites into a less idiomatic shape for marginal benefit.
      "react-hooks/set-state-in-effect": "warn",
    },
  },
];

export default eslintConfig;
