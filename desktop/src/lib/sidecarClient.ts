import type {
  SidecarMessage,
  SidecarMethod,
  SidecarRequest,
  SidecarResponse,
} from "../types";

type SendTransport = (request: SidecarRequest) => Promise<void>;
type PendingRequest = {
  resolve: (response: SidecarResponse) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
};

export class SidecarClient {
  private readonly pending = new Map<string, PendingRequest>();
  private readonly sendTransport: SendTransport;
  private readonly createId: () => string;

  constructor(
    sendTransport: SendTransport,
    createId: () => string = () => crypto.randomUUID(),
  ) {
    this.sendTransport = sendTransport;
    this.createId = createId;
  }

  async request(
    method: SidecarMethod,
    params: Record<string, unknown> = {},
    timeoutMs = 10_000,
  ): Promise<SidecarResponse> {
    const request: SidecarRequest = { id: this.createId(), method, params };
    const response = new Promise<SidecarResponse>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(request.id);
        reject(new Error(`sidecar request timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(request.id, { resolve, reject, timer });
    });

    try {
      await this.sendTransport(request);
    } catch (error) {
      this.reject(
        request.id,
        error instanceof Error ? error : new Error(String(error)),
      );
    }
    return response;
  }

  accept(message: SidecarMessage): boolean {
    if (message.kind !== "response") return false;
    const pending = this.pending.get(message.id);
    if (!pending) return false;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);
    if (message.ok) {
      pending.resolve(message);
    } else {
      pending.reject(new Error(message.error || "sidecar request failed"));
    }
    return true;
  }

  dispose(reason = "sidecar client disposed"): void {
    for (const id of [...this.pending.keys()]) {
      this.reject(id, new Error(reason));
    }
  }

  private reject(id: string, error: Error): void {
    const pending = this.pending.get(id);
    if (!pending) return;
    this.pending.delete(id);
    clearTimeout(pending.timer);
    pending.reject(error);
  }
}
