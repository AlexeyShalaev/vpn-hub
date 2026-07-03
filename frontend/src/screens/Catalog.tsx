import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Btn, Empty, Field, Icon, Modal, ScreenHeader, Spinner } from "../components/ui";
import { ApiError } from "../lib/api";
import * as q from "../lib/queries";
import type { Provider } from "../lib/types";
import { useNav } from "../nav";
import { useStore } from "../store";

interface FormState {
  id?: string;
  name: string;
  url: string;
  blurb: string;
  tags: string;
}

const EMPTY: FormState = { name: "", url: "", blurb: "", tags: "" };

export function CatalogScreen() {
  const go = useNav((s) => s.go);
  const isAdmin = useStore((s) => s.me?.isAdmin ?? false);
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();

  const { data: providers, isLoading } = useQuery({
    queryKey: ["providers"],
    queryFn: q.listProviders,
  });

  const [form, setForm] = useState<FormState | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const set = (k: keyof FormState, v: string) => setForm((f) => (f ? { ...f, [k]: v } : f));

  const invalidate = () => qc.invalidateQueries({ queryKey: ["providers"] });

  const save = useMutation({
    mutationFn: async (f: FormState) => {
      const body = {
        name: f.name,
        url: f.url,
        blurb: f.blurb,
        tags: f.tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      };
      return f.id ? q.adminUpdateProvider(f.id, body) : q.adminCreateProvider(body);
    },
    onSuccess: () => {
      invalidate();
      setForm(null);
      toast("Сохранено");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Ошибка"),
  });

  const del = useMutation({
    mutationFn: (id: string) => q.adminDeleteProvider(id),
    onSuccess: () => {
      invalidate();
      setConfirmId(null);
      toast("Провайдер удалён");
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : "Ошибка"),
  });

  const openCreate = () => setForm({ ...EMPTY });
  const openEdit = (p: Provider) =>
    setForm({ id: p.id, name: p.name, url: p.url, blurb: p.blurb, tags: p.tags.join(", ") });

  return (
    <div className="stack">
      <ScreenHeader
        title="Каталог провайдеров"
        sub="Где арендовать VPS под VPN"
        onBack={() => go("servers")}
        action={
          isAdmin ? (
            <Btn variant="primary" onClick={openCreate}>
              <Icon name="plus" size={16} />
              Добавить
            </Btn>
          ) : undefined
        }
      />

      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner />
        </div>
      ) : !providers || providers.length === 0 ? (
        <Empty
          title="Каталог пуст"
          sub="Провайдеры пока не добавлены"
          action={
            isAdmin ? (
              <Btn variant="primary" onClick={openCreate}>
                Добавить провайдера
              </Btn>
            ) : undefined
          }
        />
      ) : (
        <div className="grid">
          {providers.map((p) => (
            <div key={p.id} className="card" style={{ display: "flex", flexDirection: "column", gap: 13 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 12,
                    background: "var(--surface-2)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 800,
                    fontSize: 17,
                    color: "var(--text-2)",
                    flex: "none",
                  }}
                >
                  {(p.name || "?").trim().slice(0, 2).toUpperCase()}
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontWeight: 700, fontSize: 16, letterSpacing: "-.01em" }}>{p.name}</div>
                </div>
                {isAdmin && (
                  <div style={{ display: "flex", gap: 4 }}>
                    <Btn variant="ghost" sm onClick={() => openEdit(p)}>
                      <Icon name="edit" size={16} />
                    </Btn>
                    <Btn variant="ghost" sm onClick={() => setConfirmId(p.id)}>
                      <Icon name="trash" size={16} />
                    </Btn>
                  </div>
                )}
              </div>

              <p className="muted" style={{ fontSize: 13.5, lineHeight: 1.45, minHeight: 38, margin: 0 }}>
                {p.blurb}
              </p>

              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, minHeight: 24 }}>
                {p.tags.map((t) => (
                  <span
                    key={t}
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "4px 9px",
                      borderRadius: 999,
                      background: "var(--surface-2)",
                      color: "var(--text-2)",
                    }}
                  >
                    {t}
                  </span>
                ))}
              </div>

              <div style={{ display: "flex", gap: 8, marginTop: "auto" }}>
                <a
                  href={p.url}
                  target="_blank"
                  rel="noopener"
                  style={{
                    flex: 1,
                    height: 42,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 7,
                    borderRadius: 11,
                    background: "var(--ink)",
                    color: "var(--on-ink)",
                    font: "600 13.5px/1 var(--font)",
                    textDecoration: "none",
                  }}
                >
                  Перейти и купить
                  <Icon name="external" size={15} />
                </a>
                <button
                  onClick={() => go("serverForm", { provider: p.name })}
                  style={{
                    height: 42,
                    padding: "0 14px",
                    border: "1px solid var(--border-strong)",
                    borderRadius: 11,
                    background: "var(--surface)",
                    color: "var(--text)",
                    font: "600 13px/1 var(--font)",
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  У меня уже есть
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {form && (
        <Modal
          title={form.id ? "Редактировать провайдера" : "Новый провайдер"}
          onClose={() => setForm(null)}
          footer={
            <>
              <Btn onClick={() => setForm(null)}>Отмена</Btn>
              <Btn variant="primary" disabled={save.isPending} onClick={() => save.mutate(form)}>
                Сохранить
              </Btn>
            </>
          }
        >
          <Field label="Название">
            <input className="input" value={form.name} onChange={(e) => set("name", e.target.value)} />
          </Field>
          <Field label="Ссылка для покупки">
            <input
              className="input"
              placeholder="https://…"
              value={form.url}
              onChange={(e) => set("url", e.target.value)}
            />
          </Field>
          <Field label="Описание">
            <textarea
              className="input"
              rows={3}
              style={{ resize: "vertical", lineHeight: 1.5, minHeight: 78 }}
              value={form.blurb}
              onChange={(e) => set("blurb", e.target.value)}
            />
          </Field>
          <Field label="Теги (через запятую)">
            <input
              className="input"
              placeholder="Дёшево, Европа"
              value={form.tags}
              onChange={(e) => set("tags", e.target.value)}
            />
          </Field>
        </Modal>
      )}

      {confirmId && (
        <Modal
          title="Удалить провайдера?"
          onClose={() => setConfirmId(null)}
          footer={
            <>
              <Btn onClick={() => setConfirmId(null)}>Отмена</Btn>
              <Btn variant="danger" disabled={del.isPending} onClick={() => del.mutate(confirmId)}>
                Удалить
              </Btn>
            </>
          }
        >
          <p className="muted">Провайдер исчезнет из каталога. На уже созданные серверы это не влияет.</p>
        </Modal>
      )}
    </div>
  );
}
