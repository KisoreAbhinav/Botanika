// Simple inline SVG line icons: square geometry, ~1.8 px strokes, no emoji.

const strokeProps = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
};

export function LeafMark({ size = 30 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <g {...strokeProps}>
        <path d="M16 28 C 16 18, 16 12, 16 4" />
        <path d="M16 26 C 8 24, 5 18, 6 11 C 12 12, 15 16, 16 22" />
        <path d="M16 22 C 17 16, 20 12, 26 11 C 27 18, 24 24, 16 26" />
        <path d="M9 16 L 14 18" />
        <path d="M23 16 L 18 18" />
      </g>
    </svg>
  );
}

export function ScanIcon({ size = 36 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden="true">
      <g {...strokeProps}>
        <path d="M4 12 V 4 H 12" />
        <path d="M24 4 H 32 V 12" />
        <path d="M32 24 V 32 H 24" />
        <path d="M12 32 H 4 V 24" />
        <path d="M18 9 V 27" />
        <path d="M11 14 C 14 13, 15 15, 15 18 C 15 21, 14 23, 11 22" />
        <path d="M25 14 C 22 13, 21 15, 21 18 C 21 21, 22 23, 25 22" />
      </g>
    </svg>
  );
}

export function LibraryIcon({ size = 36 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden="true">
      <g {...strokeProps}>
        <rect x="5" y="5" width="26" height="26" />
        <path d="M5 13 H 31" />
        <path d="M13 13 V 31" />
        <path d="M21 21 H 27" />
        <path d="M21 25 H 27" />
      </g>
    </svg>
  );
}

export function WeedIcon({ size = 36 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden="true">
      <g {...strokeProps}>
        <path d="M18 31 V 14" />
        <path d="M18 20 C 12 19, 9 15, 9 9 C 15 10, 18 14, 18 20" />
        <path d="M18 20 C 24 19, 27 15, 27 9 C 21 10, 18 14, 18 20" />
        <path d="M6 31 H 30" />
      </g>
    </svg>
  );
}

export function AskIcon({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <g {...strokeProps}>
        <rect x="3" y="4" width="18" height="13" />
        <path d="M8 21 L 12 17 L 16 21" />
        <path d="M8.5 9 C 8.5 7.5, 10 6.5, 12 6.5 C 14 6.5, 15.5 7.5, 15.5 9 C 15.5 11, 12 11, 12 13" />
        <path d="M12 15.2 V 15.4" />
      </g>
    </svg>
  );
}

export function CameraIcon({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <g {...strokeProps}>
        <rect x="3" y="7" width="18" height="13" />
        <path d="M8 7 L 10 4 H 14 L 16 7" />
        <circle cx="12" cy="13" r="3.6" />
      </g>
    </svg>
  );
}

export function Foliage() {
  return (
    <svg width="190" height="150" viewBox="0 0 190 150" aria-hidden="true">
      <g {...strokeProps} strokeWidth="1.4">
        <path d="M0 150 C 30 130, 60 120, 90 118" />
        <path d="M0 132 C 24 120, 46 116, 66 112" />
        <path d="M8 150 C 40 140, 78 132, 120 132" />
        <path d="M30 141 C 28 130, 34 122, 46 118" />
        <path d="M60 130 C 60 120, 68 114, 80 112" />
        <path d="M96 128 C 98 118, 106 112, 118 112" />
        <path d="M18 122 C 24 116, 32 114, 40 116" />
        <path d="M50 118 C 58 112, 66 110, 74 112" />
      </g>
    </svg>
  );
}
