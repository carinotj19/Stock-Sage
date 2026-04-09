import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { createProcessConfigs, getNpmCommand, getPythonCandidates, pickAvailablePython } from "./dev-stack.mjs";

test("getPythonCandidates prefers STOCK_SAGE_PYTHON override", () => {
  const candidates = getPythonCandidates("win32", { STOCK_SAGE_PYTHON: "custom-python" });

  assert.deepEqual(candidates, [{ command: "custom-python", args: [] }]);
});

test("getPythonCandidates returns expected windows launcher order", () => {
  const candidates = getPythonCandidates("win32", {});

  assert.deepEqual(candidates, [
    { command: "py", args: ["-3"] },
    { command: "python", args: [] }
  ]);
});

test("pickAvailablePython returns the first matching candidate", () => {
  const python = pickAvailablePython({
    platform: "linux",
    env: {},
    probe: (candidate) => candidate.command === "python"
  });

  assert.deepEqual(python, { command: "python", args: [] });
});

test("getNpmCommand uses npm.cmd on windows", () => {
  assert.equal(getNpmCommand("win32"), "npm.cmd");
  assert.equal(getNpmCommand("linux"), "npm");
});

test("createProcessConfigs wires backend and frontend commands", () => {
  const repoRoot = mkdtempSync(join(tmpdir(), "stock-sage-dev-stack-"));
  const backendDir = join(repoRoot, "backend");
  const frontendDir = join(repoRoot, "frontend");

  mkdirSync(backendDir);
  mkdirSync(frontendDir);

  try {
    const configs = createProcessConfigs({
      repoRoot,
      platform: "win32",
      env: {},
      probe: () => true
    });

    assert.equal(configs.length, 2);
    assert.deepEqual(configs[0], {
      name: "backend",
      command: "py",
      args: ["-3", "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000", "--app-dir", backendDir],
      cwd: repoRoot
    });
    assert.deepEqual(configs[1], {
      name: "frontend",
      command: "npm.cmd",
      args: ["run", "dev"],
      cwd: frontendDir,
      shell: true
    });
  } finally {
    rmSync(repoRoot, { force: true, recursive: true });
  }
});
