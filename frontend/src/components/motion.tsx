/** Small presentation-only motion helpers: pointer tilt, scroll reveal and scroll progress.
 * No dependencies; everything switches off for touch screens and for people who prefer reduced motion. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import clsx from "clsx";

const reduced = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const finePointer = () => typeof window !== "undefined" && !!window.matchMedia?.("(hover: hover) and (pointer: fine)").matches;

/** Adds a gentle 3D tilt that follows the pointer. Use with the `tilt` (and optionally `tilt-glare`) classes. */
export function useTilt<T extends HTMLElement>(max = 6, rest: [number, number] = [0, 0]) {
  const ref = useRef<T>(null);
  const [rx0, ry0] = rest;
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--rx", `${rx0}deg`);
    el.style.setProperty("--ry", `${ry0}deg`);
    if (reduced() || !finePointer()) return;
    let raf = 0;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width;
      const y = (e.clientY - r.top) / r.height;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        el.dataset.active = "1";
        el.style.setProperty("--ry", `${(ry0 * 0.4 + (x - 0.5) * max * 2).toFixed(2)}deg`);
        el.style.setProperty("--rx", `${(rx0 * 0.4 + (0.5 - y) * max * 2).toFixed(2)}deg`);
        el.style.setProperty("--gx", `${(x * 100).toFixed(1)}%`);
        el.style.setProperty("--gy", `${(y * 100).toFixed(1)}%`);
      });
    };
    const leave = () => {
      cancelAnimationFrame(raf);
      el.dataset.active = "0";
      el.style.setProperty("--rx", `${rx0}deg`);
      el.style.setProperty("--ry", `${ry0}deg`);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
    };
  }, [max, rx0, ry0]);
  return ref;
}

/** Fades and lifts its content into place the first time it scrolls into view. */
export function Reveal({ children, className, delay = 0, as: Tag = "div" }: { children: ReactNode; className?: string; delay?: number; as?: any }) {
  const ref = useRef<HTMLElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduced() || typeof IntersectionObserver === "undefined") return setShown(true);
    const io = new IntersectionObserver(
      (es) => es.forEach((e) => e.isIntersecting && (setShown(true), io.disconnect())),
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <Tag ref={ref} data-shown={shown ? "1" : "0"} className={clsx("reveal", className)} style={delay ? { transitionDelay: `${delay}ms` } : undefined}>
      {children}
    </Tag>
  );
}

/** 0 → 1 as the element travels from the bottom of the viewport to `end` (fraction of viewport height from the top). */
export function useScrollProgress<T extends HTMLElement>(end = 0.25) {
  const ref = useRef<T>(null);
  const [p, setP] = useState(reduced() ? 1 : 0);
  useEffect(() => {
    if (reduced()) return;
    let raf = 0;
    const on = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const el = ref.current;
        if (!el) return;
        const r = el.getBoundingClientRect();
        const vh = window.innerHeight;
        const v = (vh - r.top) / (vh - vh * end);
        setP(Math.max(0, Math.min(1, v)));
      });
    };
    on();
    window.addEventListener("scroll", on, { passive: true });
    window.addEventListener("resize", on);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", on);
      window.removeEventListener("resize", on);
    };
  }, [end]);
  return [ref, p] as const;
}
