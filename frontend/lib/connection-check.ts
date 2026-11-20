type Result = { ok: boolean; message: string };
type Checked = { result: Result; reused: boolean };
type Flight = { fresh: boolean; promise: Promise<Checked | null> };
type Scope = { key: string; success?: { result: Result; expires: number }; flight?: Flight };

// One tab, one exact user/session/destination. Only entry/focus may reuse a success
// for 15 seconds; explicit review/submit checks always bypass it. Nothing is persisted.
const ENTRY_REUSE_MS = 15_000;
let scope: Scope | null = null;

export function invalidateConnectionChecks(): void {
  scope = null;
}

export function verifyScopedConnection(key: string, check: () => Promise<Result>, fresh: boolean): Promise<Checked | null> {
  if (!scope || scope.key !== key) scope = { key };
  const current = scope;
  if (current.flight && (!fresh || current.flight.fresh)) return current.flight.promise;
  const success = current.success;
  if (!fresh && success && performance.now() < success.expires) {
    return Promise.resolve().then(() => scope === current && current.success === success
      ? { result: success.result, reused: true } : null);
  }
  current.success = undefined;
  const flight: Flight = {
    fresh,
    promise: Promise.resolve().then(check).then((result) => {
      if (scope !== current || current.flight !== flight) return null;
      if (typeof result?.ok !== 'boolean' || typeof result?.message !== 'string') {
        throw new Error('The connection check returned an unexpected response. Retry the check.');
      }
      if (result.ok) current.success = { result, expires: performance.now() + ENTRY_REUSE_MS };
      return { result, reused: false };
    }).catch((error) => {
      if (scope !== current || current.flight !== flight) return null;
      throw error;
    }).finally(() => {
      if (current.flight === flight) current.flight = undefined;
    }),
  };
  current.flight = flight;
  return flight.promise;
}
