const common = {
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  "stroke-width": 1.5,
  "stroke-linecap": "round" as const,
  "stroke-linejoin": "round" as const,
  "aria-hidden": true,
};

export const RefreshIcon = ({ spinning = false }: { spinning?: boolean }) => (
  <svg {...common} class={spinning ? "spin" : undefined}>
    <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" />
    <path d="M13.5 2.5v3h-3" />
  </svg>
);

export const SlidersIcon = () => (
  <svg {...common}>
    <path d="M2.5 4.5h7M12.5 4.5h1M2.5 11.5h1M6.5 11.5h7" />
    <circle cx="11" cy="4.5" r="1.5" />
    <circle cx="5" cy="11.5" r="1.5" />
  </svg>
);

export const GlobeIcon = () => (
  <svg {...common}>
    <circle cx="8" cy="8" r="6" />
    <path d="M2 8h12M8 2c1.8 1.7 2.6 3.7 2.6 6S9.8 12.3 8 14M8 2C6.2 3.7 5.4 5.7 5.4 8s.8 4.3 2.6 6" />
  </svg>
);

export const CloseIcon = () => (
  <svg {...common}>
    <path d="M4 4l8 8M12 4l-8 8" />
  </svg>
);

export const MonitorIcon = () => (
  <svg {...common}>
    <rect x="2" y="3" width="12" height="8" rx="1.5" />
    <path d="M6 13.5h4M8 11v2.5" />
  </svg>
);

export const SyncIcon = () => (
  <svg {...common}>
    <path d="M3 6.5A5 5 0 0 1 12.2 4M13 9.5A5 5 0 0 1 3.8 12" />
    <path d="M12.5 1.8v2.7H9.8M3.5 14.2v-2.7h2.7" />
  </svg>
);

export const BellIcon = () => (
  <svg {...common}>
    <path d="M4 11V7a4 4 0 0 1 8 0v4l1 1.5H3z" />
    <path d="M6.5 14a1.5 1.5 0 0 0 3 0" />
  </svg>
);

export const KeyIcon = () => (
  <svg {...common}>
    <circle cx="5.5" cy="10.5" r="3" />
    <path d="M7.7 8.3L13.5 2.5M11 5l1.5 1.5M12.5 3.5L14 5" />
  </svg>
);

export const PowerIcon = () => (
  <svg {...common}>
    <path d="M8 2v6" />
    <path d="M4.5 4.2a5 5 0 1 0 7 0" />
  </svg>
);

export const KeyboardIcon = () => (
  <svg {...common}>
    <rect x="1.5" y="4" width="13" height="8" rx="1.5" />
    <path d="M4 7h.01M6.5 7h.01M9 7h.01M11.5 7h.01M5 9.5h6" />
  </svg>
);

export const BoxIcon = () => (
  <svg {...common}>
    <path d="M2.5 5L8 2l5.5 3v6L8 14l-5.5-3z" />
    <path d="M2.5 5L8 8l5.5-3M8 8v6" />
  </svg>
);

export const ChevronIcon = ({ dir = "down" }: { dir?: "up" | "down" }) => (
  <svg {...common}>
    <path d={dir === "up" ? "M4.5 9.5 8 6l3.5 3.5" : "M4.5 6.5 8 10l3.5-3.5"} />
  </svg>
);

export const DownloadIcon = () => (
  <svg {...common}>
    <path d="M8 2.5v7.5M4.75 7 8 10.25 11.25 7" />
    <path d="M2.75 11v1.25c0 .7.55 1.25 1.25 1.25h8c.7 0 1.25-.55 1.25-1.25V11" />
  </svg>
);

/** Same mark as the app icon (cursor_usage_app/icon_art.py): graphite tile, gauge with a blue arc. */
export const LogoMark = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" class="logo">
    <rect x="0.5" y="0.5" width="23" height="23" rx="5.5" fill="#1c1c20" stroke="rgba(255,255,255,0.1)" />
    <path d="M7.76 16.24A6 6 0 1 1 16.24 16.24" fill="none" stroke="rgba(255,255,255,0.16)" stroke-width="2.4" stroke-linecap="round" />
    <path d="M7.76 16.24A6 6 0 1 1 16.5 8.03" fill="none" stroke="#4f8cff" stroke-width="2.4" stroke-linecap="round" />
    <circle cx="16.5" cy="8.03" r="0.85" fill="#fff" />
  </svg>
);
