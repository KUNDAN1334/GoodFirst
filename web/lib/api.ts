import type { AnalyzeResult, CIResult, Health, Language, StepEvent } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export interface AnalyzeInput {
  repo: string;
  question: string; // the user's optional question about the repo
  language: Language;
}

export interface CIInput {
  pr: string;
  language: Language;
}

export interface StreamHandlers<T> {
  onStep: (e: StepEvent) => void;
  onResult: (r: T) => void;
  onError: (message: string) => void;
}

export type AnalyzeHandlers = StreamHandlers<AnalyzeResult>;

/**
 * POST to a GoodFirst endpoint and read its Server-Sent Events stream.
 * EventSource only supports GET, so we parse the stream from fetch() ourselves:
 * events are separated by a blank line; lines starting with ":" are keep-alives.
 */
async function postStream<T>(path: string, body: unknown, handlers: StreamHandlers<T>, signal: AbortSignal) {
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    if (signal.aborted) return;
    handlers.onError(
      `Couldn't reach the GoodFirst backend at ${API_URL}. Start it with "python -m goodfirst.api" and try again.`,
    );
    return;
  }
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => "");
    handlers.onError(
      resp.status === 422
        ? "That doesn't look like a valid request. Check the link."
        : `The backend answered with HTTP ${resp.status}. ${text.slice(0, 200)}`,
    );
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const dispatch = (block: string) => {
    let name = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (!data.length) return;
    const payload = JSON.parse(data.join("\n"));
    if (name === "step") handlers.onStep(payload as StepEvent);
    else if (name === "result") {
      finished = true;
      handlers.onResult(payload as T);
    } else if (name === "error") {
      finished = true;
      handlers.onError((payload as { message: string }).message);
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        dispatch(buffer.slice(0, idx));
        buffer = buffer.slice(idx + 2);
      }
    }
  } catch {
    if (signal.aborted) return;
    handlers.onError("The connection to the backend dropped before the analysis finished.");
    return;
  }
  if (!finished && !signal.aborted) {
    handlers.onError("The backend stopped before sending a result. Check the terminal running the API.");
  }
}

export function analyze(input: AnalyzeInput, handlers: StreamHandlers<AnalyzeResult>, signal: AbortSignal) {
  return postStream("/api/analyze", input, handlers, signal);
}

export function explainCI(input: CIInput, handlers: StreamHandlers<CIResult>, signal: AbortSignal) {
  return postStream("/api/ci", input, handlers, signal);
}

export async function getHealth(): Promise<Health | null> {
  try {
    const resp = await fetch(`${API_URL}/api/health`, { cache: "no-store" });
    return resp.ok ? ((await resp.json()) as Health) : null;
  } catch {
    return null;
  }
}
