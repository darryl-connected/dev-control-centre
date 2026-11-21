// Synthetic provider for disposable TUI tests only. It never calls a service.
import { createAssistantMessageEventStream } from '@earendil-works/pi-ai/compat';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { appendFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

export default function (pi: ExtensionAPI) {
  const root = process.env.DCC_OFFLINE_FIXTURE;
  if (!root || process.env.PI_OFFLINE !== '1') throw new Error('offline test fixture only');
  function trace(event: string, fields: Record<string, unknown> = {}) {
    appendFileSync(join(root!, 'provider.jsonl'), JSON.stringify({ event, pid: process.pid, ...fields }) + '\n', { mode: 0o600 });
  }
  pi.registerCommand('fixture-clear-output', {
    description: 'Replace the terminal toast before a diagnostic probe',
    handler: async (_args, ctx) => ctx.ui.notify('Fixture diagnostic barrier.', 'info'),
  });
  pi.on('session_start', (_e, ctx) => trace('session-start', { session: ctx.sessionManager.getSessionId(), mode: ctx.mode }));
  pi.on('session_shutdown', (_e, ctx) => trace('session-shutdown', { session: ctx.sessionManager.getSessionId() }));
  pi.on('before_agent_start', e => trace('requested', { type: e.messageType,
    ...(e.messageType === 'custom' ? { text: e.message.content } : {}) }));
  pi.on('tool_execution_start', () => trace('unexpected-tool'));
  pi.registerProvider('dcc-offline-fixture', {
    baseUrl: 'http://127.0.0.1:1', apiKey: 'fixture-not-a-credential', api: 'dcc-synthetic-api',
    models: [{ id: 'deterministic', name: 'DCC deterministic fixture', reasoning: false, input: ['text'],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 32000, maxTokens: 1024 }],
    streamSimple(model, context, options) {
      const stream = createAssistantMessageEventStream();
      const last = context.messages.at(-1);
      const serialized = JSON.stringify(last);
      const callback = serialized?.includes('DCC factory handoff (notification-only):') ?? false;
      const hold = serialized?.includes('HOLD_THIS_PLANNING_TURN') ?? false;
      void (async () => {
        trace('provider-start', { callback, hold, model: model.id, provider: model.provider });
        const stop = Date.now() + 20000;
        const released = () => existsSync(join(root, 'release'));
        while (hold && !released() && Date.now() < stop && !options?.signal?.aborted) {
          await new Promise(resolve => setTimeout(resolve, 25));
        }
        const text = callback ? 'OFFLINE_CALLBACK_REPLY'
          : (!hold || released()) ? 'OFFLINE_PLANNING_REPLY' : 'OFFLINE_BARRIER_FAILED';
        const message = {
          role: 'assistant' as const, content: [{ type: 'text' as const, text }], api: model.api,
          provider: model.provider, model: model.id, stopReason: 'stop' as const, timestamp: Date.now(),
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
            cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
        };
        trace('provider-reply', { text });
        stream.push({ type: 'done', reason: 'stop', message });
        stream.end();
      })();
      return stream;
    },
  });
}