import { describe, expect, it } from "vitest";

import { byDay, mostConfident, numberWord, pickProb, rearranged } from "./fixtures";

const f = (kickoff: string, prediction: "H" | "D" | "A", homeProb: number, drawProb: number, awayProb: number) => ({
  kickoff,
  prediction,
  homeProb,
  drawProb,
  awayProb,
});

describe("fixtures helpers", () => {
  const list = [
    f("2026-11-07T15:00:00", "H", 55, 25, 20),
    f("2026-11-06T20:00:00", "A", 20, 22, 58),
    f("2026-11-07T12:30:00", "D", 33, 34, 33),
  ];

  it("pickProb is the probability of the pick", () => {
    expect(list.map(pickProb)).toEqual([55, 58, 34]);
  });

  it("mostConfident takes the highest pick probability", () => {
    expect(mostConfident(list)?.kickoff).toBe("2026-11-06T20:00:00");
    expect(mostConfident([])).toBeUndefined();
  });

  it("byDay groups by date in kick-off order", () => {
    const days = byDay(list);
    expect(days.map((d) => d.date)).toEqual(["2026-11-06", "2026-11-07"]);
    expect(days[1]!.fixtures.map((x) => x.kickoff)).toEqual(["2026-11-07T12:30:00", "2026-11-07T15:00:00"]);
  });

  it("numberWord uses words up to ten", () => {
    expect([numberWord(7), numberWord(10), numberWord(12)]).toEqual(["seven", "ten", "12"]);
  });
});

describe("rearranged", () => {
  it("flags games more than 4 days from the gameweek's median kick-off", () => {
    const games = ["2026-10-03T15:00:00", "2026-10-04T14:00:00", "2026-10-04T16:30:00", "2026-10-29T19:45:00"].map(
      (kickoff) => ({ kickoff }),
    );
    expect([...rearranged(games)]).toEqual([3]);
  });

  it("flags nothing in a normal weekend, or an empty list", () => {
    expect(rearranged([{ kickoff: "2026-10-03T15:00:00" }, { kickoff: "2026-10-06T20:00:00" }]).size).toBe(0);
    expect(rearranged([]).size).toBe(0);
  });
});
