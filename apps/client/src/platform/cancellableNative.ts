import { ApiError } from "./api";

/** Native requests may finish after cancellation; discard their result without claiming rollback. */
export async function cancellableNative<T>(
  signal: AbortSignal | undefined,
  request: () => Promise<T>,
): Promise<T> {
  if (signal?.aborted) throw new ApiError(0, "REQUEST_CANCELLED");
  const result = await request();
  if (signal?.aborted) throw new ApiError(0, "REQUEST_CANCELLED");
  return result;
}
