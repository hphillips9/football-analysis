/**
 * An internal link under the site's base path.
 *
 *   href()            -> "/football-analysis/"
 *   href("e0/table")  -> "/football-analysis/e0/table/"
 *   href("/about")    -> "/football-analysis/about/"
 *
 * Every internal link goes through this, so the base path is one setting
 * (`base` in astro.config.mjs). Links end in "/" to match the directory
 * build format.
 */

const BASE = import.meta.env.BASE_URL.replace(/\/?$/, "/");

export function href(path = ""): string {
  const trimmed = path.replace(/^\/+/, "").replace(/\/+$/, "");
  return trimmed ? `${BASE}${trimmed}/` : BASE;
}
