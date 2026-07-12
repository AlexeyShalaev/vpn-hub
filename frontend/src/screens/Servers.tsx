import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Btn, Empty, Icon, ScreenHeader, SkeletonCard, StatusBadge, VpnChip } from "../components/ui";
import { useT } from "../lib/i18n";
import * as q from "../lib/queries";
import type { Server } from "../lib/types";
import { useNav } from "../nav";

function mono(name: string) {
  return (name || "?").slice(0, 2).toUpperCase();
}

function ServerCard({ s }: { s: Server }) {
  const go = useNav((n) => n.go);
  const t = useT();
  const chips = s.vpns.filter((v) => v.installed);
  return (
    <button
      onClick={() => go("server", { serverId: s.id })}
      style={{
        textAlign: "left",
        display: "flex",
        flexDirection: "column",
        gap: 14,
        padding: "var(--pad)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r)",
        background: "var(--surface)",
        boxShadow: "var(--shadow)",
        cursor: "pointer",
        // grid-элемент по умолчанию min-width:auto — без этого длинное имя/содержимое распирало бы карточку за трек.
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
        <div
          style={{
            width: 42,
            height: 42,
            borderRadius: 12,
            background: "var(--surface-2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
            fontSize: 15,
            color: "var(--text-2)",
            flex: "none",
          }}
        >
          {mono(s.name)}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontWeight: 700,
              fontSize: 16,
              letterSpacing: "-.01em",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {s.name}
          </div>
          <div
            style={{
              fontSize: 12.5,
              color: "var(--text-3)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {s.provider} · {s.location}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
          {s.latency && (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                fontSize: 12,
                color: "var(--text-2)",
                whiteSpace: "nowrap",
              }}
            >
              <Icon name="refresh" size={13} />
              {s.latency}
            </span>
          )}
          <StatusBadge status={s.status} />
        </div>
      </div>
      <div
        style={{
          fontFamily: "var(--mono)",
          fontSize: 12.5,
          color: "var(--text-2)",
          background: "var(--surface-2)",
          borderRadius: 9,
          padding: "8px 11px",
        }}
      >
        {s.ip}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 7,
          flexWrap: "wrap",
          minHeight: 24,
        }}
      >
        {chips.length > 0 ? (
          chips.map((v) => <VpnChip key={v.type} type={v.type} />)
        ) : (
          <span style={{ fontSize: 12, color: "var(--text-3)" }}>{t("servers.vpnNotInstalled")}</span>
        )}
      </div>
    </button>
  );
}

export function ServersScreen() {
  const go = useNav((n) => n.go);
  const t = useT();
  const [query, setQuery] = useState("");

  const { data: servers, isLoading } = useQuery({
    queryKey: ["servers"],
    queryFn: q.listServers,
    // статусы приходят пушем по SSE (см. lib/events); поллинг — страховка на обрыв SSE (реже)
    refetchInterval: 60000,
  });

  const all = servers ?? [];
  const showSearch = all.length >= 3;

  const filtered = useMemo(() => {
    const sq = query.trim().toLowerCase();
    if (!sq) return all;
    return all.filter((s) => `${s.name} ${s.ip} ${s.provider} ${s.location}`.toLowerCase().includes(sq));
  }, [all, query]);

  return (
    <div className="screen">
      <ScreenHeader
        title={t("nav.servers")}
        sub={t("servers.subtitle")}
        action={
          <div style={{ display: "flex", gap: 10 }}>
            <Btn variant="primary" onClick={() => go("serverForm")}>
              {t("servers.addServer")}
            </Btn>
            <Btn onClick={() => go("catalog")}>{t("servers.catalog")}</Btn>
          </div>
        }
      />

      {isLoading ? (
        <div className="grid">
          {Array.from({ length: 3 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : all.length === 0 ? (
        <Empty
          title={t("servers.emptyTitle")}
          sub={t("servers.emptySub")}
          action={
            <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
              <Btn onClick={() => go("catalog")}>{t("servers.catalogProviders")}</Btn>
              <Btn variant="primary" onClick={() => go("serverForm")}>
                {t("servers.addServer")}
              </Btn>
            </div>
          }
        />
      ) : (
        <>
          {showSearch && (
            <div style={{ position: "relative" }}>
              <span
                style={{
                  position: "absolute",
                  left: 13,
                  top: "50%",
                  transform: "translateY(-50%)",
                  color: "var(--text-3)",
                  pointerEvents: "none",
                  display: "inline-flex",
                }}
              >
                <Icon name="search" size={18} />
              </span>
              <input
                className="input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("servers.searchPlaceholder")}
                style={{ paddingLeft: 42 }}
              />
            </div>
          )}

          {filtered.length === 0 ? (
            <Empty title={t("common.nothingFound")} sub={t("servers.tryDifferentQuery")} />
          ) : (
            <div className="grid">
              {filtered.map((s) => (
                <ServerCard key={s.id} s={s} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
