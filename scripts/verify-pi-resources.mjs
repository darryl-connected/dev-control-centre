// Offline evidence probe. Use only a disposable fixture, never a real Pi HOME.
import { createHash } from "node:crypto";
import { lstatSync, readFileSync, readdirSync, realpathSync } from "node:fs";
import { findPackageJSON } from "node:module";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const kit = realpathSync(fileURLToPath(new URL("..", import.meta.url)));
const names = ["setup", "factory", "grilling"];
const sha = (data) => createHash("sha256").update(data).digest("hex");
const xml = (text) => text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[c]);
const local = (parent, child) => {
  const suffix = relative(parent, child);
  return suffix !== ".." && !suffix.startsWith(`..${sep}`) && !isAbsolute(suffix);
};
const insist = (condition, label) => { if (!condition) throw new Error(label); };
const text = (message) => typeof message?.content === "string" ? message.content :
  message?.content.filter((part) => part.type === "text").map((part) => part.text).join("") ?? "";

function fileStat(path) {
  try { return lstatSync(path); }
  catch (error) { if (error.code === "ENOENT") return undefined; throw error; }
}

function settings(path, allowed) {
  const stat = fileStat(path);
  if (!stat) return {};
  insist(stat.isFile(), `expected fixture settings file: ${path}`);
  const value = JSON.parse(readFileSync(path, "utf8"));
  insist(value && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).every((key) => allowed.includes(key)), `unexpected fixture settings: ${path}`);
  return value;
}

function validateFixture(root, cwd, home, agentDir) {
  for (const path of [root, cwd, home, dirname(agentDir), agentDir, join(cwd, ".pi")]) {
    const entry = fileStat(path);
    if (path === dirname(agentDir) || path === agentDir) {
      if (!entry) continue;
    }
    insist(entry?.isDirectory() && realpathSync(path) === path, `expected physical fixture directory: ${path}`);
  }
  insist(process.env.HOME === home && !process.env.PI_CODING_AGENT_DIR,
    "set HOME to FIXTURE_ROOT/home and unset PI_CODING_AGENT_DIR; do not probe a real user profile");
  insist([cwd, home].every((directory) => !local(directory, kit) && !local(kit, directory)),
    "fixture workspace, HOME and kit must be separate");
  for (const [directory, allowed] of [
    [home, [".pi"]], [dirname(agentDir), ["agent"]],
    [agentDir, ["settings.json", "APPEND_SYSTEM.md", "auth.json", "trust.json", "skills"]],
    [join(cwd, ".pi"), ["settings.json", "APPEND_SYSTEM.md", "skills"]],
  ]) {
    if (!fileStat(directory)) continue;
    for (const item of readdirSync(directory, { withFileTypes: true })) {
      insist(allowed.includes(item.name) && (item.name === "skills" || item.name === ".pi" || item.name === "agent"
        ? item.isDirectory() : item.isFile()), `unexpected fixture resource: ${join(directory, item.name)}`);
    }
    const checkSkills = (path) => {
      if (!fileStat(path)) return;
      for (const item of readdirSync(path, { withFileTypes: true })) {
        const child = join(path, item.name);
        if (item.isDirectory()) checkSkills(child);
        else insist(item.isFile() && item.name.endsWith(".md"), `unexpected skill fixture resource: ${child}`);
      }
    };
    if (allowed.includes("skills")) checkSkills(join(directory, "skills"));
  }
  settings(join(agentDir, "settings.json"), ["quietStartup"]);
  const project = settings(join(cwd, ".pi/settings.json"), ["skills"]);
  if (Object.hasOwn(project, "skills")) {
    insist(Array.isArray(project.skills), "expected a fixture skills array");
    for (const skillPath of project.skills) {
      insist(typeof skillPath === "string" && isAbsolute(skillPath) && resolve(skillPath) === skillPath &&
        local(join(kit, "skills"), skillPath), "configured skill path is not inside the kit skills tree");
      // Permit a missing path so the actual loader can demonstrate the missing-resource failure.
      if (fileStat(skillPath)) insist(realpathSync(skillPath) === skillPath && lstatSync(skillPath).isFile(),
        `configured skill file is not a regular kit file: ${skillPath}`);
    }
  }
}

async function main() {
  insist(process.argv.length === 4 && process.argv[2] === "--fixture-root",
    "usage: node scripts/verify-pi-resources.mjs --fixture-root ABSOLUTE_FIXTURE_ROOT");
  const root = resolve(process.argv[3]);
  const home = join(root, "home");
  const cwd = join(root, "workspace");
  const agentDir = join(home, ".pi/agent");
  const sdkPath = process.env.DCC_PI_SDK_MODULE;
  insist(sdkPath && isAbsolute(sdkPath), "missing absolute DCC_PI_SDK_MODULE for Pi SDK 1.4.0");
  validateFixture(root, cwd, home, agentDir);
  process.env.PI_OFFLINE = "1";
  const sdkUrl = pathToFileURL(sdkPath);
  const { VERSION, DefaultResourceLoader, SettingsManager, SessionManager, ModelRuntime, createAgentSession, getPackageDir } = await import(sdkUrl);
  insist(VERSION === "1.4.0", `expected Pi SDK 1.4.0, observed ${VERSION}`);
  const aiPackage = findPackageJSON("@earendil-works/pi-ai", sdkUrl);
  insist(aiPackage, "could not resolve Pi AI dependency for the local transport");
  const ai = JSON.parse(readFileSync(aiPackage, "utf8"));
  const { fauxProvider, fauxAssistantMessage, InMemoryCredentialStore, getCurrentSystemPrompt } =
    await import(pathToFileURL(join(dirname(aiPackage), ai.main)));
  const appendPath = join(cwd, ".pi/APPEND_SYSTEM.md");
  const globalAppend = join(agentDir, "APPEND_SYSTEM.md");
  const neutral = readFileSync(join(kit, "templates/pi/APPEND_SYSTEM.md"), "utf8");
  const global = fileStat(globalAppend) ? readFileSync(globalAppend, "utf8").trim() : undefined;
  const privateMarker = /\b(?:samson|darryl|godfather|mobster)\b|personal salary|(?:^|[\s"'])(?:\/home\/|\/Users\/|[a-z]:\\Users\\)/im;
  const errors = [];
  const requireEvidence = (condition, label) => { if (!condition) errors.push(label); };
  const normalized = (value) => value.replaceAll(cwd, "<workspace>").replaceAll(kit, "<kit>")
    .replaceAll(home, "<fixture-home>").replaceAll(getPackageDir(), "<pi-sdk>");
  const callerArgs = {
    setup: "dcc-offline-setup inspect only",
    factory: "dcc-offline-factory inspect only",
    grilling: "dcc-offline-grilling inspect fixture decisions.md, example.csv and task.md; do not implement",
  };

  async function observe(trusted) {
    const settingsManager = SettingsManager.create(cwd, agentDir);
    const loader = new DefaultResourceLoader({ cwd, agentDir, settingsManager });
    let decisions = 0;
    await loader.reload({ resolveProjectTrust: async () => { decisions++; return trusted; } });
    const label = trusted ? "trusted" : "denied";
    requireEvidence(decisions === 1 && settingsManager.isProjectTrusted() === trusted, `${label}: actual trust state differs`);
    const settingErrors = settingsManager.drainErrors();
    requireEvidence(!settingErrors.length, `${label}: Pi settings diagnostics`);
    const { skills, diagnostics } = loader.getSkills();
    insist(loader.getAgentsFiles().agentsFiles.length === 0, `${label}: unexpected context files; use a clean disposable fixture`);
    const appendSources = loader.getAppendSystemPromptSources().map(({ path }) => ({ path, sha256: sha(readFileSync(path)) }));
    const expectedAppend = trusted ? appendPath : (global !== undefined ? globalAppend : undefined);
    requireEvidence(appendSources.length === Number(expectedAppend !== undefined) &&
      (!expectedAppend || appendSources[0]?.path === expectedAppend), `${label}: wrong APPEND_SYSTEM source`);
    if (trusted) {
      requireEvidence(appendSources[0]?.sha256 === sha(neutral), "trusted: project append is not byte-identical to neutral template");
      requireEvidence(!diagnostics.length, "trusted: Pi skill diagnostics (including collisions) must be empty");
    }
    const modelRuntime = await ModelRuntime.create({
      credentials: new InMemoryCredentialStore(), modelsPath: null, refreshOnCreate: false, allowModelNetwork: false,
    });
    const recorder = fauxProvider({ provider: "dcc-offline-recorder", models: [{ id: "record-only" }] });
    modelRuntime.registerNativeProvider(recorder.provider);
    // Pi advertises discoverable skills only when it can read their files. The recorder never returns a tool call.
    const { session } = await createAgentSession({ cwd, agentDir, settingsManager, resourceLoader: loader, modelRuntime,
      model: recorder.getModel(), sessionManager: SessionManager.inMemory(cwd), tools: ["read"], thinkingLevel: "off" });
    try {
      const systemPrompt = session.systemPrompt;
      requireEvidence(!privateMarker.test(normalized(systemPrompt)), `${label}: private marker in effective prompt`);
      requireEvidence(systemPrompt.includes(neutral.trim()) === trusted, `${label}: neutral append not in expected effective prompt`);
      if (global) requireEvidence(systemPrompt.includes(global) === !trusted, `${label}: incorrect user append precedence`);
      if (trusted) {
        requireEvidence(skills.length === names.length, "trusted: expected only three kit skills");
      } else {
        requireEvidence(skills.every(({ filePath }) => !local(kit, filePath) && !local(cwd, filePath)) &&
          !systemPrompt.includes(`${kit}${sep}skills${sep}`), "denied: project skills loaded or advertised");
      }
      const observedSkills = skills.map(({ name, description, filePath, baseDir, disableModelInvocation }) => ({
        name, description, filePath, baseDir, disableModelInvocation, sha256: sha(readFileSync(filePath)),
      }));
      const expansions = [];
      if (trusted) {
        for (const name of names) {
          const expectedPath = join(kit, "skills", name, "SKILL.md");
          const skill = observedSkills.find((item) => item.name === name);
          requireEvidence(skill?.filePath === expectedPath && skill.baseDir === dirname(expectedPath) && !skill.disableModelInvocation,
            `trusted: wrong source or not model-discoverable: ${name}`);
          const advertisement = skill && `<name>${name}</name>\n    <description>${xml(skill.description)}</description>\n    <location>${xml(expectedPath)}</location>`;
          requireEvidence(advertisement && systemPrompt.includes(advertisement), `trusted: missing system prompt advertisement: ${name}`);
          const command = `/skill:${name} ${callerArgs[name]}`;
          const calls = [];
          recorder.setResponses([(context) => {
            calls.push({ userText: text(context.messages.findLast(({ role }) => role === "user")),
              systemPrompt: getCurrentSystemPrompt(context.messages) });
            return fauxAssistantMessage("recorded locally");
          }]);
          await session.prompt(command);
          const capture = calls[0];
          requireEvidence(calls.length === 1 && capture?.systemPrompt === systemPrompt, `trusted: incorrect transport capture for ${name}`);
          if (capture) {
            const raw = fileStat(expectedPath)?.isFile() ? readFileSync(expectedPath, "utf8") : "";
            const body = /^---\r?\n[\s\S]*?\r?\n---\r?\n/.test(raw)
              ? raw.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, "").trim().replaceAll("\r\n", "\n") : "";
            const expectedText = `<skill name="${name}" location="${expectedPath}">\nReferences are relative to ${dirname(expectedPath)}.\n\n${body}\n</skill>\n\n${callerArgs[name]}`;
            requireEvidence(body && capture.userText === expectedText, `trusted: incomplete Pi command expansion: ${name}`);
            requireEvidence(!privateMarker.test(normalized(capture.userText)), `trusted: private marker in expansion: ${name}`);
            expansions.push({ name, command, ...capture, bodySha256: sha(body) });
          }
        }
      }
      return { requestedTrust: trusted, projectTrusted: settingsManager.isProjectTrusted(), systemPrompt,
        appendSources, skills: observedSkills, diagnostics, expansions };
    } finally {
      session.dispose();
    }
  }

  const trusted = await observe(true);
  const denied = await observe(false);
  const result = { ok: !errors.length, platform: process.platform, sdkVersion: VERSION,
    resourceLoader: "DefaultResourceLoader", sessionStorage: "in memory", transport: "Pi faux provider with local context recorder; no model API",
    kit, workspace: cwd, trusted, denied, errors,
    workflow: "blocked; resource loading is not overall readiness or launch permission",
    notVerified: ["fresh macOS V9/prepared exercise", "full macOS V10", "Windows follow-up", "authenticated integrations", "live orchestration/fallback", "model obedience"],
  };
  console.log(JSON.stringify(result, null, 2));
  if (errors.length) process.exitCode = 1;
}

try {
  await main();
} catch (error) {
  console.error(`Pi resource evidence unavailable: ${error.message}`);
  process.exitCode = 1;
}
