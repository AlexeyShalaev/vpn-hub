import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, http } from "./api";

function stubFetch(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const text = body === null ? "" : JSON.stringify(body);
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: () => Promise.resolve(text),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("http client", () => {
  it("GET → распарсенный JSON, same-origin, credentials include", async () => {
    const fn = stubFetch(200, { a: 1 });
    const r = await http.get<{ a: number }>("/x");
    expect(r).toEqual({ a: 1 });
    expect(fn).toHaveBeenCalledWith("/api/v1/x", expect.objectContaining({ method: "GET", credentials: "include" }));
  });

  it("на все запросы ставит X-Requested-With (защита от CSRF)", async () => {
    const fn = stubFetch(200, {});
    await http.get("/x");
    const getInit = fn.mock.calls[0][1] as RequestInit;
    expect((getInit.headers as Record<string, string>)["X-Requested-With"]).toBe("fetch");
  });

  it("POST сериализует тело и ставит Content-Type", async () => {
    const fn = stubFetch(200, {});
    await http.post("/y", { n: 1 });
    const init = fn.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-Requested-With"]).toBe("fetch");
    expect(init.body).toBe(JSON.stringify({ n: 1 }));
  });

  it("не-2xx → ApiError с code/status из тела", async () => {
    stubFetch(403, { code: "CSRF", message: "Запрос отклонён (CSRF)" });
    const err = await http.get("/z").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ code: "CSRF", status: 403, message: "Запрос отклонён (CSRF)" });
  });

  it("не-2xx без тела → дефолтный code ERROR", async () => {
    stubFetch(500, null);
    const err = await http.get("/z").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ code: "ERROR", status: 500 });
  });
});
