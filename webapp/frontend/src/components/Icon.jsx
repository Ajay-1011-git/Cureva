/**
 * The icon set.
 *
 * Flat, single-colour, line-only, one stroke weight, no filled variants —
 * the design treats icons as the one place a vivid blue is allowed, so they
 * have to look like one family or the colour stops reading as deliberate.
 *
 * Every glyph is drawn on a 24-grid and inherits `currentColor`, so a caller
 * sets the colour by setting text colour. Default size is 16px because almost
 * every use is inline beside 12-14px text; the accent is reserved for glyphs
 * under 24px and nothing here is bigger.
 */

const PATHS = {
  mic: (
    <>
      <rect x="9" y="2.5" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3.5" />
    </>
  ),
  send: <path d="M3.5 12 20.5 4l-8 16.5-1.9-6.6z" />,
  check: <path d="M4.5 12.5 9.5 17.5 19.5 6.5" />,
  close: <path d="M6 6l12 12M18 6 6 18" />,
  chevron: <path d="m6 9.5 6 6 6-6" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  flag: (
    <>
      <path d="M5.5 21V3.5" />
      <path d="M5.5 4.5h11l-2.2 4 2.2 4h-11z" />
    </>
  ),
  pulse: <path d="M2.5 12h4l2.5-7 4 14 2.5-7h6" />,
  graph: (
    <>
      <circle cx="6" cy="6.5" r="2.6" />
      <circle cx="18" cy="9" r="2.6" />
      <circle cx="10.5" cy="18.5" r="2.6" />
      <path d="M8.3 8 15.6 8.4M16.6 11.3l-4.4 5M8.8 15.9 7 9.1" />
    </>
  ),
  scales: (
    <>
      <path d="M12 3.5v17M7 20.5h10" />
      <path d="M4 7.5h16" />
      <path d="M4 7.5 1.5 14h5zM20 7.5 17.5 14h5" />
    </>
  ),
  shield: <path d="M12 2.8 20 6v6c0 4.4-3.3 7.9-8 9.2C7.3 19.9 4 16.4 4 12V6z" />,
  refresh: (
    <>
      <path d="M20 5.5v5h-5" />
      <path d="M19.4 10.5A7.8 7.8 0 1 0 20 14.6" />
    </>
  ),
  play: <path d="M8 5.2 19 12 8 18.8z" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="8.8" />
      <path d="M12 7v5.3l3.4 2" />
    </>
  ),
  document: (
    <>
      <path d="M6.5 2.8h7l4.5 4.5v13.9h-11.5z" />
      <path d="M13.3 2.8v4.8h4.7M9.3 12.5h5.4M9.3 16h5.4" />
    </>
  ),
  sparkle: (
    <>
      <path d="M12 2.8 13.9 9 20 11l-6.1 2L12 19.2 10.1 13 4 11l6.1-2z" />
      <path d="M18.8 17.2 19.6 19.8 22 20.6 19.6 21.4 18.8 24" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="3.9" />
      <path d="M4.6 20.5a7.6 7.6 0 0 1 14.8 0" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3.4 22 20.6H2z" />
      <path d="M12 9.6v4.8M12 17.4v.05" />
    </>
  ),
  arrowRight: <path d="M4.5 12h15M13.5 6l6 6-6 6" />,
  layers: (
    <>
      <path d="m12 3 9 4.8-9 4.8-9-4.8z" />
      <path d="m3.6 12.4 8.4 4.5 8.4-4.5" />
    </>
  ),
  filter: <path d="M3.2 5.3h17.6l-6.9 8v6.4l-3.8-2.3v-4.1z" />,
}

export default function Icon({ name, size = 16, strokeWidth = 1.6, className = '', ...rest }) {
  const glyph = PATHS[name]
  if (!glyph) return null
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {glyph}
    </svg>
  )
}

/**
 * The Cureva mark: a stylised pulse enclosed in a rounded shield — the two
 * ideas the product is about, a vital sign and something standing guard over
 * it. Drawn rather than imported so it inherits currentColor like every other
 * glyph and never fights the monochrome rule.
 */
export function BrandMark({ size = 26 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <rect x="1.2" y="1.2" width="29.6" height="29.6" rx="9.4"
            fill="var(--color-obsidian)" />
      <path d="M6.6 16.6h4.1l2.3-6.2 3.9 12.3 2.4-6.1h6.1"
            stroke="var(--color-surgical-blue)" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
