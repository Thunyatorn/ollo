import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (existsSync(path.join(root, ".env")))
  process.loadEnvFile(path.join(root, ".env"));
const python = path.join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
if (!existsSync(python)) {
  console.error(
    "Set up the Python environment first. See README.md → Run locally.",
  );
  process.exit(1);
}
const api = spawn(
  python,
  ["-m", "uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8000"],
  { cwd: root, stdio: "inherit" },
);
const web = spawn(
  process.platform === "win32" ? "npm.cmd" : "npm",
  ["run", "dev"],
  { cwd: root, stdio: "inherit" },
);
let stopping = false;
function stop() {
  if (stopping) return;
  stopping = true;
  api.kill("SIGTERM");
  web.kill("SIGTERM");
}
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
for (const child of [api, web])
  child.on("exit", (code) => {
    if (!stopping) {
      stop();
      process.exitCode = code ?? 1;
    }
  });
