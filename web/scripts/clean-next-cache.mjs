import { existsSync, rmSync } from "node:fs";
import { resolve } from "node:path";

for (const dirName of [".next", ".next-dev", ".next-build"]) {
  const dirPath = resolve(process.cwd(), dirName);
  if (existsSync(dirPath)) {
    rmSync(dirPath, { recursive: true, force: true });
  }
}
