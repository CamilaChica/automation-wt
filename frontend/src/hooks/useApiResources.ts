import { useCallback, useEffect, useRef, useState } from 'react';
import { apiService, getApiErrorMessage } from '../services/api';
import type {
  ApiStatus,
  ExtractionReviewDecisionBody,
  ExtractionReviewResponse,
  CarrierTrackingBody,
  CreateShipmentBody,
  FreightQuoteBody,
  FreightQuoteResponse,
  FailedIntakeResetBody,
  FailedIntakeResetResponse,
  FulfillmentStage,
  IntakeRequestBody,
  LlmHealthResponse,
  LlmTelemetryRecord,
  MailboxHealthResponse,
  MailboxInboxResponse,
  MailboxMessageBody,
  MailboxSendResponse,
  PurchaseOrderApprovalRequest,
  ShipmentTraceResponse,
  ShipmentEventBody,
  ShipmentSmsBody,
  SystemHealthResponse,
} from '../types/api';
import type { AutomationEvent, InternalCommand, InventoryItem, RFQ, RFQDetailResponse, Shipment, Supplier, SupplierQuote } from '../types';

export interface ApiQueryState<T> {
  data: T | undefined;
  isLoading: boolean;
  error: Error | null;
  isSampleData: boolean;
  isEmpty: boolean;
  refetch: () => Promise<void>;
}

interface ApiQueryValue<T> {
  data: T;
  isSampleData?: boolean;
}

type Loader<T> = () => Promise<ApiQueryValue<T>>;
const invalidators = new Map<string, Set<() => Promise<void>>>();

export async function invalidateApiQueries(...keys: string[]): Promise<void> {
  const pendingRefetches = new Set<() => Promise<void>>();
  for (const key of keys) {
    for (const [registeredKey, listeners] of invalidators) {
      if (registeredKey === key || registeredKey.startsWith(`${key}:`)) {
        for (const refetch of listeners) pendingRefetches.add(refetch);
      }
    }
  }
  await Promise.all(Array.from(pendingRefetches, refetch => refetch()));
}

export function useApiQuery<T>(key: string, loader: Loader<T>, enabled = true): ApiQueryState<T> {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const requestVersion = useRef(0);
  const [state, setState] = useState<{ key: string; data?: T; isLoading: boolean; error: Error | null; isSampleData: boolean }>({
    key,
    isLoading: enabled,
    error: null,
    isSampleData: false,
  });

  const refetch = useCallback(async () => {
    if (!enabled) return;
    const version = ++requestVersion.current;
    setState(current => ({
      key,
      data: current.key === key ? current.data : undefined,
      isLoading: current.key !== key || current.data === undefined,
      error: null,
      isSampleData: current.key === key ? current.isSampleData : false,
    }));
    try {
      const result = await loaderRef.current();
      if (requestVersion.current !== version) return;
      setState({ key, data: result.data, isLoading: false, error: null, isSampleData: Boolean(result.isSampleData) });
    } catch (cause) {
      if (requestVersion.current !== version) return;
      setState(current => ({
        key,
        data: current.key === key ? current.data : undefined,
        isLoading: false,
        error: new Error(getApiErrorMessage(cause, 'Unable to load data.')),
        isSampleData: false,
      }));
    }
  }, [enabled, key]);

  useEffect(() => {
    if (!enabled) {
      setState({ key, isLoading: false, error: null, isSampleData: false });
      return undefined;
    }
    let keyInvalidators = invalidators.get(key);
    if (!keyInvalidators) {
      keyInvalidators = new Set();
      invalidators.set(key, keyInvalidators);
    }
    keyInvalidators.add(refetch);
    void refetch();
    return () => {
      requestVersion.current += 1;
      keyInvalidators?.delete(refetch);
      if (keyInvalidators?.size === 0) invalidators.delete(key);
    };
  }, [enabled, key, refetch]);

  const current = state.key === key ? state : { key, isLoading: enabled, error: null, isSampleData: false };
  return {
    data: current.data,
    isLoading: current.isLoading,
    error: current.error,
    isSampleData: current.isSampleData,
    isEmpty: Array.isArray(current.data) && current.data.length === 0,
    refetch,
  };
}

export interface ApiMutationState<TInput, TOutput> {
  mutateAsync: (input: TInput) => Promise<TOutput | undefined>;
  isPending: boolean;
  error: Error | null;
}

export function useApiMutation<TInput, TOutput>(
  mutation: (input: TInput) => Promise<TOutput>,
  invalidates: string[] = [],
): ApiMutationState<TInput, TOutput> {
  const mutationRef = useRef(mutation);
  mutationRef.current = mutation;
  const inFlight = useRef(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const mutateAsync = useCallback(async (input: TInput) => {
    if (inFlight.current) return undefined;
    inFlight.current = true;
    setIsPending(true);
    setError(null);
    try {
      const result = await mutationRef.current(input);
      await invalidateApiQueries(...invalidates);
      return result;
    } catch (cause) {
      const mutationError = cause instanceof Error ? cause : new Error('Unable to complete the operation.');
      setError(mutationError);
      throw mutationError;
    } finally {
      inFlight.current = false;
      setIsPending(false);
    }
  }, [invalidates]);

  return { mutateAsync, isPending, error };
}

export const apiQueryKeys = {
  rfqs: 'rfqs',
  rfqDetail: (rfqId: string) => `rfq-detail:${rfqId}`,
  supplierOffers: (partNumber: string) => `supplier-offers:${partNumber.toUpperCase()}`,
  shipments: 'shipments',
  shipmentTrace: (token: string) => `shipment-trace:${token}`,
  automationEvents: 'automation-events',
  systemHealth: 'system-health',
  mailboxHealth: 'mailbox-health',
  operatorReviews: 'operator-reviews',
  operatorReviewDetail: (reviewId: string) => `operator-review-detail:${reviewId}`,
  llmHealth: 'llm-health',
  llmTelemetry: 'llm-telemetry',
  inventory: 'inventory',
  suppliers: 'suppliers',
  supplierDetail: (supplierId: string) => `supplier-detail:${supplierId}`,
  mailboxInbox: (mailbox: 'sales' | 'purchasing') => `mailbox-inbox:${mailbox}`,
  purchaseOrders: 'purchase-orders',
} as const;

export function useRFQs() {
  return useApiQuery<RFQ[]>(apiQueryKeys.rfqs, async () => {
    const result = await apiService.getRFQsWithSource();
    return { data: result.rfqs, isSampleData: result.isFallback };
  });
}

export function useRFQDetail(rfqId: string) {
  return useApiQuery<RFQDetailResponse>(apiQueryKeys.rfqDetail(rfqId), async () => {
    const detail = await apiService.getRFQDetail(rfqId);
    return { data: detail, isSampleData: Boolean(detail.isFallback) };
  }, Boolean(rfqId));
}

export function useQuotes(rfqId: string) {
  const detail = useRFQDetail(rfqId);
  return { ...detail, data: detail.data?.quote_details };
}

export function useCreateRFQ() {
  return useApiMutation((input: IntakeRequestBody) => apiService.submitCustomerRFQ(
    input.raw_text,
    input.customer_name || '',
    input.customer_email || '',
    input.attachment_ids || [],
  ), [apiQueryKeys.rfqs]);
}

export function useSupplierOffers(partNumber: string) {
  return useApiQuery<SupplierQuote[]>(apiQueryKeys.supplierOffers(partNumber), async () => ({
    data: await apiService.getSupplierOffers(partNumber),
  }), Boolean(partNumber.trim()));
}

export function useShipments(enabled = true) {
  return useApiQuery<Shipment[]>(apiQueryKeys.shipments, async () => ({ data: await apiService.getShipments() }), enabled);
}

export function useShipmentTrace(publicToken: string) {
  return useApiQuery<ShipmentTraceResponse>(apiQueryKeys.shipmentTrace(publicToken), async () => ({
    data: await apiService.trackShipment(publicToken),
  }), Boolean(publicToken.trim()));
}

export function useFulfillmentStages(enabled = true) {
  const shipments = useShipments(enabled);
  const data: FulfillmentStage[] | undefined = shipments.data?.map(shipment => ({
    shipment_id: shipment.id,
    stage: stageFromShipmentStatus(shipment.status),
    status: shipment.status,
    carrier: shipment.carrier,
    tracking_number: shipment.tracking_number,
    updated_at: shipment.updated_at,
    is_derived_from_shipment: true,
  }));
  return { ...shipments, data };
}

function stageFromShipmentStatus(status: string): string {
  const normalized = status.toLowerCase();
  if (/delivered|complete/.test(normalized)) return 'Delivered';
  if (/transit|shipped|out_for_delivery/.test(normalized)) return 'In Transit';
  if (/label|tracking/.test(normalized)) return 'Carrier Tracking';
  if (/prepar|pending|created/.test(normalized)) return 'Preparing Shipment';
  return 'Shipment Status';
}

export function useAutomationEvents() {
  return useApiQuery<AutomationEvent[]>(apiQueryKeys.automationEvents, async () => ({
    data: await apiService.getAutomationEvents(),
  }));
}

export function useSystemHealth() {
  return useApiQuery<SystemHealthResponse>('system-health', async () => ({ data: await apiService.getReadiness() }));
}

export function useMailboxHealth(enabled = true) {
  return useApiQuery<MailboxHealthResponse>('mailbox-health', async () => ({ data: await apiService.getMailboxHealth() }), enabled);
}

export function useCreatePurchaseOrder() {
  return useApiMutation((input: { quoteId: string; poNumber: string; customerEmail: string; attachmentIds?: string[] }) =>
    apiService.submitPurchaseOrder(input.quoteId, input.poNumber, input.customerEmail, input.attachmentIds), [apiQueryKeys.rfqs, 'rfq-detail']);
}

export function useDispatchQuote() {
  return useApiMutation((input: { quoteId: string; operatorName: string; overrides?: Array<{ quote_item_id: string; unit_price: number }>; expectedVersion?: number }) =>
    apiService.approveQuote(input.quoteId, input.operatorName, input.overrides, input.expectedVersion), [apiQueryKeys.rfqs, 'rfq-detail']);
}

export function useProcessRFQ() {
  return useApiMutation((rfqId: string) => apiService.processRFQ(rfqId), [
    apiQueryKeys.rfqs,
    'rfq-detail',
    apiQueryKeys.automationEvents,
  ]);
}

export function useResetFailedIntake() {
  return useApiMutation(
    (input: { rfqId: string; body: FailedIntakeResetBody }): Promise<FailedIntakeResetResponse> =>
      apiService.resetFailedIntake(input.rfqId, input.body),
    [apiQueryKeys.rfqs, 'rfq-detail', apiQueryKeys.automationEvents],
  );
}

export function useRejectQuote() {
  return useApiMutation((input: { quoteId: string; operatorName: string; comments: string }) =>
    apiService.rejectQuote(input.quoteId, input.operatorName, input.comments), [
      apiQueryKeys.rfqs,
      'rfq-detail',
    ]);
}

export function useSetAutomationPause() {
  return useApiMutation((input: { rfqId: string; paused: boolean; reason?: string }) =>
    apiService.setAutomationPause(input.rfqId, { paused: input.paused, reason: input.reason }), [
      apiQueryKeys.rfqs,
      apiQueryKeys.automationEvents,
    ]);
}

  export function useExtractionReviews(enabled = true) {
    return useApiQuery<ExtractionReviewResponse[]>(apiQueryKeys.operatorReviews, async () => ({
      data: await apiService.getExtractionReviews('PENDING', 100),
    }), enabled);
  }

  export function useExtractionReview(reviewId: string) {
    return useApiQuery<ExtractionReviewResponse>(apiQueryKeys.operatorReviewDetail(reviewId), async () => ({
      data: await apiService.getExtractionReview(reviewId),
    }), Boolean(reviewId));
  }

  export function useDecideExtractionReview() {
    return useApiMutation((input: { reviewId: string; body: ExtractionReviewDecisionBody }) =>
      apiService.decideExtractionReview(input.reviewId, input.body), [
        apiQueryKeys.operatorReviews,
        'operator-review-detail',
        apiQueryKeys.rfqs,
      ]);
  }

    export function useLlmHealth(enabled = true) {
      return useApiQuery<LlmHealthResponse>(apiQueryKeys.llmHealth, async () => ({
        data: await apiService.getLlmHealth(),
      }), enabled);
    }

    export function useLlmTelemetry(enabled = true) {
      return useApiQuery<LlmTelemetryRecord[]>(apiQueryKeys.llmTelemetry, async () => ({
        data: await apiService.getLlmTelemetry(undefined, 50),
      }), enabled);
    }

    export function useInventoryDirectory(enabled = true) {
      return useApiQuery<InventoryItem[]>(apiQueryKeys.inventory, async () => {
        const result = await apiService.getInventoryWithSource();
        return { data: result.inventory, isSampleData: result.isFallback };
      }, enabled);
    }

    export function useSupplierDirectory(enabled = true) {
      return useApiQuery<Supplier[]>(apiQueryKeys.suppliers, async () => {
        const result = await apiService.getSuppliersWithSource();
        return { data: result.suppliers, isSampleData: result.isFallback };
      }, enabled);
    }

    export function useSupplierProfile(supplierId: string) {
      return useApiQuery<Supplier>(apiQueryKeys.supplierDetail(supplierId), async () => ({
        data: await apiService.getSupplier(supplierId),
      }), Boolean(supplierId));
    }

    export function useFreightQuote() {
      return useApiMutation((request: FreightQuoteBody): Promise<FreightQuoteResponse> =>
        apiService.quoteFreight(request));
    }

    export function useMailboxInbox(mailbox: 'sales' | 'purchasing', enabled = true) {
      return useApiQuery<MailboxInboxResponse>(apiQueryKeys.mailboxInbox(mailbox), async () => ({
        data: await apiService.getMailboxInbox(mailbox),
      }), enabled);
    }

    export function useSendMailboxMessage() {
      return useApiMutation((input: { mailbox: 'sales' | 'purchasing'; message: MailboxMessageBody }): Promise<MailboxSendResponse> =>
        apiService.sendMailboxMessage(input.mailbox, input.message), [
          apiQueryKeys.mailboxInbox('sales'),
          apiQueryKeys.mailboxInbox('purchasing'),
        ]);
    }

      export function useApprovePurchaseOrder() {
        return useApiMutation((input: { quoteId: string; body: PurchaseOrderApprovalRequest }) =>
          apiService.approvePurchaseOrder(input.quoteId, input.body), [
            apiQueryKeys.purchaseOrders,
            apiQueryKeys.rfqs,
          ]);
      }

      export function useCreateShipment() {
        return useApiMutation((body: CreateShipmentBody) => apiService.createShipment(body), [
          apiQueryKeys.shipments,
          apiQueryKeys.rfqs,
        ]);
      }

      export function useAddShipmentEvent() {
        return useApiMutation((input: { shipmentId: string; body: ShipmentEventBody }) =>
          apiService.addShipmentEvent(input.shipmentId, input.body), [apiQueryKeys.shipments]);
      }

      export function useRegisterCarrierTracking() {
        return useApiMutation((input: { shipmentId: string; body: CarrierTrackingBody }) =>
          apiService.registerCarrierTracking(input.shipmentId, input.body), [apiQueryKeys.shipments]);
      }

      export function useRefreshCarrierTracking() {
        return useApiMutation((shipmentId: string) => apiService.refreshCarrierTracking(shipmentId), [apiQueryKeys.shipments]);
      }

      export function useSendShipmentSms() {
        return useApiMutation((input: { shipmentId: string; body: ShipmentSmsBody }) =>
          apiService.sendShipmentSms(input.shipmentId, input.body), [apiQueryKeys.shipments]);
      }

export function useTraceDecision() {
  return useApiMutation((input: { rfqId: string; decision: 'certify' | 'reject' | 'rescan' | 'freeze'; reason?: string }) =>
    apiService.recordTraceDecision(input.rfqId, input.decision, input.reason), [apiQueryKeys.rfqs, apiQueryKeys.automationEvents]);
}

export function useExecuteInternalCommand() {
  return useApiMutation((input: { command: InternalCommand; entityId: string; details?: string }) =>
    apiService.executeInternalCommand(input.command, input.entityId, input.details), [apiQueryKeys.automationEvents, apiQueryKeys.shipments]);
}

export type { ApiStatus };
