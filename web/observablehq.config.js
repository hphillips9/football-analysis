export default {
  title: "Brian The Football Brain",

  // Left-hand nav. Home doubles as "this gameweek".
  pages: [
    { name: "This Gameweek", path: "/" },
    { name: "Track Record", path: "/track-record" },
    { name: "The Model", path: "/model" },
  ],

  root: "src",
  cleanUrls: true,
  head: '<meta name="color-scheme" content="light dark">',
  footer: "Brian The Football Brain — a hobby model. Not betting advice.",
};
