import { describe, expect, it } from "vitest";

import { wholePercents } from "./probabilities";

const sum = (p: { H: number; D: number; A: number }) => p.H + p.D + p.A;

describe("wholePercents", () => {
  it("rounds to whole numbers that add up to 100", () => {
    // Plain rounding gives 55 + 23 + 22 = 100 here...
    expect(wholePercents({ H: 54.9, D: 23.3, A: 21.8 })).toEqual({ H: 55, D: 23, A: 22 });
    // ...but 33 + 33 + 33 = 99 here, and 51 + 25 + 25 = 101 here
    expect(sum(wholePercents({ H: 33.4, D: 33.3, A: 33.3 }))).toBe(100);
    expect(wholePercents({ H: 50.5, D: 24.5, A: 25 })).toEqual({ H: 51, D: 24, A: 25 });
  });

  it("gives ties to home, then draw", () => {
    expect(wholePercents({ H: 100 / 3, D: 100 / 3, A: 100 / 3 })).toEqual({ H: 34, D: 33, A: 33 });
  });

  it("scales inputs that don't sum to 100", () => {
    expect(wholePercents({ H: 0.5, D: 0.25, A: 0.25 })).toEqual({ H: 50, D: 25, A: 25 });
  });

  it("copes with zeros and nonsense", () => {
    expect(wholePercents({ H: 0, D: 0, A: 0 })).toEqual({ H: 0, D: 0, A: 0 });
    expect(wholePercents({ H: 100, D: 0, A: -3 })).toEqual({ H: 100, D: 0, A: 0 });
  });

  it("adds up to 100 for every real-looking split", () => {
    for (let h = 0; h <= 100; h += 0.7) {
      for (let d = 0; d <= 100 - h; d += 1.3) {
        expect(sum(wholePercents({ H: h, D: d, A: 100 - h - d }))).toBe(100);
      }
    }
  });
});
