/**
 * Every route on the site, in one place (docs/react-site-plan.md §4, R9).
 *
 *   /                       Home: about the site, every league
 *   /matchday/              Every competition's fixtures this week
 *   /ratings/               Ratings across leagues
 *   /about/                 Method
 *   /{c}/                   Fixtures   (Observable: "This Gameweek")
 *   /{c}/gameweeks/         Results    (Observable: "Gameweeks")
 *   /{c}/table/             Table
 *   /{c}/track-record/      Record     (Observable: "Track Record")
 *   /{c}/ratings/           Ratings
 *
 * A cup (kind "cup" in leagues.json: the Champions League) has its own set:
 *
 *   /{c}/                   Fixtures
 *   /{c}/league-phase/      League phase
 *   /{c}/knockouts/         Knockouts
 *   /{c}/track-record/      Record
 *
 * League sections keep the old Observable site's paths, so old links and
 * bookmarks still work; only the labels are new. Pages are built for every
 * competition in leagues.json, so enabling one in the pipeline needs no
 * change here.
 */

import { href } from "./href";

export interface Section {
  key: "fixtures" | "results" | "table" | "record" | "ratings" | "league-phase" | "knockouts";
  label: string;
  /** Path under /{c}/ ("" for the league's front page). */
  path: string;
}

/** A domestic league's sections. */
export const SECTIONS: readonly Section[] = [
  { key: "fixtures", label: "Fixtures", path: "" },
  { key: "results", label: "Results", path: "gameweeks" },
  { key: "table", label: "Table", path: "table" },
  { key: "record", label: "Record", path: "track-record" },
  { key: "ratings", label: "Ratings", path: "ratings" },
];

/** A cup's sections (plan §4: Fixtures · League phase · Knockouts · Record). */
export const CUP_SECTIONS: readonly Section[] = [
  { key: "fixtures", label: "Fixtures", path: "" },
  { key: "league-phase", label: "League phase", path: "league-phase" },
  { key: "knockouts", label: "Knockouts", path: "knockouts" },
  { key: "record", label: "Record", path: "track-record" },
];

export type SectionKey = Section["key"];

export type CompetitionKind = "league" | "cup";

/** What a round is called: "Gameweek" in a league, "Matchday" in a cup. */
export function roundName(kind: CompetitionKind): string {
  return kind === "cup" ? "Matchday" : "Gameweek";
}

/** The sections a competition of this kind has. */
export function sectionsFor(kind: CompetitionKind): readonly Section[] {
  return kind === "cup" ? CUP_SECTIONS : SECTIONS;
}

/** The section with this key, if a competition of this kind has it. */
export function sectionByKey(kind: CompetitionKind, key: SectionKey): Section | undefined {
  return sectionsFor(kind).find((s) => s.key === key);
}

export interface SiteLink {
  key: "home" | "matchday" | "ratings" | "method";
  label: string;
  path: string;
}

/** Site-wide pages: the header nav (without Home) and the phone tab bar off league pages. */
export const SITE_LINKS: readonly SiteLink[] = [
  { key: "home", label: "Home", path: "" },
  { key: "matchday", label: "Matchday", path: "matchday" },
  { key: "ratings", label: "Ratings", path: "ratings" },
  { key: "method", label: "Method", path: "about" },
];

export type SiteKey = SiteLink["key"];

export function sectionByPath(path: string | undefined, kind: CompetitionKind = "league"): Section {
  const found = sectionsFor(kind).find((s) => s.path === (path ?? ""));
  if (!found) throw new Error(`No ${kind} section at "${path}"`);
  return found;
}

/** /{slug}/{section path}/ */
export function leagueHref(slug: string, section: Section = SECTIONS[0]!): string {
  return href(section.path ? `${slug}/${section.path}` : slug);
}

export function siteHref(link: SiteLink): string {
  return href(link.path);
}
