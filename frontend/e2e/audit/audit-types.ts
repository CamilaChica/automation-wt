export type AuditPersona = 'public' | 'customer' | 'internal';
export type FindingSeverity = 'error' | 'warning';
export type InteractionOutcome = 'changed' | 'unchanged' | 'skipped' | 'failed';

export interface AuditFinding {
  severity: FindingSeverity;
  category: string;
  message: string;
  route?: string;
  action?: string;
  evidence?: string;
}

export interface AuditedRoute {
  path: string;
  status?: number;
  title?: string;
  stateCount: number;
  interactiveCount: number;
  inputCount: number;
}

export interface AuditedInteraction {
  route: string;
  control: string;
  outcome: InteractionOutcome;
  before?: string;
  after?: string;
  note?: string;
}

export interface AuditReport {
  schemaVersion: 1;
  runId: string;
  persona: AuditPersona;
  startedAt: string;
  finishedAt?: string;
  entryRoutes: string[];
  routes: AuditedRoute[];
  interactions: AuditedInteraction[];
  findings: AuditFinding[];
  counts: {
    routes: number;
    states: number;
    interactions: number;
    skippedMutations: number;
    errors: number;
    warnings: number;
  };
}

export interface CrawlOptions {
  maxRoutes?: number;
  maxStates?: number;
  maxActions?: number;
  maxActionsPerState?: number;
  allowedRoutePrefixes?: string[];
}

export interface ControlToken {
  index: number;
  occurrence: number;
  name: string;
  role: string;
}