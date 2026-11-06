/**
 * Static-data charts on the Table and Ratings pages, one island each:
 *
 *   ratings   V9  each club's Elo against the 1500 average
 *   places    V8  projected places gained / lost (wide screens only: the
 *                 page hydrates it with client:media and hides it on a
 *                 phone, where the projected table's Δ column takes over)
 */

import { useMemo } from "react";

import PlotFigure from "../charts/PlotFigure";
import { divergingHeight, placesMoved, ratingVsAverage, type MoveRow, type RatingRow } from "../charts/specs";

type Props = { league: string; leagueName: string } & (
  | { kind: "ratings"; clubs: RatingRow[] }
  | { kind: "places"; rows: MoveRow[] }
);

export default function LeagueChart(props: Props) {
  const data = props.kind === "ratings" ? props.clubs : props.rows;
  const spec = useMemo(
    () => (props.kind === "ratings" ? ratingVsAverage(props.clubs) : placesMoved(props.rows)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data],
  );

  return (
    <PlotFigure
      spec={spec}
      label={
        props.kind === "ratings"
          ? `${props.leagueName}: each club's Elo rating against the 1500 average`
          : `${props.leagueName}: places each club is projected to gain or lose by the season's end`
      }
      height={divergingHeight(data.length)}
      compactHeight={divergingHeight(data.length, true)}
      league={props.league}
    />
  );
}
