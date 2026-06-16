export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_TRADE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    if (typeof payload.detail === "string") return payload.detail;
    if (typeof payload.message === "string") return payload.message;
  } catch {
    // Fall through to status text.
  }
  return response.statusText || `HTTP ${response.status}`;
}

export async function apiGet<T>(path: string, timeoutMs = 10_000): Promise<T> {
  const controller = new AbortController();
  const url = `${apiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new ApiError(await errorMessage(response), response.status);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("Network request failed", 0);
  } finally {
    globalThis.clearTimeout(timeout);
  }
}
