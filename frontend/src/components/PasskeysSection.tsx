import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../lib/api";
import { useT } from "../lib/i18n";
import { createPasskey } from "../lib/passkeyFlow";
import * as q from "../lib/queries";
import type { Passkey } from "../lib/types";
import { isUserCancel, originMatches, passkeysSupported } from "../lib/webauthn";
import { useStore } from "../store";
import { Btn, Field, Icon, Modal, Spinner } from "./ui";

/** Блок «Ключи доступа» в профиле: список своих passkeys, добавление, переименование, удаление. */
export function PasskeysSection() {
  const t = useT();
  const qc = useQueryClient();
  const toast = useStore((s) => s.toast);
  const supported = passkeysSupported();
  const configQ = useQuery({ queryKey: ["passkeys-config"], queryFn: q.passkeyConfig, staleTime: Infinity });
  const listQ = useQuery({ queryKey: ["passkeys"], queryFn: q.listPasskeys });
  const [renaming, setRenaming] = useState<Passkey | null>(null);
  const [newName, setNewName] = useState("");
  const [deleting, setDeleting] = useState<Passkey | null>(null);

  const cfg = configQ.data;
  const wrongOrigin = !!cfg?.available && !originMatches(cfg.origin, window.location.origin);
  const notice = !supported
    ? t("profile.passkeyUnsupported")
    : cfg && !cfg.available
      ? t("profile.passkeyUnavailable")
      : wrongOrigin
        ? t("profile.passkeyWrongOrigin", { origin: cfg?.origin ?? "" })
        : "";
  const canAdd = supported && !!cfg?.available && !wrongOrigin;

  const addM = useMutation({
    mutationFn: createPasskey,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["passkeys"] });
      toast(t("profile.passkeyAdded"));
    },
    onError: (e) => {
      if (e instanceof DOMException && e.name === "InvalidStateError") toast(t("profile.passkeyExists"));
      else if (!isUserCancel(e)) toast(e instanceof ApiError ? e.message : t("profile.passkeyFailed"));
    },
  });

  const renameM = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => q.renamePasskey(id, name),
    onSuccess: () => {
      setRenaming(null);
      qc.invalidateQueries({ queryKey: ["passkeys"] });
      toast(t("profile.passkeyRenamed"));
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("common.requestError")),
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => q.deletePasskey(id),
    onSuccess: () => {
      setDeleting(null);
      qc.invalidateQueries({ queryKey: ["passkeys"] });
      toast(t("profile.passkeyRemoved"));
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : t("common.requestError")),
  });

  const passkeys = listQ.data ?? [];

  return (
    <div className="card stack" style={{ gap: 12 }}>
      <div className="rowflex" style={{ justifyContent: "space-between" }}>
        <div
          className="muted-3"
          style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
        >
          {t("profile.passkeys")}
        </div>
        <Btn sm disabled={!canAdd || addM.isPending} onClick={() => addM.mutate()}>
          <Icon name="plus" size={15} />
          {t("profile.passkeyAdd")}
        </Btn>
      </div>
      <p className="muted" style={{ fontSize: 13, margin: 0 }}>
        {t("profile.passkeysHint")}
      </p>
      {notice && (
        <div className="muted-3" style={{ fontSize: 12.5 }}>
          {notice}
        </div>
      )}

      {listQ.isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 12 }}>
          <Spinner />
        </div>
      ) : passkeys.length === 0 ? (
        <div className="muted-3" style={{ fontSize: 13 }}>
          {t("profile.passkeysEmpty")}
        </div>
      ) : (
        <div className="stack" style={{ gap: 8 }}>
          {passkeys.map((pk) => (
            <div
              key={pk.id}
              className="card-row"
              style={{ gap: 12, border: "1px solid var(--border)", borderRadius: 12, padding: "10px 12px" }}
            >
              <Icon name="key" size={18} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="rowflex" style={{ gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 14, overflowWrap: "anywhere" }}>{pk.name}</span>
                  {pk.synced && <span className="badge">{t("profile.passkeySynced")}</span>}
                </div>
                <div className="muted-3" style={{ fontSize: 12 }}>
                  {t("profile.passkeyCreated", { at: pk.createdAt })}
                  {pk.lastUsed ? ` · ${t("profile.passkeyUsed", { at: pk.lastUsed })}` : ""}
                </div>
              </div>
              <Btn
                variant="ghost"
                sm
                title={t("profile.passkeyRename")}
                onClick={() => {
                  setNewName(pk.name);
                  setRenaming(pk);
                }}
              >
                <Icon name="edit" size={16} />
              </Btn>
              <Btn variant="ghost" sm title={t("common.delete")} onClick={() => setDeleting(pk)}>
                <Icon name="trash" size={16} />
              </Btn>
            </div>
          ))}
        </div>
      )}

      {renaming && (
        <Modal
          title={t("profile.passkeyRename")}
          onClose={() => setRenaming(null)}
          footer={
            <>
              <Btn block onClick={() => setRenaming(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn
                variant="primary"
                block
                disabled={renameM.isPending || !newName.trim()}
                onClick={() => renameM.mutate({ id: renaming.id, name: newName })}
              >
                {t("common.save")}
              </Btn>
            </>
          }
        >
          <Field label={t("profile.passkeyName")}>
            <input
              className="input"
              value={newName}
              maxLength={120}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newName.trim()) renameM.mutate({ id: renaming.id, name: newName });
              }}
            />
          </Field>
        </Modal>
      )}

      {deleting && (
        <Modal
          title={t("profile.passkeyDeleteTitle")}
          onClose={() => setDeleting(null)}
          footer={
            <>
              <Btn block onClick={() => setDeleting(null)}>
                {t("common.cancel")}
              </Btn>
              <Btn variant="danger" block disabled={deleteM.isPending} onClick={() => deleteM.mutate(deleting.id)}>
                {t("common.delete")}
              </Btn>
            </>
          }
        >
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>
            {t("profile.passkeyDeleteText", { name: deleting.name })}
          </p>
        </Modal>
      )}
    </div>
  );
}
