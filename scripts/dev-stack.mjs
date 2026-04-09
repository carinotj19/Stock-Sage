import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

export const getNpmCommand = (platform = process.platform) => (platform === "win32" ? "npm.cmd" : "npm");

export const getPythonCandidates = (platform = process.platform, env = process.env) => {
  if (env.STOCK_SAGE_PYTHON) {
    return [{ command: env.STOCK_SAGE_PYTHON, args: [] }];
  }

  return platform === "win32"
    ? [
        { command: "py", args: ["-3"] },
        { command: "python", args: [] }
      ]
    : [
        { command: "python3", args: [] },
        { command: "python", args: [] }
      ];
};

const defaultProbe = (candidate) => {
  const result = spawnSync(candidate.command, [...candidate.args, "--version"], {
    stdio: "ignore"
  });

  return result.status === 0;
};

export const pickAvailablePython = ({
  platform = process.platform,
  env = process.env,
  probe = defaultProbe
} = {}) => {
  const match = getPythonCandidates(platform, env).find((candidate) => probe(candidate));

  if (!match) {
    throw new Error(
      "No Python executable was found. Set STOCK_SAGE_PYTHON or install a working Python launcher."
    );
  }

  return match;
};

export const createProcessConfigs = ({
  repoRoot,
  platform = process.platform,
  env = process.env,
  probe = defaultProbe
}) => {
  const backendDir = join(repoRoot, "backend");
  const frontendDir = join(repoRoot, "frontend");

  if (!existsSync(backendDir)) {
    throw new Error(`Backend directory not found: ${backendDir}`);
  }

  if (!existsSync(frontendDir)) {
    throw new Error(`Frontend directory not found: ${frontendDir}`);
  }

  const python = pickAvailablePython({ platform, env, probe });

  return [
    {
      name: "backend",
      command: python.command,
      args: [...python.args, "-m", "uvicorn", "app.main:app", "--reload", "--port", "8000", "--app-dir", backendDir],
      cwd: repoRoot
    },
    {
      name: "frontend",
      command: getNpmCommand(platform),
      args: ["run", "dev"],
      cwd: frontendDir,
      shell: platform === "win32"
    }
  ];
};

const run = () => {
  const repoRoot = process.cwd();
  const processConfigs = createProcessConfigs({ repoRoot });
  const children = [];
  let shuttingDown = false;

  const shutdown = (exitCode = 0) => {
    if (shuttingDown) return;
    shuttingDown = true;

    for (const child of children) {
      if (!child.killed) {
        child.kill("SIGTERM");
      }
    }

    process.exit(exitCode);
  };

  for (const config of processConfigs) {
    console.log(`[dev-stack] starting ${config.name}: ${config.command} ${config.args.join(" ")}`);

    const child = spawn(config.command, config.args, {
      cwd: config.cwd,
      env: process.env,
      shell: config.shell ?? false,
      stdio: "inherit"
    });

    child.on("exit", (code) => {
      if (shuttingDown) return;

      if (code && code !== 0) {
        console.error(`[dev-stack] ${config.name} exited with code ${code}`);
        shutdown(code);
        return;
      }

      console.log(`[dev-stack] ${config.name} exited`);
      shutdown(0);
    });

    child.on("error", (error) => {
      if (shuttingDown) return;
      console.error(`[dev-stack] failed to start ${config.name}: ${error.message}`);
      shutdown(1);
    });

    children.push(child);
  }

  process.on("SIGINT", () => shutdown(0));
  process.on("SIGTERM", () => shutdown(0));
};

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  run();
}
