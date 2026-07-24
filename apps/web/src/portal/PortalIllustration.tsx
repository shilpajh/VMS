// Decorative reception-scene illustration for the portal landing page's left
// panel (US-13b restyle to match the org prototype's look & feel). Purely
// decorative -> aria-hidden, so it adds no noise to the accessibility tree.
export function PortalIllustration() {
  return (
    <svg viewBox="0 90 400 230" fill="none" className="w-full h-auto" aria-hidden="true">
      {/* Potted plant */}
      <rect x="22" y="272" width="34" height="26" rx="4" fill="#7C3AED" />
      <path d="M39 272 C39 250 15 245 10 225 C28 235 40 240 39 262 Z" fill="#3EA36B" />
      <path d="M39 272 C39 250 63 245 68 222 C50 233 38 238 39 262 Z" fill="#4DBF82" />
      <path d="M39 272 L39 232" stroke="#2F8A5C" strokeWidth="4" strokeLinecap="round" />
      {/* Desk */}
      <rect x="70" y="220" width="210" height="18" rx="5" fill="#3E7FC1" />
      <rect x="78" y="234" width="194" height="58" rx="8" fill="#5B9BD5" />
      <ellipse cx="175" cy="263" rx="42" ry="13" fill="#7EB6E8" opacity="0.55" />
      {/* Monitor */}
      <rect x="96" y="188" width="46" height="34" rx="3" fill="#2857D6" />
      <rect x="112" y="222" width="12" height="8" fill="#2857D6" />
      {/* Receptionist */}
      <rect x="150" y="168" width="42" height="58" rx="16" fill="#EAF2FB" stroke="#B9D3F0" strokeWidth="1.5" />
      <path d="M150 200 Q128 190 122 165" stroke="#F4B183" strokeWidth="11" fill="none" strokeLinecap="round" />
      <circle cx="171" cy="152" r="18" fill="#F4B183" />
      <path d="M153 150 Q171 118 189 150 Q189 132 171 126 Q153 132 153 150 Z" fill="#3B2314" />
      {/* Man visitor */}
      <rect x="246" y="252" width="14" height="52" rx="4" fill="#241F3D" />
      <rect x="266" y="252" width="14" height="52" rx="4" fill="#241F3D" />
      <path d="M235 200 Q235 190 245 190 L281 190 Q291 190 291 200 L291 252 Q263 262 235 252 Z" fill="#6D3FA0" />
      <rect x="257" y="196" width="12" height="34" rx="3" fill="#fff" />
      <rect x="221" y="222" width="18" height="24" rx="3" fill="#3EA36B" />
      <circle cx="263" cy="178" r="17" fill="#EFB78E" />
      <path d="M247 176 Q263 148 279 176 Q279 160 263 154 Q247 160 247 176 Z" fill="#3B2314" />
      {/* Woman visitor */}
      <path d="M296 230 L288 275 L336 275 L328 230 Z" fill="#7A3FA0" />
      <rect x="296" y="196" width="32" height="38" rx="8" fill="#4CAF7D" />
      <rect x="298" y="275" width="12" height="30" rx="3" fill="#EFB78E" />
      <rect x="314" y="275" width="12" height="30" rx="3" fill="#EFB78E" />
      <rect x="296" y="303" width="16" height="6" rx="3" fill="#241F3D" />
      <rect x="312" y="303" width="16" height="6" rx="3" fill="#241F3D" />
      <circle cx="312" cy="180" r="17" fill="#EFB78E" />
      <path d="M296 182 Q294 210 302 218 Q298 195 300 180 Z" fill="#5C2E1A" />
      <path d="M296 178 Q312 148 328 178 Q328 160 312 154 Q296 160 296 178 Z" fill="#5C2E1A" />
      <rect x="322" y="210" width="10" height="16" rx="2" fill="#2B1F55" />
      {/* Speech bubbles */}
      <path d="M212 118 h34 a6 6 0 0 1 6 6 v14 a6 6 0 0 1 -6 6 h-20 l-8 10 v-10 h-6 a6 6 0 0 1 -6 -6 v-14 a6 6 0 0 1 6 -6 Z" fill="#EAF2FB" stroke="#2857D6" strokeWidth="1.5" />
      <rect x="220" y="126" width="22" height="3" rx="1.5" fill="#2857D6" />
      <rect x="220" y="133" width="14" height="3" rx="1.5" fill="#2857D6" />
      <path d="M300 100 h34 a6 6 0 0 1 6 6 v14 a6 6 0 0 1 -6 6 h-6 v10 l-8 -10 h-20 a6 6 0 0 1 -6 -6 v-14 a6 6 0 0 1 6 -6 Z" fill="#EAF2FB" stroke="#9333B8" strokeWidth="1.5" />
      <rect x="308" y="108" width="22" height="3" rx="1.5" fill="#9333B8" />
      <rect x="308" y="115" width="14" height="3" rx="1.5" fill="#9333B8" />
    </svg>
  )
}
