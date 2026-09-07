export default {
  title: "Premier League Football Predictor",

  pages: [
    { name: "This Gameweek", path: "/" },
    { name: "Gameweeks", path: "/gameweeks" },
    { name: "Track Record", path: "/track-record" },
    { name: "Ratings", path: "/ratings" },
    { name: "About", path: "/about" },
  ],

  root: "src",
  cleanUrls: true,
  head: '<meta name="color-scheme" content="light dark">',
  footer: "A hobby model. Predictions are not betting advice.",
};
