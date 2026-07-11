import { useState } from "react";
import { Btn, Icon, ScreenHeader } from "../components/ui";
import {
  AMNEZIA_APP,
  DEFAULTVPN_APP,
  GUIDE_PLATFORMS,
  type GuideApp,
  type GuidePlatform,
  OPENVPN_APP,
  OUTLINE_APP,
  PLATFORM_GUIDES,
} from "../lib/deviceGuide";
import { useT } from "../lib/i18n";

// Справочный экран «Настрой устройство»: выбор платформы → рекомендованное приложение
// (ссылка в стор) + пошаговая инструкция. Все тексты — из i18n (setup.*), данные —
// из lib/deviceGuide.ts, чтобы легко переводить и поддерживать без правки JSX.
export function SetupScreen() {
  const t = useT();
  const [platform, setPlatform] = useState<GuidePlatform>("ios");
  const guide = PLATFORM_GUIDES.find((g) => g.platform === platform) ?? PLATFORM_GUIDES[0];

  return (
    <div className="screen">
      <ScreenHeader title={t("setup.title")} sub={t("setup.sub")} />

      {/* выбор платформы */}
      <div style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-2)", marginBottom: 9 }}>
          {t("setup.pickPlatform")}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {GUIDE_PLATFORMS.map((p) => {
            const g = PLATFORM_GUIDES.find((x) => x.platform === p);
            if (!g) return null;
            return (
              <button
                key={p}
                type="button"
                className={`chip ${p === platform ? "selected" : ""}`}
                style={{ cursor: "pointer", padding: "8px 14px", gap: 7 }}
                onClick={() => setPlatform(p)}
              >
                <Icon name={p} size={15} />
                {t(g.labelKey)}
              </button>
            );
          })}
        </div>
      </div>

      {/* рекомендованное приложение */}
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 16 }}>
        <div style={{ fontSize: 11.5, color: "var(--text-3)" }}>{t("setup.recommendedApp")}</div>
        <AppRow app={guide.app} openLabel={t("setup.openStore")} storeLabel={t(guide.app.storeKey)} />

        <div style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 12 }}>{t("setup.stepsTitle")}</div>
          <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 12 }}>
            {guide.stepKeys.map((k, i) => (
              <li key={k} style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                <span
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 7,
                    background: "var(--ink)",
                    color: "var(--on-ink)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    font: "700 12px/1 var(--font)",
                    flex: "none",
                  }}
                >
                  {i + 1}
                </span>
                <span style={{ fontSize: 13.5, lineHeight: 1.5, color: "var(--text-2)" }}>{t(k)}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>

      {/* приложения по формату конфига (Amnezia / Outline) */}
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ fontSize: 11.5, color: "var(--text-3)" }}>{t("setup.vendorApps")}</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 12, color: "var(--text-3)" }}>{t("setup.vendorAmnezia")}</div>
          <AppRow app={AMNEZIA_APP} openLabel={t("setup.openStore")} storeLabel={t(AMNEZIA_APP.storeKey)} />
          {/* DefaultVPN есть только в App Store — показываем лишь для iPhone/iPad */}
          {platform === "ios" && (
            <AppRow app={DEFAULTVPN_APP} openLabel={t("setup.openStore")} storeLabel={t(DEFAULTVPN_APP.storeKey)} />
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 12, color: "var(--text-3)" }}>{t("setup.vendorOutline")}</div>
          <AppRow app={OUTLINE_APP} openLabel={t("setup.openStore")} storeLabel={t(OUTLINE_APP.storeKey)} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 12, color: "var(--text-3)" }}>{t("setup.vendorOpenvpn")}</div>
          <AppRow app={OPENVPN_APP} openLabel={t("setup.openStore")} storeLabel={t(OPENVPN_APP.storeKey)} />
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 8,
          fontSize: 12.5,
          color: "var(--text-3)",
          marginTop: 16,
          lineHeight: 1.5,
        }}
      >
        <Icon name="file" size={15} />
        <span>{t("setup.hint")}</span>
      </div>
    </div>
  );
}

function AppRow({ app, openLabel, storeLabel }: { app: GuideApp; openLabel: string; storeLabel: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "11px 13px",
        border: "1px solid var(--border-strong)",
        borderRadius: 12,
        background: "var(--surface)",
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 9,
          background: "var(--surface-2)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontWeight: 700,
          fontSize: 14,
          color: "var(--text-2)",
          flex: "none",
        }}
      >
        {app.name.slice(0, 1)}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{app.name}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)" }}>{storeLabel}</div>
      </div>
      <a href={app.url} target="_blank" rel="noopener" style={{ textDecoration: "none", flex: "none" }}>
        <Btn sm>
          <Icon name="external" size={15} />
          {openLabel}
        </Btn>
      </a>
    </div>
  );
}
