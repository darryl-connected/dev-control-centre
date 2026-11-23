// Synthetic role provider for disposable factory-loop tests only. No service calls.
import { createAssistantMessageEventStream } from '@earendil-works/pi-ai/compat';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { appendFileSync } from 'node:fs';
import { join } from 'node:path';

export default function (pi: ExtensionAPI) {
  const root = process.env.DCC_RUN_FIXTURE;
  if (!root || process.env.PI_OFFLINE !== '1') throw new Error('offline run fixture only');
  function trace(event: string, fields: Record<string, unknown> = {}) {
    appendFileSync(join(root!, 'provider.jsonl'), JSON.stringify({ event, at_ms: Date.now(), pid: process.pid, ...fields }) + '\n',
      { mode: 0o600 });
  }
  function role(text: string) {
    if (text.includes('implementation writer repair')) return 'writer';
    if (text.includes('implementation writer')) return 'writer';
    if (text.includes('independent acceptance reviewer')) return 'reviewer';
    return 'unknown';
  }
  pi.on('session_start', (_e, ctx) => trace('session-start', {
    session: ctx.sessionManager.getSessionId(), cwd: ctx.cwd, mode: ctx.mode }));
  pi.on('before_agent_start', e => trace('requested', { type: e.messageType,
    ...(e.messageType === 'custom' ? { text: e.message.content } : {}) }));
  pi.on('tool_execution_start', () => trace('unexpected-tool'));
  const synthetic = {
    baseUrl: 'http://127.0.0.1:1', apiKey: 'fixture-not-a-credential', api: 'dcc-run-synthetic-api',
    streamSimple(model: { id: string; api: string; provider: string }, context: { messages: unknown[] }) {
      const last = context.messages.at(-1);
      const text = JSON.stringify(last);
      const which = role(text);
      const stream = createAssistantMessageEventStream();
      void (async () => {
        trace('provider-start', { model: model.id, provider: model.provider, role: which, agent_dir: process.env.PI_CODING_AGENT_DIR ?? null });
        const reply = `OFFLINE_${which.toUpperCase()}_REPLY`;
        const message = {
          role: 'assistant' as const, content: [{ type: 'text' as const, text: reply }], api: model.api,
          provider: model.provider, model: model.id, stopReason: 'stop' as const, timestamp: Date.now(),
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
        };
        trace('provider-reply', { role: which, text: reply });
        stream.push({ type: 'done', reason: 'stop', message });
        stream.end();
      })();
      return stream;
    },
  };
  pi.registerProvider('deepseek', {
    ...synthetic,
    models: [{ id: 'deepseek-flash', name: 'DCC synthetic DeepSeek Flash', reasoning: false,
      input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 128000, maxTokens: 2048 }],
  });
  pi.registerProvider('openai', {
    ...synthetic,
    models: [
      { id: 'gpt-6.1-sol', name: 'DCC synthetic Sol', reasoning: true, input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 2048 },
      { id: 'gpt-6.2-sol', name: 'DCC synthetic Sol alternate', reasoning: true, input: ['text'],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 2048 },
    ],
  });
}
