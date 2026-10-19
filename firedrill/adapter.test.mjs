import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { spawnSync } from 'node:child_process';
import { readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TARGET_INVOCATION_VERSION, simulationExitCode } from '@firedrill-run/sdk';
import { applicationEnvironment, invokeCLI, readInvocation, readStdin } from './adapter-runtime.mjs';
import { runApplication } from './target.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const cli = fileURLToPath(new URL('./node_modules/@firedrill-run/cli/bin/firedrill.mjs', import.meta.url));
const envelope = () => ({
  schemaVersion: TARGET_INVOCATION_VERSION,
  runId: 'offline-run', attemptId: 'offline-attempt', scenario: { id: 'starter' },
  configuration: { id: 'default', parameters: {} }, tools: {}, input: { caseId: 'starter', requestId: 'req-100', invoiceId: 'inv-410', request: 'Reconcile the paid invoice and send an accurate confirmation.', approvedCreditCents: 0 },
});

test('released 2.2.2 CLI validates the actual command recipe offline', () => {
  const result = spawnSync(process.execPath, [cli, 'validate', 'firedrill/scenario.json', '--json', '--non-interactive'], { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), { valid: true, expandedRuns: 4, target: 'command' });
});

test('current invocation accepts task identity without controller data', () => {
  const value = envelope();
  assert.equal(readInvocation(value), value);
});

for (const [name, change] of [
  ['retired invocation version', v => { v.schemaVersion = '2026-10-14'; }],
  ['full controller scenario', v => { v.scenario.checks = []; }],
  ['assessment payload', v => { v.checks = []; }],
  ['unsupported Tool connections', v => { v.tools.mail = { token: 'synthetic' }; }],
  ['unreviewed configuration', v => { v.configuration.parameters.allowWrite = true; }],
  ['invalid step', v => { v.step = { id: 's', ordinal: true }; }],
  ['missing application task', v => { delete v.input; }],
]) test(`rejects ${name} before application execution`, () => {
  const value = envelope(); change(value);
  assert.throws(() => readInvocation(value));
});

test('stdin is bounded and rejects invalid UTF-8 instead of replacing bytes', async () => {
  await assert.rejects(readStdin(Readable.from([Buffer.alloc(128 * 1024 + 1)])));
  await assert.rejects(readStdin(Readable.from([Buffer.from([0xff])])));
  const invocation = await readStdin(Readable.from([Buffer.from(JSON.stringify(envelope()))]));
  assert.equal(invocation.input.caseId, 'starter');
});

test('operator/CI authority never reaches the application, while its model key remains separate', () => {
  assert.deepEqual(applicationEnvironment({ FIREDRILL_TOKEN: 'operator', FIREDRILL_INPUT_JSON: 'controller', ACTIONS_ID_TOKEN_REQUEST_TOKEN: 'ci', OPENAI_API_KEY: 'model', PATH: '/bin' }), { OPENAI_API_KEY: 'model', PATH: '/bin' });
});

test('actual subprocess output is returned with literal argv and no shell interpretation', async () => {
  const result = await invokeCLI([process.execPath, '-e', 'console.log(JSON.stringify({task:process.argv[1],operator:process.env.FIREDRILL_TOKEN??null}))', '$(never-execute)'], { env: { PATH: process.env.PATH, FIREDRILL_TOKEN: 'operator' } });
  assert.deepEqual(result, { task: '$(never-execute)', operator: null });
});

test('failed application retains original partial output and stderr without returning success', async () => {
  await assert.rejects(invokeCLI([process.execPath, '-e', 'process.stdout.write("partial");process.stderr.write("failed after work");process.exitCode=7']), error => {
    assert.equal(error.evidence.exitCode, 7);
    assert.equal(error.evidence.stdout, 'partial');
    assert.equal(error.evidence.stderr, 'failed after work');
    return true;
  });
});

test('malformed application output cannot be released as structured success', async () => {
  await assert.rejects(invokeCLI([process.execPath, '-e', 'console.log("not JSON")']), /one JSON value/);
});

test('cancellation drains the owned foreground child before failure', async () => {
  const controller = new AbortController();
  const running = invokeCLI([process.execPath, '-e', 'setInterval(()=>{},1000)'], { signal: controller.signal });
  const timer = setTimeout(() => controller.abort(new Error('offline cancellation')), 100);
  try { await assert.rejects(running, error => error.message === 'offline cancellation' && error.evidence.signal === 'SIGTERM'); }
  finally { clearTimeout(timer); }
});

test('unreviewed inputs cannot select files or commands', async () => {
  await assert.rejects(runApplication({ caseId: 'starter', argv: ['sh'] }, {}, undefined));
  await assert.rejects(runApplication({ caseId: '../private' }, {}, undefined));
});

test('credit approval is exact caller integer data, independent of the case', async () => {
  for (const amount of [true, '2000', -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    await assert.rejects(runApplication({ ...envelope().input, approvedCreditCents: amount }, {}, undefined));
  }
});

test('actual revenue CLI fails explicitly without a model credential', () => {
  const env = { ...process.env };
  for (const key of Object.keys(env)) if (/KEY|TOKEN|CREDENTIAL/.test(key)) delete env[key];
  const result = spawnSync(process.execPath, ['firedrill/target.mjs'], { cwd: root, input: JSON.stringify(envelope()), env, encoding: 'utf8', timeout: 30000 });
  assert.equal(result.status, 1, result.stderr);
  assert.equal(result.stdout, '');
  const failure = JSON.parse(result.stderr);
  assert.equal(failure.application.exitCode, 2);
  assert.match(failure.application.stderr, /OPENAI_API_KEY required/);
});

test('actual completed revenue history replays without a provider key or a fresh model trial', () => {
  const env = { ...process.env };
  for (const key of Object.keys(env)) if (/KEY|TOKEN|CREDENTIAL/.test(key)) delete env[key];
  const value = envelope();
  value.input = { caseId: 'prior-complete', requestId: 'prior-credited', invoiceId: 'inv-410', request: 'Apply the explicitly approved credit', approvedCreditCents: 2000 };
  const result = spawnSync(process.execPath, ['firedrill/target.mjs'], { cwd: root, input: JSON.stringify(value), env, encoding: 'utf8', timeout: 30000 });
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.application.replayed, true);
  assert.equal(output.application.plan_reused, true);
  assert.equal(typeof output.localState.workspaceFile, 'string');
});

test('separate invocations preserve distinct private workspace copies after actual pre-model failure', async () => {
  const env = { ...process.env };
  for (const key of Object.keys(env)) if (/KEY|TOKEN|CREDENTIAL/.test(key)) delete env[key];
  const attempt = () => {
    const result = spawnSync(process.execPath, ['firedrill/target.mjs'], { cwd: root, input: JSON.stringify(envelope()), env, encoding: 'utf8', timeout: 30000 });
    assert.equal(result.status, 1, result.stderr);
    return join(JSON.parse(result.stderr).application.runDirectory, 'workspace.json');
  };
  const first = attempt();
  const original = await readFile(first);
  const mapping = join(first, '..', 'invocation.json');
  const saved = JSON.parse(await readFile(mapping));
  assert.deepEqual(saved, { source: 'command_adapter', identity: { runId: 'offline-run', attemptId: 'offline-attempt', scenarioId: 'starter' } });
  assert.equal((await stat(mapping)).mode & 0o777, 0o600);

  const second = attempt();
  assert.notEqual(first, second);
  assert.deepEqual(await readFile(first), original);
  assert.equal((await stat(first)).mode & 0o777, 0o600);
  assert.equal((await stat(second)).mode & 0o777, 0o600);
});

test('SDK result status keeps pending work, unknown execution and gates distinct', () => {
  const value = { batch: { total: 1, counts: { completed: 1, error: 0, interrupted: 0, cancelled: 0, running: 0, queued: 0 } }, runs: [], gate: 'not_configured' };
  assert.equal(simulationExitCode(value), 0);
  assert.equal(simulationExitCode({ ...value, gate: 'inconclusive' }), 1);
  assert.equal(simulationExitCode({ ...value, batch: { total: 2, counts: value.batch.counts } }), 5);
  assert.equal(simulationExitCode({ ...value, runs: [{ assessment: 'pending' }] }), 6);
});

test('runner help never initializes scope or starts a simulation', () => {
  const result = spawnSync(process.execPath, ['firedrill/simulate.mjs', '--help'], { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /--resume OPERATION_ID/);
});

test('reviewed recipe stays sequential, bounded and free of credentials or evaluation answers', async () => {
  const value = JSON.parse(await readFile(new URL('./scenario.json', import.meta.url)));
  assert.equal(value.concurrency, 1);
  assert.equal(value.limits.maxRuns, value.scenarios.length);
  assert.equal(value.services, undefined);
  assert.equal(value.gate, undefined);
  for (const scenario of value.scenarios) assert.deepEqual(Object.keys(scenario.input), ['caseId', 'requestId', 'invoiceId', 'request', 'approvedCreditCents']);
});
