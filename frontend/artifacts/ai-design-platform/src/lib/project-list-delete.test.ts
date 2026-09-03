import test from "node:test";
import assert from "node:assert/strict";

import {
  removeProjectFromList,
  shouldResetProjectListForUserChange,
  type ProjectListItem,
} from "./project-list-state.ts";

function createProject(id: string): ProjectListItem & { name: string } {
  return {
    id,
    name: `Project ${id}`,
  };
}

test("removeProjectFromList removes the matching project and keeps the others", () => {
  const projects = [createProject("p1"), createProject("p2"), createProject("p3")];

  const next = removeProjectFromList(projects, "p2");

  assert.deepEqual(
    next.map((project) => project.id),
    ["p1", "p3"],
  );
});

test("removeProjectFromList returns the original list shape when the project does not exist", () => {
  const projects = [createProject("p1"), createProject("p2")];

  const next = removeProjectFromList(projects, "missing");

  assert.deepEqual(next, projects);
});

test("shouldResetProjectListForUserChange keeps cached projects on first home mount", () => {
  assert.equal(shouldResetProjectListForUserChange(null, "user-a"), false);
});

test("shouldResetProjectListForUserChange resets projects when the signed-in user changes", () => {
  assert.equal(shouldResetProjectListForUserChange("user-a", "user-b"), true);
});
