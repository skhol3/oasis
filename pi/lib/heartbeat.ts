// Progress for work that is silent until it ends. No Pi imports.

/**
 * Run `work`, calling `beat` with the elapsed whole seconds every `intervalMs` until it settles.
 * The result or the error of `work` passes through unchanged, and no beat follows it.
 */
export async function withHeartbeat<T>(
  work: () => Promise<T>,
  beat: (seconds: number) => void,
  intervalMs: number,
): Promise<T> {
  const started = Date.now();
  const timer = setInterval(() => beat(Math.round((Date.now() - started) / 1000)), intervalMs);
  try {
    return await work();
  } finally {
    clearInterval(timer);
  }
}
