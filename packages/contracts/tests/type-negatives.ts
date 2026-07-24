import type { EventEnvelope, ReviewView } from "../src/generated/api.js";

const validReview: ReviewView = {
  kind: "review",
  review_id: "review-1",
  state: "READY",
  generation: 1,
  summary: "2 files changed",
};

const validEvent: EventEnvelope = {
  profile_id: "profile-1",
  sequence: 1,
  event_type: "run.state",
  generation: 1,
  payload: {
    run_id: "run-1",
    state: "RUNNING",
  },
};

// @ts-expect-error review_id is required and must stay snake_case.
const missingReviewId: ReviewView = {
  kind: "review",
  state: "READY",
  generation: 1,
  summary: "2 files changed",
};

const camelCaseReview: ReviewView = {
  kind: "review",
  // @ts-expect-error camelCase aliases are forbidden at the wire boundary.
  reviewId: "review-1",
  state: "READY",
  generation: 1,
  summary: "2 files changed",
};

const invalidReviewState: ReviewView = {
  kind: "review",
  review_id: "review-1",
  // @ts-expect-error generated enum must reject values outside the schema.
  state: "DONE",
  generation: 1,
  summary: "2 files changed",
};

const invalidGeneration: ReviewView = {
  kind: "review",
  review_id: "review-1",
  state: "READY",
  // @ts-expect-error generation is a number, not a string.
  generation: "1",
  summary: "2 files changed",
};

// @ts-expect-error sequence is required.
const missingSequence: EventEnvelope = {
  profile_id: "profile-1",
  event_type: "run.state",
  payload: { run_id: "run-1", state: "RUNNING" },
};

const invalidEventName: EventEnvelope = {
  profile_id: "profile-1",
  sequence: 1,
  // @ts-expect-error event_type is generated from the event enum.
  event_type: "run.done",
  payload: { run_id: "run-1", state: "RUNNING" },
};

const camelCaseEvent: EventEnvelope = {
  // @ts-expect-error profile_id must remain snake_case.
  profileId: "profile-1",
  sequence: 1,
  event_type: "run.state",
  payload: { run_id: "run-1", state: "RUNNING" },
};

void validReview;
void validEvent;
void missingReviewId;
void camelCaseReview;
void invalidReviewState;
void invalidGeneration;
void missingSequence;
void invalidEventName;
void camelCaseEvent;
