import { existsSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import { spawn } from "node:child_process";

const cwd = process.cwd();
const devDistDir = ".next-dev";

for (const dirName of [devDistDir]) {
  const dirPath = resolve(cwd, dirName);
  if (existsSync(dirPath)) {
    rmSync(dirPath, { recursive: true, force: true });
  }
}

const child = spawn(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["next", "dev", "--hostname", "127.0.0.1"],
  {
    cwd,
    stdio: "inherit",
    env: {
      ...process.env,
      NEXT_DIST_DIR: devDistDir,
      NEXT_DISABLE_WEBPACK_CACHE: "1",
    },
  },
);

const forwardSignal = (signal) => {
  if (!child.killed) {
    child.kill(signal);
  }
};

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
