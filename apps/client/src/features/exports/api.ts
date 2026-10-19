import { useMemo } from "react";
import { requireWebAuth } from "../../platform/api";
import { cancellableNative } from "../../platform/cancellableNative";
import { nativeExports } from "../../platform/nativeExports";
import { useAuth } from "../auth/AuthProvider";
import { receiveExport } from "./download";
import type { ExportFile, ExportProgress } from "./download";
import type { ExportInput } from "./model";

export function useExportsApi() {
  const { domainApi, state } = useAuth();
  const householdId = state.status === "authenticated" ? state.member.household_id : null;
  return useMemo(
    () => ({
      nativeExport: (input: ExportInput, signal: AbortSignal) =>
        domainApi.write(undefined, () =>
          cancellableNative(signal, () => nativeExports.export({ input })),
        ),
      webExport: async (
        input: ExportInput,
        signal: AbortSignal,
        progress: (value: ExportProgress) => void,
        passkey = false,
      ): Promise<ExportFile> => {
        requireWebAuth();
        let received: ExportFile | undefined;
        try {
          return await domainApi.write<ExportFile>(
            async (client) => {
              const result = await client.POST("/api/v1/exports", {
                body: input,
                parseAs: "stream",
                signal,
              });
              if (!result.response.ok) return { response: result.response, error: result.error };
              received = await receiveExport(result.response, signal, progress);
              return { response: result.response, data: received };
            },
            undefined,
            passkey && householdId
              ? { purpose: "data.export", targetId: householdId, signal }
              : undefined,
          );
        } catch (error) {
          received?.bytes.fill(0);
          throw error;
        }
      },
    }),
    [domainApi, householdId],
  );
}
