"use client";
import { useEffect, useId, useRef, useState } from "react";
import {
  Activity,
  AlignLeft,
  Apple,
  Bot,
  Check,
  ChevronDown,
  Clock,
  Eye,
  Gamepad,
  Gamepad2,
  Glasses,
  Hash,
  Headphones,
  Image as ImageIcon,
  Link2,
  Loader2,
  MessageSquareText,
  Monitor,
  Music2,
  Plus,
  Power,
  Radio,
  Save,
  Smartphone,
  Timer,
  Trophy,
  Type,
  Video,
} from "lucide-react";
import Toggle from "../Toggle";
import { FeatureHero, Panel, ChoiceGrid, IconInput } from "../kit";
import { useAccent } from "../../../lib/theme";
import { useSessionContext } from "../../../lib/session";
import { api } from "../../../lib/api";
import { TG_EMOJI } from "../../../lib/tgEmoji";

const TYPES = [
  { value: "playing", label: "Playing", icon: Gamepad2 },
  { value: "listening", label: "Listening", icon: Headphones },
  { value: "watching", label: "Watching", icon: Eye },
  { value: "competing", label: "Competing", icon: Trophy },
  { value: "streaming", label: "Streaming", icon: Video },
];
const TYPE_OPTIONS = [
  ...TYPES,
  { value: "spotify", label: "Spotify", icon: Music2 },
];
const TYPE_ICONS = {
  playing: Gamepad2,
  listening: Headphones,
  watching: Eye,
  competing: Trophy,
  streaming: Video,
};

const PLATFORMS = [
  { value: "desktop", label: "Desktop", icon: Monitor },
  { value: "samsung", label: "Samsung", icon: Smartphone },
  { value: "ios", label: "iOS", icon: Apple },
  { value: "android", label: "Android", icon: Bot },
  { value: "xbox", label: "Xbox", icon: Gamepad2 },
  { value: "ps4", label: "PS4", icon: Gamepad },
  { value: "ps5", label: "PS5", icon: Gamepad },
  { value: "meta_quest", label: "Meta Quest", icon: Glasses },
  { value: "meta", label: "Meta", icon: Glasses },
  { value: "embedded", label: "Embedded", icon: Monitor },
];
const PLATFORM_CHOICES = [
  { value: "", label: "None", icon: Monitor },
  ...PLATFORMS,
];
// App-identity presets: each service carries its own Application ID, so
// picking one changes the card identity. This is separate from Platform,
// which spoofs the device instead.
const SERVICE_PRESETS = [
  { value: "none", label: "None", appId: "" },
  { value: "custom", label: "Custom", appId: null },
  {
    value: "xbox",
    label: "Xbox",
    appId: "438122941302046720",
    platform: "xbox",
    defaultImage: "https://cdn.simpleicons.org/xbox/107C10",
  },
  {
    value: "samsung",
    label: "Samsung / YouTube",
    appId: "463097721130188830",
    platform: "samsung",
    defaultImage: "https://cdn.simpleicons.org/samsung/1428A0",
  },
  {
    value: "vr",
    label: "VR",
    appId: "1142517036449517618",
    platform: "meta_quest",
    defaultImage: "https://cdn.simpleicons.org/meta/0467DF",
  },
  {
    value: "ytmusic",
    label: "YT Music",
    appId: "1055747806543183922",
    platform: "",
    defaultImage: "https://cdn.simpleicons.org/youtubemusic/FF0000",
  },
  {
    value: "crunchyroll",
    label: "Crunchyroll",
    appId: "981509069309354054",
    platform: "desktop",
    defaultImage: "https://cdn.simpleicons.org/crunchyroll/F47521",
  },
  {
    value: "playstation",
    label: "PlayStation",
    appId: "1008890871240179832",
    platform: "ps5",
    defaultImage: "https://cdn.simpleicons.org/playstation/003791",
  },
];
const TYPE_HINTS = {
  playing: "Playing card — Details is the first line, State the second.",
  listening: "Listening card — Album renders as the third line.",
  watching: "Watching card — End time adds a countdown badge.",
  competing: "Competing card — Details is the first line, State the second.",
  streaming: "Streaming card — purple LIVE card; the URL is required.",
};

const STATUSES = [
  { value: "online", label: "Online", dot: "#23A55A" },
  { value: "idle", label: "Idle", dot: "#F0B232" },
  { value: "dnd", label: "DND", dot: "#F23F43" },
  { value: "invisible", label: "Invisible", dot: "#80848E" },
];
const STATUS_COLORS = {
  online: "#23A55A",
  idle: "#F0B232",
  dnd: "#F23F43",
  invisible: "#80848E",
};

const DEFAULT_APPLICATION_ID = "1459720870787547359";
const NAME_MAX_LENGTH = 128;
const TEXT_MAX_LENGTH = 128;
const IMAGE_MAX_LENGTH = 2048;
const BUTTON_LABEL_MAX_LENGTH = 32;
const BUTTON_URL_MAX_LENGTH = 512;
const STREAM_URL_PREFIXES = [
  "https://twitch.tv/",
  "https://www.twitch.tv/",
  "https://youtube.com/",
  "https://www.youtube.com/",
];

function platformLabel(value) {
  if (!value) return "";
  return PLATFORMS.find((platform) => platform.value === value)?.label || "";
}

function serviceValueFor(appId) {
  const value = String(appId || "").trim();
  if (!value) return "none";
  const preset = SERVICE_PRESETS.find((item) => item.appId === value);
  return preset ? preset.value : "custom";
}

function CollapseSelect({
  name,
  options,
  value,
  onChange,
  accent = "#58B8E8",
  fallbackLabel = "None",
}) {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const wrapRef = useRef(null);
  const listId = useId();
  const optionId = (index) => `${listId}-option-${index}`;
  const selectedValue = value || "";
  const selectedIndex = options.findIndex(
    (option) => option.value === selectedValue,
  );

  const openList = (preferredIndex) => {
    const index = preferredIndex ?? (selectedIndex >= 0 ? selectedIndex : 0);
    setOpen(true);
    setHighlighted(Math.max(0, Math.min(options.length - 1, index)));
  };

  const closeList = () => {
    setOpen(false);
    setHighlighted(-1);
  };

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target)) {
        setOpen(false);
        setHighlighted(-1);
      }
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        setOpen(false);
        setHighlighted(-1);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const onTriggerKeyDown = (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        openList(event.key === "ArrowUp" ? options.length - 1 : undefined);
        return;
      }
      setHighlighted((prev) => {
        const current =
          prev < 0
            ? event.key === "ArrowDown"
              ? -1
              : options.length
            : prev;
        const next = event.key === "ArrowDown" ? current + 1 : current - 1;
        return Math.max(0, Math.min(options.length - 1, next));
      });
      return;
    }
    if (event.key === "Home" || event.key === "End") {
      if (!open) return;
      event.preventDefault();
      setHighlighted(event.key === "Home" ? 0 : options.length - 1);
      return;
    }
    if (event.key === "Enter" && open) {
      event.preventDefault();
      const option = options[highlighted];
      if (option) {
        onChange(option.value);
        closeList();
      }
    }
  };

  const current =
    options.find((option) => option.value === selectedValue)?.label ||
    fallbackLabel;

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={name}
        aria-activedescendant={
          open && highlighted >= 0 ? optionId(highlighted) : undefined
        }
        aria-controls={open ? listId : undefined}
        onClick={() => (open ? closeList() : openList())}
        onKeyDown={onTriggerKeyDown}
        className="w-full flex items-center justify-between gap-2 rounded-xl border px-3 py-2.5 text-sm outline-none transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-sky-400/70"
        style={{
          background: "var(--surface-inset)",
          borderColor: "var(--glass-border)",
          color: "#E2E8F0",
        }}
      >
        <span className="truncate">{current}</span>
        <ChevronDown
          size={14}
          style={{
            color: "#94A3B8",
            flexShrink: 0,
            transform: open ? "rotate(180deg)" : "none",
            transition: "transform 200ms ease",
          }}
        />
      </button>
      {open && (
        <div
          id={listId}
          role="listbox"
          aria-label={`${name} options`}
          className="absolute left-0 right-0 z-30 mt-1.5 rounded-xl border overflow-hidden"
          style={{
            background: "var(--surface-glass-strong)",
            borderColor: "var(--glass-border)",
            boxShadow: "0 12px 32px rgba(0,0,0,0.45)",
            backdropFilter: "blur(12px)",
          }}
        >
          <div className="max-h-[200px] overflow-y-auto flex flex-col py-1">
            {options.map((option, index) => {
              const selected = selectedValue === option.value;
              const active = highlighted === index;
              return (
                <button
                  key={option.value}
                  id={optionId(index)}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  tabIndex={-1}
                  onMouseEnter={() => setHighlighted(index)}
                  onClick={() => {
                    onChange(option.value);
                    closeList();
                  }}
                  className="flex items-center justify-between gap-2 px-3 py-2 text-left text-sm transition-colors duration-150 hover:bg-white/5"
                  style={{
                    background: selected
                      ? `${accent}14`
                      : active
                        ? "rgba(255,255,255,0.06)"
                        : "transparent",
                    color: selected ? "#E2E8F0" : "#B9C2D0",
                  }}
                >
                  <span className="truncate">{option.label}</span>
                  {selected && (
                    <Check
                      size={14}
                      style={{ color: accent, flexShrink: 0 }}
                    />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function sliceActivitiesForSpotify(activities) {
  return Array.isArray(activities) ? activities.slice(0, 2) : [];
}

function normalizeEntry(raw) {
  const entry = raw && typeof raw === "object" ? raw : {};
  return {
    enabled: entry.enabled !== false,
    mode: entry.mode === "spotify" ? "spotify" : "custom",
    status: STATUS_COLORS[entry.status] ? entry.status : "online",
    service: typeof entry.service === "string" ? entry.service : "",
    activities: Array.isArray(entry.activities)
      ? entry.activities.slice(0, 3)
      : [],
  };
}

function emptyDraft(type) {
  const draft = {
    type,
    name: "",
    details: "",
    state: "",
    application_id: DEFAULT_APPLICATION_ID,
    platform: "",
    large_image: "",
    large_text: "",
    small_image: "",
    small_text: "",
    buttons: [],
    show_elapsed: true,
    elapsed_hours: 1,
    show_end: false,
    end_minutes: 30,
    duration_minutes: 0,
    url: "",
  };
  if (type === "streaming") {
    return {
      ...draft,
      name: "Twitch",
      large_image: "https://cdn.simpleicons.org/twitch/9146FF",
      buttons: [{ label: "Watch Stream", url: "" }],
    };
  }
  return draft;
}

function emptySongDraft() {
  return { url: "", name: "", artist: "", duration: "", image: "" };
}

function formatSongDuration(ms) {
  const total = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function parseSongDuration(value) {
  const text = String(value ?? "").trim();
  if (!text) return 0;
  if (text.includes(":")) {
    const [minutes, seconds] = text.split(":");
    return (Number(minutes) || 0) * 60 + (Number(seconds) || 0);
  }
  const seconds = Number(text);
  return Number.isFinite(seconds) ? seconds : 0;
}

function songImageUrl(image) {
  const value = String(image || "").trim();
  if (!value) return "";
  if (/^https?:\/\//i.test(value)) return value;
  return `https://i.scdn.co/image/${value}`;
}

function extractSpotifyId(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const match = text.match(/\/track\/([A-Za-z0-9]+)/);
  return match ? match[1] : text;
}

function discordImageExpiry(url) {
  const text = String(url || "").trim();
  if (!text) return null;
  if (!/cdn\.discordapp\.com|media\.discordapp\.net/i.test(text)) return null;
  const match = text.match(/[?&]ex=([0-9a-fA-F]+)/);
  if (!match) return null;
  const timestamp = Number.parseInt(match[1], 16);
  if (!Number.isFinite(timestamp)) return null;
  const date = new Date(timestamp * 1000);
  if (Number.isNaN(date.getTime())) return null;
  return { date, expired: date.getTime() < Date.now() };
}

function isExternalImage(url) {
  const text = String(url || "").trim();
  if (!/^https?:\/\//i.test(text)) return false;
  return !/cdn\.discordapp\.com|media\.discordapp\.net/i.test(text);
}

function Thumb({ url, size = 64, round = false }) {
  const [err, setErr] = useState(false);
  useEffect(() => setErr(false), [url]);
  const radius = round ? "9999px" : "14px";
  if (!url || err) {
    return (
      <div
        className="flex items-center justify-center shrink-0"
        style={{
          width: size,
          height: size,
          borderRadius: radius,
          background: "var(--surface-inset)",
        }}
      >
        <ImageIcon size={size / 3} style={{ color: "#64748B" }} />
      </div>
    );
  }
  return (
    <img
      src={url}
      alt="preview"
      onError={() => setErr(true)}
      className="object-cover shrink-0"
      style={{ width: size, height: size, borderRadius: radius }}
    />
  );
}

function formatElapsed(totalSeconds) {
  const total = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

const TYPE_VERBS = {
  playing: "Playing",
  listening: "Listening to",
  watching: "Watching",
  competing: "Competing in",
  streaming: "Streaming",
};

function DiscordCard({ s }) {
  const ACCENT = useAccent();
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const total = (Number(s.duration) || 0) + elapsed;
  const plat = PLATFORMS.find((p) => p.label === s.platform);
  const PlatIcon = plat?.icon || Monitor;

  return (
    <div
      className="rounded-2xl overflow-hidden border"
      style={{ background: "#232428", borderColor: "#2d2f34" }}
    >
      <div
        className="h-20"
        style={{
          background: `linear-gradient(135deg, ${ACCENT}, #5865F2 60%, #23A55A)`,
        }}
      />
      <div className="px-4 pb-4">
        <div className="flex items-end justify-between -mt-9">
          <div className="relative">
            <img
              src="https://api.dicebear.com/8.x/bottts-neutral/svg?seed=shadowbyte&backgroundColor=5865F2"
              alt="avatar"
              className="w-[76px] h-[76px] rounded-full border-[5px]"
              style={{ borderColor: "#232428" }}
            />
            <span
              className="absolute w-5 h-5 rounded-full border-4"
              style={{
                background: STATUS_COLORS[s.status],
                borderColor: "#232428",
                bottom: 2,
                right: 2,
              }}
            />
          </div>
          {s.platform && s.type !== "streaming" && (
            <div
              className="flex items-center gap-1 px-2 py-1 rounded-lg mb-1"
              style={{ background: "#111214" }}
            >
              <PlatIcon size={12} style={{ color: "#CBD5E1" }} />
              <span
                className="text-xs font-semibold"
                style={{ color: "#CBD5E1" }}
              >
                {s.platform}
              </span>
            </div>
          )}
        </div>
        <div
          className="rounded-xl p-3 mt-3 flex flex-col gap-3"
          style={{
            background: "#111214",
            borderLeft:
              s.type === "streaming" ? "3px solid #9146FF" : undefined,
          }}
        >
          <div>
            <div className="text-lg font-bold text-white leading-tight">
              shadowbyte_exe
            </div>
            <div className="text-xs font-mono" style={{ color: "#CBD5E1" }}>
              1216388407337680936
            </div>
          </div>
          <div className="h-px" style={{ background: "#2E3035" }} />
          <div className="flex gap-3">
            <div className="relative shrink-0">
              {s.largeImage ? (
                <Thumb url={s.largeImage} size={68} />
              ) : (
                <div
                  className="w-[68px] h-[68px] rounded-xl flex items-center justify-center"
                  style={{
                    background: `linear-gradient(135deg, ${ACCENT}, #5865F2)`,
                  }}
                >
                  <Headphones size={26} color="#fff" />
                </div>
              )}
              {s.smallImage && (
                <div
                  className="absolute -bottom-1 -right-1 rounded-full border-[3px]"
                  style={{ borderColor: "#111214" }}
                >
                  <Thumb url={s.smallImage} size={22} round />
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1 text-xs flex flex-col gap-0.5">
              <div className="flex items-center gap-1.5 min-w-0">
                <div className="font-bold text-white truncate text-sm">
                  <span>{TYPE_VERBS[s.type] || "Playing"}</span>{" "}
                  <span>{s.name || "Activity"}</span>
                </div>
                {s.type === "streaming" && (
                  <span
                    className="text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0"
                    style={{ background: "#9146FF", color: "#fff" }}
                  >
                    LIVE
                  </span>
                )}
              </div>
              {s.details && (
                <div className="truncate text-sm" style={{ color: "#E2E8F0" }}>
                  {s.details}
                </div>
              )}
              {s.state && (
                <div className="truncate text-sm" style={{ color: "#E2E8F0" }}>
                  {s.state}
                </div>
              )}
              {s.type === "listening" && s.largeText && (
                <div className="truncate text-sm" style={{ color: "#E2E8F0" }}>
                  {s.largeText}
                </div>
              )}
              {s.type !== "streaming" && s.showElapsed && (
                <div
                  className="flex items-center gap-1 font-mono"
                  style={{ color: "#23A55A" }}
                >
                  <Clock size={10} /> {formatElapsed(total)}
                </div>
              )}
              {s.progressMinutes > 0 && (
                <div
                  data-testid="presence-progress-bar"
                  className="rounded-full overflow-hidden"
                  style={{ background: "#2E3035", height: 4 }}
                >
                  <div
                    data-testid="presence-progress-fill"
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.min(
                        100,
                        (total / (s.progressMinutes * 60)) * 100,
                      )}%`,
                      background: "#23A55A",
                    }}
                  />
                </div>
              )}
              {(s.type === "listening" || s.type === "watching") &&
                s.showEnd &&
                !(s.progressMinutes > 0) && (
                  <div
                    className="flex items-center gap-1 font-mono"
                    style={{ color: "#F5B642" }}
                  >
                    ⏳{" "}
                    {formatElapsed(
                      Math.max(
                        0,
                        (Number(s.endMinutes) || 30) * 60 - elapsed,
                      ),
                    )}{" "}
                    left
                  </div>
                )}
            </div>
          </div>
          {s.type !== "streaming" &&
            [s.btn1Label, s.btn2Label].filter(Boolean).map((l, index) => (
              <button
                key={index}
                className="w-full text-sm font-semibold py-2 rounded-md transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                style={{ background: "#4E5058", color: "#fff" }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.background = "#6D6F78")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.background = "#4E5058")
                }
              >
                {l}
              </button>
            ))}
        </div>
      </div>
    </div>
  );
}

function RowButton({ children, onClick, danger = false, disabled = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="text-xs font-semibold px-2.5 py-1.5 rounded-lg border transition-all duration-200 ease-[var(--ease-out)] hover:brightness-110 active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
      style={{
        background: danger ? "#F23F4312" : "var(--surface-inset)",
        borderColor: danger ? "#F23F4335" : "var(--glass-border)",
        color: danger ? "#F23F43" : "#94A3B8",
      }}
    >
      {children}
    </button>
  );
}

export default function RichPresenceFeature({ toast }) {
  const ACCENT = useAccent();
  const session = useSessionContext();
  const [entry, setEntry] = useState(() => normalizeEntry(null));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [addingType, setAddingType] = useState(null);
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState(null);
  const [songs, setSongs] = useState([]);
  const [songsLoading, setSongsLoading] = useState(true);
  const [songFormOpen, setSongFormOpen] = useState(false);
  const [songDraft, setSongDraft] = useState(emptySongDraft);
  const [resolving, setResolving] = useState(false);
  const [savingSongs, setSavingSongs] = useState(false);
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [fetchingYouTube, setFetchingYouTube] = useState(false);
  const [uploadingImage, setUploadingImage] = useState(null);
  const mountedRef = useRef(true);
  const buttonKeyRef = useRef(0);
  const lastCustomAppIdRef = useRef(DEFAULT_APPLICATION_ID);
  const largeImageInputRef = useRef(null);
  const smallImageInputRef = useRef(null);

  useEffect(() => {
    if (session.loading) return;
    if (!session.authenticated) {
      setLoading(false);
      return;
    }
    mountedRef.current = true;
    setLoading(true);
    let cancelled = false;
    (async () => {
      try {
        const data = await api.getPresenceConfig();
        if (!mountedRef.current || cancelled) return;
        setEntry(normalizeEntry(data?.config));
      } catch (err) {
        if (mountedRef.current && !cancelled) {
          toast?.error?.(
            err?.message || "Could not load rich presence.",
            "Rich Presence",
          );
        }
      } finally {
        if (mountedRef.current && !cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      mountedRef.current = false;
    };
  }, [session.loading, session.authenticated]);

  useEffect(() => {
    if (session.loading) return;
    if (!session.authenticated) {
      setSongsLoading(false);
      return;
    }
    setSongsLoading(true);
    let cancelled = false;
    (async () => {
      try {
        const data = await api.getSongs();
        if (!mountedRef.current || cancelled) return;
        setSongs(Array.isArray(data?.songs) ? data.songs : []);
      } catch (err) {
        if (mountedRef.current && !cancelled) {
          toast?.error?.(
            err?.message || "Could not load Spotify songs.",
            "Rich Presence",
          );
        }
      } finally {
        if (mountedRef.current && !cancelled) setSongsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [session.loading, session.authenticated]);

  const pairingRequired = () => {
    if (session.authenticated && session.csrf) return false;
    toast?.error?.("Pair the dashboard first.", "Rich Presence");
    return true;
  };

  const updateEntry = (patch) => {
    setEntry((prev) => ({ ...prev, ...patch }));
  };

  const nextButtonKey = () => {
    buttonKeyRef.current += 1;
    return buttonKeyRef.current;
  };

  const cancelForm = () => {
    setDraft(null);
    setEditing(null);
    setAddingType(null);
  };

  const openAdd = () => {
    setEditing(null);
    setDraft(null);
    setAddingType("picker");
  };

  const chooseType = (type) => {
    if (type === "spotify") {
      if (entry.activities.length > 2) {
        toast?.error?.(
          "Spotify mode keeps at most 2 custom presences — remove one first.",
          "Rich Presence",
        );
        return;
      }
      setEntry((prev) => ({
        ...prev,
        mode: "spotify",
        activities: sliceActivitiesForSpotify(prev.activities),
      }));
      cancelForm();
      return;
    }
    if (entry.activities.some((activity) => activity?.type === type)) {
      toast?.error?.(
        "This type is already in use — Discord shows only one activity per type.",
        "Rich Presence",
      );
      return;
    }
    setDraft(emptyDraft(type));
    setAddingType(null);
    setEditing(null);
  };

  const openEdit = (index) => {
    const activity = entry.activities[index];
    if (!activity) return;
    const hasProgress = Number(activity.duration_minutes) > 0;
    setDraft({
      ...emptyDraft(activity.type || "playing"),
      ...activity,
      ...(hasProgress ? { show_elapsed: true } : {}),
      buttons: Array.isArray(activity.buttons)
        ? activity.buttons.slice(0, 2).map((button) => ({
            key: nextButtonKey(),
            label: button?.label || "",
            url: button?.url || "",
          }))
        : [],
    });
    setEditing(index);
    setAddingType(null);
  };

  const deleteActivity = (index) => {
    setEntry((prev) => ({
      ...prev,
      activities: prev.activities.filter((_, i) => i !== index),
    }));
    if (editing === index) {
      cancelForm();
    } else if (editing !== null && editing > index) {
      setEditing(editing - 1);
    }
  };

  const updDraft = (key) => (value) => {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  const toggleProgress = (enabled) => {
    setDraft((prev) => {
      if (!prev) return prev;
      if (!enabled) {
        return { ...prev, duration_minutes: 0 };
      }
      const current = Number(prev.duration_minutes) || 0;
      return {
        ...prev,
        duration_minutes: current > 0 ? current : 30,
        show_elapsed: true,
      };
    });
  };

  const chooseService = (value) => {
    const preset = SERVICE_PRESETS.find((item) => item.value === value);
    if (!preset) return;
    setDraft((prev) => {
      if (!prev) return prev;
      if (value === "custom") {
        const current = String(prev.application_id || "").trim();
        const isPreset = SERVICE_PRESETS.some(
          (item) => item.appId && item.appId === current,
        );
        return {
          ...prev,
          application_id:
            current && !isPreset
              ? current
              : lastCustomAppIdRef.current || DEFAULT_APPLICATION_ID,
        };
      }
      const hasPlatform = String(prev.platform ?? "").trim() !== "";
      const hasImage = String(prev.large_image ?? "").trim() !== "";
      return {
        ...prev,
        application_id: preset.appId,
        platform: hasPlatform
          ? prev.platform
          : preset.platform ?? prev.platform,
        large_image: hasImage
          ? prev.large_image
          : preset.defaultImage ?? prev.large_image,
      };
    });
  };

  const updateApplicationId = (value) => {
    const trimmed = String(value || "").trim();
    const isPreset = SERVICE_PRESETS.some(
      (item) => item.appId && item.appId === trimmed,
    );
    if (trimmed && !isPreset) {
      lastCustomAppIdRef.current = trimmed;
    }
    updDraft("application_id")(value);
  };

  const setButton = (index, key, value) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const buttons = [...(prev.buttons || [])];
      buttons[index] = {
        ...(buttons[index] || { label: "", url: "" }),
        [key]: value,
      };
      return { ...prev, buttons };
    });
  };

  const addButton = () => {
    const key = nextButtonKey();
    setDraft((prev) => {
      if (!prev || (prev.buttons?.length || 0) >= 2) return prev;
      return {
        ...prev,
        buttons: [...(prev.buttons || []), { key, label: "", url: "" }],
      };
    });
  };

  const removeButton = (index) => {
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            buttons: (prev.buttons || []).filter((_, i) => i !== index),
          }
        : prev,
    );
  };

  const saveDraft = () => {
    if (!draft) return;
    if (!String(draft.name ?? "").trim()) {
      toast?.error?.("Give this presence a name first.", "Rich Presence");
      return;
    }
    const streamUrl =
      draft.type === "streaming" ? String(draft.url ?? "").trim() : "";
    if (draft.type === "streaming") {
      if (!streamUrl) {
        toast?.error?.(
          "Streaming activities need a Twitch or YouTube URL.",
          "Rich Presence",
        );
        return;
      }
      if (!STREAM_URL_PREFIXES.some((prefix) => streamUrl.startsWith(prefix))) {
        toast?.error?.(
          "Stream URLs must start with https://twitch.tv/, https://www.twitch.tv/, https://youtube.com/ or https://www.youtube.com/.",
          "Rich Presence",
        );
        return;
      }
    }
    const applicationId = String(draft.application_id ?? "");
    if (applicationId !== "" && !/^[0-9]+$/.test(applicationId)) {
      toast?.error?.(
        "Application ID must contain digits only.",
        "Rich Presence",
      );
      return;
    }
    const cleanDraft = {
      ...draft,
      buttons: (draft.buttons || [])
        .map((button) => {
          const label = String(button?.label ?? "").trim();
          const url = String(button?.url ?? "").trim();
          if (
            draft.type === "streaming" &&
            label === "Watch Stream" &&
            url === ""
          ) {
            return { ...button, url: streamUrl };
          }
          return button;
        })
        .filter(
          (button) =>
            String(button?.label ?? "").trim() !== "" &&
            String(button?.url ?? "").trim() !== "",
        )
        .map((button) => ({
          label: String(button.label ?? "").trim(),
          url: String(button.url ?? "").trim(),
        })),
    };
    setEntry((prev) => {
      const activities = [...prev.activities];
      if (editing !== null && editing >= 0 && editing < activities.length) {
        activities[editing] = cleanDraft;
      } else if (activities.length < (prev.mode === "spotify" ? 2 : 3)) {
        activities.push(cleanDraft);
      }
      return {
        ...prev,
        enabled: editing === null ? true : prev.enabled,
        activities,
      };
    });
    cancelForm();
  };

  const handleApply = async () => {
    if (pairingRequired()) return;
    if (saving) return;
    if (entry.enabled && duplicateTypeCount > 0) {
      toast?.error?.(
        "Discord shows only one activity per type — fix the duplicates before applying.",
        "Rich Presence",
      );
      return;
    }
    if (entry.mode === "custom" && entry.activities.length === 0) {
      toast?.error?.(
        "Nothing to apply — add a presence first.",
        "Rich Presence",
      );
      return;
    }
    if (entry.mode === "spotify" && songs.length === 0) {
      toast?.error?.(
        "Add at least one Spotify song before applying.",
        "Rich Presence",
      );
      return;
    }
    setSaving(true);
    try {
      await api.savePresenceConfig({ config: entry }, session.csrf);
      await api.applyPresence({}, session.csrf);
      if (mountedRef.current) {
        toast?.success?.("Presence applied.", "Rich Presence");
      }
    } catch (err) {
      if (mountedRef.current) {
        toast?.error?.(
          err?.message || "Could not apply presence.",
          "Rich Presence",
        );
      }
    } finally {
      if (mountedRef.current) setSaving(false);
    }
  };

  const handleStop = async () => {
    if (pairingRequired()) return;
    if (saving) return;
    setSaving(true);
    try {
      await api.clearPresence({}, session.csrf);
      if (mountedRef.current) {
        toast?.info?.("Presence stopped.", "Rich Presence");
      }
    } catch (err) {
      if (mountedRef.current) {
        toast?.error?.(
          err?.message || "Could not stop presence.",
          "Rich Presence",
        );
      }
    } finally {
      if (mountedRef.current) setSaving(false);
    }
  };

  const updateSongDraft = (key) => (value) => {
    setSongDraft((prev) => ({ ...prev, [key]: value }));
  };

  const openSongForm = () => {
    setSongDraft(emptySongDraft());
    setSongFormOpen(true);
  };

  const closeSongForm = () => {
    setSongDraft(emptySongDraft());
    setSongFormOpen(false);
  };

  const handleResolveSong = async () => {
    if (pairingRequired()) return;
    const url = songDraft.url.trim();
    if (!url || resolving) return;
    setResolving(true);
    try {
      const data = await api.resolveSong({ url }, session.csrf);
      const song = data?.song;
      if (!song) throw new Error("resolve_failed");
      if (!mountedRef.current) return;
      setSongDraft((prev) => ({
        ...prev,
        name: song.name || prev.name,
        artist: song.artist || prev.artist,
        duration: song.duration_ms
          ? formatSongDuration(song.duration_ms)
          : prev.duration,
        image: song.image || prev.image,
      }));
    } catch (err) {
      if (mountedRef.current) {
        toast?.error?.(
          err?.message || "Could not fetch song details.",
          "Rich Presence",
        );
      }
    } finally {
      if (mountedRef.current) setResolving(false);
    }
  };

  const handleFetchYouTube = async () => {
    if (pairingRequired()) return;
    const url = youtubeUrl.trim();
    if (!url) {
      toast?.error?.("Paste a YouTube URL first.", "Rich Presence");
      return;
    }
    if (fetchingYouTube) return;
    setFetchingYouTube(true);
    try {
      const data = await api.resolveYouTube({ url }, session.csrf);
      const video = data?.video;
      if (!video) throw new Error("Could not fetch YouTube details.");
      if (!mountedRef.current) return;
      setDraft((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          name: String(prev.name ?? "").trim()
            ? prev.name
            : video.title || prev.name,
          details: String(prev.details ?? "").trim()
            ? prev.details
            : video.channel || prev.details,
          large_image: String(prev.large_image ?? "").trim()
            ? prev.large_image
            : video.image || prev.large_image,
        };
      });
      toast?.success?.("YouTube details filled.", "Rich Presence");
    } catch (err) {
      if (mountedRef.current) {
        toast?.error?.(
          err?.message || "Could not fetch YouTube details.",
          "Rich Presence",
        );
      }
    } finally {
      if (mountedRef.current) setFetchingYouTube(false);
    }
  };

  const handleImageFile = (field) => (event) => {
    if (pairingRequired()) return;
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 700 * 1024) {
      toast?.error?.("Image must be 700 KB or smaller.", "Rich Presence");
      return;
    }
    setUploadingImage(field);
    const reader = new FileReader();
    reader.onload = async () => {
      if (!mountedRef.current) return;
      try {
        const result = String(reader.result || "");
        const base64 = result.includes(",")
          ? result.slice(result.indexOf(",") + 1)
          : result;
        const data = await api.uploadPresenceImage(
          { filename: file.name, data: base64 },
          session.csrf,
        );
        if (!mountedRef.current) return;
        if (!data?.url) throw new Error("Could not upload the image.");
        setDraft((prev) => (prev ? { ...prev, [field]: data.url } : prev));
        toast?.success?.("Image uploaded.", "Rich Presence");
      } catch (err) {
        if (mountedRef.current) {
          toast?.error?.(
            err?.message || "Could not upload the image.",
            "Rich Presence",
          );
        }
      } finally {
        if (mountedRef.current) setUploadingImage(null);
      }
    };
    reader.onerror = () => {
      if (mountedRef.current) {
        setUploadingImage(null);
        toast?.error?.("Could not upload the image.", "Rich Presence");
      }
    };
    reader.readAsDataURL(file);
  };

  const handleAddSong = async () => {
    if (pairingRequired()) return;
    if (savingSongs) return;
    const name = songDraft.name.trim();
    const durationSeconds = parseSongDuration(songDraft.duration);
    if (!name || durationSeconds <= 0) {
      toast?.error?.(
        "Add a song name and a duration greater than zero.",
        "Rich Presence",
      );
      return;
    }
    const id = extractSpotifyId(songDraft.url);
    if (id && songs.some((song) => song.id === id)) {
      toast?.error?.("This song is already in the list.", "Rich Presence");
      return;
    }
    const song = {
      name,
      artist: songDraft.artist.trim(),
      id,
      duration_ms: Math.round(durationSeconds * 1000),
      image: songDraft.image.trim(),
    };
    const next = [...songs, song];
    setSavingSongs(true);
    try {
      await api.saveSongs({ songs: next }, session.csrf);
      if (!mountedRef.current) return;
      setSongs(next);
      closeSongForm();
      toast?.success?.("Song added.", "Rich Presence");
    } catch (err) {
      if (mountedRef.current) {
        toast?.error?.(
          err?.message || "Could not save songs.",
          "Rich Presence",
        );
      }
    } finally {
      if (mountedRef.current) setSavingSongs(false);
    }
  };

  const handleDeleteSong = async (index) => {
    if (pairingRequired()) return;
    if (savingSongs) return;
    const previous = songs;
    const next = songs.filter((_, i) => i !== index);
    setSongs(next);
    setSavingSongs(true);
    try {
      await api.saveSongs({ songs: next }, session.csrf);
      if (mountedRef.current) {
        toast?.success?.("Song removed.", "Rich Presence");
      }
    } catch (err) {
      if (mountedRef.current) {
        setSongs(previous);
        toast?.error?.(
          err?.message || "Could not save songs.",
          "Rich Presence",
        );
      }
    } finally {
      if (mountedRef.current) setSavingSongs(false);
    }
  };

  const spotifySong =
    entry.mode === "spotify" && songs.length > 0 ? songs[0] : null;
  const previewSource = draft || entry.activities[0] || null;
  const previewButtons = Array.isArray(previewSource?.buttons)
    ? previewSource.buttons
    : [];
  const elapsedHours = Number(previewSource?.elapsed_hours);
  const preview = spotifySong
    ? {
        type: "listening",
        name: "Spotify",
        details: spotifySong.name || "",
        state: spotifySong.artist ? `by ${spotifySong.artist}` : "",
        platform: "Desktop",
        status: entry.status,
        showElapsed: true,
        duration: (Number(spotifySong.duration_ms) || 210000) / 1000,
        largeImage: songImageUrl(spotifySong.image),
        largeText: "",
        smallImage: "",
        btn1Label: "",
        btn2Label: "",
      }
    : {
        type: previewSource?.type || "playing",
        name: previewSource?.name || "Discord",
        details: previewSource?.details || "",
        state: previewSource?.state || "",
        platform: platformLabel(previewSource?.platform),
        status: entry.status,
        showElapsed: previewSource?.show_elapsed ?? true,
        showEnd: previewSource?.show_end === true,
        endMinutes: Number(previewSource?.end_minutes) || 30,
        duration: (Number.isFinite(elapsedHours) ? elapsedHours : 1) * 3600,
        progressMinutes: Number(previewSource?.duration_minutes) || 0,
        largeImage: previewSource?.large_image || "",
        largeText: previewSource?.large_text || "",
        smallImage: previewSource?.small_image || "",
        btn1Label: previewButtons[0]?.label || "",
        btn2Label: previewButtons[1]?.label || "",
      };

  const formOpen = Boolean(addingType) || editing !== null || draft !== null;
  const duplicateTypeCount =
    entry.activities.length > 1
      ? entry.activities.filter(
          (activity, index) =>
            entry.activities.findIndex(
              (other) => other?.type === activity?.type,
            ) !== index,
        ).length
      : 0;
  const activityAppIds = entry.activities
    .map((activity) => activity?.application_id)
    .filter(Boolean);
  const hasSharedAppId =
    activityAppIds.length !== new Set(activityAppIds).size;
  const invalidService =
    typeof entry.service === "string" &&
    entry.service !== "" &&
    !PLATFORMS.some((platform) => platform.value === entry.service)
      ? entry.service
      : "";
  const isStreaming = draft?.type === "streaming";
  const showButtons = Boolean(draft) && !isStreaming;
  const showElapsed = Boolean(draft) && !isStreaming;
  const elapsedEnabled = draft?.show_elapsed !== false;
  const progressEnabled = Number(draft?.duration_minutes) > 0;
  const showLargeText = Boolean(draft) && !isStreaming;
  const showSmallText = Boolean(draft);
  const imageWarnings = draft
    ? [draft.large_image, draft.small_image]
        .map(discordImageExpiry)
        .filter(Boolean)
    : [];
  const externalImageHint = Boolean(
    draft &&
      (isExternalImage(draft.large_image) ||
        isExternalImage(draft.small_image)),
  );

  return (
    <div className="flex flex-col gap-3">
      <FeatureHero
        icon={Radio}
        title="Rich Presence"
        emojiId={TG_EMOJI.sparkle}
        accent={ACCENT}
        stats={[
          {
            icon: Activity,
            label: "Presences",
            value:
              entry.mode === "spotify"
                ? "Spotify"
                : String(entry.activities.length),
            color: "#58B8E8",
          },
          {
            icon: Music2,
            label: "Mode",
            value: entry.mode === "spotify" ? "Spotify" : "Custom",
            color: entry.mode === "spotify" ? "#1DB954" : "#F5B642",
          },
          {
            icon: Radio,
            label: "Status",
            value: entry.status.toUpperCase(),
            color: STATUS_COLORS[entry.status] || "#80848E",
          },
        ]}
      />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 items-start">
        <div className="flex flex-col gap-3 min-w-0">
          <Panel
            icon={Activity}
            title={`Presences (${entry.activities.length}/${
              entry.mode === "spotify" ? 2 : 3
            })`}
            accent={ACCENT}
            action={
              <button
                type="button"
                onClick={openAdd}
                disabled={
                  loading ||
                  saving ||
                  entry.activities.length >=
                    (entry.mode === "spotify" ? 2 : 3)
                }
                className="text-xs font-bold px-2.5 py-1.5 rounded-lg border transition-all duration-200 ease-[var(--ease-out)] hover:brightness-110 active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                style={{
                  background: `${ACCENT}18`,
                  color: ACCENT,
                  borderColor: `${ACCENT}40`,
                }}
              >
                + Add presence
              </button>
            }
          >
            {loading ? (
              <div
                className="flex items-center gap-2 text-sm py-2"
                style={{ color: "#94A3B8" }}
              >
                <Loader2 size={16} className="animate-spin" />
                Loading presences…
              </div>
            ) : (
              <div className="flex flex-col gap-2" data-testid="presence-list">
                {entry.mode === "spotify" && (
                  <div
                    className="flex items-center gap-3 rounded-xl border p-3"
                    style={{
                      background: "var(--surface-inset)",
                      borderColor: "var(--glass-border)",
                    }}
                  >
                    <div
                      className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                      style={{ background: "#1DB95420" }}
                    >
                      <Music2 size={18} style={{ color: "#1DB954" }} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-bold text-white">Spotify</div>
                      <div className="text-xs" style={{ color: "#94A3B8" }}>
                        Uses songs.json
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <RowButton
                        danger
                        onClick={() => updateEntry({ mode: "custom" })}
                      >
                        Remove
                      </RowButton>
                    </div>
                  </div>
                )}
                {entry.mode !== "spotify" && entry.activities.length === 0 && (
                  <p className="text-sm" style={{ color: "#94A3B8" }}>
                    No presences yet. Add one to show an activity on Discord.
                  </p>
                )}
                {entry.activities.map((activity, index) => {
                    const Icon = TYPE_ICONS[activity?.type] || Gamepad2;
                    const secondary =
                      [activity?.details, activity?.state]
                        .filter(Boolean)
                        .join(" · ") ||
                      TYPES.find((type) => type.value === activity?.type)?.label ||
                      "Activity";
                    return (
                      <div
                        key={index}
                        className="flex items-center gap-3 rounded-xl border p-2.5"
                        style={{
                          background: "var(--surface-inset)",
                          borderColor: "var(--glass-border)",
                        }}
                      >
                        <div
                          className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                          style={{ background: `${ACCENT}18` }}
                        >
                          <Icon size={16} style={{ color: ACCENT }} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-bold text-white truncate">
                            {activity?.name || "Untitled presence"}
                          </div>
                          <div
                            className="text-xs truncate"
                            style={{ color: "#94A3B8" }}
                          >
                            {secondary}
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <RowButton
                            onClick={() => openEdit(index)}
                            disabled={saving}
                          >
                            Edit
                          </RowButton>
                          <RowButton
                            danger
                            onClick={() => deleteActivity(index)}
                            disabled={saving}
                          >
                            Delete
                          </RowButton>
                        </div>
                      </div>
                    );
                  })}
                {duplicateTypeCount > 0 && (
                  <p className="text-xs" style={{ color: "#F5B642" }}>
                    Discord only shows one activity per type — switch duplicate
                    types to display every presence.
                  </p>
                )}
                {hasSharedAppId && (
                  <p className="text-xs" style={{ color: "#F5B642" }}>
                    Presences share one Application ID — Discord shows one card
                    per app. Give each presence its own ID, or leave one empty.
                  </p>
                )}
                {invalidService && (
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs" style={{ color: "#F5B642" }}>
                      {`Stored service "${invalidService}" is not supported — Apply will fail until it is cleared.`}
                    </p>
                    <RowButton onClick={() => updateEntry({ service: "" })}>
                      Clear service
                    </RowButton>
                  </div>
                )}
                {entry.mode === "custom" &&
                  entry.activities.length >= 2 &&
                  duplicateTypeCount === 0 && (
                    <p className="text-xs" style={{ color: "#94A3B8" }}>
                      Discord shows only the first custom card — switch to
                      Spotify mode to display two.
                    </p>
                  )}
                <div className="flex items-center gap-2 pt-1">
                  <button
                    type="button"
                    onClick={handleApply}
                    disabled={saving || loading}
                    className="flex-1 flex items-center justify-center gap-2 text-sm font-bold px-4 py-2.5 rounded-xl transition-all duration-200 ease-[var(--ease-out)] hover:brightness-110 active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                    style={{
                      background: ACCENT,
                      color: "#0B0E14",
                      boxShadow: `0 4px 16px ${ACCENT}50`,
                    }}
                  >
                    {saving ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Check size={14} />
                    )}
                    Apply
                  </button>
                  <button
                    type="button"
                    onClick={handleStop}
                    disabled={saving || loading}
                    className="flex items-center gap-2 text-sm font-bold px-3.5 py-2.5 rounded-xl border transition-all duration-200 ease-[var(--ease-out)] hover:brightness-110 active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                    style={{
                      background: "#F23F4312",
                      borderColor: "#F23F4335",
                      color: "#F23F43",
                    }}
                  >
                    <Power size={14} />
                    Stop presence
                  </button>
                </div>
              </div>
            )}
          </Panel>

          {formOpen && (
            <Panel
              icon={draft ? TYPE_ICONS[draft.type] || Gamepad2 : Plus}
              title={
                draft
                  ? editing !== null
                    ? "Edit presence"
                    : "New presence"
                  : "Add presence"
              }
              accent={ACCENT}
            >
              {addingType !== null && !draft ? (
                <div className="flex flex-col gap-2">
                  <p className="text-xs" style={{ color: "#94A3B8" }}>
                    Choose the type of presence to add.
                  </p>
                  <ChoiceGrid
                    options={TYPE_OPTIONS}
                    value={null}
                    onChange={chooseType}
                    accent={ACCENT}
                    cols={3}
                  />
                </div>
              ) : draft ? (
                <>
                  {editing !== null && (
                    <div className="flex flex-col gap-1.5">
                      <span
                        className="text-xs font-semibold"
                        style={{ color: "#94A3B8" }}
                      >
                        Type
                      </span>
                      <ChoiceGrid
                        options={TYPES.filter(
                          (type) =>
                            type.value === draft.type ||
                            !entry.activities.some(
                              (activity, index) =>
                                index !== editing &&
                                activity?.type === type.value,
                            ),
                        )}
                        value={draft.type}
                        onChange={updDraft("type")}
                        accent={ACCENT}
                        cols={5}
                      />
                    </div>
                  )}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <IconInput
                      icon={Type}
                      value={draft.name}
                      onChange={updDraft("name")}
                      placeholder="Name"
                      maxLength={NAME_MAX_LENGTH}
                      accent={ACCENT}
                    />
                    <IconInput
                      icon={AlignLeft}
                      value={draft.details}
                      onChange={updDraft("details")}
                      placeholder={
                        isStreaming
                          ? "Details — stream title"
                          : "Details — line 1"
                      }
                      maxLength={TEXT_MAX_LENGTH}
                      accent={ACCENT}
                    />
                    <IconInput
                      icon={MessageSquareText}
                      value={draft.state}
                      onChange={updDraft("state")}
                      placeholder={
                        isStreaming
                          ? "State — channel name"
                          : "State — line 2"
                      }
                      maxLength={TEXT_MAX_LENGTH}
                      accent={ACCENT}
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <p className="text-xs" style={{ color: "#64748B" }}>
                      Header shows:{" "}
                      <span style={{ color: "#E2E8F0" }}>
                        {TYPE_VERBS[draft.type] || "Playing"}{" "}
                        {draft.name || "…"}
                      </span>
                    </p>
                    <p className="text-xs" style={{ color: "#64748B" }}>
                      {TYPE_HINTS[draft.type] || TYPE_HINTS.playing}
                    </p>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <span
                      className="text-xs font-semibold"
                      style={{ color: "#94A3B8" }}
                    >
                      Service
                    </span>
                    <CollapseSelect
                      name="Service"
                      options={SERVICE_PRESETS}
                      value={serviceValueFor(draft.application_id)}
                      onChange={chooseService}
                      accent="#B48CF2"
                    />
                    <p className="text-xs" style={{ color: "#64748B" }}>
                      App identity — each service carries its own Application
                      ID. Different IDs render separate cards.
                    </p>
                  </div>
                  {serviceValueFor(draft.application_id) === "custom" ? (
                    <IconInput
                      icon={Hash}
                      value={draft.application_id}
                      onChange={updateApplicationId}
                      placeholder="Application ID"
                      mono
                      accent={ACCENT}
                    />
                  ) : draft.application_id ? (
                    <p
                      className="text-xs font-mono"
                      style={{ color: "#64748B" }}
                    >
                      Application ID: {draft.application_id}
                    </p>
                  ) : null}
                  {isStreaming && (
                    <IconInput
                      icon={Link2}
                      value={draft.url || ""}
                      onChange={updDraft("url")}
                      placeholder="Stream URL"
                      maxLength={BUTTON_URL_MAX_LENGTH}
                      mono
                      accent={ACCENT}
                    />
                  )}

                  {!isStreaming && (
                    <div className="flex flex-col gap-1.5">
                      <span
                        className="text-xs font-semibold"
                        style={{ color: "#94A3B8" }}
                      >
                        Platform
                      </span>
                      <CollapseSelect
                        name="Platform"
                        options={PLATFORM_CHOICES}
                        value={draft.platform || ""}
                        onChange={updDraft("platform")}
                        accent="#58B8E8"
                      />
                    </div>
                  )}

                  <div className="flex items-center gap-2 min-w-0">
                    <div className="flex-1 min-w-0">
                      <IconInput
                        icon={Link2}
                        value={youtubeUrl}
                        onChange={setYoutubeUrl}
                        placeholder="YouTube URL"
                        mono
                        accent="#FF0000"
                      />
                    </div>
                    <RowButton
                      onClick={handleFetchYouTube}
                      disabled={fetchingYouTube}
                    >
                      {fetchingYouTube ? "Fetching…" : "Fetch from YouTube"}
                    </RowButton>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="flex-1 min-w-0">
                        <IconInput
                          icon={Link2}
                          value={draft.large_image}
                          onChange={updDraft("large_image")}
                          placeholder="Large image"
                          maxLength={IMAGE_MAX_LENGTH}
                          mono
                          accent="#35C46A"
                        />
                      </div>
                      <RowButton
                        onClick={() => largeImageInputRef.current?.click()}
                        disabled={uploadingImage !== null}
                      >
                        {uploadingImage === "large_image"
                          ? "Uploading…"
                          : "Upload"}
                      </RowButton>
                    </div>
                    {showLargeText && (
                      <IconInput
                        icon={MessageSquareText}
                        value={draft.large_text}
                        onChange={updDraft("large_text")}
                        placeholder={
                          draft.type === "listening" ? "Album" : "Large text"
                        }
                        maxLength={TEXT_MAX_LENGTH}
                        accent="#35C46A"
                      />
                    )}
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="flex-1 min-w-0">
                        <IconInput
                          icon={Link2}
                          value={draft.small_image}
                          onChange={updDraft("small_image")}
                          placeholder="Small image"
                          maxLength={IMAGE_MAX_LENGTH}
                          mono
                          accent="#35C46A"
                        />
                      </div>
                      <RowButton
                        onClick={() => smallImageInputRef.current?.click()}
                        disabled={uploadingImage !== null}
                      >
                        {uploadingImage === "small_image"
                          ? "Uploading…"
                          : "Upload"}
                      </RowButton>
                    </div>
                    {showSmallText && (
                      <IconInput
                        icon={MessageSquareText}
                        value={draft.small_text}
                        onChange={updDraft("small_text")}
                        placeholder="Small text"
                        maxLength={TEXT_MAX_LENGTH}
                        accent="#35C46A"
                      />
                    )}
                  </div>
                  <input
                    ref={largeImageInputRef}
                    data-testid="large-image-upload"
                    type="file"
                    accept="image/png,image/jpeg,image/gif,image/webp"
                    className="hidden"
                    onChange={handleImageFile("large_image")}
                  />
                  <input
                    ref={smallImageInputRef}
                    data-testid="small-image-upload"
                    type="file"
                    accept="image/png,image/jpeg,image/gif,image/webp"
                    className="hidden"
                    onChange={handleImageFile("small_image")}
                  />

                  <div className="flex flex-col gap-1">
                    {imageWarnings.map((warning, index) => (
                      <p
                        key={index}
                        className="text-xs"
                        style={{
                          color: warning.expired ? "#F23F43" : "#F5B642",
                        }}
                      >
                        {warning.expired
                          ? `This Discord link expired on ${warning.date.toLocaleString()} — paste a fresh link or use an external GIF URL.`
                          : `This Discord link expires on ${warning.date.toLocaleString()} (Discord attachment links last 24 hours).`}
                      </p>
                    ))}
                    {externalImageHint && (
                      <p className="text-xs" style={{ color: "#94A3B8" }}>
                        External images are resolved through Discord.
                      </p>
                    )}
                    <p className="text-xs" style={{ color: "#64748B" }}>
                      GIF supported.
                    </p>
                    <p className="text-xs" style={{ color: "#64748B" }}>
                      Paste a YouTube link to use its thumbnail.
                    </p>
                    <p className="text-xs" style={{ color: "#64748B" }}>
                      Uploaded images are hosted publicly.
                    </p>
                  </div>

                  {showButtons && (
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className="text-xs font-semibold"
                          style={{ color: "#94A3B8" }}
                        >
                          Buttons
                        </span>
                        <RowButton
                          onClick={addButton}
                          disabled={(draft.buttons?.length || 0) >= 2}
                        >
                          + Add button
                        </RowButton>
                      </div>
                      {(draft.buttons || []).length === 0 ? (
                        <p className="text-xs" style={{ color: "#64748B" }}>
                          Up to 2 buttons.
                        </p>
                      ) : (
                        (draft.buttons || []).map((button, index) => (
                          <div
                            key={button.key ?? index}
                            className="flex items-center gap-2 min-w-0"
                          >
                            <span
                              className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-extrabold shrink-0"
                              style={{
                                background: "#5865F220",
                                color: "#5865F2",
                              }}
                            >
                              {index + 1}
                            </span>
                            <div className="flex-1 min-w-0 grid grid-cols-1 sm:grid-cols-2 gap-2">
                              <IconInput
                                icon={Type}
                                value={button.label}
                                onChange={(value) =>
                                  setButton(index, "label", value)
                                }
                                placeholder="Button label"
                                maxLength={BUTTON_LABEL_MAX_LENGTH}
                                accent="#5865F2"
                              />
                              <IconInput
                                icon={Link2}
                                value={button.url}
                                onChange={(value) =>
                                  setButton(index, "url", value)
                                }
                                placeholder="https://"
                                maxLength={BUTTON_URL_MAX_LENGTH}
                                mono
                                accent="#5865F2"
                              />
                            </div>
                            <RowButton
                              danger
                              onClick={() => removeButton(index)}
                            >
                              Remove
                            </RowButton>
                          </div>
                        ))
                      )}
                      <p className="text-xs" style={{ color: "#64748B" }}>
                        Custom buttons are hidden on your own profile — test
                        with a second account.
                      </p>
                    </div>
                  )}

                  {showElapsed && (
                    <div
                      className="flex items-center gap-3 px-3 py-2 rounded-xl"
                      style={{ background: "var(--surface-inset)" }}
                    >
                      <Timer
                        size={16}
                        style={{
                          color: elapsedEnabled ? "#F5B642" : "#64748B",
                        }}
                      />
                      <span
                        className="text-xs font-semibold"
                        style={{ color: "#94A3B8" }}
                      >
                        Elapsed
                      </span>
                      <input
                        type="number"
                        min="0"
                        step="5"
                        aria-label="Elapsed minutes"
                        value={Math.round(
                          Number(draft.elapsed_hours ?? 1) * 60,
                        )}
                        onChange={(event) =>
                          updDraft("elapsed_hours")(
                            Math.max(0, Number(event.target.value) || 0) / 60,
                          )
                        }
                        disabled={!elapsedEnabled}
                        placeholder="Minutes"
                        className="flex-1 min-w-0 bg-transparent outline-none text-sm font-mono"
                        style={{
                          color: elapsedEnabled ? "#E2E8F0" : "#64748B",
                        }}
                      />
                      <span className="text-xs" style={{ color: "#94A3B8" }}>
                        minutes
                      </span>
                      <Toggle
                        enabled={elapsedEnabled}
                        onChange={updDraft("show_elapsed")}
                        disabled={progressEnabled}
                        size="sm"
                        label="Elapsed"
                      />
                    </div>
                  )}

                  {(draft.type === "listening" ||
                    draft.type === "watching") && (
                    <div
                      className="flex items-center gap-3 px-3 py-2 rounded-xl"
                      style={{ background: "var(--surface-inset)" }}
                    >
                      <Timer
                        size={16}
                        style={{
                          color: progressEnabled ? "#F5B642" : "#64748B",
                        }}
                      />
                      <span
                        className="text-xs font-semibold"
                        style={{ color: "#94A3B8" }}
                      >
                        Progress
                      </span>
                      <input
                        type="number"
                        min="1"
                        max="1440"
                        aria-label="Progress minutes"
                        value={progressEnabled ? draft.duration_minutes : 30}
                        onChange={(event) =>
                          updDraft("duration_minutes")(
                            Math.max(
                              1,
                              Math.min(
                                1440,
                                Number(event.target.value) || 1,
                              ),
                            ),
                          )
                        }
                        disabled={!progressEnabled}
                        placeholder="Minutes"
                        className="flex-1 min-w-0 bg-transparent outline-none text-sm font-mono"
                        style={{
                          color: progressEnabled ? "#E2E8F0" : "#64748B",
                        }}
                      />
                      <span className="text-xs" style={{ color: "#94A3B8" }}>
                        minutes
                      </span>
                      <Toggle
                        enabled={progressEnabled}
                        onChange={toggleProgress}
                        size="sm"
                        label="Progress"
                      />
                    </div>
                  )}

                  {(draft.type === "listening" ||
                    draft.type === "watching") &&
                    !progressEnabled && (
                    <div
                      className="flex items-center gap-3 px-3 py-2 rounded-xl"
                      style={{ background: "var(--surface-inset)" }}
                    >
                      <Timer
                        size={16}
                        style={{
                          color: draft.show_end ? "#F5B642" : "#64748B",
                        }}
                      />
                      <span
                        className="text-xs font-semibold"
                        style={{ color: "#94A3B8" }}
                      >
                        End time
                      </span>
                      <input
                        type="number"
                        min="1"
                        max="1440"
                        value={draft.end_minutes ?? 30}
                        onChange={(event) =>
                          updDraft("end_minutes")(
                            Math.max(
                              1,
                              Math.min(
                                1440,
                                Number(event.target.value) || 1,
                              ),
                            ),
                          )
                        }
                        disabled={!draft.show_end}
                        placeholder="Minutes"
                        className="flex-1 min-w-0 bg-transparent outline-none text-sm font-mono"
                        style={{
                          color: draft.show_end ? "#E2E8F0" : "#64748B",
                        }}
                      />
                      <span
                        className="text-xs"
                        style={{ color: "#94A3B8" }}
                      >
                        minutes
                      </span>
                      <Toggle
                        enabled={draft.show_end === true}
                        onChange={updDraft("show_end")}
                        size="sm"
                        label="End time"
                      />
                    </div>
                  )}

                  <div className="flex items-center justify-end gap-2 pt-1">
                    <RowButton onClick={cancelForm}>Cancel</RowButton>
                    <button
                      type="button"
                      onClick={saveDraft}
                      className="flex items-center gap-2 text-sm font-bold px-4 py-2 rounded-xl text-white transition-all duration-200 ease-[var(--ease-out)] hover:brightness-110 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                      style={{
                        background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT}BB)`,
                        boxShadow: `0 4px 16px ${ACCENT}50`,
                      }}
                    >
                      <Save size={14} />
                      Save presence
                    </button>
                  </div>
                </>
              ) : null}
            </Panel>
          )}
        </div>

        <div data-testid="presence-preview" className="min-w-0">
          <Panel icon={Eye} title="Preview" accent={ACCENT}>
            <div className="flex flex-col gap-2">
              <div
                className="flex items-center gap-2 text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: "#23A55A",
                    boxShadow: "0 0 6px #23A55A",
                  }}
                />
                Live preview
              </div>
              <div className="flex flex-col sm:flex-row items-stretch sm:items-start gap-2">
                <div className="flex-1 min-w-0">
                  <DiscordCard s={preview} />
                </div>
                <div className="flex sm:flex-col gap-1.5 sm:w-[118px] shrink-0">
                  {STATUSES.map((status) => {
                    const active = entry.status === status.value;
                    return (
                      <button
                        key={status.value}
                        type="button"
                        title={status.label}
                        aria-pressed={active}
                        onClick={() => updateEntry({ status: status.value })}
                        className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-xl border transition-all duration-200 ease-[var(--ease-out)] hover:-translate-y-px active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                        style={{
                          background: active ? `${status.dot}1A` : "#0B0E14",
                          borderColor: active ? `${status.dot}66` : "#1F2636",
                          boxShadow: active
                            ? `0 0 10px ${status.dot}30`
                            : "none",
                        }}
                      >
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{
                            background: status.dot,
                            boxShadow: active
                              ? `0 0 6px ${status.dot}`
                              : "none",
                          }}
                        />
                        <span
                          className="text-xs font-semibold truncate"
                          style={{ color: active ? "#fff" : "#94A3B8" }}
                        >
                          {status.label}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </Panel>
        </div>
      </div>

      {entry.mode === "spotify" && (
        <Panel
          icon={Music2}
          title={`Spotify Songs (${songs.length})`}
          accent="#1DB954"
          action={
            <button
              type="button"
              onClick={() => (songFormOpen ? closeSongForm() : openSongForm())}
              disabled={songsLoading}
              className="text-xs font-bold px-2.5 py-1.5 rounded-lg border transition-all duration-200 ease-[var(--ease-out)] hover:brightness-110 active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
              style={{
                background: "#1DB95418",
                color: "#1DB954",
                borderColor: "#1DB95440",
              }}
            >
              + Add song
            </button>
          }
        >
          {songsLoading ? (
            <div
              className="flex items-center gap-2 text-sm py-2"
              style={{ color: "#94A3B8" }}
            >
              <Loader2 size={16} className="animate-spin" />
              Loading songs…
            </div>
          ) : (
            <div className="flex flex-col gap-2" data-testid="songs-list">
              {songs.length === 0 ? (
                <p className="text-sm" style={{ color: "#94A3B8" }}>
                  No songs yet — add a Spotify track.
                </p>
              ) : (
                songs.map((song, index) => (
                  <div
                    key={song.id || `${song.name}-${index}`}
                    className="flex items-center gap-3 rounded-xl border p-2.5"
                    style={{
                      background: "var(--surface-inset)",
                      borderColor: "var(--glass-border)",
                    }}
                  >
                    {song.image ? (
                      <img
                        src={songImageUrl(song.image)}
                        alt=""
                        className="w-10 h-10 rounded-lg object-cover shrink-0"
                      />
                    ) : (
                      <div
                        className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
                        style={{ background: "#1DB95418" }}
                      >
                        <Music2 size={16} style={{ color: "#1DB954" }} />
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-bold text-white truncate">
                        {song.name || "Untitled song"}
                      </div>
                      <div
                        className="text-xs truncate"
                        style={{ color: "#94A3B8" }}
                      >
                        {song.artist || "Unknown artist"}
                      </div>
                    </div>
                    <span
                      className="text-xs font-mono shrink-0"
                      style={{ color: "#94A3B8" }}
                    >
                      {formatSongDuration(song.duration_ms)}
                    </span>
                    <RowButton
                      danger
                      onClick={() => handleDeleteSong(index)}
                      disabled={savingSongs}
                    >
                      Delete
                    </RowButton>
                  </div>
                ))
              )}
            </div>
          )}

          {songFormOpen && (
            <div
              className="flex flex-col gap-2 rounded-xl border p-3"
              style={{
                background: "var(--surface-inset)",
                borderColor: "var(--glass-border)",
              }}
            >
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <IconInput
                  icon={Link2}
                  value={songDraft.url}
                  onChange={updateSongDraft("url")}
                  placeholder="Spotify URL or ID"
                  mono
                  accent="#1DB954"
                />
                <IconInput
                  icon={Type}
                  value={songDraft.name}
                  onChange={updateSongDraft("name")}
                  placeholder="Name"
                  accent="#1DB954"
                />
                <IconInput
                  icon={MessageSquareText}
                  value={songDraft.artist}
                  onChange={updateSongDraft("artist")}
                  placeholder="Artist"
                  accent="#1DB954"
                />
                <IconInput
                  icon={Timer}
                  value={songDraft.duration}
                  onChange={updateSongDraft("duration")}
                  placeholder="Duration (seconds or m:ss)"
                  accent="#1DB954"
                />
                <IconInput
                  icon={ImageIcon}
                  value={songDraft.image}
                  onChange={updateSongDraft("image")}
                  placeholder="Image URL or hash"
                  mono
                  accent="#1DB954"
                />
              </div>
              <div className="flex flex-wrap items-center justify-end gap-2">
                <RowButton
                  onClick={handleResolveSong}
                  disabled={resolving || !songDraft.url.trim()}
                >
                  {resolving ? (
                    <span className="inline-flex items-center gap-1.5">
                      <Loader2 size={12} className="animate-spin" />
                      Fetch details
                    </span>
                  ) : (
                    "Fetch details"
                  )}
                </RowButton>
                <button
                  type="button"
                  onClick={handleAddSong}
                  disabled={savingSongs}
                  className="flex items-center gap-2 text-sm font-bold px-4 py-2 rounded-xl text-white transition-all duration-200 ease-[var(--ease-out)] hover:brightness-110 active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                  style={{
                    background: "linear-gradient(135deg, #1DB954, #1DB954BB)",
                    boxShadow: "0 4px 16px #1DB95450",
                  }}
                >
                  <Plus size={14} />
                  Add song
                </button>
                <RowButton onClick={closeSongForm}>Cancel</RowButton>
              </div>
            </div>
          )}
        </Panel>
      )}

    </div>
  );
}
