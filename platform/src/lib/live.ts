/**
 * Wakes the programs waiting on /api/v1/wait the moment an administrator changes a licence or a
 * computer, so a lock reaches the screen within seconds instead of at the next check-in.
 *
 * In-process only. The waiters also re-read the database every few seconds, which covers a
 * second replica during a deploy and changes nobody announces (an expiry date passing).
 */
type Waiter = () => void;

const globalForLive = globalThis as unknown as { licenceWaiters?: Set<Waiter> };
const waiters: Set<Waiter> = (globalForLive.licenceWaiters ??= new Set());

/** Call after changing a licence or a computer: every waiting program re-reads its status. */
export function announceChange(): void {
  for (const wake of [...waiters]) wake();
}

/** Resolves on the next announceChange(), after `ms`, or when `signal` aborts, whichever comes first. */
export function nextChange(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      waiters.delete(finish);
      signal?.removeEventListener("abort", finish);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    waiters.add(finish);
    signal?.addEventListener("abort", finish, { once: true });
  });
}
