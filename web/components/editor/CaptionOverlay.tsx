"use client";

import * as React from "react";
import { chunk, type CaptionFont, type CaptionStyle, type CaptionWord } from "@/lib/captions";

const hexA = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

/** CSS for caption text, matching what captions.ass() makes libass draw at a video height. */
export function captionTextStyle(style: CaptionStyle, fonts: CaptionFont[], height: number): React.CSSProperties {
  const font = fonts.find((f) => f.id === style.font);
  const size = (style.size / 100) * height;                  // the ASS size
  const outline = (size * style.outline) / 100;
  const shadow = (size * style.shadow) / 100;
  return {
    fontFamily: `"cap-${style.font}", sans-serif`,
    fontSize: size * (font?.em_scale ?? 0.7),
    lineHeight: 1.25,
    color: style.color,
    textTransform: style.uppercase ? "uppercase" : undefined,
    whiteSpace: "nowrap",
    ...(style.box
      ? {
          background: hexA(style.box_color, style.box_opacity),
          padding: `${Math.max(size * 0.18, 4) * 0.6}px ${Math.max(size * 0.18, 4)}px`,
          boxDecorationBreak: "clone",
          WebkitBoxDecorationBreak: "clone",
        }
      : {
          WebkitTextStroke: outline ? `${outline * 2}px ${style.outline_color}` : undefined,
          paintOrder: "stroke fill",
        }),
    textShadow: shadow ? `${shadow}px ${shadow}px 0 rgba(0,0,0,0.6)` : undefined,
  };
}

/** Live caption preview over a video box of width x height, at time t. */
export function CaptionOverlay({
  words,
  style,
  fonts,
  t,
  width,
  height,
}: {
  words: CaptionWord[];
  style: CaptionStyle;
  fonts: CaptionFont[];
  t: number;
  width: number;
  height: number;
}) {
  const chunks = React.useMemo(() => chunk(words, style), [words, style]);
  const ci = chunks.findIndex((c) => c.start <= t && t < c.end);
  if (ci < 0 || !height) return null;
  const c = chunks[ci];
  let active = 0;
  c.words.forEach((i, k) => {
    if (k === 0 || words[i].start <= t) active = k;
  });
  const anim = style.animation;
  const parts = c.words.map((i, k) => {
    const on = k === active && (anim === "highlight" || anim === "highlight_pop");
    const hidden = anim === "word_by_word" && k > active;
    return (
      <span
        key={i}
        style={{
          color: on ? style.highlight : undefined,
          visibility: hidden ? "hidden" : undefined,
          // a real size change, so the line reflows like libass font scaling (a transform would overlap)
          fontSize: on && anim === "highlight_pop" ? "1.15em" : undefined,
        }}
      >
        {words[i].text}
      </span>
    );
  });
  const withSpaces = (xs: React.ReactNode[]) => xs.flatMap((x, k) => (k ? [" ", x] : [x]));
  const two = style.lines === 2 && parts.length >= 4;
  const mid = Math.ceil(parts.length / 2);
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        key={`${ci}-${anim}`}
        className="absolute left-1/2 text-center"
        style={{
          top: `${style.position}%`,
          transform: "translate(-50%,-50%)",
          maxWidth: width * 0.88,
          animation: anim === "pop" ? "cap-pop 160ms ease-out" : anim === "fade" ? "cap-fade 120ms ease-out" : undefined,
        }}
      >
        <span style={captionTextStyle(style, fonts, height)}>
          {two ? (
            <>
              {withSpaces(parts.slice(0, mid))}
              <br />
              {withSpaces(parts.slice(mid))}
            </>
          ) : (
            withSpaces(parts)
          )}
        </span>
      </div>
      <style>{`@keyframes cap-pop{0%{transform:translate(-50%,-50%) scale(.8)}56%{transform:translate(-50%,-50%) scale(1.08)}100%{transform:translate(-50%,-50%) scale(1)}}@keyframes cap-fade{from{opacity:0}to{opacity:1}}`}</style>
    </div>
  );
}
