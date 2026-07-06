import type { ReactNode } from "react";
import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PLATFORM_GLYPH_D } from "../lib/platformGlyphs";
import { generateRecoveryKey } from "../lib/recoveryKey";
import type { VpnType } from "../lib/types";
import { VPN_LABEL } from "../lib/types";

// ---------- icons ----------
const PATHS: Record<string, ReactNode> = {
  home: (
    <>
      <path d="M4 11l8-7 8 7" />
      <path d="M6 10v9a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-9" />
    </>
  ),
  servers: (
    <>
      <rect x="3" y="4" width="18" height="7" rx="2" />
      <rect x="3" y="13" width="18" height="7" rx="2" />
    </>
  ),
  groups: (
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
      <path d="M16 6a3 3 0 0 1 0 6" />
    </>
  ),
  access: (
    <>
      <path d="M12 3l7 3v5c0 4.4-3 7.4-7 9-4-1.6-7-4.6-7-9V6z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  available: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M15.5 8.5l-2 5-5 2 2-5z" />
    </>
  ),
  devices: (
    <>
      <rect x="7" y="3" width="10" height="18" rx="2.5" />
      <path d="M11 18h2" />
    </>
  ),
  monitoring: (
    <>
      <path d="M3 12h4l2 6 4-14 2 8h6" />
    </>
  ),
  // ---- иконки платформ устройств (имя = platform-ключ, см. Device.platform) ----
  ios: (
    <>
      <rect x="7" y="2" width="10" height="20" rx="2.6" />
      <path d="M10.5 4.7h3" />
      <path d="M11 19.2h2" />
    </>
  ),
  mac: (
    <>
      <rect x="5" y="4" width="14" height="10" rx="1.6" />
      <path d="M2.5 18h19l-1.8-2.6a1 1 0 0 0-.82-.44H5.12a1 1 0 0 0-.82.44z" />
    </>
  ),
  router: (
    <>
      <rect x="3" y="13" width="18" height="7" rx="2" />
      <path d="M7 16.5h.01" />
      <path d="M10.5 16.5h7" />
      <path d="M12 13v-1.4" />
      <path d="M9.2 9.4a4 4 0 0 1 5.6 0" />
      <path d="M6.8 7a7.5 7.5 0 0 1 10.4 0" />
    </>
  ),
  // ---- иконки VPN-вендоров (ПО), имя = VpnType; красятся акцентом вендора ----
  // Amnezia — маска (маскируется под обычный трафик)
  vpn_amnezia: (
    <>
      <path d="M3.5 8.5c1.2-.7 3-1 4.5-1 1.6 0 2.8.6 4 .6s2.4-.6 4-.6c1.5 0 3.3.3 4.5 1 .5 3.5-1.7 6-4.5 6-1.6 0-2.6-1.2-3.5-1.2S9.6 14.5 8 14.5c-2.8 0-5-2.5-4.5-6z" />
      <path d="M7.6 10h.01" />
      <path d="M14.4 10h.01" />
    </>
  ),
  // OpenVPN — навесной замок (классика безопасности)
  vpn_openvpn: (
    <>
      <rect x="5" y="10" width="14" height="9.5" rx="2" />
      <path d="M8 10V7.5a4 4 0 0 1 8 0V10" />
      <path d="M12 13.6v2.3" />
    </>
  ),
  // Outline — ключ (один ключ, проще всего)
  vpn_outline: (
    <>
      <circle cx="8" cy="8.5" r="4" />
      <path d="M10.9 11.4l7.1 7.1" />
      <path d="M15.5 15.5l1.8-1.8" />
    </>
  ),
  // Hysteria2 — молния (быстрый QUIC)
  vpn_hysteria2: <path d="M13 2.5 5 13.5h5.5L9.5 21.5 19 9.5h-5.5z" />,
  users: (
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
      <circle cx="17" cy="9" r="2" />
    </>
  ),
  system: (
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </>
  ),
  events: (
    <>
      <path d="M4 5h16M4 12h16M4 19h10" />
      <circle cx="19" cy="19" r="2" />
    </>
  ),
  profile: (
    <>
      <circle cx="12" cy="8" r="3.4" />
      <path d="M5.5 20a6.5 6.5 0 0 1 13 0" />
    </>
  ),
  back: <path d="M15 18l-6-6 6-6" />,
  chevron: <path d="M9 6l6 6-6 6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  check: <path d="M5 12l5 5L20 6" />,
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </>
  ),
  trash: <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />,
  edit: <path d="M4 20h4L18 10l-4-4L4 16v4zM13 5l4 4" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5" />
    </>
  ),
  moon: <path d="M21 12.8A8 8 0 1 1 11.2 3a6 6 0 0 0 9.8 9.8z" />,
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4-4" />
    </>
  ),
  x: <path d="M6 6l12 12M18 6L6 18" />,
  link: (
    <>
      <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
    </>
  ),
  external: <path d="M7 17L17 7M9 7h8v8" />,
  refresh: <path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 4v4h-4" />,
  play: <path d="M7 5l12 7-12 7z" />,
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  download: <path d="M12 4v11m-5-5l5 5 5-5M5 20h14" />,
  share: (
    <>
      <path d="M12 3v13" />
      <path d="M8 7l4-4 4 4" />
      <path d="M5 12v7a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-7" />
    </>
  ),
  eye: (
    <>
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  logout: <path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4M9 12h11M16 8l4 4-4 4" />,
  "eye-off": (
    <>
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <path d="M1 1l22 22" />
    </>
  ),
  sparkles: (
    <>
      <path d="M12 3l1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7z" />
      <path d="M18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9z" />
    </>
  ),
};

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  // Официальные бренд-глифы платформ рисуются заливкой (currentColor), остальные — штрихом.
  const glyph = PLATFORM_GLYPH_D[name];
  if (glyph) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
        <path d={glyph} />
      </svg>
    );
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {PATHS[name] ?? null}
    </svg>
  );
}

// ---------- primitives ----------
export function Btn({
  children,
  variant = "default",
  sm,
  block,
  ...rest
}: {
  children: ReactNode;
  variant?: "default" | "primary" | "danger" | "ghost";
  sm?: boolean;
  block?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls = ["btn", variant !== "default" ? variant : "", sm ? "sm" : "", block ? "block" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <button className={cls} {...rest}>
      {children}
    </button>
  );
}

export function FilePicker({
  accept,
  file,
  onPick,
  placeholder = "Файл не выбран",
}: {
  accept?: string;
  file: File | null;
  onPick: (f: File | null) => void;
  placeholder?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div
      onClick={() => ref.current?.click()}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "6px 6px 6px 13px",
        borderRadius: "var(--r-sm)",
        border: "1px solid var(--border-strong)",
        background: "var(--surface)",
        cursor: "pointer",
      }}
    >
      <span
        style={{
          flex: 1,
          minWidth: 0,
          fontSize: 14,
          color: file ? "var(--text)" : "var(--text-3)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {file ? file.name : placeholder}
      </span>
      <span className="btn sm" style={{ flex: "none", pointerEvents: "none" }}>
        Выбрать файл
      </span>
      <input
        ref={ref}
        type="file"
        accept={accept}
        style={{ display: "none" }}
        onChange={(e) => onPick(e.target.files?.[0] ?? null)}
      />
    </div>
  );
}

export function KeyInput({
  value,
  onChange,
  placeholder,
  withGenerate = true,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  withGenerate?: boolean;
}) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ position: "relative" }}>
        <input
          className="input"
          type={show ? "text" : "password"}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          style={{ paddingRight: 40 }}
        />
        <button
          type="button"
          title={show ? "Скрыть" : "Показать"}
          onClick={() => setShow((s) => !s)}
          style={{
            position: "absolute",
            right: 5,
            top: "50%",
            transform: "translateY(-50%)",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 30,
            height: 30,
            borderRadius: 8,
            border: "none",
            background: "transparent",
            color: "var(--text-3)",
            cursor: "pointer",
          }}
        >
          <Icon name={show ? "eye" : "eye-off"} size={16} />
        </button>
      </div>
      {withGenerate && (
        <Btn
          sm
          onClick={() => {
            onChange(generateRecoveryKey());
            setShow(true);
          }}
        >
          <Icon name="sparkles" size={15} />
          Сгенерировать ключ
        </Btn>
      )}
    </div>
  );
}

export function Switch({ on, onClick }: { on: boolean; onClick?: () => void }) {
  return <button type="button" className={`switch ${on ? "on" : ""}`} onClick={onClick} />;
}

export function Avatar({ name }: { name: string }) {
  return <div className="avatar">{(name || "?").trim().charAt(0).toUpperCase()}</div>;
}

export function StatusBadge({ status }: { status: "online" | "offline" | "unknown" }) {
  const map = {
    online: { c: "ok", t: "онлайн" },
    offline: { c: "danger", t: "офлайн" },
    unknown: { c: "neutral", t: "не проверен" },
  } as const;
  const s = map[status];
  return (
    <span className={`badge ${s.c}`}>
      <span className={`dot ${status}`} />
      {s.t}
    </span>
  );
}

export function VpnChip({ type, dimmed }: { type: VpnType; dimmed?: boolean }) {
  return (
    <span className="chip" style={dimmed ? { opacity: 0.5 } : undefined}>
      <span className={`dot ${type}`} />
      {VPN_LABEL[type]}
    </span>
  );
}

export function Field({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <div className="field">
      {label && <label>{label}</label>}
      {children}
    </div>
  );
}

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  // Портал в body: модалка не должна зависеть от трансформируемых/анимируемых
  // родителей (иначе position: fixed считается от них, и центрирование ломается).
  return createPortal(
    <div className="overlay" onClick={onClose}>
      <div className="modal" style={wide ? { maxWidth: 560 } : undefined} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <div className="spacer" />
          <Btn variant="ghost" sm onClick={onClose}>
            <Icon name="x" size={18} />
          </Btn>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Empty({ title, sub, action }: { title: string; sub?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {sub && <p className="muted">{sub}</p>}
      {action && <div style={{ marginTop: 16 }}>{action}</div>}
    </div>
  );
}

export function ScreenHeader({
  title,
  sub,
  action,
  onBack,
}: {
  title: string;
  sub?: string;
  action?: ReactNode;
  onBack?: () => void;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
      {onBack && (
        <Btn variant="ghost" sm onClick={onBack}>
          <Icon name="back" size={18} />
        </Btn>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 22, fontWeight: 800 }}>{title}</div>
        {sub && (
          <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>
            {sub}
          </div>
        )}
      </div>
      {action}
    </div>
  );
}

export function Spinner() {
  return (
    <span className="spin" style={{ display: "inline-flex" }}>
      <Icon name="refresh" size={16} />
    </span>
  );
}

// Плейсхолдер-заглушка с шиммером — показываем во время загрузки списков вместо
// голого спиннера, чтобы каркас страницы не «прыгал».
export function Skeleton({
  width = "100%",
  height = 16,
  radius = 8,
  style,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number | string;
  style?: React.CSSProperties;
}) {
  return <span className="skeleton" style={{ width, height, borderRadius: radius, ...style }} />;
}

// Готовый скелет-каркас карточки для сеток (Серверы, Группы и т.п.).
export function SkeletonCard() {
  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Skeleton width={44} height={44} radius={13} />
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
          <Skeleton width="60%" height={15} />
          <Skeleton width="35%" height={12} />
        </div>
      </div>
      <Skeleton width="100%" height={12} />
      <Skeleton width="45%" height={12} />
    </div>
  );
}
