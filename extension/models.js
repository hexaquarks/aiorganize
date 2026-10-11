function isTextModel(id) {
  const base = id.startsWith("ft:") ? id.split(":")[1] : id;
  // The models endpoint has no capability metadata. Exclude known incompatible families;
  // the synthetic connection test determines whether a candidate supports our schema.
  const incompatible = /audio|realtime|transcrib|tts|image|search|instruct|embedding|moderation|computer-use|oss/i;
  if (incompatible.test(base)) {
    return false;
  }
  if (/^o\d+(?:-|$)/.test(base)) return !/^o1-(mini|preview)/.test(base);
  if (/^gpt-4o(?:-|$)/.test(base)) return !base.startsWith("gpt-4o-2024-05");
  const version = /^gpt-(\d+)(?:\.(\d+))?(?:-|$)/.exec(base);
  return Boolean(version && (Number(version[1]) >= 5 ||
    (Number(version[1]) === 4 && Number(version[2]) >= 1)));
}

export async function fetchModels(apiKey, signal) {
  const response = await fetch("https://api.openai.com/v1/models", {
    headers: {Authorization: `Bearer ${apiKey}`},
    signal: AbortSignal.any([signal, AbortSignal.timeout(20000)].filter(Boolean)),
    redirect: "error",
    credentials: "omit",
  });
  // Never expose provider error bodies, which can contain sensitive data.
  if (!response.ok) throw new Error("Could not load available models.");
  const result = await response.json();
  if (!Array.isArray(result?.data)) throw new Error("Invalid model list.");
  const unique = new Map();
  for (const item of result.data) {
    if (typeof item?.id !== "string" || !/^[a-zA-Z0-9._:-]{1,100}$/.test(item.id) || !isTextModel(item.id)) continue;
    if (item.shutdown_date && Date.parse(item.shutdown_date) <= Date.now()) continue;
    unique.set(item.id, {
      id: item.id,
      name: item.id,
      created: Number.isFinite(item.created) ? item.created : 0,
      note: "Available to this key. Test the connection to verify compatibility.",
    });
  }
  return [...unique.values()].sort((a, b) => b.created - a.created || a.id.localeCompare(b.id));
}
