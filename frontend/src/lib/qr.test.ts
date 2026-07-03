import { describe, expect, it } from "vitest";
import { amneziaQrChunks } from "./qr";

// декодирование base64url без паддинга обратно в байты (зеркалит b64urlNoPad из qr.ts)
function b64urlToBytes(s: string): Uint8Array {
  let t = s.replace(/-/g, "+").replace(/_/g, "/");
  const rem = t.length % 4;
  if (rem) t += "=".repeat(4 - rem);
  const bin = atob(t);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

function view(bytes: Uint8Array): DataView {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}

describe("amneziaQrChunks", () => {
  it("пустой конфиг → один пустой чанк", () => {
    expect(amneziaQrChunks("")).toEqual([""]);
  });

  it("короткий конфиг → один чанк с корректным заголовком", () => {
    const chunks = amneziaQrChunks("hello"); // не vpn:// → UTF-8 байты "hello" (5)
    expect(chunks).toHaveLength(1);
    const buf = b64urlToBytes(chunks[0]);
    const dv = view(buf);
    expect(dv.getInt16(0, false)).toBe(1984); // magic
    expect(buf[2]).toBe(1); // chunksCount
    expect(buf[3]).toBe(0); // chunkIndex
    expect(dv.getUint32(4, false)).toBe(5); // длина payload (QByteArray)
    expect(new TextDecoder().decode(buf.subarray(8))).toBe("hello");
  });

  it("конфиг > 850 байт → несколько чанков с возрастающим индексом", () => {
    const chunks = amneziaQrChunks("x".repeat(2000)); // 2000 байт → ceil(2000/850) = 3
    expect(chunks).toHaveLength(3);
    chunks.forEach((c, i) => {
      const buf = b64urlToBytes(c);
      expect(buf[2]).toBe(3); // общий chunksCount во всех чанках
      expect(buf[3]).toBe(i); // индекс 0, 1, 2
    });
  });

  it("vpn://<base64url> → в payload кладутся ДЕКОДИРОВАННЫЕ байты, а не строка", () => {
    // 'AAECAw' — base64url для байтов [0, 1, 2, 3]
    const buf = b64urlToBytes(amneziaQrChunks("vpn://AAECAw")[0]);
    expect(view(buf).getUint32(4, false)).toBe(4);
    expect(Array.from(buf.subarray(8))).toEqual([0, 1, 2, 3]);
  });
});
