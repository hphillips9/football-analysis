import * as Plot from "npm:@observablehq/plot";

export const OUTCOME = {
  H: { label: "Home win", color: "#2563eb" },
  D: { label: "Draw", color: "#9ca3af" },
  A: { label: "Away win", color: "#dc2626" },
};

export const outcomeColor = {
  domain: ["H", "D", "A"],
  range: [OUTCOME.H.color, OUTCOME.D.color, OUTCOME.A.color],
  tickFormat: (d) => OUTCOME[d].label,
};

// Horizontal stacked H/D/A probability bars, one row per fixture.
export function probabilityBars(fixtures, { width } = {}) {
  const rows = fixtures.flatMap((f) => {
    const match = `${f.home} v ${f.away}`;
    return [
      { match, outcome: "H", prob: f.homeProb },
      { match, outcome: "D", prob: f.drawProb },
      { match, outcome: "A", prob: f.awayProb },
    ];
  });

  return Plot.plot({
    width,
    height: fixtures.length * 32 + 46,
    marginLeft: 200,
    x: { domain: [0, 100], label: "win probability (%)", grid: true },
    y: { label: null, domain: fixtures.map((f) => `${f.home} v ${f.away}`) },
    color: { ...outcomeColor, legend: true },
    marks: [
      Plot.barX(rows, {
        y: "match",
        x: "prob",
        fill: "outcome",
        order: ["H", "D", "A"],
        tip: true,
        title: (d) => `${OUTCOME[d.outcome].label}: ${d.prob}%`,
      }),
      Plot.ruleX([50], { strokeOpacity: 0.25 }),
    ],
  });
}

// Signed number with a + / − and fixed decimals.
export function signed(value, digits = 2) {
  if (value == null) return "—";
  return (value >= 0 ? "+" : "") + value.toFixed(digits);
}

export const resultName = { H: "Home", D: "Draw", A: "Away" };
