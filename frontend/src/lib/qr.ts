import QRCode from "qrcode";

type Ecc = "L" | "M" | "Q" | "H";

export async function toDataUrl(text: string, width = 380, ecc: Ecc = "M"): Promise<string> {
  return QRCode.toDataURL(text, {
    margin: 1,
    width,
    errorCorrectionLevel: ecc,
    color: { dark: "#16181C", light: "#FFFFFF" },
  });
}

// ---- Формат мульти-QR AmneziaVPN (для больших vpn://-конфигов) ----
// Повторяет exportController::generateQrCodesFromConfig + qrCodeUtils::generateQrCodeImageSeries:
// в серию кладутся НЕ строка "vpn://<base64>", а сами ДЕКОДИРОВАННЫЕ (сжатые qCompress) байты —
// то есть base64url-декод части после "vpn://". Читатель собирает их и делает qUncompress→JSON.
// Байты режутся по 850; каждый чанк (QDataStream, big-endian):
//   qint16 magic(1984) | quint8 chunksCount | quint8 chunkIndex | QByteArray payload
// QByteArray в QDataStream = quint32 длина (BE) + байты. Затем base64url без '='. ECC LOW.
const AMNEZIA_QR_MAGIC = 1984;
const AMNEZIA_QR_CHUNK = 850;

function b64urlNoPad(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(s: string): Uint8Array {
  let t = s.replace(/-/g, "+").replace(/_/g, "/");
  const rem = t.length % 4;
  if (rem) t += "=".repeat(4 - rem);
  const bin = atob(t);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** Байты, которые кладутся в QR-серию. Для "vpn://<base64>" — декодированный payload
 *  (сжатые байты, как в оф. клиенте); для прочего — UTF-8 самой строки. */
function amneziaQrPayloadBytes(config: string): Uint8Array {
  const s = (config || "").trim();
  if (s.startsWith("vpn://")) {
    try {
      return b64urlDecode(s.slice("vpn://".length));
    } catch {
      /* повреждённый base64 — упадём на UTF-8 ниже */
    }
  }
  return new TextEncoder().encode(s);
}

/** Строки для QR-серии AmneziaVPN из строки конфига (vpn://…). Возвращает base64url-чанки. */
export function amneziaQrChunks(config: string): string[] {
  const data = amneziaQrPayloadBytes(config);
  const k = AMNEZIA_QR_CHUNK;
  const chunksCount = Math.ceil(data.length / k);
  const out: string[] = [];
  for (let i = 0; i < data.length; i += k) {
    const payload = data.subarray(i, i + k);
    const index = Math.round(i / k);
    const buf = new Uint8Array(8 + payload.length);
    const dv = new DataView(buf.buffer);
    dv.setInt16(0, AMNEZIA_QR_MAGIC, false); // big-endian
    buf[2] = chunksCount & 0xff;
    buf[3] = index & 0xff;
    dv.setUint32(4, payload.length, false); // big-endian длина QByteArray
    buf.set(payload, 8);
    out.push(b64urlNoPad(buf));
  }
  return out.length ? out : [""];
}
