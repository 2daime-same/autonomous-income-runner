import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { gunzipSync } from 'node:zlib';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const entries = [
  ['styles.css.gz', 'styles.css', 'd1bc6ebb94731a2871c9d5ad9f612ad574d25bb64351d73d6611423a610379af'],
  ['app.mjs.gz', 'app.mjs', 'ac0ae184b9639008a387f547f2e7c99595b045d2ba4a0f6ed92fb8837fb14a3e'],
  ['engine.mjs.gz', 'engine.mjs', '10b85b102fa8fda4c40a73a304899d6c024ad49bcf3c24e67412ca3e9b6bebe4'],
  ['engine.test.mjs.gz', 'tests/engine.test.mjs', 'a64f98201a8e0814a21a72d2e77a15e8e9bd6716bde7198ddc0045be3dafe9fd'],
];

for (const [archiveName, outputName, expectedHash] of entries) {
  const archive = await readFile(join(root, '.seed', archiveName));
  const output = gunzipSync(archive);
  const actualHash = createHash('sha256').update(output).digest('hex');
  if (actualHash !== expectedHash) {
    throw new Error(`Checksum mismatch for ${outputName}: ${actualHash}`);
  }
  const destination = join(root, outputName);
  await mkdir(dirname(destination), { recursive: true });
  await writeFile(destination, output);
  console.log(`materialized ${outputName}`);
}
