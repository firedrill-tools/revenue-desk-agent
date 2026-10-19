import { fileURLToPath } from 'node:url';
import { resolve, join } from 'node:path';
import { ApplicationError, commandMain, invokeCLI, privateDirectory } from './adapter-runtime.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const cases = new Set(['starter', 'approved-credit', 'unapproved-credit', 'prior-complete']);
const id = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,80}$/.test(value);

export async function runApplication(input, parameters, signal) {
  if (Object.keys(input).some(key => !['caseId', 'requestId', 'invoiceId', 'request', 'approvedCreditCents'].includes(key)) ||
      !cases.has(input.caseId) || !id(input.requestId) || !id(input.invoiceId) ||
      typeof input.request !== 'string' || input.request.length < 5 || input.request.length > 4000 || !input.request.trim() || input.request.includes('\0') ||
      !Number.isSafeInteger(input.approvedCreditCents) || input.approvedCreditCents < 0) {
    throw new Error('Supply a reviewed case, exact request/invoice IDs, bounded request and independent integer credit approval.');
  }
  const directory = await privateDirectory(root);
  const state = join(directory, 'workspace.json');
  const cli = ['uv', 'run', '--locked', '--no-sync', 'revenue-desk'];
  const env = { ...process.env, ...(parameters.model ? { OPENAI_MODEL: parameters.model } : {}) };
  try {
    await invokeCLI([...cli, '--init-case', input.caseId, '--workspace', state], { cwd: root, signal });
    const output = await invokeCLI([...cli, '--workspace', state, '--approved-credit-cents', String(input.approvedCreditCents),
      input.requestId, input.invoiceId, input.request], { cwd: root, signal, env, timeoutMs: 270000 });
    return { application: output, localState: { directory, workspaceFile: state } };
  } catch (error) {
    if (error instanceof ApplicationError) error.evidence.runDirectory = directory;
    throw error;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await commandMain(runApplication);
}
