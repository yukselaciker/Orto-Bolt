import { spawn } from "node:child_process";

const buildDistDir = ".next-build";

const child = spawn(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["next", "start", "--hostname", "127.0.0.1"],
  {
    cwd: process.cwd(),
    stdio: "inherit",
    env: {
      ...process.env,
      NEXT_DIST_DIR: buildDistDir,
    },
  },
);

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
