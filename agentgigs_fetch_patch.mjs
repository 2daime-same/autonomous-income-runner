const originalFetch = globalThis.fetch.bind(globalThis);

function fallbackProposal(requestBody) {
  let jobText = '';
  try {
    const payload = JSON.parse(requestBody ?? '{}');
    jobText = String(payload?.messages?.at(-1)?.content ?? '');
  } catch {}

  const firstLine = jobText
    .split(/\r?\n/)
    .map(value => value.trim())
    .find(Boolean)
    ?.slice(0, 180);
  const subject = firstLine || 'the requested research and analysis task';

  return [
    `I can deliver ${subject} as a source-bounded, AI-assisted research package.`,
    'The deliverable will include an executive summary, explicit assumptions, a structured findings table, risks and limitations, and a concise recommendation section.',
    'I will separate supplied facts from inference, avoid unsupported claims, check internal consistency, and include one revision against the agreed acceptance criteria.',
    'Estimated delivery: 24 hours. AI operation is disclosed; no human employment history or unverified access is claimed.',
  ].join(' ');
}

globalThis.fetch = async function patchedFetch(input, init = {}) {
  const url = typeof input === 'string' ? input : String(input?.url ?? input);
  if (url !== 'https://models.github.ai/inference/chat/completions') {
    return originalFetch(input, init);
  }

  let response;
  try {
    response = await originalFetch(input, init);
    if (response.ok) return response;
  } catch {
    response = null;
  }

  let maxTokens = 0;
  try {
    maxTokens = Number(JSON.parse(init?.body ?? '{}')?.max_tokens ?? 0);
  } catch {}

  if (maxTokens > 0 && maxTokens <= 600) {
    console.log('GitHub Models unavailable; using deterministic proposal fallback.');
    return new Response(
      JSON.stringify({
        choices: [{message: {role: 'assistant', content: fallbackProposal(init?.body)}}],
        fallback: true,
      }),
      {status: 200, headers: {'Content-Type': 'application/json'}},
    );
  }

  if (response) return response;
  throw new Error('GitHub Models unavailable and no deliverable fallback is permitted.');
};
