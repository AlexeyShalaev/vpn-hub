import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Avatar, Btn, Empty, Field, Icon, Modal, ScreenHeader, Spinner } from "../components/ui";
import * as q from "../lib/queries";
import type { Group, Pool } from "../lib/types";
import { useNav } from "../nav";
import { useStore } from "../store";

function plural(n: number, a: string, b: string, c: string): string {
  const n10 = n % 10;
  const n100 = n % 100;
  if (n10 === 1 && n100 !== 11) return a;
  if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return b;
  return c;
}

function mono2(name: string): string {
  return (name || "?").slice(0, 2).toUpperCase();
}

// эффективное число серверов: серверы из пулов + прямые доступы
function effectiveServerCount(g: Group, pools: Pool[]): number {
  const set = new Set<string>();
  (g.access.pools || []).forEach((pid) => {
    const pl = pools.find((p) => p.id === pid);
    if (pl) {
      for (const id of pl.serverIds) set.add(id);
    }
  });
  for (const id of Object.keys(g.access.servers || {})) set.add(id);
  return set.size;
}

export function GroupsScreen() {
  const toast = useStore((s) => s.toast);
  const go = useNav((s) => s.go);
  const qc = useQueryClient();

  const groupsQ = useQuery({ queryKey: ["groups"], queryFn: q.listGroups });
  const poolsQ = useQuery({ queryKey: ["pools"], queryFn: q.listPools });

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const createMut = useMutation({
    mutationFn: (b: { name: string }) => q.createGroup(b),
    onSuccess: (g) => {
      qc.invalidateQueries({ queryKey: ["groups"] });
      setCreating(false);
      setName("");
      toast("Сохранено");
      go("group", { groupId: g.id });
    },
  });

  const groups = groupsQ.data ?? [];
  const pools = poolsQ.data ?? [];

  const cards = useMemo(
    () =>
      groups.map((g) => {
        const count = effectiveServerCount(g, pools);
        return {
          id: g.id,
          name: g.name,
          mono: mono2(g.name),
          memberLabel: `${g.members.length} ${plural(g.members.length, "участник", "участника", "участников")}`,
          accessSummary: count ? `${count} ${plural(count, "сервер", "сервера", "серверов")}` : "без доступов",
          avatars: g.members.slice(0, 4),
          extra: g.members.length > 4 ? `+${g.members.length - 4}` : "",
        };
      }),
    [groups, pools],
  );

  function submit() {
    const n = name.trim();
    if (!n) {
      toast("Введите название");
      return;
    }
    createMut.mutate({ name: n });
  }

  const action = (
    <Btn variant="primary" onClick={() => setCreating(true)}>
      <Icon name="plus" size={18} />
      Создать группу
    </Btn>
  );

  return (
    <div className="stack">
      <ScreenHeader title="Группы" sub="Кому вы раздаёте доступ" action={action} />

      {groupsQ.isLoading ? (
        <div className="card" style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner />
        </div>
      ) : groups.length === 0 ? (
        <Empty
          title="Нет групп"
          sub="Создайте группу — например «Семья» — и пригласите близких по ссылке."
          action={
            <Btn variant="primary" onClick={() => setCreating(true)}>
              Создать группу
            </Btn>
          }
        />
      ) : (
        <div className="grid">
          {cards.map((c) => (
            <button
              key={c.id}
              className="card"
              onClick={() => go("group", { groupId: c.id })}
              style={{
                textAlign: "left",
                display: "flex",
                flexDirection: "column",
                gap: 14,
                cursor: "pointer",
              }}
            >
              <div className="card-row" style={{ width: "100%" }}>
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 13,
                    background: "var(--accent-soft)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 700,
                    fontSize: 15,
                    color: "var(--text)",
                    flex: "none",
                  }}
                >
                  {c.mono}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: 16.5, letterSpacing: "-.01em" }}>{c.name}</div>
                  <div className="muted-3" style={{ fontSize: 12.5 }}>
                    {c.memberLabel}
                  </div>
                </div>
                <Icon name="back" size={18} />
              </div>

              <div style={{ display: "flex", alignItems: "center" }}>
                <div style={{ display: "flex" }}>
                  {c.avatars.map((m) => (
                    <span key={m.id} style={{ marginRight: -8 }}>
                      <Avatar name={m.name} />
                    </span>
                  ))}
                </div>
                {c.extra && (
                  <span className="muted-3" style={{ fontSize: 12, marginLeft: 14 }}>
                    {c.extra}
                  </span>
                )}
              </div>

              <div
                className="rowflex"
                style={{ gap: 8, paddingTop: 12, borderTop: "1px solid var(--border)", width: "100%" }}
              >
                <Icon name="access" size={15} />
                <span className="muted" style={{ fontSize: 13 }}>
                  Доступ: {c.accessSummary}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}

      {creating && (
        <Modal
          title="Новая группа"
          onClose={() => {
            setCreating(false);
            setName("");
          }}
          footer={
            <>
              <Btn
                block
                onClick={() => {
                  setCreating(false);
                  setName("");
                }}
              >
                Отмена
              </Btn>
              <Btn variant="primary" block onClick={submit} disabled={createMut.isPending}>
                {createMut.isPending ? "Сохранение…" : "Сохранить"}
              </Btn>
            </>
          }
        >
          <Field label="Название группы">
            <input
              className="input"
              value={name}
              autoFocus
              placeholder="Семья"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
            />
          </Field>
        </Modal>
      )}
    </div>
  );
}
