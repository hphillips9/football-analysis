/**
 * Data an island only needs in the browser (a chart's points), shipped as a
 * plain JSON block in the page instead of island props:
 *
 *   page    <script type="application/json" id="offsets-data" set:html={pageJson(points)} />
 *   island  const points = usePageData<OffsetPoint[]>("offsets-data");
 *
 * Astro serialises island props with a type tag around every value and
 * HTML-escapes them, which made /ratings/'s two history charts ~680 KB of
 * HTML; as a JSON block the same data is a fraction of that. The island
 * renders its skeleton on the server either way.
 */

import { useEffect, useState } from "react";

/** JSON safe to put inside <script>: no "</script>" or "<!--" can end it early. */
export function pageJson(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

/** The parsed JSON block with this id, once mounted (undefined on the server and before). */
export function usePageData<T>(id: string): T | undefined {
  const [data, setData] = useState<T>();

  useEffect(() => {
    const el = document.getElementById(id);
    if (!el?.textContent) {
      console.error(`No page data block #${id}`);
      return;
    }
    setData(JSON.parse(el.textContent) as T);
  }, [id]);

  return data;
}

const DAY_MS = 86_400_000;

/** "2025-11-02" + n days → ISO date. Dates in the compact series are day offsets from a base. */
export function addDays(base: string, days: number): string {
  return new Date(Date.parse(`${base}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

/** ISO date → whole days since `base`. */
export function daysSince(base: string, date: string): number {
  return Math.round((Date.parse(`${date}T00:00:00Z`) - Date.parse(`${base}T00:00:00Z`)) / DAY_MS);
}
