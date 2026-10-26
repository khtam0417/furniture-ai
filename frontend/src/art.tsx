// Original, code-native drawings (no external assets). Decorative only: they show no real apartment.

export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 24 24" aria-hidden>
      <rect x="2" y="2" width="20" height="20" fill="none" stroke="#fff" strokeWidth="1.6" />
      <path d="M2 13h9V2M11 13v9" fill="none" stroke="#fff" strokeWidth="1.2" />
      <rect x="14" y="5" width="5" height="7" fill="#9fc0e8" />
    </svg>
  );
}

const CHARCOAL = "#25313a";
const TEAL = "#0f766e";
const TINT = "#e6f4f2";

export function HomeIllustration() {
  return (
    <svg viewBox="0 0 520 360" role="img" aria-label="Illustration: an architectural floor plan with furniture drawn in blue">
      <defs>
        <pattern id="hg" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M20 0H0V20" fill="none" stroke="#25313a" strokeOpacity="0.07" strokeWidth="1" />
        </pattern>
        <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" stroke="#7c8690" strokeWidth="1.2" />
        </pattern>
      </defs>
      <rect width="520" height="360" fill="#f8f9fa" />
      <rect width="520" height="360" fill="url(#hg)" />
      {/* walls */}
      <g fill="none" stroke={CHARCOAL} strokeWidth="6" strokeLinecap="square">
        <path d="M30 30H490V330H30Z" />
        <path d="M250 30V150M250 200V330" />
        <path d="M30 200H120M170 200H250" />
        <path d="M390 30V110" />
      </g>
      {/* door swings */}
      <g fill="none" stroke={TEAL} strokeWidth="1.4">
        <path d="M120 200A50 50 0 0 1 170 150" strokeDasharray="3 3" />
        <line x1="120" y1="200" x2="120" y2="150" />
        <path d="M250 150A50 50 0 0 1 300 200" strokeDasharray="3 3" />
      </g>
      {/* kitchen counter (fixed) */}
      <rect x="392" y="36" width="94" height="22" fill="url(#hatch)" stroke="#7c8690" />
      {/* bedroom furniture */}
      <g stroke={CHARCOAL} strokeWidth="1.5">
        <rect x="50" y="48" width="96" height="124" fill={TINT} />
        <rect x="56" y="54" width="84" height="26" fill="#fff" />
        <rect x="152" y="48" width="30" height="26" fill={TINT} />
        <rect x="196" y="48" width="44" height="22" fill={TINT} />
        <rect x="40" y="220" width="70" height="30" fill={TINT} />
      </g>
      {/* living furniture */}
      <g stroke={CHARCOAL} strokeWidth="1.5">
        <rect x="272" y="270" width="150" height="46" fill={TINT} />
        <rect x="306" y="206" width="84" height="44" fill="#fff" />
        <rect x="440" y="150" width="36" height="110" fill={TINT} />
        <circle cx="300" cy="80" r="26" fill="#fff" />
      </g>
      {/* access zones */}
      <g fill="none" stroke={TEAL} strokeDasharray="4 3" strokeWidth="1">
        <rect x="146" y="80" width="30" height="92" />
        <rect x="272" y="252" width="150" height="16" />
      </g>
      {/* labels */}
      <g fontFamily="Georgia, serif" fontSize="13" fill={CHARCOAL}>
        <text x="62" y="130">Bed</text>
        <text x="320" y="300">Sofa</text>
        <text x="420" y="74">Kitchen</text>
        <text x="40" y="270" fontSize="11">Desk</text>
      </g>
      <g fontFamily="system-ui, sans-serif" fontSize="10" fill="#55606b" letterSpacing="1.5">
        <text x="30" y="352">CONCEPT DRAWING · NOT A REAL APARTMENT</text>
      </g>
    </svg>
  );
}

/** Tiny glyph for an apartment type: boxes for bedrooms, a wide box for living, small boxes for baths. */
export function AptGlyph({ bedrooms, bathrooms }: { bedrooms: number; bathrooms: number }) {
  const boxes: { x: number; w: number; kind: string }[] = [];
  let x = 2;
  if (bedrooms === 0) {
    boxes.push({ x, w: 64, kind: "studio" });
    x += 66;
  } else {
    for (let i = 0; i < bedrooms; i++) { boxes.push({ x, w: 26, kind: "bed" }); x += 28; }
    boxes.push({ x, w: 40, kind: "living" });
    x += 42;
  }
  for (let i = 0; i < bathrooms; i++) { boxes.push({ x, w: 14, kind: "bath" }); x += 16; }
  return (
    <svg viewBox={`0 0 ${x + 2} 40`} preserveAspectRatio="xMinYMid meet" aria-hidden>
      {boxes.map((b, i) => (
        <rect key={i} x={b.x} y={b.kind === "bath" ? 18 : 4} width={b.w} height={b.kind === "bath" ? 18 : 32}
          fill={b.kind === "bath" ? "#fff" : TINT} stroke={b.kind === "bath" ? "#7c8690" : CHARCOAL}
          strokeDasharray={b.kind === "bath" ? "3 2" : undefined} strokeWidth="1.4" />
      ))}
    </svg>
  );
}
