import { Ajv2020 } from "ajv/dist/2020.js";
import publicViewsSchema from "../../../contracts/api/public-views.schema.json" with { type: "json" };
import eventsSchema from "../../../contracts/api/events.schema.json" with { type: "json" };

export type ValidationResult = { ok: true } | { ok: false; code: "SCHEMA_VALIDATION_FAILED"; errors: string[] };

type CompiledValidator = ReturnType<Ajv2020["compile"]>;

const ajv = new Ajv2020({ allErrors: true, strict: false });
const publicViewValidator = ajv.compile(publicViewsSchema);
const eventEnvelopeValidator = ajv.compile(eventsSchema);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toResult(validator: CompiledValidator, value: unknown, kind?: string): ValidationResult {
  if (validator(value) === true && (kind === undefined || (isRecord(value) && value.kind === kind))) return { ok: true };
  const errors = validator.errors?.map((error) => `${error.instancePath || "/"} ${error.message ?? "invalid"}`) ?? [];
  if (kind !== undefined && isRecord(value) && value.kind !== kind) errors.push(`/kind must be ${kind}`);
  return { ok: false, code: "SCHEMA_VALIDATION_FAILED", errors };
}

export function validateReviewView(value: unknown): ValidationResult {
  return toResult(publicViewValidator, value, "review");
}

export function validateEventEnvelope(value: unknown): ValidationResult {
  return toResult(eventEnvelopeValidator, value);
}
