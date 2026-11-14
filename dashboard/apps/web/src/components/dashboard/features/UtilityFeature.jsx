"use client";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  CloudSun,
  Copy,
  CopyPlus,
  Droplets,
  ExternalLink,
  Hash,
  Image as ImageIcon,
  Info,
  Loader2,
  MapPin,
  Play,
  Server,
  Smile,
  Thermometer,
  Wind,
  Wrench,
  X,
} from "lucide-react";
import { EmptyState, FeatureHero, IconInput, Panel } from "../kit";
import Modal from "../Modal";
import Toggle from "../Toggle";
import { api, ApiError } from "../../../lib/api";
import { useSessionContext } from "../../../lib/session";
import { useAccent } from "../../../lib/theme";
import { TG_EMOJI } from "../../../lib/tgEmoji";

const WEATHER_ACCENT = "#38BDF8";
const IMAGE_ACCENT = "#F59E0B";
const CLONE_ACCENT = "#F43F5E";
const WEATHER_CARD =
  "h-[230px] sm:h-[170px] rounded-xl p-4 flex flex-col gap-3";
const IMAGE_CARD = "h-[170px] rounded-xl overflow-hidden relative";

function GuildField({ label, value, onChange, accent, placeholder }) {
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="text-xs font-semibold" style={{ color: accent }}>
        {label}
      </span>
      <IconInput
        icon={Hash}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        mono
        accent={accent}
      />
    </div>
  );
}

function RunButton({ onClick, disabled, busy, icon: Icon, children, accent }) {
  const blocked = disabled || busy;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={blocked}
      className="flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl text-sm font-bold shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
      style={{
        background: `${accent}20`,
        color: accent,
        border: `1px solid ${accent}40`,
        opacity: blocked ? 0.5 : 1,
        cursor: blocked ? "not-allowed" : "pointer",
      }}
    >
      {busy ? (
        <Loader2 size={14} className="animate-spin" />
      ) : (
        <Icon size={14} />
      )}
      {children}
    </button>
  );
}

function InlineError({ children }) {
  return (
    <span className="text-sm" style={{ color: "#F23F43" }}>
      {children}
    </span>
  );
}

function Notice({ tone = "info", children }) {
  const warn = tone === "warn";
  return (
    <div
      className="flex items-start gap-2.5 px-3 py-1.5 rounded-xl border text-sm"
      style={{
        background: warn ? "#F5B64212" : "#58B8E812",
        borderColor: warn ? "#F5B64240" : "#58B8E840",
        color: warn ? "#D8C08A" : "#C9D1DB",
      }}
    >
      {warn ? (
        <AlertTriangle
          size={14}
          style={{ color: "#F5B642", flexShrink: 0, marginTop: 1 }}
        />
      ) : (
        <Info
          size={14}
          style={{ color: "#58B8E8", flexShrink: 0, marginTop: 1 }}
        />
      )}
      <span>{children}</span>
    </div>
  );
}

function UtilityStatus({ status }) {
  if (!status) return null;

  const state =
    status.status ||
    (status.applied === true
      ? "success"
      : status.reason === "bot_offline"
        ? "offline"
        : "queued");
  const meta = {
    queued: {
      color: "#F5B642",
      icon: Loader2,
      text: status.message || "Clone queued — waiting for the bot.",
    },
    running: {
      color: "#58B8E8",
      icon: Loader2,
      text: status.message || "Clone running…",
    },
    success: {
      color: "#23A55A",
      icon: CheckCircle2,
      text: status.message || "Completed.",
    },
    error: {
      color: "#F23F43",
      icon: AlertTriangle,
      text: status.message || "Clone failed.",
    },
    offline: {
      color: "#F5B642",
      icon: Info,
      text: "Not executed — bot offline.",
    },
  }[state] || {
    color: "#94A3B8",
    icon: Info,
    text: status.message || "Clone status unknown.",
  };
  const Icon = meta.icon;
  const spinning = state === "queued" || state === "running";

  return (
    <div
      className="flex items-start gap-2 px-2.5 py-2 rounded-lg text-sm"
      style={{
        background: `${meta.color}12`,
        color: meta.color,
      }}
    >
      <Icon
        size={13}
        className={spinning ? "animate-spin" : ""}
        style={{ flexShrink: 0, marginTop: 1 }}
      />
      <span>{meta.text}</span>
    </div>
  );
}

function Metric({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span
        className="flex items-center gap-1.5 shrink-0"
        style={{ color: "#94A3B8" }}
      >
        <Icon size={12} style={{ color: WEATHER_ACCENT }} />
        {label}
      </span>
      <span className="font-mono font-bold text-white text-right">{value}</span>
    </div>
  );
}

function WeatherPlaceholder({ loading = false }) {
  return (
    <div
      data-testid="weather-card"
      className={WEATHER_CARD}
      style={{ background: "var(--surface-inset)" }}
    >
      {loading ? (
        <div className="flex flex-1 items-center justify-center gap-2">
          <Loader2
            size={14}
            className="animate-spin"
            style={{ color: WEATHER_ACCENT }}
          />
          <span className="text-sm" style={{ color: "#94A3B8" }}>
            Loading weather…
          </span>
        </div>
      ) : (
        <EmptyState
          emojiId={TG_EMOJI.gamepad}
          icon={CloudSun}
          title="No weather data yet"
          className="!py-0 flex-1"
        />
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 opacity-60">
        <Metric icon={Droplets} label="Humidity" value="—" />
        <Metric icon={Wind} label="Wind" value="—" />
        <Metric icon={Thermometer} label="Feels like" value="—" />
        <Metric icon={MapPin} label="Coordinates" value="—" />
      </div>
    </div>
  );
}

function WeatherResult({ data }) {
  const shown = (value, suffix = "") =>
    value === null || value === undefined ? "—" : `${value}${suffix}`;
  const coord = (value) =>
    typeof value === "number" && Number.isFinite(value)
      ? value.toFixed(2)
      : "—";

  return (
    <div
      data-testid="weather-card"
      className={WEATHER_CARD}
      style={{ background: "var(--surface-inset)" }}
    >
      <div className="flex items-center gap-2 min-w-0">
        <MapPin size={14} style={{ color: WEATHER_ACCENT, flexShrink: 0 }} />
        <span className="text-sm font-bold text-white truncate">
          {data.location}
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 flex-1 min-h-0">
        <div className="flex flex-col justify-center gap-1">
          <div className="text-4xl sm:text-5xl font-extrabold text-white leading-none tabular-nums">
            {shown(data.temperature_c, "°C")}
          </div>
          <div className="text-sm" style={{ color: "#94A3B8" }}>
            {data.description}
          </div>
        </div>
        <div className="flex flex-col justify-center gap-1.5">
          <Metric
            icon={Droplets}
            label="Humidity"
            value={shown(data.humidity, "%")}
          />
          <Metric
            icon={Wind}
            label="Wind"
            value={shown(data.wind_kmh, " km/h")}
          />
          <Metric
            icon={Thermometer}
            label="Feels like"
            value={shown(data.feels_like_c, "°C")}
          />
          <Metric
            icon={MapPin}
            label="Coordinates"
            value={`${coord(data.latitude)}, ${coord(data.longitude)}`}
          />
        </div>
      </div>
    </div>
  );
}

function ImagePlaceholder() {
  return (
    <div
      data-testid="image-card"
      className={`${IMAGE_CARD} flex items-center justify-center`}
      style={{ background: "var(--surface-inset)" }}
    >
      <EmptyState
        emojiId={TG_EMOJI.image}
        icon={ImageIcon}
        title="Your image will appear here"
      />
    </div>
  );
}

function ImageLoading() {
  return (
    <div
      data-testid="image-card"
      className={`${IMAGE_CARD} flex flex-col items-center justify-center gap-2`}
      style={{ background: "var(--surface-inset)" }}
    >
      <Loader2
        size={24}
        className="animate-spin"
        style={{ color: IMAGE_ACCENT }}
      />
      <span className="text-sm" style={{ color: "#94A3B8" }}>
        Generating image…
      </span>
    </div>
  );
}

function ImageResult({ data }) {
  return (
    <div
      data-testid="image-card"
      className={`${IMAGE_CARD} group`}
      style={{ background: "var(--surface-inset)" }}
    >
      <img
        src={data.url}
        alt={data.prompt}
        loading="lazy"
        className="w-full h-full object-cover"
      />
      <a
        href={data.url}
        target="_blank"
        rel="noreferrer"
        className="absolute inset-0 flex items-center justify-center gap-1.5 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity text-sm font-bold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
      >
        Open original <ExternalLink size={12} />
      </a>
    </div>
  );
}

function CloneConfirm({
  open,
  srcId,
  dstId,
  options,
  busy,
  onConfirm,
  onCancel,
}) {
  const cancelRef = useRef(null);
  const sections = [
    { key: "info", label: "Server info (name + icon)" },
    { key: "structure", label: "Structure (roles + categories + channels)" },
    { key: "emojis", label: "Emojis" },
  ];
  return (
    <Modal
      open={open}
      onClose={onCancel}
      role="alertdialog"
      label="Destructive Operation"
      maxWidthClass="max-w-md"
      panelClassName="p-6 flex flex-col gap-4"
      closeOnBackdrop={!busy}
      initialFocusRef={cancelRef}
      overlayStyle={{
        background: "rgba(0,0,0,0.85)",
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
      }}
      panelStyle={{
        background: "var(--surface-glass-strong)",
        borderColor: "#F23F4355",
      }}
    >
      <div className="flex items-center gap-3">
        <div
          className="p-2.5 rounded-xl shrink-0"
          style={{ background: "#F23F4322" }}
        >
          <AlertTriangle size={22} style={{ color: "#F23F43" }} />
        </div>
        <div>
          <div className="font-extrabold text-white text-base">
            Destructive Operation
          </div>
          <div className="text-sm mt-0.5" style={{ color: "#F87171" }}>
            Enabled sections in the target server will be overwritten.
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-2 text-sm">
        <div className="flex justify-between">
          <span style={{ color: "#94A3B8" }}>Source Guild:</span>
          <span className="font-mono" style={{ color: "#E2E8F0" }}>
            {srcId || "—"}
          </span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: "#94A3B8" }}>Target Guild:</span>
          <span className="font-mono font-bold" style={{ color: "#F23F43" }}>
            {dstId || "—"}
          </span>
        </div>
        <div
          className="pt-2 mt-1 border-t flex flex-col gap-1"
          style={{ borderColor: "var(--glass-border)" }}
        >
          <span className="text-xs font-semibold" style={{ color: "#94A3B8" }}>
            Will clone:
          </span>
          {sections.map(({ key, label }) => {
            const on = Boolean(options?.[key]);
            const Icon = on ? CheckCircle2 : X;
            return (
              <span
                key={key}
                className="flex items-center gap-1.5 text-sm"
                style={{ color: on ? "#23A55A" : "#94A3B8" }}
              >
                <Icon size={12} style={{ flexShrink: 0 }} />
                {label}
              </span>
            );
          })}
        </div>
      </div>
      <p className="text-sm" style={{ color: "#94A3B8" }}>
        <strong className="text-white">This is irreversible.</strong>
      </p>
      <div className="flex gap-2">
        <button
          onClick={onConfirm}
          disabled={busy}
          className="flex-1 py-2.5 text-sm font-bold rounded-xl text-white transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#1A1F2E]"
          style={{
            background: "linear-gradient(135deg,#F23F43,#C0392B)",
            boxShadow: "0 4px 16px rgba(242,63,67,0.35)",
            opacity: busy ? 0.6 : 1,
            cursor: busy ? "not-allowed" : "pointer",
          }}
        >
          {busy ? "Cloning…" : "Yes, Run .clone"}
        </button>
        <button
          ref={cancelRef}
          onClick={onCancel}
          disabled={busy}
          className="flex-1 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
          style={{ background: "#2D3748", color: "#E2E8F0" }}
        >
          Cancel
        </button>
      </div>
    </Modal>
  );
}

function utilityErrorMessage(err, fallback) {
  if (!(err instanceof ApiError)) return fallback;
  if (err.data?.error === "location_not_found") return "Location not found.";
  if (err.data?.error === "upstream_error")
    return "Weather service unavailable.";
  const details = Array.isArray(err.data?.details)
    ? err.data.details.filter(Boolean)
    : [];
  return details.length ? details.join(" · ") : err.message || fallback;
}

export default function UtilityFeature({ toast }) {
  const ACCENT = useAccent();
  const {
    loading: sessionLoading,
    authenticated,
    csrf,
    error: sessionError,
  } = useSessionContext();

  const [weatherLocation, setWeatherLocation] = useState("");
  const [weatherBusy, setWeatherBusy] = useState(false);
  const [weatherResult, setWeatherResult] = useState(null);
  const [weatherError, setWeatherError] = useState("");

  const [imagePrompt, setImagePrompt] = useState("");
  const [imageBusy, setImageBusy] = useState(false);
  const [imageResult, setImageResult] = useState(null);
  const [imageError, setImageError] = useState("");

  const [emojiSrc, setEmojiSrc] = useState("");
  const [emojiDst, setEmojiDst] = useState("");
  const [emojiIds, setEmojiIds] = useState("");
  const [emojiBusy, setEmojiBusy] = useState(false);
  const [emojiStatus, setEmojiStatus] = useState(null);
  const [emojiError, setEmojiError] = useState("");

  const [cloneSrc, setCloneSrc] = useState("");
  const [cloneDst, setCloneDst] = useState("");
  const [cloneOptions, setCloneOptions] = useState({
    info: true,
    structure: true,
    emojis: false,
  });
  const [cloneConfirm, setCloneConfirm] = useState(false);
  const [cloneBusy, setCloneBusy] = useState(false);
  const [cloneStatus, setCloneStatus] = useState(null);
  const [cloneError, setCloneError] = useState("");
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const canRun = authenticated && !sessionLoading && Boolean(csrf);

  const emojiState = emojiBusy
    ? "Running"
    : emojiError
      ? "Failed"
      : emojiStatus
        ? emojiStatus.applied === false
          ? "Offline"
          : "Done"
        : "Idle";
  const cloneState = cloneBusy
    ? "Running"
    : cloneError
      ? "Failed"
      : cloneStatus
        ? cloneStatus.applied === false
          ? "Offline"
          : "Done"
        : "Idle";

  const runWeather = async () => {
    if (!canRun || !csrf) {
      setWeatherError("Pair the dashboard first.");
      return;
    }
    if (!weatherLocation.trim()) {
      setWeatherError("Enter a city name or lat,lon.");
      return;
    }

    setWeatherBusy(true);
    setWeatherError("");
    setWeatherResult(null);
    try {
      const res = await api.utilityWeather(
        { location: weatherLocation.trim() },
        csrf,
      );
      setWeatherResult(res.data);
    } catch (err) {
      setWeatherError(utilityErrorMessage(err, "Could not load weather data."));
    } finally {
      setWeatherBusy(false);
    }
  };

  const runImage = async () => {
    if (!canRun || !csrf) {
      setImageError("Pair the dashboard first.");
      return;
    }
    if (!imagePrompt.trim()) {
      setImageError("Enter an image description.");
      return;
    }

    setImageBusy(true);
    setImageError("");
    setImageResult(null);
    try {
      const res = await api.utilityImage({ prompt: imagePrompt.trim() }, csrf);
      setImageResult(res.data);
    } catch (err) {
      setImageError(
        utilityErrorMessage(err, "Could not generate the image URL."),
      );
    } finally {
      setImageBusy(false);
    }
  };

  const runEmojiCopy = async () => {
    if (!canRun || !csrf) {
      setEmojiError("Pair the dashboard first.");
      return;
    }
    if (!emojiSrc.trim() || !emojiDst.trim()) {
      setEmojiError("Enter both source and target guild IDs.");
      return;
    }
    if (emojiSrc.trim() === emojiDst.trim()) {
      setEmojiError("Source and target must be different.");
      return;
    }

    const ids = emojiIds.split(/[\s,]+/).filter(Boolean);
    if (ids.some((id) => !/^\d+$/.test(id))) {
      setEmojiError("Emoji IDs must be numeric.");
      return;
    }

    setEmojiBusy(true);
    setEmojiError("");
    setEmojiStatus(null);
    try {
      const res = await api.utilityEmojiCopy(
        {
          source_id: emojiSrc.trim(),
          target_id: emojiDst.trim(),
          emoji_ids: ids,
        },
        csrf,
      );

      if (res.queued && res.request_id) {
        setEmojiStatus({
          status: "queued",
          message: "Emoji copy queued — waiting for the bot.",
        });
        toast.info("Emoji copy queued for the bot", "🛠️ Utility");

        const deadline = Date.now() + 5 * 60 * 1000;
        while (Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
          if (!mountedRef.current) return;

          let status;
          try {
            status = await api.getEmojiCopyStatus(res.request_id);
          } catch {
            continue;
          }
          if (!mountedRef.current) return;
          setEmojiStatus(status);

          if (status.status === "success") {
            toast.success("Emoji copy completed", "🛠️ Utility");
            return;
          }
          if (status.status === "error") {
            setEmojiError(status.message || "Emoji copy failed.");
            return;
          }
        }
        if (mountedRef.current) {
          setEmojiError("Emoji copy timed out while waiting for the bot.");
        }
      } else {
        setEmojiStatus(res);
        if (res.applied) {
          toast.success("Emoji copy completed", "🛠️ Utility");
        } else {
          toast.info("Not executed — bot offline", "🛠️ Utility");
        }
      }
    } catch (err) {
      setEmojiError(utilityErrorMessage(err, "Could not run emoji copy."));
    } finally {
      if (mountedRef.current) setEmojiBusy(false);
    }
  };

  const toggleCloneOption = (key) => {
    setCloneOptions((previous) => ({ ...previous, [key]: !previous[key] }));
    if (cloneError) setCloneError("");
  };

  const openCloneConfirm = () => {
    if (!canRun || !csrf) {
      setCloneError("Pair the dashboard first.");
      return;
    }
    if (!cloneSrc.trim() || !cloneDst.trim()) {
      setCloneError("Enter both source and target guild IDs.");
      return;
    }
    if (cloneSrc.trim() === cloneDst.trim()) {
      setCloneError("Source and target must be different.");
      return;
    }
    if (!cloneOptions.info && !cloneOptions.structure && !cloneOptions.emojis) {
      setCloneError("Select at least one clone option.");
      return;
    }
    setCloneError("");
    setCloneConfirm(true);
  };

  const runClone = async () => {
    setCloneConfirm(false);
    if (!canRun || !csrf) {
      setCloneError("Pair the dashboard first.");
      return;
    }

    setCloneBusy(true);
    setCloneError("");
    setCloneStatus(null);
    try {
      const res = await api.utilityClone(
        {
          source_id: cloneSrc.trim(),
          target_id: cloneDst.trim(),
          confirm: true,
          options: cloneOptions,
        },
        csrf,
      );

      if (res.queued && res.request_id) {
        setCloneStatus({
          status: "queued",
          message: "Clone queued — waiting for the bot.",
        });
        toast.info("Clone queued for the bot", "🛠️ Utility");

        const deadline = Date.now() + 20 * 60 * 1000;
        while (Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 2000));
          if (!mountedRef.current) return;

          let status;
          try {
            status = await api.getCloneStatus(res.request_id);
          } catch {
            continue;
          }
          if (!mountedRef.current) return;
          setCloneStatus(status);

          if (status.status === "success") {
            toast.success("Server clone completed", "🛠️ Utility");
            return;
          }
          if (status.status === "error") {
            setCloneError(status.message || "Clone failed.");
            return;
          }
        }
        if (mountedRef.current) {
          setCloneError("Clone timed out while waiting for the bot.");
        }
      } else {
        setCloneStatus(res);
        if (res.applied) {
          toast.success("Server clone completed", "🛠️ Utility");
        } else {
          toast.info("Not executed — bot offline", "🛠️ Utility");
        }
      }
    } catch (err) {
      setCloneError(
        utilityErrorMessage(err, "Could not run the server clone."),
      );
    } finally {
      if (mountedRef.current) setCloneBusy(false);
    }
  };

  return (
    <>
      <CloneConfirm
        open={cloneConfirm}
        srcId={cloneSrc}
        dstId={cloneDst}
        options={cloneOptions}
        busy={cloneBusy}
        onConfirm={runClone}
        onCancel={() => setCloneConfirm(false)}
      />

      <div className="flex flex-col gap-3">
        {sessionLoading && <Notice>Checking local session…</Notice>}

        {!sessionLoading && !authenticated && (
          <Notice tone="warn">
            {sessionError?.status === 0
              ? "Local API offline — start the backend."
              : "Pair the dashboard to run Utility actions."}
          </Notice>
        )}

        <FeatureHero
          icon={Wrench}
          title="Utility"
          emojiId={TG_EMOJI.tools}
          accent={ACCENT}
          stats={[
            {
              icon: CloudSun,
              label: "Weather",
              value: weatherBusy ? "Loading" : weatherResult ? "Ready" : "Idle",
              color: WEATHER_ACCENT,
            },
            {
              icon: ImageIcon,
              label: "Image",
              value: imageBusy ? "Loading" : imageResult ? "Ready" : "Idle",
              color: IMAGE_ACCENT,
            },
            {
              icon: CopyPlus,
              label: "Emoji copy",
              value: emojiState,
              color: ACCENT,
            },
            {
              icon: AlertTriangle,
              label: "Server clone",
              value: cloneState,
              color: CLONE_ACCENT,
            },
          ]}
        />

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 items-stretch">
          <div className="flex flex-col gap-3 min-w-0 h-full">
            <Panel icon={CloudSun} title="Weather" accent={WEATHER_ACCENT}>
              <div className="flex gap-2">
                <div className="flex-1 min-w-0">
                  <IconInput
                    icon={CloudSun}
                    value={weatherLocation}
                    onChange={(v) => {
                      setWeatherLocation(v);
                      if (weatherError) setWeatherError("");
                    }}
                    placeholder="City or lat,lon"
                    accent={WEATHER_ACCENT}
                  />
                </div>
                <RunButton
                  onClick={runWeather}
                  disabled={!canRun}
                  busy={weatherBusy}
                  icon={Play}
                  accent={WEATHER_ACCENT}
                >
                  Get
                </RunButton>
              </div>
              {weatherError && <InlineError>{weatherError}</InlineError>}
              {weatherBusy ? (
                <WeatherPlaceholder loading />
              ) : weatherResult ? (
                <WeatherResult data={weatherResult} />
              ) : (
                <WeatherPlaceholder />
              )}
            </Panel>

            <Panel
              icon={ImageIcon}
              title="Image Generator"
              accent={IMAGE_ACCENT}
              className="flex-1"
            >
              <div className="flex gap-2">
                <div className="flex-1 min-w-0">
                  <IconInput
                    icon={ImageIcon}
                    value={imagePrompt}
                    onChange={(v) => {
                      setImagePrompt(v);
                      if (imageError) setImageError("");
                    }}
                    placeholder="Describe the image…"
                    accent={IMAGE_ACCENT}
                  />
                </div>
                <RunButton
                  onClick={runImage}
                  disabled={!canRun}
                  busy={imageBusy}
                  icon={Play}
                  accent={IMAGE_ACCENT}
                >
                  Generate
                </RunButton>
              </div>
              {imageError && <InlineError>{imageError}</InlineError>}
              {imageBusy ? (
                <ImageLoading />
              ) : imageResult ? (
                <ImageResult data={imageResult} />
              ) : (
                <ImagePlaceholder />
              )}
            </Panel>
          </div>

          <div className="flex flex-col gap-3 min-w-0 h-full">
            <Panel icon={CopyPlus} title="Emoji Copy" accent={ACCENT}>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <GuildField
                  label="Source"
                  value={emojiSrc}
                  onChange={(v) => {
                    setEmojiSrc(v);
                    if (emojiError) setEmojiError("");
                  }}
                  accent={ACCENT}
                  placeholder="Emoji source guild ID"
                />
                <GuildField
                  label="Target"
                  value={emojiDst}
                  onChange={(v) => {
                    setEmojiDst(v);
                    if (emojiError) setEmojiError("");
                  }}
                  accent={ACCENT}
                  placeholder="Emoji target guild ID"
                />
              </div>
              <IconInput
                icon={Hash}
                value={emojiIds}
                onChange={(v) => {
                  setEmojiIds(v);
                  if (emojiError) setEmojiError("");
                }}
                placeholder="Emoji IDs (blank = all)"
                mono
                accent={ACCENT}
              />
              <button
                type="button"
                onClick={runEmojiCopy}
                disabled={!canRun || emojiBusy}
                className="flex items-center justify-center gap-2 text-sm font-bold px-4 py-2.5 rounded-xl transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117] w-full"
                style={{
                  background: `linear-gradient(135deg, ${ACCENT}, #059669)`,
                  color: "#fff",
                  border: `1px solid ${ACCENT}55`,
                  boxShadow: `0 4px 16px ${ACCENT}30`,
                  opacity: !canRun || emojiBusy ? 0.5 : 1,
                  cursor: !canRun || emojiBusy ? "not-allowed" : "pointer",
                }}
              >
                {emojiBusy ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Copy size={14} />
                )}{" "}
                {emojiBusy ? "Copying…" : "Copy Emojis"}
              </button>
              {emojiError && <InlineError>{emojiError}</InlineError>}
              <UtilityStatus status={emojiStatus} />
            </Panel>

            <Panel
              icon={AlertTriangle}
              title="Server Clone"
              accent={CLONE_ACCENT}
              danger
              className="flex-1"
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <GuildField
                  label="Source"
                  value={cloneSrc}
                  onChange={(v) => {
                    setCloneSrc(v);
                    if (cloneError) setCloneError("");
                  }}
                  accent={CLONE_ACCENT}
                  placeholder="Clone source guild ID"
                />
                <GuildField
                  label="Target"
                  value={cloneDst}
                  onChange={(v) => {
                    setCloneDst(v);
                    if (cloneError) setCloneError("");
                  }}
                  accent={CLONE_ACCENT}
                  placeholder="Clone target guild ID"
                />
              </div>
              <div className="flex flex-col">
                {[
                  { key: "info", icon: Info, label: "Server info" },
                  { key: "structure", icon: Server, label: "Structure" },
                  { key: "emojis", icon: Smile, label: "Emojis" },
                ].map(({ key, icon: Icon, label }) => (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-2 py-2 border-t first:border-t-0"
                    style={{ borderColor: "var(--glass-border)" }}
                  >
                    <div className="flex items-center gap-1.5 min-w-0">
                      <Icon
                        size={13}
                        style={{
                          color: cloneOptions[key] ? CLONE_ACCENT : "#94A3B8",
                          flexShrink: 0,
                        }}
                      />
                      <span
                        className="text-sm font-semibold truncate"
                        style={{
                          color: cloneOptions[key] ? "#E2E8F0" : "#94A3B8",
                        }}
                      >
                        {label}
                      </span>
                    </div>
                    <Toggle
                      enabled={cloneOptions[key]}
                      onChange={() => toggleCloneOption(key)}
                      size="sm"
                      label={`${label} clone option`}
                    />
                  </div>
                ))}
              </div>
              <div
                className="flex items-center gap-1.5 text-xs"
                style={{ color: "#F87171" }}
              >
                <AlertTriangle size={11} style={{ flexShrink: 0 }} />
                <span>Selected sections in target will be wiped.</span>
              </div>
              <button
                type="button"
                onClick={openCloneConfirm}
                disabled={!canRun || cloneBusy}
                className="flex items-center justify-center gap-2 text-sm font-bold px-4 py-2.5 rounded-xl transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117] w-full"
                style={{
                  background: cloneBusy
                    ? "#2D3748"
                    : `linear-gradient(135deg, ${CLONE_ACCENT}, #BE123C)`,
                  color: "#fff",
                  boxShadow: cloneBusy
                    ? "none"
                    : `0 4px 18px ${CLONE_ACCENT}35`,
                  opacity: !canRun || cloneBusy ? 0.6 : 1,
                  cursor: !canRun || cloneBusy ? "not-allowed" : "pointer",
                }}
              >
                {cloneBusy ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <AlertTriangle size={14} />
                )}{" "}
                {cloneBusy ? "Cloning…" : "Run .clone"}
              </button>
              {cloneError && <InlineError>{cloneError}</InlineError>}
              <UtilityStatus status={cloneStatus} />
            </Panel>
          </div>
        </div>
      </div>
    </>
  );
}
