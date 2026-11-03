import { readFileSync } from "node:fs";

// The competitions the pipeline runs (written by src/export_web.py from the
// registry in src/competitions.py). Each gets its own pages under /<slug>/.
const { competitions } = JSON.parse(
  readFileSync(new URL("./src/data/leagues.json", import.meta.url), "utf-8")
);

const COMPETITION_PAGES = [
  { name: "This Gameweek", page: "" },
  { name: "Gameweeks", page: "gameweeks" },
  { name: "League Table", page: "table" },
  { name: "Track Record", page: "track-record" },
  { name: "Ratings", page: "ratings" },
];

export default {
  title: "Football Predictor",

  pages: [
    { name: "This Week", path: "/" },
    ...competitions.map((c, i) => ({
      name: c.name,
      collapsible: true,
      open: i === 0,
      pages: COMPETITION_PAGES.map((p) => ({ name: p.name, path: `/${c.slug}/${p.page}` })),
    })),
    { name: "About", path: "/about" },
  ],

  // Fills web/src/[comp]/*.md once per competition
  dynamicPaths: competitions.flatMap((c) => COMPETITION_PAGES.map((p) => `/${c.slug}/${p.page}`)),

  root: "src",
  // Framework emits relative URLs, so the site works unchanged from the
  // /football-analysis/ subpath on GitHub Pages.
  preserveExtension: false,
  head: '<meta name="color-scheme" content="light dark">',
  footer: "A hobby model. Predictions are not betting advice.",
};
