"use client";

// Discord-ish palette used to keep initials avatars recognizable without any
// network request (dicebear previews broke whenever the API was unreachable).
const PALETTE = [
  "#5865F2",
  "#3BA55D",
  "#FAA61A",
  "#EB459E",
  "#ED4245",
  "#7289DA",
  "#1ABC9C",
  "#9B59B6",
];

function hashName(value) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0;
  }
  return hash;
}

function getInitials(value) {
  const words = value.trim().split(/\s+/).filter(Boolean).slice(0, 2);
  const initials = words.map((word) => word[0]).join("").toUpperCase();
  return initials || "?";
}

export default function Avatar({ name = "", size = 28, className = "" }) {
  const label = typeof name === "string" ? name : "";
  const background = PALETTE[hashName(label) % PALETTE.length];

  return (
    <div
      aria-hidden="true"
      className={`rounded-full flex items-center justify-center shrink-0 select-none font-bold text-white ${className}`}
      style={{
        width: size,
        height: size,
        minWidth: size,
        background,
        fontSize: Math.max(9, Math.round(size * 0.4)),
        lineHeight: 1,
      }}
    >
      {getInitials(label)}
    </div>
  );
}
