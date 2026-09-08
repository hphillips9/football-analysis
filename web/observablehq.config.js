export default {
  title: "Premier League Football Predictor",

  pages: [
    { name: "This Gameweek", path: "/" },
    { name: "Gameweeks", path: "/gameweeks" },
    { name: "League Table", path: "/table" },
    { name: "Track Record", path: "/track-record" },
    { name: "Ratings", path: "/ratings" },
    { name: "About", path: "/about" },
  ],

  root: "src",
  // Framework emits relative URLs, so the site works unchanged from the
  // /football-analysis/ subpath on GitHub Pages.
  preserveExtension: false,
  head: '<meta name="color-scheme" content="light dark">',
  footer: "A hobby model. Predictions are not betting advice.",
};
