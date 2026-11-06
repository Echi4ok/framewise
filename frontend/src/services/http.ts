function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function responseMessage(data: unknown, status: number): string {
  const detail = isRecord(data) ? data.detail : undefined;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (
    isRecord(detail) &&
    typeof detail.message === "string" &&
    detail.message.trim()
  )
    return detail.message;
  if (Array.isArray(detail)) {
    const messages = detail.filter(isRecord).flatMap((item) => {
      if (typeof item.msg !== "string" || !item.msg.trim()) return [];
      const location = Array.isArray(item.loc)
        ? item.loc.slice(1).join(".")
        : "";
      return [`${location || "Данные"}: ${item.msg}`];
    });
    if (messages.length) return messages.join("; ");
  }
  if (status === 408 || status === 504)
    return "Сервер отвечает слишком долго. Повторите попытку.";
  return `Не удалось выполнить запрос (${status}).`;
}

export async function request(
  path: string,
  init: RequestInit,
  timeoutMs = 10_000,
): Promise<unknown> {
  const controller = new AbortController();
  const caller = init.signal;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const cancel = () => {
    clearTimeout(timer);
    controller.abort(caller?.reason);
  };
  if (caller?.aborted) cancel();
  else caller?.addEventListener("abort", cancel, { once: true });
  let response: Response | undefined;
  try {
    response = await fetch(path, { ...init, signal: controller.signal });
    const data: unknown = await response.json().catch((cause: unknown) => {
      if (controller.signal.aborted) throw cause;
      return null;
    });
    controller.signal.throwIfAborted();
    if (!response.ok) throw new Error(responseMessage(data, response.status));
    if (data === null)
      throw new Error("Сервер вернул некорректный ответ. Повторите попытку.");
    return data;
  } catch (cause) {
    if (caller?.aborted) throw cause;
    if (timedOut)
      throw new Error("Сервер отвечает слишком долго. Повторите попытку.", {
        cause,
      });
    if (!response)
      throw new Error(
        "Сервер недоступен. Проверьте подключение и повторите попытку.",
        { cause },
      );
    throw cause;
  } finally {
    clearTimeout(timer);
    caller?.removeEventListener("abort", cancel);
  }
}

export function post(path: string, data: unknown, signal: AbortSignal) {
  return request(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
      signal,
    },
    370_000,
  );
}
