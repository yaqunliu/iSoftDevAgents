import test from "node:test";
import assert from "node:assert/strict";

import {
  appendProjectPage,
  getNextProjectPage,
  hasMoreProjectPages,
  renameProjectInList,
  type ProjectListItem,
} from "./project-list-state.ts";

function createProject(id: string): ProjectListItem {
  return {
    id,
    name: `Project ${id}`,
    description: `Description for ${id}`,
    status: "idle",
    currentVersion: 1,
    createdAt: "2026-04-01T00:00:00Z",
    updatedAt: "2026-04-01T00:00:00Z",
  };
}

test("appendProjectPage appends later pages for the same search", () => {
  const current = [createProject("p1"), createProject("p2")];
  const next = [createProject("p3"), createProject("p4")];

  const merged = appendProjectPage({
    currentProjects: current,
    incomingProjects: next,
    incomingPage: 2,
    activeSearch: "",
    incomingSearch: "",
  });

  assert.deepEqual(
    merged.map((project) => project.id),
    ["p1", "p2", "p3", "p4"],
  );
});

test("appendProjectPage replaces the list when the search changes", () => {
  const current = [createProject("p1"), createProject("p2")];
  const next = [createProject("p9")];

  const merged = appendProjectPage({
    currentProjects: current,
    incomingProjects: next,
    incomingPage: 1,
    activeSearch: "invoice",
    incomingSearch: "design",
  });

  assert.deepEqual(
    merged.map((project) => project.id),
    ["p9"],
  );
});

test("appendProjectPage keeps project ids unique when later pages overlap", () => {
  const current = [createProject("p1"), createProject("p2")];
  const next = [createProject("p2"), createProject("p3")];

  const merged = appendProjectPage({
    currentProjects: current,
    incomingProjects: next,
    incomingPage: 2,
    activeSearch: "",
    incomingSearch: "",
  });

  assert.deepEqual(
    merged.map((project) => project.id),
    ["p1", "p2", "p3"],
  );
});

test("paging helpers expose next page and whether more pages remain", () => {
  assert.equal(hasMoreProjectPages({ page: 1, totalPages: 3 }), true);
  assert.equal(hasMoreProjectPages({ page: 3, totalPages: 3 }), false);
  assert.equal(getNextProjectPage({ page: 2, totalPages: 4 }), 3);
  assert.equal(getNextProjectPage({ page: 4, totalPages: 4 }), null);
});

test("renameProjectInList only updates the matching project name", () => {
  const current = [createProject("p1"), createProject("p2")];

  const renamed = renameProjectInList(current, "p2", "Renamed Project");

  assert.equal(renamed[0]?.name, "Project p1");
  assert.equal(renamed[1]?.name, "Renamed Project");
  assert.equal(renamed[1]?.id, "p2");
});
