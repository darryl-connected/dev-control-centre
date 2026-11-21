// Pi 1.4.0 local opt-in. No tools, child processes, settings writes or provider controls.
import { createHash } from 'node:crypto';
import { closeSync, constants, fstatSync, lstatSync, openSync, opendirSync, readSync } from 'node:fs';
import { basename, dirname, isAbsolute, join, normalize } from 'node:path';
import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent';

const STATE = 'dcc-handoff-state-v1';
const NOTICE = 'dcc-handoff-v1';
const DETAIL = {
  'missing-registration': 'No job registration at the specified path.',
  'invalid-registration': 'Expected a private version 1 job registration.',
  'expired-registration': 'The job registration has expired.',
  'unsafe-path': 'Use an absolute, canonical path with safe directory ancestry.',
  'wrong-session': 'Registration belongs to another conversation.',
  'conflicting-registration': 'This conversation is bound to a different registration.',
  'unsupported-session': 'Use an established persistent Pi TUI conversation.',
  'invalid-attempt': 'Expected a registered role and attempt with matching identity.',
  'invalid-event': 'Published event or its bound records do not match.',
  'receipt-mismatch': 'Reviewer receipt does not match the registered candidate and verdict.',
  'invalid-inbox': 'Cannot scan the private inbox within its limits.',
} as const;
type Code = keyof typeof DETAIL;
class Refusal extends Error {
  constructor(readonly code: Code) { super(`${code}: ${DETAIL[code]}`); }
}
const usage = 'Use /dcc-handoff enable <absolute-registration>, status, or disable.';
const outcomes = { writer: ['reported', 'blocked'], reviewer: ['approved', 'changes_requested', 'blocked'] };
type Stage = keyof typeof outcomes;
const slotPattern = /^(writer|reviewer)\.([a-z0-9][a-z0-9_-]{0,31})(?![\s\S])/;
const identity = (v: unknown): v is string => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}(?![\s\S])/.test(v);
const digest = (v: unknown): v is string => typeof v === 'string' && v.length === 64 && /^[0-9a-f]{64}$/.test(v);
const sha = (data: Buffer) => createHash('sha256').update(data).digest('hex');
const missing = (error: unknown) => (error as NodeJS.ErrnoException)?.code === 'ENOENT';
const recordLimit = 4096;
const payloadLimit = 128 * 1024;
const scanLimit = 256;

type Row = Record<string, unknown>;
type Job = { version: 1; job: string; session: string; session_file: string; expires_ms: number; manifest_digest: string };
type Binding = { version: 1; job: string; session: string; manifest_digest: string;
  stage: Stage; attempt: string; candidate_digest: string | null };
type State = { session: string; file: string; registration: string; hash: string; enabled: boolean };
const jobKeys = ['version', 'job', 'session', 'session_file', 'expires_ms', 'manifest_digest'];
const bindingKeys = ['version', 'job', 'session', 'manifest_digest', 'stage', 'attempt', 'candidate_digest'] as const;
const eventKeys = [...bindingKeys, 'outcome', 'report_sha256', 'evidence_sha256'];
const keys = (row: Row, fields: readonly string[]) =>
  Object.keys(row).length === fields.length && fields.every(key => Object.hasOwn(row, key));
const same = (a: Row, b: Binding) => bindingKeys.every(key => a[key] === b[key]);

function safePath(value: unknown): value is string {
  return typeof value === 'string' && value !== '/' && !value.endsWith('/') &&
    Buffer.byteLength(value) <= 2048 && !/[\x00-\x1f\x7f]/.test(value) && isAbsolute(value) && normalize(value) === value;
}
function dir(path: string, privateLeaf = false) {
  const parents: string[] = [];
  for (let current = path; current !== '/'; current = dirname(current)) parents.push(current);
  for (const parent of ['/', ...parents.reverse()]) {
    const info = lstatSync(parent);
    // In a root-mapped Linux user namespace the host's system directories
    // appear as the overflow UID. Do not extend this exception to other paths.
    const mappedSystemDir = process.platform === 'linux' && process.getuid?.() === 0 &&
      info.uid === 65534 && (parent === '/' || parent === '/tmp');
    const systemOwner = info.uid === 0 || mappedSystemDir;
    const stickySystemDir = systemOwner && (info.mode & 0o1000) !== 0;
    if (!info.isDirectory() || (!systemOwner && info.uid !== process.getuid?.()) ||
        ((info.mode & 0o022) !== 0 && !stickySystemDir) ||
        (parent === path && privateLeaf && (info.uid !== process.getuid?.() || (info.mode & 0o077) !== 0))) {
      throw new Refusal('unsafe-path');
    }
  }
}
function bytes(path: string, max: number): Buffer {
  const before = lstatSync(path);
  if (!before.isFile()) throw new Error('not a regular file');
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.uid !== process.getuid?.() || (info.mode & 0o7777) !== 0o400 ||
        info.dev !== before.dev || info.ino !== before.ino || info.size <= 0 || info.size > max) {
      throw new Error('not a bounded private record');
    }
    const data = Buffer.alloc(info.size + 1);
    let size = 0;
    while (size < data.length) {
      const count = readSync(fd, data, size, data.length - size, size);
      if (!count) break;
      size += count;
    }
    if (size !== info.size) throw new Error('incomplete record');
    return data.subarray(0, size);
  } finally {
    closeSync(fd);
  }
}
function json(data: Buffer, canonical = false): Row {
  const row = JSON.parse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(data));
  if (row === null || Array.isArray(row) || typeof row !== 'object') throw new Error('not a record');
  if (canonical && !data.equals(Buffer.from(JSON.stringify(row, Object.keys(row).sort()) + '\n'))) {
    throw new Error('non-canonical record');
  }
  return row;
}
function established(ctx: ExtensionContext): string {
  const file = ctx.sessionManager.getSessionFile();
  if (ctx.mode === 'tui' && safePath(file)) {
    try {
      const info = lstatSync(file);
      if (info.isFile() && info.uid === process.getuid?.() && (info.mode & 0o077) === 0) return file;
    } catch { /* a new/ephemeral conversation may not have a transcript */ }
  }
  throw new Refusal('unsupported-session');
}
function readRegistration(path: string, ctx: ExtensionContext) {
  if (!safePath(path)) throw new Refusal('unsafe-path');
  if (basename(path) !== 'registration.json') throw new Refusal('invalid-registration');
  let row: Row;
  let hash: string;
  try {
    dir(dirname(path), true);
    const data = bytes(path, recordLimit);
    hash = sha(data);
    row = json(data, true);
    if (!keys(row, jobKeys) || row.version !== 1 || !identity(row.job) || !identity(row.session) ||
        !safePath(row.session_file) || !Number.isSafeInteger(row.expires_ms) || (row.expires_ms as number) <= 0 ||
        !digest(row.manifest_digest)) throw new Error('bad schema');
  } catch (error) {
    if (error instanceof Refusal) throw error;
    throw new Refusal(missing(error) ? 'missing-registration' : 'invalid-registration');
  }
  const job = row as Job;
  if (job.session !== ctx.sessionManager.getSessionId() || job.session_file !== established(ctx)) throw new Refusal('wrong-session');
  if (job.expires_ms <= Date.now()) throw new Refusal('expired-registration');
  return { job, hash };
}
function slots(root: string) {
  const handle = opendirSync(root);
  const found: string[] = [];
  try {
    for (let count = 0; ; count++) {
      const entry = handle.readSync();
      if (!entry) break;
      if (count >= scanLimit) throw new Refusal('invalid-inbox');
      if (slotPattern.test(entry.name)) found.push(entry.name);
    }
  } finally {
    handle.closeSync();
  }
  return found.sort();
}
function validatedEvent(root: string, slot: string, job: Job) {
  const [, stageRaw, attempt] = slotPattern.exec(slot)!;
  const stage = stageRaw as Stage;
  const parent = join(root, slot);
  const terminal = join(parent, 'event.json');
  try {
    dir(parent, true);
    lstatSync(terminal);
  } catch (error) {
    if (missing(error)) return;
    throw new Refusal('invalid-event');
  }
  let binding: Binding;
  try {
    const row = json(bytes(join(parent, 'attempt.json'), recordLimit), true);
    const candidate = row.candidate_digest;
    if (stage === 'reviewer' ? !digest(candidate) : candidate !== null) throw new Error('bad candidate');
    binding = { version: 1, job: job.job, session: job.session, manifest_digest: job.manifest_digest,
      stage, attempt, candidate_digest: candidate as string | null };
    if (!keys(row, bindingKeys) || !same(row, binding)) throw new Error('bad binding');
  } catch {
    throw new Refusal('invalid-attempt');
  }
  let outcome: string;
  let evidenceHash: string;
  let report: Buffer;
  try {
    const row = json(bytes(terminal, recordLimit), true);
    if (!keys(row, eventKeys) || !same(row, binding) || typeof row.outcome !== 'string' ||
        !outcomes[stage].includes(row.outcome) || !digest(row.report_sha256) || !digest(row.evidence_sha256)) {
      throw new Error('bad terminal event');
    }
    const records = join(parent, 'records');
    dir(records, true);
    report = bytes(join(records, 'report'), payloadLimit);
    evidenceHash = sha(bytes(join(records, 'evidence'), payloadLimit));
    if (row.report_sha256 !== sha(report) || row.evidence_sha256 !== evidenceHash) throw new Error('digest mismatch');
    outcome = row.outcome;
  } catch {
    throw new Refusal('invalid-event');
  }
  if (stage === 'reviewer') {
    let receipt: Row;
    try { receipt = json(report); } catch { throw new Refusal('receipt-mismatch'); }
    if (receipt.version !== 1 || receipt.manifest_digest !== binding.manifest_digest ||
        receipt.candidate_digest !== binding.candidate_digest || receipt.verdict !== outcome) throw new Refusal('receipt-mismatch');
  }
  return { ...binding, outcome, evidence_sha256: evidenceHash };
}

export default function (pi: ExtensionAPI) {
  let state: State | undefined;
  let stop: (() => void) | undefined;
  let schedule: (() => void) | undefined;
  let problem: Refusal | undefined;
  const ui = (ctx: ExtensionContext, detail: string, kind: 'info' | 'warning' | 'error' = 'info') =>
    ctx.ui.notify(`DCC handoff: ${detail}`, kind);
  const status = (ctx: ExtensionContext) => {
    if (problem) ui(ctx, problem.message, 'error');
    else ui(ctx, `${stop ? 'enabled' : state?.enabled === false ? 'disabled' : 'inactive'} (notification-only).`);
  };
  function persist(next: State) {
    pi.appendEntry(STATE, next);
    state = next;
  }
  function arm(ctx: ExtensionContext, active: State) {
    stop?.();
    const root = dirname(active.registration);
    const seen = new Set<string>();
    for (const entry of ctx.sessionManager.getBranch()) {
      if (entry.type === 'custom_message' && entry.customType === NOTICE &&
          entry.details?.registration === active.hash && typeof entry.details?.event === 'string') seen.add(entry.details.event);
    }
    let closed = false;
    let tick: ReturnType<typeof setImmediate> | undefined;
    const logged = new Map<string, string>();
    function audit(slot: string, detail: string) {
      if (logged.get(slot) === detail) return;
      if (logged.size >= scanLimit && !logged.has(slot)) logged.clear();
      logged.set(slot, detail);
      ui(ctx, detail);
    }
    function scan() {
      let job: Job;
      let available: string[];
      try {
        const loaded = readRegistration(active.registration, ctx);
        if (loaded.hash !== active.hash) throw new Refusal('conflicting-registration');
        job = loaded.job;
        try { available = slots(root); } catch { throw new Refusal('invalid-inbox'); }
      } catch (error) {
        problem = error instanceof Refusal ? error : new Refusal('invalid-inbox');
        stop?.();
        status(ctx);
        return;
      }
      for (const slot of available) {
        let event: ReturnType<typeof validatedEvent>;
        try { event = validatedEvent(root, slot, job); }
        catch (error) {
          audit(slot, (error instanceof Refusal ? error : new Refusal('invalid-event')).message);
          continue;
        }
        if (!event) continue;
        if (seen.has(slot)) { audit(slot, 'duplicate.'); continue; }
        if (!ctx.isIdle()) { audit(slot, 'deferred-busy.'); return; }
        if (job.expires_ms <= Date.now()) { schedule?.(); return; }
        const content = event.stage === 'writer'
          ? `DCC factory handoff (notification-only): writer reported ${event.outcome === 'reported' ? 'a candidate' : 'a blocker'}. This is not independent acceptance or launch or integration approval.`
          : `DCC factory handoff (notification-only): reviewer reported ${event.outcome}. This is not launch, repair or integration approval.`;
        seen.add(slot);
        logged.set(slot, 'duplicate.'); // Report retained/replayed inputs on a fresh runtime, not on every scan.
        pi.sendMessage({ customType: NOTICE, content, display: true,
          details: { ...event, event: slot, registration: active.hash, action: 'notification-only' } }, { triggerTurn: true });
        return;
      }
    }
    schedule = () => {
      if (closed || tick) return;
      tick = setImmediate(() => { tick = undefined; if (!closed) scan(); });
    };
    const timer = setInterval(schedule, 500);
    timer.unref();
    stop = () => {
      closed = true;
      if (tick) clearImmediate(tick);
      clearInterval(timer);
      stop = schedule = undefined;
    };
    schedule();
  }
  pi.on('session_start', (_event, ctx) => {
    stop?.();
    state = problem = undefined;
    if (ctx.mode !== 'tui') return;
    const entry = ctx.sessionManager.getBranch().findLast(row => row.type === 'custom' && row.customType === STATE);
    if (entry?.type !== 'custom') return;
    const saved = entry.data as Partial<State> | undefined;
    if (!saved || typeof saved.enabled !== 'boolean' || !safePath(saved.registration) || !digest(saved.hash) ||
        saved.session !== ctx.sessionManager.getSessionId() || saved.file !== ctx.sessionManager.getSessionFile()) return;
    state = saved as State;
    if (state.enabled) arm(ctx, state);
  });
  pi.on('agent_settled', () => schedule?.());
  pi.on('session_shutdown', () => stop?.());
  pi.on('session_tree', () => { stop?.(); }); // Branch traversal does not rearm a watcher.
  pi.registerCommand('dcc-handoff', {
    description: 'Enable, inspect or disable notification-only factory handoff',
    handler: async (args, ctx) => {
      const input = args.trim();
      if (input !== 'status' && input !== 'disable' && !input.startsWith('enable ')) {
        ui(ctx, usage, 'warning');
        return;
      }
      try {
        const file = established(ctx);
        if (input === 'status') { status(ctx); return; }
        if (input === 'disable') {
          stop?.();
          if (state?.enabled) persist({ ...state, enabled: false });
          problem = undefined;
          status(ctx);
          return;
        }
        const path = input.slice('enable '.length).trim();
        if (state && state.registration !== path) throw new Refusal('conflicting-registration');
        const loaded = readRegistration(path, ctx);
        if (state && state.hash !== loaded.hash) throw new Refusal('conflicting-registration');
        try { slots(dirname(path)); } catch { throw new Refusal('invalid-inbox'); }
        if (!state?.enabled) persist({ session: loaded.job.session, file, registration: path, hash: loaded.hash, enabled: true });
        problem = undefined;
        if (!stop && state?.enabled) arm(ctx, state);
        status(ctx);
      } catch (error) {
        ui(ctx, (error instanceof Refusal ? error : new Refusal('unsupported-session')).message, 'error');
      }
    },
  });
}