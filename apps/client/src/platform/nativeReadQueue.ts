import { ApiError } from "./api";

/** Keep metadata reads below the native bridge's eight-call limit, leaving room for auth/writes. */
export function createNativeReadQueue() {
  let active = 0;
  const waiting: (() => void)[] = [];
  return async function read<T>(request: () => Promise<T>): Promise<T> {
    if (active >= 4) {
      if (waiting.length >= 128) throw new ApiError(0, "REQUEST_FAILED");
      await new Promise<void>((resolve) => waiting.push(resolve));
    } else active++;
    try {
      return await request();
    } finally {
      // Transfer this slot to the next reader before admitting a new one.
      const next = waiting.shift();
      if (next) next();
      else active--;
    }
  };
}
