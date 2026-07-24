import type { EventEnvelope, RunStatePayload } from "@yagcode/contracts";
import { validateEventEnvelope } from "@yagcode/contracts/validate";

export class SchemaValidationError extends Error {
  readonly code = "SCHEMA_VALIDATION_FAILED";

  constructor(readonly errors: readonly string[]) {
    super("SCHEMA_VALIDATION_FAILED");
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string") throw new SchemaValidationError([`/${key} must be string`]);
  return value;
}

function readNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number") throw new SchemaValidationError([`/${key} must be number`]);
  return value;
}

function readGeneration(record: Record<string, unknown>): number | null | undefined {
  if (!("generation" in record)) return undefined;
  const value = record.generation;
  if (value === null || typeof value === "number") return value;
  throw new SchemaValidationError(["/generation must be number or null"]);
}

function validateEvent(value: unknown): void {
  const result = validateEventEnvelope(value);
  if (result.ok === false) throw new SchemaValidationError(result.errors);
}

export function toEventEnvelope(value: unknown): EventEnvelope {
  validateEvent(value);
  if (!isRecord(value)) throw new SchemaValidationError(["/ must be object"]);
  const eventType = readString(value, "event_type");
  const payloadValue = value.payload;
  if (!isRecord(payloadValue)) throw new SchemaValidationError(["/payload must be object"]);
  if (eventType === "run.state") {
    const payload: RunStatePayload = {
      run_id: readString(payloadValue, "run_id"),
      state: readString(payloadValue, "state"),
    };
    const generation = readGeneration(value);
    const runStateType: "run.state" = "run.state";
    const envelope = {
      event_type: runStateType,
      payload,
      profile_id: readString(value, "profile_id"),
      sequence: readNumber(value, "sequence"),
    };
    return generation === undefined ? envelope : { ...envelope, generation };
  }
  if (eventType === "action.intent") {
    const generation = readGeneration(value);
    const actionIntentType: "action.intent" = "action.intent";
    const envelope = {
      event_type: actionIntentType,
      payload: {
        kind: readString(payloadValue, "kind"),
      },
      profile_id: readString(value, "profile_id"),
      sequence: readNumber(value, "sequence"),
    };
    return generation === undefined ? envelope : { ...envelope, generation };
  }
  throw new SchemaValidationError(["/event_type invalid"]);
}

export function parseEventEnvelope(raw: string): EventEnvelope {
  let value: unknown;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    throw new SchemaValidationError(["/ must be valid JSON"]);
  }
  return toEventEnvelope(value);
}

export async function readSseMessages(stream: ReadableStream<Uint8Array>, onMessage: (message: string) => void): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    let separator = buffer.indexOf("\n\n");
    while (separator >= 0) {
      const frame = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      const dataLines = frame
        .split(/\r?\n/u)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice("data:".length).trimStart());
      if (dataLines.length > 0) onMessage(dataLines.join("\n"));
      separator = buffer.indexOf("\n\n");
    }
  }
}
