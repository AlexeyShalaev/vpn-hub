import { describe, expect, it } from "vitest";
import {
  assertionToJSON,
  base64urlToBuffer,
  bufferToBase64url,
  type CredentialLike,
  isUserCancel,
  originMatches,
  registrationToJSON,
  toCreationOptions,
  toRequestOptions,
} from "./webauthn";

const bytes = (...xs: number[]) => new Uint8Array(xs).buffer;

describe("base64url", () => {
  it("кодирует без паддинга и с URL-безопасным алфавитом", () => {
    expect(bufferToBase64url(bytes(0xfb, 0xff, 0xbf))).toBe("-_-_");
    expect(bufferToBase64url(bytes(1))).toBe("AQ");
    expect(bufferToBase64url(new Uint8Array(0))).toBe("");
  });

  it("round-trip для произвольных байтов, в том числе срезов Uint8Array", () => {
    const src = new Uint8Array(256).map((_, i) => i);
    const back = new Uint8Array(base64urlToBuffer(bufferToBase64url(src)));
    expect(Array.from(back)).toEqual(Array.from(src));
    const slice = src.subarray(10, 13);
    expect(Array.from(new Uint8Array(base64urlToBuffer(bufferToBase64url(slice))))).toEqual([10, 11, 12]);
  });

  it("декодирует строки без паддинга любой длины", () => {
    expect(Array.from(new Uint8Array(base64urlToBuffer("AQ")))).toEqual([1]);
    expect(Array.from(new Uint8Array(base64urlToBuffer("AQI")))).toEqual([1, 2]);
    expect(Array.from(new Uint8Array(base64urlToBuffer("AQID")))).toEqual([1, 2, 3]);
  });
});

describe("опции сервера → navigator.credentials", () => {
  it("toCreationOptions переводит challenge, user.id и excludeCredentials в буферы", () => {
    const opts = toCreationOptions({
      rp: { id: "vpn.example.com", name: "VPN Hub" },
      user: { id: "dXNlcjE", name: "+79001112233", displayName: "Иван" },
      challenge: "AQID",
      pubKeyCredParams: [{ type: "public-key", alg: -7 }],
      excludeCredentials: [{ id: "BAU", type: "public-key", transports: ["internal"] }],
      authenticatorSelection: { residentKey: "required", userVerification: "required" },
      attestation: "none",
    });
    expect(Array.from(new Uint8Array(opts.challenge as ArrayBuffer))).toEqual([1, 2, 3]);
    expect(new TextDecoder().decode(opts.user.id as ArrayBuffer)).toBe("user1");
    const ex = opts.excludeCredentials?.[0];
    expect(Array.from(new Uint8Array(ex?.id as ArrayBuffer))).toEqual([4, 5]);
    expect(ex?.transports).toEqual(["internal"]);
    expect(opts.authenticatorSelection?.residentKey).toBe("required");
  });

  it("toRequestOptions: пустой allowCredentials — вход без логина (discoverable)", () => {
    const opts = toRequestOptions({ challenge: "AQID", rpId: "vpn.example.com", userVerification: "required" });
    expect(opts.allowCredentials).toEqual([]);
    expect(opts.rpId).toBe("vpn.example.com");
    expect(Array.from(new Uint8Array(opts.challenge as ArrayBuffer))).toEqual([1, 2, 3]);
  });
});

describe("ответ браузера → JSON", () => {
  it("registrationToJSON кодирует поля и берёт transports из getTransports()", () => {
    const cred: CredentialLike = {
      id: "AQ",
      rawId: bytes(1),
      type: "public-key",
      authenticatorAttachment: "platform",
      response: { clientDataJSON: bytes(2), attestationObject: bytes(3), getTransports: () => ["internal", "hybrid"] },
    };
    expect(registrationToJSON(cred)).toEqual({
      id: "AQ",
      rawId: "AQ",
      type: "public-key",
      authenticatorAttachment: "platform",
      response: { clientDataJSON: "Ag", attestationObject: "Aw", transports: ["internal", "hybrid"] },
      clientExtensionResults: {},
    });
  });

  it("assertionToJSON: userHandle null, если аутентификатор его не вернул", () => {
    const cred: CredentialLike = {
      id: "AQ",
      rawId: bytes(1),
      type: "public-key",
      response: { clientDataJSON: bytes(2), authenticatorData: bytes(3), signature: bytes(4), userHandle: null },
    };
    const json = assertionToJSON(cred) as { response: Record<string, unknown> };
    expect(json.response).toEqual({ clientDataJSON: "Ag", authenticatorData: "Aw", signature: "BA", userHandle: null });
  });

  it("путаница типов ответа — явная ошибка, а не тихий мусор на сервер", () => {
    const reg: CredentialLike = {
      id: "AQ",
      rawId: bytes(1),
      type: "public-key",
      response: { clientDataJSON: bytes(2) },
    };
    expect(() => registrationToJSON(reg)).toThrow();
    expect(() => assertionToJSON(reg)).toThrow();
  });
});

describe("служебные проверки", () => {
  it("originMatches сравнивает без учёта регистра и хвостового слэша", () => {
    expect(originMatches("https://VPN.example.com/", "https://vpn.example.com")).toBe(true);
    expect(originMatches("https://vpn.example.com", "http://localhost:3000")).toBe(false);
    expect(originMatches(null, "https://vpn.example.com")).toBe(false);
  });

  it("isUserCancel распознаёт отмену системного диалога", () => {
    expect(isUserCancel(new DOMException("cancelled", "NotAllowedError"))).toBe(true);
    expect(isUserCancel(new DOMException("aborted", "AbortError"))).toBe(true);
    expect(isUserCancel(new DOMException("dup", "InvalidStateError"))).toBe(false);
    expect(isUserCancel(new Error("x"))).toBe(false);
  });
});
