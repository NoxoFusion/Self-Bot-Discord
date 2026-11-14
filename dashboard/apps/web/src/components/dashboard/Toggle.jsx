export default function Toggle({
  enabled,
  onChange,
  size = "md",
  label,
  disabled = false,
}) {
  const sizes = {
    sm: { track: "w-8 h-4", thumb: "w-3 h-3", translate: "translate-x-4" },
    md: { track: "w-11 h-6", thumb: "w-5 h-5", translate: "translate-x-5" },
    lg: { track: "w-14 h-7", thumb: "w-6 h-6", translate: "translate-x-7" },
  };
  const s = sizes[size] ?? sizes.md;
  return (
    <button
      type="button"
      role="switch"
      aria-label={label || "Toggle"}
      aria-checked={enabled}
      disabled={disabled}
      onClick={() => !disabled && onChange(!enabled)}
      className={`toggle-focus relative inline-flex items-center rounded-full transition-colors duration-200 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${s.track} ${
        enabled ? "bg-[#23A55A]" : "bg-[#2B3346]"
      }`}
      style={{
        transitionTimingFunction: "var(--ease-out)",
        boxShadow: enabled
          ? "0 0 0 1px rgba(35,165,90,0.35), 0 0 10px rgba(35,165,90,0.22)"
          : "inset 0 1px 2px rgba(0,0,0,0.35)",
      }}
    >
      <span
        className={`inline-block rounded-full bg-white transform transition-transform duration-200 ${s.thumb} ${
          enabled ? s.translate : "translate-x-0.5"
        }`}
        style={{
          transitionTimingFunction: "var(--ease-out)",
          boxShadow:
            "0 1px 2px rgba(0,0,0,0.45), 0 2px 6px rgba(0,0,0,0.25)",
        }}
      />
    </button>
  );
}
