"use client";
import { useEffect, useRef, useState } from "react";

const EXIT_MS = 160;
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "area[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "iframe",
  "object",
  "embed",
  "[contenteditable='true']",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function focusableElements(panel) {
  if (!panel) return [];
  return Array.from(panel.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
    (node) =>
      !node.hasAttribute("hidden") &&
      node.getAttribute("aria-hidden") !== "true",
  );
}

export default function Modal({
  open,
  onClose,
  children,
  label,
  role = "dialog",
  backdropTestId,
  panelClassName = "",
  maxWidthClass = "max-w-2xl",
  overlayStyle,
  panelStyle,
  initialFocusRef,
  closeOnBackdrop = true,
}) {
  const [rendered, setRendered] = useState(Boolean(open));
  const [closing, setClosing] = useState(false);
  const panelRef = useRef(null);
  const restoreFocusRef = useRef(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  // Keep the panel mounted for one exit-animation frame after `open` flips
  // false, without delaying the parent's onClose callback.
  useEffect(() => {
    if (open) {
      setRendered(true);
      setClosing(false);
      return undefined;
    }
    if (!rendered) return undefined;

    setClosing(true);
    const timer = window.setTimeout(() => {
      setRendered(false);
      setClosing(false);
    }, EXIT_MS);
    return () => window.clearTimeout(timer);
  }, [open, rendered]);

  useEffect(() => {
    if (!rendered) return undefined;
    const panel = panelRef.current;
    if (!panel) return undefined;

    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    restoreFocusRef.current = previous;

    const preferred = initialFocusRef?.current;
    const target =
      preferred && panel.contains(preferred)
        ? preferred
        : focusableElements(panel)[0] || panel;
    target.focus?.();

    return () => {
      const restore = restoreFocusRef.current;
      restoreFocusRef.current = null;
      if (
        restore &&
        restore !== document.body &&
        document.contains(restore)
      ) {
        restore.focus?.();
      }
    };
  }, [rendered, initialFocusRef]);

  useEffect(() => {
    if (!rendered) return undefined;

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        onCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab") return;

      const panel = panelRef.current;
      if (!panel) return;

      const items = focusableElements(panel);
      if (!items.length) {
        event.preventDefault();
        panel.focus();
        return;
      }

      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const inside = panel.contains(active) && active !== panel;

      if (event.shiftKey) {
        if (!inside || active === first) {
          event.preventDefault();
          last.focus();
        }
      } else if (!inside || active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [rendered]);

  if (!rendered) return null;

  return (
    <div
      data-testid={backdropTestId}
      className="modal-overlay fixed inset-0 z-[9999] flex items-center justify-center p-4"
      data-closing={closing ? "true" : "false"}
      style={{
        background: "rgba(0,0,0,0.68)",
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        ...overlayStyle,
      }}
      onClick={(event) => {
        if (!closeOnBackdrop) return;
        if (event.target === event.currentTarget) onCloseRef.current?.();
      }}
    >
      <div
        ref={panelRef}
        role={role}
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        data-closing={closing ? "true" : "false"}
        className={`modal-panel w-full ${maxWidthClass} max-h-[90vh] rounded-2xl border flex flex-col ${panelClassName}`}
        style={panelStyle}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
