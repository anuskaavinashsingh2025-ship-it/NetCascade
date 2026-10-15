// SVG device illustrations (3D-style) and UI line icons.

export const DEVICE_SYMBOLS = `
<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <filter id="dev-shadow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3.2"/>
    </filter>
    <linearGradient id="g-screen" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#7cc4ff"/>
      <stop offset="0.45" stop-color="#2f86ef"/>
      <stop offset="1" stop-color="#0b4fb3"/>
    </linearGradient>
    <linearGradient id="g-bezel" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#2c3946"/>
      <stop offset="1" stop-color="#121a22"/>
    </linearGradient>
    <linearGradient id="g-base" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#4a5664"/>
      <stop offset="1" stop-color="#222b35"/>
    </linearGradient>
    <linearGradient id="g-sw-top" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#7b93b4"/>
      <stop offset="1" stop-color="#4c6688"/>
    </linearGradient>
    <linearGradient id="g-sw-front" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#3f5878"/>
      <stop offset="1" stop-color="#2a3d57"/>
    </linearGradient>
    <linearGradient id="g-rt-body" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#17345c"/>
      <stop offset="0.45" stop-color="#2f5f9c"/>
      <stop offset="1" stop-color="#132b4c"/>
    </linearGradient>
    <linearGradient id="g-rt-top" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#6aa0de"/>
      <stop offset="1" stop-color="#2f62a3"/>
    </linearGradient>
    <linearGradient id="g-srv-front" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#2d4a73"/>
      <stop offset="1" stop-color="#16263f"/>
    </linearGradient>
    <linearGradient id="g-srv-top" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#5677a4"/>
      <stop offset="1" stop-color="#3a5680"/>
    </linearGradient>

    <symbol id="dev-pc" viewBox="0 0 120 120">
      <ellipse cx="62" cy="104" rx="34" ry="6" fill="#0b2346" opacity=".22" filter="url(#dev-shadow)"/>
      <polygon points="88,13 96,17 97,69 91,67" fill="#0d141b"/>
      <polygon points="20,25 90,13 92,67 22,81" fill="url(#g-bezel)"/>
      <polygon points="25,30 86,19 88,62 27,75" fill="url(#g-screen)"/>
      <polygon points="25,30 60,23.6 34,73.3 27,75" fill="#fff" opacity=".13"/>
      <polygon points="53,76 63,74 65,92 55,94" fill="#26303b"/>
      <polygon points="32,96 72,89 88,97 48,105" fill="url(#g-base)"/>
      <polygon points="48,105 88,97 88,99.5 48,107.5" fill="#151c24"/>
      <polygon points="32,96 48,105 48,107.5 32,98.5" fill="#1d252e"/>
    </symbol>

    <symbol id="dev-switch" viewBox="0 0 120 120">
      <ellipse cx="62" cy="86" rx="50" ry="8" fill="#0b2346" opacity=".22" filter="url(#dev-shadow)"/>
      <polygon points="10,47 40,35 110,49 80,61" fill="url(#g-sw-top)"/>
      <polygon points="10,47 80,61 80,80 10,66" fill="url(#g-sw-front)"/>
      <polygon points="80,61 110,49 110,68 80,80" fill="#22334a"/>
      <polygon points="10,47 80,61 80,62.2 10,48.2" fill="#9db2cf" opacity=".6"/>
      <g transform="matrix(1,0.2,0,1,10,47)">
        <rect x="3" y="4" width="3" height="11" rx=".8" fill="#4fb3ff" opacity=".9"/>
        ${Array.from({ length: 11 }, (_, i) => `
          <rect x="${9 + i * 5.4}" y="4.2" width="4.2" height="4" rx=".5" fill="#0d1520"/>
          <rect x="${9 + i * 5.4}" y="10" width="4.2" height="4" rx=".5" fill="#0d1520"/>
          <rect x="${9.6 + i * 5.4}" y="2.4" width="1.6" height=".9" fill="${i % 3 ? "#5ee38a" : "#62b8ff"}"/>`).join("")}
      </g>
    </symbol>

    <symbol id="dev-router" viewBox="0 0 120 120">
      <ellipse cx="60" cy="88" rx="44" ry="9" fill="#0b2346" opacity=".25" filter="url(#dev-shadow)"/>
      <path d="M17,50 v24 a43,14 0 0 0 86,0 v-24 z" fill="url(#g-rt-body)"/>
      <ellipse cx="60" cy="50" rx="43" ry="14" fill="url(#g-rt-top)"/>
      <ellipse cx="60" cy="50" rx="43" ry="14" fill="none" stroke="#9cc3f0" stroke-opacity=".5"/>
      <g transform="translate(60,50) scale(1,0.36)" stroke="#fff" stroke-width="3.6" fill="none" stroke-linecap="round" stroke-linejoin="round">
        <path d="M-30,-10 h14 M-22,-17 l7,7 -7,7"/>
        <path d="M30,10 h-14 M22,17 l-7,-7 7,-7"/>
        <path d="M-8,-12 l-14,-14 M-22,-17 v-9 h9" transform="rotate(90) translate(0,-8)"/>
        <path d="M8,12 l14,14 M22,17 v9 h-9" transform="rotate(90) translate(0,8)"/>
      </g>
      <circle cx="48" cy="72" r="2.2" fill="#49c2ff"/>
      <circle cx="60" cy="73.5" r="2.2" fill="#49c2ff"/>
      <circle cx="72" cy="72" r="2.2" fill="#49c2ff"/>
    </symbol>

    <symbol id="dev-server" viewBox="0 0 120 120">
      <ellipse cx="62" cy="106" rx="30" ry="6" fill="#0b2346" opacity=".25" filter="url(#dev-shadow)"/>
      <polygon points="34,20 52,10 88,20 70,30" fill="url(#g-srv-top)"/>
      <polygon points="34,20 70,30 70,106 34,96" fill="url(#g-srv-front)"/>
      <polygon points="70,30 88,20 88,96 70,106" fill="#0f1d33"/>
      <g transform="matrix(1,0.278,0,1,34,20)">
        ${Array.from({ length: 7 }, (_, i) => `
          <rect x="4" y="${7 + i * 9.6}" width="28" height="6.4" rx="1" fill="#0c172a"/>
          <rect x="6.5" y="${9.2 + i * 9.6}" width="17" height="1.8" rx=".9" fill="#4fb3ff"/>
          <circle cx="28" cy="${10.2 + i * 9.6}" r="1.2" fill="${i % 2 ? "#5ee38a" : "#4fb3ff"}"/>`).join("")}
      </g>
      <polygon points="34,20 70,30 70,31.2 34,21.2" fill="#a9c2e6" opacity=".45"/>
    </symbol>
  </defs>
</svg>`;

const PATHS = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h5v-6h4v6h5V9.5"/>',
  topology: '<rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4M6 16v-4h12v4"/>',
  scenarios: '<path d="M4 21V10M10 21V4M16 21v-8M21 21H3"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.5-4.5"/>',
  pointer: '<path d="M5 3l14 7-6 2-2 6z"/>',
  link: '<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3.2-3.2a4.5 4.5 0 0 0-6.4-6.4L11.6 6"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3.2 3.2a4.5 4.5 0 0 0 6.4 6.4l1.6-1.6"/>',
  pencil: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
  layout: '<rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4M6 16v-4h12v4"/>',
  minus: '<path d="M5 12h14"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  fit: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17v.5"/>',
  monitor: '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M9 20h6M12 16v4"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  restore: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.8"/><path d="M16.5 14.3A5.5 5.5 0 0 1 21.5 20"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4"/>',
  linkoff: '<path d="M14 7.5l1.6-1.6a3.5 3.5 0 0 1 5 5L19 12.5"/><path d="M10 16.5l-1.6 1.6a3.5 3.5 0 0 1-5-5L5 11.5"/><path d="M8 3v3M3 8h3M16 21v-3M21 16h-3"/>',
  chevron: '<path d="m6 15 6-6 6 6"/>',
  chevdown: '<path d="m6 9 6 6 6-6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
  play: '<path d="M7.5 4.8v14.4L19 12z"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
  more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
  doc: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  circle: '<circle cx="12" cy="12" r="8.5"/>',
  checkcircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12.4 2.8 2.8L16.2 9.6"/>',
  fitscreen: '<path d="M11 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-6"/><path d="M14 4h6v6M20 4l-8 8"/>',
};

export function icon(name, size = 20, extra = "") {
  return `<svg class="ic ${extra}" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name] || ""}</svg>`;
}

export function deviceIcon(type, size = 64) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 120 120" aria-hidden="true"><use href="#dev-${type}"/></svg>`;
}

export const LOGO = `
<svg width="44" height="44" viewBox="0 0 48 48" aria-hidden="true">
  <g stroke="#1a73e8" stroke-width="3.2" fill="none" stroke-linecap="round">
    <path d="M17 17 11 11M31 17l6-6M17 31l-6 6M31 31l6 6"/>
    <circle cx="24" cy="24" r="9"/>
  </g>
  <circle cx="24" cy="24" r="4" fill="#1a73e8"/>
  <g fill="#fff" stroke="#1a73e8" stroke-width="3.2">
    <circle cx="8.5" cy="8.5" r="4.5"/><circle cx="39.5" cy="8.5" r="4.5"/>
    <circle cx="8.5" cy="39.5" r="4.5"/><circle cx="39.5" cy="39.5" r="4.5"/>
  </g>
</svg>`;
