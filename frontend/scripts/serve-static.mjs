#!/usr/bin/env node
/**
 * Serve the static export (out/) the way the production hosts do, for local
 * checks and end-to-end tests: `npm run build && npm start`.
 *
 * `next start` cannot serve an `output: "export"` build, and the production
 * hosts (Netlify, Cloudflare Pages, Render) are not available locally. This
 * reproduces the parts of their behaviour the app depends on:
 *   - /route and /route/ both serve route/index.html (/route redirects);
 *   - unknown paths get 404.html with status 404;
 *   - the headers in public/_headers.
 * It is not meant to face the internet.
 *
 * Usage: node scripts/serve-static.mjs [port]   (default 3000, or $PORT)
 */
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)), "out");
const port = Number(process.argv[2] || process.env.PORT || 3000);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".map": "application/json",
};

/** "/_next/static/*" → RegExp. Only the `*` wildcard is used in _headers. */
function globToRegExp(glob) {
  const escaped = glob.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
  return new RegExp(`^${escaped}$`);
}

async function loadHeaderRules() {
  let text;
  try {
    text = await readFile(join(root, "_headers"), "utf8");
  } catch {
    return [];
  }
  const rules = [];
  let current = null;
  for (const raw of text.split("\n")) {
    if (!raw.trim() || raw.trim().startsWith("#")) continue;
    if (!/^\s/.test(raw)) {
      current = { match: globToRegExp(raw.trim()), headers: [] };
      rules.push(current);
    } else if (current) {
      const i = raw.indexOf(":");
      if (i > 0) current.headers.push([raw.slice(0, i).trim(), raw.slice(i + 1).trim()]);
    }
  }
  return rules;
}

async function isFile(path) {
  try {
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
}

const headerRules = await loadHeaderRules();

function applyHeaders(res, pathname) {
  for (const rule of headerRules) {
    if (rule.match.test(pathname)) for (const [k, v] of rule.headers) res.setHeader(k, v);
  }
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url || "/", "http://localhost");
  let pathname;
  try {
    pathname = decodeURIComponent(url.pathname);
  } catch {
    res.writeHead(400).end("Bad request");
    return;
  }
  applyHeaders(res, pathname);

  // Resolve inside out/ only: normalize() collapses "..", and the prefix check
  // refuses anything that still escapes.
  const full = normalize(join(root, pathname));
  if (full !== root && !full.startsWith(root + sep)) {
    res.writeHead(403).end("Forbidden");
    return;
  }

  let file = null;
  if (await isFile(full)) file = full;
  else if (await isFile(join(full, "index.html"))) {
    if (!pathname.endsWith("/")) {
      res.writeHead(301, { Location: `${url.pathname}/${url.search}` }).end();
      return;
    }
    file = join(full, "index.html");
  }

  if (!file) {
    const body = await readFile(join(root, "404.html")).catch(() => "Not found");
    res.writeHead(404, { "Content-Type": TYPES[".html"] }).end(body);
    return;
  }

  const body = await readFile(file);
  res.writeHead(200, { "Content-Type": TYPES[extname(file)] || "application/octet-stream" });
  res.end(req.method === "HEAD" ? undefined : body);
});

if (!(await isFile(join(root, "index.html")))) {
  console.error(`No build found in ${root}. Run \`npm run build\` first.`);
  process.exit(1);
}
server.listen(port, () => console.log(`Serving ${root} on http://localhost:${port}`));
