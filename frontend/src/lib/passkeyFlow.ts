// Церемонии ключей доступа целиком: опции с сервера → системный диалог браузера → проверка на сервере.
import * as q from "./queries";
import type { Me, Passkey } from "./types";
import {
  assertionToJSON,
  type CredentialLike,
  registrationToJSON,
  toCreationOptions,
  toRequestOptions,
} from "./webauthn";

function cancelled(): DOMException {
  return new DOMException("The operation was cancelled", "NotAllowedError");
}

/** Создать ключ доступа для текущего пользователя и сохранить его на сервере. */
export async function createPasskey(): Promise<Passkey> {
  const { challengeId, publicKey } = await q.passkeyRegisterOptions();
  const cred = await navigator.credentials.create({ publicKey: toCreationOptions(publicKey) });
  if (!cred) throw cancelled();
  return q.passkeyRegister({ challengeId, credential: registrationToJSON(cred as unknown as CredentialLike) });
}

/**
 * Вход по ключу доступа. conditional — тихий запрос для автозаполнения поля логина:
 * браузер покажет ключи в подсказках и вернёт ответ, только когда пользователь выберет ключ.
 */
export async function signInWithPasskey(opts: { conditional?: boolean; signal?: AbortSignal } = {}): Promise<Me> {
  const { challengeId, publicKey } = await q.passkeyLoginOptions();
  const cred = await navigator.credentials.get({
    publicKey: toRequestOptions(publicKey),
    ...(opts.conditional ? { mediation: "conditional" as CredentialMediationRequirement } : {}),
    signal: opts.signal,
  });
  if (!cred) throw cancelled();
  return q.passkeyLogin({ challengeId, credential: assertionToJSON(cred as unknown as CredentialLike) });
}
