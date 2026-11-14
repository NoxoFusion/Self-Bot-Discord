"use client";
import { useEffect, useState } from "react";
import { tgEmojiUrl } from "../../lib/tgEmoji";

/**
 * Telegram premium emoji illustration.
 *
 * The vault serves WebP assets; when the asset is unavailable the component
 * falls back to the Lucide icon passed through `fallback` so layout never
 * collapses. Decorative by default (`alt` is empty).
 */
export default function TgEmoji({
  id,
  size = 24,
  className = "",
  fallback: Fallback,
  alt = "",
  style,
}) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [id]);

  if (!id || failed) {
    if (!Fallback) return null;
    return (
      <Fallback
        size={Math.max(12, Math.round(size * 0.8))}
        className={className}
        style={style}
        aria-hidden="true"
      />
    );
  }

  return (
    <img
      src={tgEmojiUrl(id)}
      alt={alt}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      draggable={false}
      onError={() => setFailed(true)}
      className={`object-contain select-none shrink-0 ${className}`}
      style={{ width: size, height: size, ...style }}
    />
  );
}
