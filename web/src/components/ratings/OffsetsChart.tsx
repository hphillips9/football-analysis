/**
 * /ratings/: each league's baseline below the Premier League over time.
 * The legend sits under the chart; on a phone the end labels drop and the
 * page's table of current offsets carries the numbers.
 */

import { useMemo } from "react";

import { addDays, usePageData } from "../../lib/pageData";
import Legend from "../charts/Legend";
import PlotFigure from "../charts/PlotFigure";
import { leagueOffsets, type OffsetRow } from "../charts/specs";

/**
 * The offsets history, compact (the page's JSON block): one entry per
 * league per season, with a flat [day, offset, day, offset, ...] array,
 * days counted from `base`.
 */
export interface OffsetsData {
  base: string;
  lines: { div: string; season: string; points: number[] }[];
}

interface Props {
  /** Id of the page's JSON block with the OffsetsData. */
  dataId: string;
  leagues: { div: string; name: string; slot: number }[];
}

export default function OffsetsChart({ dataId, leagues }: Props) {
  const data = usePageData<OffsetsData>(dataId);
  const points: OffsetRow[] = useMemo(() => {
    if (!data) return [];
    const byDiv = new Map(leagues.map((l) => [l.div, l]));
    return data.lines.flatMap((line) => {
      const league = byDiv.get(line.div);
      const rows: OffsetRow[] = [];
      for (let i = 0; i < line.points.length; i += 2) {
        rows.push({
          date: addDays(data.base, line.points[i]!),
          season: line.season,
          div: line.div,
          name: league?.name ?? line.div,
          slot: league?.slot ?? 0,
          offset: line.points[i + 1]!,
        });
      }
      return rows;
    });
  }, [data, leagues]);
  const spec = useMemo(() => leagueOffsets(points), [points]);

  return (
    <PlotFigure
      spec={spec}
      ready={data != null}
      label={`Each league's offset below the Premier League over time, ${leagues.length} leagues`}
      height={340}
      compactHeight={280}
      caption={
        <Legend items={leagues.map((l) => ({ label: l.name, color: `var(--series-${l.slot + 1})`, shape: "line" as const }))} />
      }
    />
  );
}
