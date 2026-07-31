import { rm, readdir } from 'node:fs/promises';

for (const target of ['dist', 'dist-submission', '.test-dist', 'coverage']) {
  await rm(target, { recursive: true, force: true });
}
for (const entry of await readdir('.')) {
  if (entry.startsWith('archimedes-market-mcp-') && entry.endsWith('.tgz')) {
    await rm(entry, { force: true });
  }
}
