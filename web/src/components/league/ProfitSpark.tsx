/**
 * V2 on the league page (plan §3): running simulated profit. In the side
 * panel (or on a phone) it's an 80 px sparkline; the final value is shown
 * as large text by the page.
 */

import { useMemo } from "react";

import { signed } from "../../lib/format";
import type { BankrollPoint } from "../../lib/schema";
import PlotFigure from "../charts/PlotFigure";
import { runningProfit } from "../charts/specs";

interface Props {
  points: BankrollPoint[];
  leagueName: string;
  league: string;
}

export default function ProfitSpark({ points, leagueName, league }: Props) {
  const spec = useMemo(() => runningProfit(points), [points]);
  const final = points.at(-1)?.cumulative ?? 0;

  return (
    <PlotFigure
      spec={spec}
      label={`${leagueName}: running simulated profit over ${points.length} priced picks, now ${signed(final)} units`}
      height={180}
      compactHeight={80}
      league={league}
    />
  );
}
