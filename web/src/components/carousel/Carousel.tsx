/**
 * Small multiples that become a swipe carousel on a phone (plan §3 V11, R6):
 *
 *   wide (>= 600 px of container)   a 2-column grid, no dots
 *   narrow                          one slide per view, CSS scroll-snap,
 *                                   page dots underneath
 *
 * Done with a container query, so the server HTML is already right and
 * nothing shifts on hydration. The dots are buttons (aria-current on the
 * slide in view); the track is a focusable, labelled region, so arrow keys
 * scroll it too.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

import styles from "./Carousel.module.css";

export interface Slide {
  key: string;
  /** Short name, for the dot and the slide's label ("2024/25"). */
  title: string;
  content: ReactNode;
}

interface Props {
  /** What the carousel holds, e.g. "Simulated profit by season". */
  label: string;
  slides: Slide[];
}

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export default function Carousel({ label, slides }: Props) {
  const track = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);

  // The slide most in view is the active dot
  useEffect(() => {
    const root = track.current;
    if (!root) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(Number((entry.target as HTMLElement).dataset.index));
        }
      },
      { root, threshold: 0.6 },
    );
    root.querySelectorAll<HTMLElement>("[data-index]").forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, [slides]);

  // A new set of slides (another competition) starts at the first
  useEffect(() => {
    track.current?.scrollTo({ left: 0 });
    setActive(0);
  }, [slides]);

  const show = (index: number) => {
    const root = track.current;
    const slide = root?.querySelector<HTMLElement>(`[data-index="${index}"]`);
    if (!root || !slide) return;
    root.scrollTo({ left: slide.offsetLeft - root.offsetLeft, behavior: reducedMotion() ? "auto" : "smooth" });
  };

  return (
    <div className={styles.carousel}>
      <div ref={track} className={styles.track} role="region" aria-roledescription="carousel" aria-label={label} tabIndex={0}>
        {slides.map((s, i) => (
          <div
            key={s.key}
            className={styles.slide}
            data-index={i}
            role="group"
            aria-roledescription="slide"
            aria-label={`${i + 1} of ${slides.length}: ${s.title}`}
          >
            {s.content}
          </div>
        ))}
      </div>
      {slides.length > 1 && (
        <div className={styles.dots}>
          {slides.map((s, i) => (
            <button
              key={s.key}
              type="button"
              aria-label={`Show ${s.title}`}
              aria-current={i === active || undefined}
              onClick={() => show(i)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
