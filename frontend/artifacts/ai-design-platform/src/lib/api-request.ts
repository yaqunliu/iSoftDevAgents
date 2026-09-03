const REQUEST_TIMEOUT_REASON = "isoftdevagents-request-timeout";

export class RequestTimeoutError extends Error {
  timeoutMs: number;
  url: string;

  constructor(url: string, timeoutMs: number) {
    super(`Request timed out after ${timeoutMs}ms: ${url}`);
    this.name = "RequestTimeoutError";
    this.timeoutMs = timeoutMs;
    this.url = url;
  }
}

export type FetchWithTimeoutOptions = {
  url: string;
  init?: RequestInit;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
};

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

// 设计注释：这里把“请求超时”收口到独立模块，避免每个 query 自己处理超时逻辑。
// 这样一来，只要底层接口挂住，页面就会稳定进入错误态，而不是永远停在 loading。
export async function fetchWithTimeout({
  url,
  init,
  timeoutMs,
  fetchImpl = fetch,
}: FetchWithTimeoutOptions): Promise<Response> {
  const controller = new AbortController();
  const upstreamSignal = init?.signal;

  // 教学注释：如果调用方本身也传了 signal，我们仍然统一走自己的 controller，
  // 这样既能继承外部取消，也能附加平台自己的超时取消。
  const abortFromUpstream = () => {
    controller.abort(upstreamSignal?.reason);
  };

  if (upstreamSignal?.aborted) {
    abortFromUpstream();
  } else if (upstreamSignal) {
    upstreamSignal.addEventListener("abort", abortFromUpstream, { once: true });
  }

  const timer = globalThis.setTimeout(() => {
    controller.abort(REQUEST_TIMEOUT_REASON);
  }, timeoutMs);

  try {
    const response = await fetchImpl(url, {
      ...init,
      signal: controller.signal,
    });
    return response;
  } catch (error) {
    if (isAbortError(error) && controller.signal.reason === REQUEST_TIMEOUT_REASON) {
      throw new RequestTimeoutError(url, timeoutMs);
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timer);
    if (upstreamSignal) {
      upstreamSignal.removeEventListener("abort", abortFromUpstream);
    }
  }
}
