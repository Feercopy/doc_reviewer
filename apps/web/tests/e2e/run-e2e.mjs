import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const required = ["E2E_ADMIN_LOGIN", "E2E_ADMIN_PASSWORD"];
const missing = required.filter((name) => !process.env[name]);

if (missing.length > 0) {
  console.error(`Missing required e2e environment variables: ${missing.join(", ")}`);
  console.error("Start the local API/worker stack, seed an admin user, then rerun with those variables set.");
  process.exit(2);
}

const require = createRequire(import.meta.url);
try {
  require.resolve("@playwright/test");
} catch {
  console.error("Missing @playwright/test in apps/web. Install Playwright before running e2e.");
  process.exit(2);
}

const webRoot = fileURLToPath(new URL("../..", import.meta.url));
const env = { ...process.env };
let server = null;
let exitCode = 1;

try {
  if (!env.E2E_BASE_URL) {
    const port = env.E2E_WEB_PORT || "3000";
    env.E2E_BASE_URL = `http://127.0.0.1:${port}`;
    server = spawn("npm", ["run", "start", "--", "--hostname", "127.0.0.1", "--port", port], {
      cwd: webRoot,
      env,
      stdio: "inherit",
    });

    await waitForHttp(`${env.E2E_BASE_URL}/login`, server);
  }

  const result = spawnSync("npx", ["--no-install", "playwright", "test", "tests/e2e/mvp-flow.spec.cjs"], {
    cwd: webRoot,
    env,
    stdio: "inherit",
  });

  if (result.error) {
    console.error(`Failed to start Playwright: ${result.error.message}`);
    exitCode = 2;
  } else {
    exitCode = result.status ?? 1;
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  exitCode = 2;
} finally {
  await stopServer(server);
}

process.exit(exitCode);

async function waitForHttp(url, child) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`Next.js test server exited before ${url} became available.`);
    }

    try {
      const response = await fetch(url, { redirect: "manual" });
      if (response.status >= 200 && response.status < 500) {
        return;
      }
    } catch {
      // Server is still starting.
    }

    await delay(250);
  }

  throw new Error(`Timed out waiting for Next.js test server at ${url}.`);
}

async function stopServer(child) {
  if (!child || child.exitCode !== null) {
    return;
  }

  child.kill("SIGTERM");
  await Promise.race([
    once(child, "exit"),
    delay(5_000).then(() => {
      if (child.exitCode === null) {
        child.kill("SIGKILL");
      }
    }),
  ]);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
