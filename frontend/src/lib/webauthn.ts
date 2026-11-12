// Ключи доступа (passkeys): мост между JSON-опциями сервера и navigator.credentials.
//
// Сервер (py_webauthn) отдаёт опции в JSON, где бинарные поля (challenge, user.id, id ключей)
// закодированы base64url. Браузерному API нужны ArrayBuffer — конвертируем туда и обратно сами,
// без зависимостей: PublicKeyCredential.parseCreationOptionsFromJSON есть не во всех браузерах.

export function bufferToBase64url(buf: ArrayBuffer | ArrayBufferView): string {
  const bytes =
    buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function base64urlToBuffer(s: string): ArrayBuffer {
  let t = s.replace(/-/g, "+").replace(/_/g, "/");
  const rem = t.length % 4;
  if (rem) t += "=".repeat(4 - rem);
  const bin = atob(t);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

// ── опции от сервера (JSON-форма WebAuthn) ──────────────────────────────────────

type DescriptorJSON = { id: string; type: "public-key"; transports?: string[] };

export interface CreationOptionsJSON {
  rp: { id?: string; name: string };
  user: { id: string; name: string; displayName: string };
  challenge: string;
  pubKeyCredParams: { type: "public-key"; alg: number }[];
  timeout?: number;
  excludeCredentials?: DescriptorJSON[];
  authenticatorSelection?: AuthenticatorSelectionCriteria;
  attestation?: AttestationConveyancePreference;
}

export interface RequestOptionsJSON {
  challenge: string;
  timeout?: number;
  rpId?: string;
  allowCredentials?: DescriptorJSON[];
  userVerification?: UserVerificationRequirement;
}

function descriptor(d: DescriptorJSON): PublicKeyCredentialDescriptor {
  return {
    id: base64urlToBuffer(d.id),
    type: d.type,
    ...(d.transports ? { transports: d.transports as AuthenticatorTransport[] } : {}),
  };
}

export function toCreationOptions(o: CreationOptionsJSON): PublicKeyCredentialCreationOptions {
  return {
    rp: o.rp,
    user: { id: base64urlToBuffer(o.user.id), name: o.user.name, displayName: o.user.displayName },
    challenge: base64urlToBuffer(o.challenge),
    pubKeyCredParams: o.pubKeyCredParams,
    timeout: o.timeout,
    excludeCredentials: (o.excludeCredentials ?? []).map(descriptor),
    authenticatorSelection: o.authenticatorSelection,
    attestation: o.attestation,
  };
}

export function toRequestOptions(o: RequestOptionsJSON): PublicKeyCredentialRequestOptions {
  return {
    challenge: base64urlToBuffer(o.challenge),
    timeout: o.timeout,
    rpId: o.rpId,
    allowCredentials: (o.allowCredentials ?? []).map(descriptor),
    userVerification: o.userVerification,
  };
}

// ── ответ браузера → JSON для сервера ───────────────────────────────────────────

// Минимальная форма PublicKeyCredential, которую мы читаем (удобно подменять в тестах).
export interface CredentialLike {
  id: string;
  rawId: ArrayBuffer;
  type: string;
  authenticatorAttachment?: string | null;
  response: {
    clientDataJSON: ArrayBuffer;
    attestationObject?: ArrayBuffer;
    getTransports?: () => string[];
    authenticatorData?: ArrayBuffer;
    signature?: ArrayBuffer;
    userHandle?: ArrayBuffer | null;
  };
}

export function registrationToJSON(c: CredentialLike): Record<string, unknown> {
  const r = c.response;
  if (!r.attestationObject) throw new Error("not a registration credential");
  return {
    id: c.id,
    rawId: bufferToBase64url(c.rawId),
    type: c.type,
    authenticatorAttachment: c.authenticatorAttachment ?? undefined,
    response: {
      clientDataJSON: bufferToBase64url(r.clientDataJSON),
      attestationObject: bufferToBase64url(r.attestationObject),
      transports: typeof r.getTransports === "function" ? r.getTransports() : [],
    },
    clientExtensionResults: {},
  };
}

export function assertionToJSON(c: CredentialLike): Record<string, unknown> {
  const r = c.response;
  if (!r.authenticatorData || !r.signature) throw new Error("not an assertion credential");
  return {
    id: c.id,
    rawId: bufferToBase64url(c.rawId),
    type: c.type,
    authenticatorAttachment: c.authenticatorAttachment ?? undefined,
    response: {
      clientDataJSON: bufferToBase64url(r.clientDataJSON),
      authenticatorData: bufferToBase64url(r.authenticatorData),
      signature: bufferToBase64url(r.signature),
      userHandle: r.userHandle ? bufferToBase64url(r.userHandle) : null,
    },
    clientExtensionResults: {},
  };
}

// ── возможности браузера ────────────────────────────────────────────────────────

/** WebAuthn вообще есть: secure context (https или localhost) и PublicKeyCredential. */
export function passkeysSupported(): boolean {
  return typeof window !== "undefined" && window.isSecureContext === true && "PublicKeyCredential" in window;
}

/** Можно ли предлагать ключи в автозаполнении поля логина (conditional mediation). */
export async function conditionalMediationAvailable(): Promise<boolean> {
  if (!passkeysSupported()) return false;
  const pkc = window.PublicKeyCredential as unknown as { isConditionalMediationAvailable?: () => Promise<boolean> };
  if (typeof pkc.isConditionalMediationAvailable !== "function") return false;
  try {
    return await pkc.isConditionalMediationAvailable();
  } catch {
    return false;
  }
}

/** Страница открыта по тому же origin, к которому сервер привязывает ключи (VPNHUB_BASE_URL). */
export function originMatches(expected: string | null | undefined, actual: string): boolean {
  return !!expected && expected.replace(/\/+$/, "").toLowerCase() === actual.toLowerCase();
}

/** Пользователь закрыл системный диалог или вышел таймаут — это не ошибка, молчим. */
export function isUserCancel(e: unknown): boolean {
  return e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "AbortError");
}
