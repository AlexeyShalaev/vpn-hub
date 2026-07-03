// Типизированный клиент REST (same-origin, cookie-сессия).

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const BASE = "/api/v1";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    credentials: "include",
    headers:
      body !== undefined
        ? { "Content-Type": "application/json", "X-Requested-With": "fetch" }
        : { "X-Requested-With": "fetch" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const code = data?.code || "ERROR";
    const message = data?.message || res.statusText || "Ошибка запроса";
    throw new ApiError(code, message, res.status);
  }
  return data as T;
}

async function upload<T>(path: string, form: FormData): Promise<T> {
  // Content-Type не задаём — браузер сам выставит multipart с boundary.
  const res = await fetch(BASE + path, {
    method: "POST",
    credentials: "include",
    headers: { "X-Requested-With": "fetch" },
    body: form,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const code = data?.code || "ERROR";
    const message = data?.message || res.statusText || "Ошибка запроса";
    throw new ApiError(code, message, res.status);
  }
  return data as T;
}

export const API_BASE = BASE;

export const http = {
  get: <T>(p: string) => req<T>("GET", p),
  post: <T>(p: string, b?: unknown) => req<T>("POST", p, b ?? {}),
  patch: <T>(p: string, b?: unknown) => req<T>("PATCH", p, b ?? {}),
  put: <T>(p: string, b?: unknown) => req<T>("PUT", p, b ?? {}),
  del: <T>(p: string) => req<T>("DELETE", p),
  upload: <T>(p: string, f: FormData) => upload<T>(p, f),
};
