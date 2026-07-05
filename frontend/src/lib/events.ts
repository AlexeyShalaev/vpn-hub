// SSE realtime: пуш сигналов инвалидации вместо агрессивного поллинга.
//
// Бэкенд держит открытый text/event-stream на GET /api/v1/stream и шлёт события-СИГНАЛЫ
// (`server`/`sync`), не полезную нагрузку — данные дотягивает react-query по инвалидации ключей.
// Поллинг НЕ удаляем: оставляем страховкой (пониженная частота) на случай тихого обрыва SSE
// (буферизация прокси / потеря сети).

import type { QueryClient } from "@tanstack/react-query";
import { API_BASE } from "./api";

// событие несёт только сигнал: {id} (id сервера или null для коарс-грейн сигнала)
type SseData = { id?: string | null; ts?: number };

// Чистая функция (юнит-тестируемая): топик события → какие react-query ключи протухли.
// Держим коарс-грейн: `server` инвалидирует список и (если пришёл id) конкретный сервер и его
// доступы/advanced; `sync` — только список серверов (детали подтянет активный ["server", id]).
export function keysToInvalidate(topic: string, id: string | null | undefined): unknown[][] {
  if (topic === "server") {
    const keys: unknown[][] = [["servers"]];
    if (id) {
      keys.push(["server", id], ["server-access", id]);
    }
    return keys;
  }
  if (topic === "sync") {
    return [["servers"]];
  }
  return [];
}

const RECONNECT_MAX_MS = 30_000;
const RECONNECT_BASE_MS = 1_000;

// Открывает EventSource и переинвалидирует ключи на события. Возвращает cleanup-функцию.
// Идемпотентность/повторный вызов под React StrictMode обеспечивает вызывающий (см. App.tsx):
// cleanup закрывает текущий коннект и отменяет запланированный reconnect.
export function subscribeEvents(qc: QueryClient): () => void {
  let es: EventSource | null = null;
  let closed = false;
  let attempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const onTopic = (topic: string) => (ev: MessageEvent) => {
    let id: string | null | undefined;
    try {
      const data = JSON.parse(ev.data) as SseData;
      id = data.id;
    } catch {
      id = null; // кадр без валидного JSON — трактуем как коарс-грейн сигнал
    }
    for (const key of keysToInvalidate(topic, id)) {
      qc.invalidateQueries({ queryKey: key });
    }
  };

  const connect = () => {
    if (closed) return;
    es = new EventSource(`${API_BASE}/stream`, { withCredentials: true });
    es.addEventListener("server", onTopic("server"));
    es.addEventListener("sync", onTopic("sync"));
    es.onopen = () => {
      attempt = 0; // успешный коннект сбрасывает backoff
    };
    es.onerror = () => {
      // EventSource сам ретраит, но при hard-close (напр. 401) переоткрываем с backoff.
      if (closed || !es) return;
      if (es.readyState === EventSource.CLOSED) {
        es.close();
        es = null;
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
        attempt += 1;
        reconnectTimer = setTimeout(connect, delay);
      }
    };
  };

  connect();

  return () => {
    closed = true;
    if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    if (es) {
      es.close();
      es = null;
    }
  };
}
