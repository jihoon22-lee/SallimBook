import { householdPeople } from "./finance";
import type { Page } from "@playwright/test";
import { members } from "./finance";
import { homeComparison } from "./homecare";
import type { mockHomecare } from "./homecare";
type State = Awaited<ReturnType<typeof mockHomecare>>;
type Args = Record<string, any>;
const mapping: Record<string, { method: string; path: string; fields: Record<string, string> }> = {
  listAssets: { method: "GET", path: "/api/v1/assets", fields: {} },
  listAccounts: { method: "GET", path: "/api/v1/accounts", fields: {} },
  listCards: { method: "GET", path: "/api/v1/cards", fields: {} },
  listInsurancePolicies: { method: "GET", path: "/api/v1/insurance/policies", fields: {} },
  getPurchasePlan: { method: "GET", path: "/api/v1/homecare/purchase-plan", fields: {} },
  listConsumableOrders: { method: "GET", path: "/api/v1/consumable-orders", fields: {} },
  createConsumableOrder: { method: "POST", path: "/api/v1/consumable-orders", fields: {} },
  getConsumableOrder: {
    method: "GET",
    path: "/api/v1/consumable-orders/{order_id}",
    fields: { order_id: "orderId" },
  },
  updateConsumableOrder: {
    method: "PATCH",
    path: "/api/v1/consumable-orders/{order_id}",
    fields: { order_id: "orderId" },
  },
  submitConsumableOrder: {
    method: "POST",
    path: "/api/v1/consumable-orders/{order_id}/submit",
    fields: { order_id: "orderId" },
  },
  receiveConsumableOrder: {
    method: "POST",
    path: "/api/v1/consumable-orders/{order_id}/receive",
    fields: { order_id: "orderId" },
  },
  cancelConsumableOrder: {
    method: "POST",
    path: "/api/v1/consumable-orders/{order_id}/cancel",
    fields: { order_id: "orderId" },
  },
  listApplianceConsumables: {
    method: "GET",
    path: "/api/v1/appliance-consumables",
    fields: {},
  },
  createApplianceConsumable: {
    method: "POST",
    path: "/api/v1/appliance-consumables",
    fields: {},
  },
  deleteApplianceConsumable: {
    method: "DELETE",
    path: "/api/v1/appliance-consumables/{link_id}",
    fields: {
      link_id: "linkId",
    },
  },
  getApplianceConsumable: {
    method: "GET",
    path: "/api/v1/appliance-consumables/{link_id}",
    fields: {
      link_id: "linkId",
    },
  },
  updateApplianceConsumable: {
    method: "PATCH",
    path: "/api/v1/appliance-consumables/{link_id}",
    fields: {
      link_id: "linkId",
    },
  },
  listConsumableReplacements: {
    method: "GET",
    path: "/api/v1/appliance-consumables/{link_id}/replacements",
    fields: {
      link_id: "linkId",
    },
  },
  createConsumableReplacement: {
    method: "POST",
    path: "/api/v1/appliance-consumables/{link_id}/replacements",
    fields: {
      link_id: "linkId",
    },
  },
  getConsumableReplacement: {
    method: "GET",
    path: "/api/v1/appliance-consumables/{link_id}/replacements/{replacement_id}",
    fields: {
      link_id: "linkId",
      replacement_id: "replacementId",
    },
  },
  cancelConsumableReplacement: {
    method: "POST",
    path: "/api/v1/appliance-consumables/{link_id}/replacements/{replacement_id}/cancel",
    fields: {
      link_id: "linkId",
      replacement_id: "replacementId",
    },
  },
  listAppliances: {
    method: "GET",
    path: "/api/v1/appliances",
    fields: {},
  },
  createAppliance: {
    method: "POST",
    path: "/api/v1/appliances",
    fields: {},
  },
  deleteAppliance: {
    method: "DELETE",
    path: "/api/v1/appliances/{appliance_id}",
    fields: {
      appliance_id: "applianceId",
    },
  },
  getAppliance: {
    method: "GET",
    path: "/api/v1/appliances/{appliance_id}",
    fields: {
      appliance_id: "applianceId",
    },
  },
  updateAppliance: {
    method: "PATCH",
    path: "/api/v1/appliances/{appliance_id}",
    fields: {
      appliance_id: "applianceId",
    },
  },
  getAssetComparison: {
    method: "GET",
    path: "/api/v1/asset-comparison",
    fields: {},
  },
  listConsumables: {
    method: "GET",
    path: "/api/v1/consumables",
    fields: {},
  },
  createConsumable: {
    method: "POST",
    path: "/api/v1/consumables",
    fields: {},
  },
  deleteConsumable: {
    method: "DELETE",
    path: "/api/v1/consumables/{consumable_id}",
    fields: {
      consumable_id: "consumableId",
    },
  },
  getConsumable: {
    method: "GET",
    path: "/api/v1/consumables/{consumable_id}",
    fields: {
      consumable_id: "consumableId",
    },
  },
  updateConsumable: {
    method: "PATCH",
    path: "/api/v1/consumables/{consumable_id}",
    fields: {
      consumable_id: "consumableId",
    },
  },
  listStockMovements: {
    method: "GET",
    path: "/api/v1/consumables/{consumable_id}/stock-movements",
    fields: {
      consumable_id: "consumableId",
    },
  },
  createStockMovement: {
    method: "POST",
    path: "/api/v1/consumables/{consumable_id}/stock-movements",
    fields: {
      consumable_id: "consumableId",
    },
  },
  getStockMovement: {
    method: "GET",
    path: "/api/v1/consumables/{consumable_id}/stock-movements/{movement_id}",
    fields: {
      consumable_id: "consumableId",
      movement_id: "movementId",
    },
  },
  cancelStockMovement: {
    method: "POST",
    path: "/api/v1/consumables/{consumable_id}/stock-movements/{movement_id}/cancel",
    fields: {
      consumable_id: "consumableId",
      movement_id: "movementId",
    },
  },
  getHomecareStatus: {
    method: "GET",
    path: "/api/v1/homecare/status",
    fields: {},
  },
  listOverdueObligations: { method: "GET", path: "/api/v1/obligations/overdue", fields: {} },
  listMedicalExpenses: { method: "GET", path: "/api/v1/insurance/medical-expenses", fields: {} },
  getAssetTrends: { method: "GET", path: "/api/v1/asset-trends", fields: {} },
  incomeSummary: {
    method: "GET",
    path: "/api/v1/income/summary",
    fields: {},
  },
  listInsuranceCases: {
    method: "GET",
    path: "/api/v1/insurance/cases",
    fields: {},
  },
  listInsuranceClaims: {
    method: "GET",
    path: "/api/v1/insurance/claims",
    fields: {},
  },
  fixedCostSummary: {
    method: "GET",
    path: "/api/v1/obligations/summary",
    fields: {},
  },
};
export async function mockNativeHomecare(page: Page, state: State) {
  const calls: { method: string; args: Args }[] = [];
  const http: string[] = [];
  const control = {
    failure: "" as "" | "APP_LOCKED" | "SESSION_EXPIRED" | "NETWORK_UNAVAILABLE",
    method: "",
    delayMethod: "",
    delayMs: 0,
    delayAllMs: 0,
    metadataGate: null as Promise<void> | null,
    maxPending: Infinity,
    pending: 0,
    peakPending: 0,
    rejected: 0,
    started: 0,
  };
  const metadata = (body: unknown, status = 200) => ({ ok: true, value: { status, body } });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) http.push(request.url());
  });
  const respond = async (method: string, args: Args) => {
    calls.push({ method, args });
    if (method === "getSession")
      return { ok: true, value: { available: true, authenticated: true } };
    if (method === "listHouseholdPeople")
      return metadata({ items: householdPeople, next_cursor: null });
    if (method === "request") return metadata(args.path === "/api/v1/me" ? members[0] : members);
    if (control.failure && (!control.method || control.method === method))
      return { ok: false, code: control.failure };
    if (method === "listAssets" || method === "listAccounts")
      return metadata({ items: [], next_cursor: null });
    if (method === "getAssetComparison") return metadata(homeComparison(args.query.to));
    if (method === "getAssetTrends")
      return metadata(state.trendResponse(new URLSearchParams(args.query)));
    const route = mapping[method];
    if (!route) return { ok: false, code: "INVALID_REQUEST" };
    let path = route.path;
    for (const [field, input] of Object.entries(route.fields))
      path = path.replace(`{${field}}`, args[input]);
    const query = new URLSearchParams(
      Object.fromEntries(
        Object.entries(args.query ?? {})
          .filter(([, value]) => value !== undefined && value !== null)
          .map(([key, value]) => [key, String(value)]),
      ),
    );
    const headers = {
      ...(args.idempotencyKey ? { "idempotency-key": args.idempotencyKey } : {}),
      ...(args.ifMatch ? { "if-match": args.ifMatch } : {}),
    };
    const result = path.startsWith("/api/v1/insurance/")
      ? await state.insurance.handle(route.method, path, query, args.input ?? {}, headers)
      : ((await state.handle(route.method, path, query, args.input ?? {}, headers)) ??
        (await state.cashflow.handle(route.method, path, query, args.input ?? {}, headers)));
    if (control.delayMethod === method && control.delayMs)
      await new Promise((resolve) => setTimeout(resolve, control.delayMs));
    return result?.abort
      ? { ok: false, code: "NETWORK_UNAVAILABLE" }
      : result
        ? metadata(result.body, result.status)
        : { ok: false, code: "INVALID_REQUEST" };
  };
  await page.exposeFunction("syntheticHomecareNative", async (method: string, args: Args) => {
    if (control.pending >= control.maxPending) {
      control.rejected++;
      return { ok: false, code: "AUTH_UNAVAILABLE" };
    }
    control.started++;
    control.pending++;
    control.peakPending = Math.max(control.peakPending, control.pending);
    try {
      if (
        control.metadataGate &&
        !["getSession", "request", "listHouseholdPeople"].includes(method)
      )
        await control.metadataGate;
      if (control.delayAllMs)
        await new Promise((resolve) => setTimeout(resolve, control.delayAllMs));
      return await respond(method, args);
    } finally {
      control.pending--;
    }
  });
  await page.addInitScript((methods) => {
    const listeners = new Map<string, (event: { locked: boolean }) => void>();
    Object.assign(window, {
      syntheticCareLock: () => listeners.forEach((listener) => listener({ locked: true })),
      CapacitorCustomPlatform: { name: "android" },
      Capacitor: {
        PluginHeaders: [
          {
            name: "SallimBookAuth",
            methods: [...methods, "listHouseholdPeople", "getSession", "request"]
              .map((name) => ({ name, rtype: "promise" }))
              .concat([
                { name: "addListener", rtype: "callback" },
                { name: "removeListener", rtype: "promise" },
              ]),
          },
        ],
        nativeCallback: (
          _plugin: string,
          _method: string,
          _args: unknown,
          listener: (event: { locked: boolean }) => void,
        ) => {
          const id = String(listeners.size + 1);
          listeners.set(id, listener);
          return id;
        },
        nativePromise: (_plugin: string, method: string, args = {}) =>
          method === "removeListener"
            ? Promise.resolve()
            : (window as any).syntheticHomecareNative(method, args),
      },
    });
  }, Object.keys(mapping));
  return {
    calls,
    http,
    control,
    lock: () => page.evaluate(() => (window as any).syntheticCareLock()),
  };
}
