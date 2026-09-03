import test from "node:test";
import assert from "node:assert/strict";

import {
  isInteractionCardMutationPending,
  resolveConfirmationCardPhase,
  resolveConfirmationMessagePhase,
  shouldShowCollapsedInteractionActions,
} from "./confirmation-card-state.ts";

test("resolveConfirmationCardPhase keeps the latest waiting card actionable", () => {
  const phase = resolveConfirmationCardPhase({
    messageId: "m2",
    activeMessageId: "m2",
    taskStatus: "waiting_user",
  });

  assert.equal(phase, "waiting");
});

test("resolveConfirmationCardPhase marks a submitted card as running", () => {
  const phase = resolveConfirmationCardPhase({
    messageId: "m2",
    activeMessageId: "m2",
    taskStatus: "running",
    currentActivePhase: "waiting_for_requirements_artifact_review",
    confirmationActivePhase: "waiting_for_requirements_artifact_review",
  });

  assert.equal(phase, "running");
});

test("resolveConfirmationCardPhase marks the requirements review card as completed after the workflow moves into architecture", () => {
  const phase = resolveConfirmationCardPhase({
    messageId: "m2",
    activeMessageId: "m2",
    taskStatus: "running",
    currentActivePhase: "architecture_generation_started",
    confirmationActivePhase: "waiting_for_requirements_artifact_review",
  });

  assert.equal(phase, "completed");
});

test("resolveConfirmationCardPhase marks the architecture review card as completed after the workflow moves into ui generation", () => {
  const phase = resolveConfirmationCardPhase({
    messageId: "m3",
    activeMessageId: "m3",
    taskStatus: "running",
    currentActivePhase: "ui_generation_started",
    confirmationActivePhase: "waiting_for_artifact_review",
  });

  assert.equal(phase, "completed");
});

test("resolveConfirmationCardPhase marks older confirmation cards as inactive", () => {
  const phase = resolveConfirmationCardPhase({
    messageId: "m1",
    activeMessageId: "m2",
    taskStatus: "waiting_user",
  });

  assert.equal(phase, "inactive");
});

test("shouldShowCollapsedInteractionActions keeps waiting cards actionable while collapsed", () => {
  assert.equal(
    shouldShowCollapsedInteractionActions({
      phase: "waiting",
      expanded: false,
    }),
    true,
  );
});

test("resolveConfirmationMessagePhase reconstructs the waiting phase for requirements feedback cards", () => {
  assert.equal(
    resolveConfirmationMessagePhase({
      confirmationKind: "requirements_feedback",
    }),
    "requirements_feedback_required",
  );
});

test("shouldShowCollapsedInteractionActions hides collapsed actions after the card is expanded or no longer waiting", () => {
  assert.equal(
    shouldShowCollapsedInteractionActions({
      phase: "waiting",
      expanded: true,
    }),
    false,
  );
  assert.equal(
    shouldShowCollapsedInteractionActions({
      phase: "running",
      expanded: false,
    }),
    false,
  );
});

test("isInteractionCardMutationPending only keeps loading on the card that actually submitted", () => {
  assert.equal(
    isInteractionCardMutationPending({
      mutationPending: true,
      submittedMessageId: "requirements-card",
      messageId: "architecture-card",
    }),
    false,
  );

  assert.equal(
    isInteractionCardMutationPending({
      mutationPending: true,
      submittedMessageId: "architecture-card",
      messageId: "architecture-card",
    }),
    true,
  );
});

test("isInteractionCardMutationPending immediately locks the clicked confirmation card before the request state catches up", () => {
  assert.equal(
    isInteractionCardMutationPending({
      mutationPending: false,
      submittedMessageId: null,
      messageId: "requirements-card",
      optimisticMessageId: "requirements-card",
    }),
    true,
  );

  assert.equal(
    isInteractionCardMutationPending({
      mutationPending: false,
      submittedMessageId: null,
      messageId: "architecture-card",
      optimisticMessageId: "requirements-card",
    }),
    false,
  );
});
