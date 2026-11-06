// Link check on the built site (P7-11; plan §7 "subpath/trailing slashes").
//
//   node scripts/check-links.mjs        (runs at the end of `npm run build`)
//
// Reads every .html page and .css file in the build output and checks each
// internal reference:
// - it is under the site's base path (astro.config.mjs `base`), so nothing
//   points at the domain root or at the Observable site by accident;
// - a page link ends in "/" (the directory build format: Pages answers
//   /e0/table with a 301) and the page exists;
// - an asset (script, stylesheet, font, icon, island) exists;
// - a #fragment exists on its page.
// External links (http:, mailto:, data:) aren't fetched. Exits 1 on any
// broken reference, so CI fails the build.

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const { default: config } = await import("../astro.config.mjs");
const base = (config.base ?? "/").replace(/\/?$/, "/");
const outDir = resolve(root, config.outDir ?? "dist");

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const files = walk(outDir);
const pages = files.filter((f) => f.endsWith(".html"));
const sheets = files.filter((f) => f.endsWith(".css"));

// The URL path a built file is served at
const urlOf = (file) => base + relative(outDir, file).split("\\").join("/");
const fileOf = (path) => join(outDir, decodeURIComponent(path.slice(base.length)));

const ids = new Map();
const idsOf = (file) => {
  if (!ids.has(file)) {
    const html = readFileSync(file, "utf8");
    ids.set(file, new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])));
  }
  return ids.get(file);
};

const ATTRS = /\s(href|src|srcset|poster|component-url|renderer-url|before-hydration-url)="([^"]*)"/g;
const problems = [];
let checked = 0;

function check(from, raw, kind) {
  const ref = raw.replaceAll("&amp;", "&").trim();
  if (!ref || /^(https?:|mailto:|tel:|data:|blob:|javascript:)/i.test(ref)) return;
  checked++;
  const fromUrl = urlOf(from);
  const say = (why) => problems.push(`${relative(outDir, from)}: ${kind} "${raw}" ${why}`);

  const url = new URL(ref, `https://site${fromUrl}`);
  const path = decodeURIComponent(url.pathname);
  const samePage = ref.startsWith("#");

  if (!samePage && !path.startsWith(base)) return say(`is outside the base path ${base}`);

  let target;
  if (samePage) {
    target = from;
  } else if (extname(path) === "") {
    // A page: directory format, so it must end in "/" and have an index.html
    if (!path.endsWith("/")) return say('is a page link without a trailing "/"');
    target = join(fileOf(path), "index.html");
    if (!existsSync(target)) return say("points at a page that doesn't exist");
  } else {
    target = fileOf(path);
    if (!existsSync(target)) return say("points at a file that doesn't exist");
  }

  const fragment = url.hash.slice(1);
  if (fragment && target.endsWith(".html") && !idsOf(target).has(decodeURIComponent(fragment))) {
    say(`has no element with id "${fragment}"`);
  }
}

for (const page of pages) {
  const html = readFileSync(page, "utf8");
  for (const [, attr, value] of html.matchAll(ATTRS)) {
    if (attr === "srcset") {
      for (const part of value.split(",")) check(page, part.trim().split(/\s+/)[0] ?? "", attr);
    } else {
      check(page, value, attr);
    }
  }
}
for (const sheet of sheets) {
  const css = readFileSync(sheet, "utf8");
  for (const [, , value] of css.matchAll(/url\(\s*(["']?)([^"')]+)\1\s*\)/g)) check(sheet, value, "url()");
}

if (problems.length) {
  console.error(`Link check: ${problems.length} broken of ${checked} references in ${pages.length} pages:`);
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log(`Link check: ${checked} references in ${pages.length} pages and ${sheets.length} stylesheets, all OK (base ${base})`);
