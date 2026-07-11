import { tg } from "./i18n";

// Генерация надёжного читаемого ключа восстановления: 4 группы по 5 символов (≈100 бит).
// Алфавит без неоднозначных символов (нет I/O/0/1); 32 делит 256 нацело → без modulo-bias.
export function generateRecoveryKey(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = new Uint8Array(20);
  crypto.getRandomValues(bytes);
  const chars = Array.from(bytes, (b) => alphabet[b % alphabet.length]);
  const groups: string[] = [];
  for (let i = 0; i < chars.length; i += 5) groups.push(chars.slice(i, i + 5).join(""));
  return groups.join("-");
}

// Скачивание ключа восстановления бэкапов в виде .txt (как recovery key в крупных системах).
export function downloadRecoveryKey(key: string) {
  const body = [
    tg("recovery.fileTitle"),
    "=====================================",
    "",
    tg("recovery.fileKeyLine", { key }),
    "",
    tg("recovery.fileDescLine1"),
    tg("recovery.fileDescLine2"),
    "",
    tg("recovery.fileTipStore"),
    tg("recovery.fileTipShare"),
    tg("recovery.fileTipLoss"),
    "",
  ].join("\n");
  const blob = new Blob([body], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "vpnhub-recovery-key.txt";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
