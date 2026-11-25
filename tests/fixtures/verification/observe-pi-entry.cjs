// Test-only Node preload. Observe the actual entrypoint/argv before Pi sets its process title.
const { appendFileSync } = require('node:fs');
const { join } = require('node:path');
const root = process.env.DCC_RUN_FIXTURE;
if (root && process.env.PI_OFFLINE === '1' && process.argv.includes('--session-id')) {
  appendFileSync(join(root, 'process-argv.jsonl'), JSON.stringify({
    pid: process.pid,
    argv: process.argv.slice(1),
    cwd: process.cwd(),
  }) + '\n', { mode: 0o600 });
}
