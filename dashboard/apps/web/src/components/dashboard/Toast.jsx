import { useEffect, useRef, useState } from "react";
import { CheckCircle, AlertTriangle, X, Info } from "lucide-react";

const icons = {
  success: <CheckCircle size={18} className="text-[#23A55A]" />,
  error: <AlertTriangle size={18} className="text-[#F23F43]" />,
  info: (
    <Info
      size={18}
      style={{ color: "var(--accent-readable, #5865F2)" }}
    />
  ),
};

const ENTER_MS = 260;
const EXIT_MS = 180;
const DEFAULT_DURATION_MS = 3500;
const ERROR_DURATION_MS = 6000;

export function ToastContainer({ toasts, removeToast }) {
  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      aria-relevant="additions"
      className="fixed top-5 right-5 z-[9999] flex flex-col gap-2 w-80 max-w-[calc(100vw-2.5rem)] pointer-events-none"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onRemove={() => removeToast(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onRemove }) {
  const [visible, setVisible] = useState(false);
  const [closing, setClosing] = useState(false);
  const onRemoveRef = useRef(onRemove);
  onRemoveRef.current = onRemove;

  const duration =
    toast.type === "error" ? ERROR_DURATION_MS : DEFAULT_DURATION_MS;
  const remainingRef = useRef(duration);
  const startedAtRef = useRef(0);
  const timerRef = useRef(null);

  const clearDismiss = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const scheduleDismiss = () => {
    clearDismiss();
    startedAtRef.current = Date.now();
    timerRef.current = setTimeout(() => setClosing(true), remainingRef.current);
  };

  useEffect(() => {
    const enter = setTimeout(() => setVisible(true), 20);
    scheduleDismiss();
    return () => {
      clearTimeout(enter);
      clearDismiss();
    };
    // Timer helpers only touch refs and setState, so the mount closure is safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!closing) return;
    clearDismiss();
    setVisible(false);
    const done = setTimeout(() => onRemoveRef.current(), EXIT_MS);
    return () => clearTimeout(done);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [closing]);

  // Pause the dismiss countdown while the pointer is over the toast, then
  // resume with the time that was left.
  const handleMouseEnter = () => {
    if (closing || timerRef.current === null) return;
    clearTimeout(timerRef.current);
    timerRef.current = null;
    const elapsed = Date.now() - startedAtRef.current;
    remainingRef.current = Math.max(0, remainingRef.current - elapsed);
  };

  const handleMouseLeave = () => {
    if (closing) return;
    scheduleDismiss();
  };

  return (
    <div
      role={toast.type === "error" ? "alert" : "status"}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className="pointer-events-auto flex items-start gap-3 p-3.5 rounded-xl border border-[#2B3346] backdrop-blur-md"
      style={{
        background: "rgba(30,35,48,0.97)",
        transform: visible ? "translate3d(0,0,0)" : "translate3d(24px,0,0)",
        opacity: visible ? 1 : 0,
        transition: `transform ${visible ? ENTER_MS : EXIT_MS}ms var(--ease-out), opacity ${visible ? ENTER_MS : EXIT_MS}ms var(--ease-out)`,
        boxShadow:
          "0 24px 60px -18px rgba(0,0,0,0.75), 0 10px 24px -12px rgba(0,0,0,0.55)",
        willChange: "transform, opacity",
      }}
    >
      <div className="mt-0.5 shrink-0">{icons[toast.type] || icons.info}</div>
      <div className="flex-1 min-w-0">
        {toast.title && (
          <div className="text-sm font-semibold text-white">{toast.title}</div>
        )}
        <div className="text-sm leading-relaxed text-[#CBD5E1]">
          {toast.message}
        </div>
      </div>
      <button
        type="button"
        onClick={() => setClosing(true)}
        aria-label="Dismiss notification"
        className="shrink-0 -mr-0.5 -mt-0.5 p-1 rounded-md text-[#94A3B8] hover:text-white hover:bg-white/5 transition-all duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#1E2330]"
      >
        <X size={16} />
      </button>
    </div>
  );
}

let toastId = 0;
export function useToast() {
  const [toasts, setToasts] = useState([]);
  const addToast = (type, message, title) => {
    const id = ++toastId;
    setToasts((prev) => [...prev, { id, type, message, title }]);
  };
  const removeToast = (id) =>
    setToasts((prev) => prev.filter((t) => t.id !== id));
  const toast = {
    success: (msg, title) => addToast("success", msg, title),
    error: (msg, title) => addToast("error", msg, title),
    info: (msg, title) => addToast("info", msg, title),
  };
  return { toasts, removeToast, toast };
}
