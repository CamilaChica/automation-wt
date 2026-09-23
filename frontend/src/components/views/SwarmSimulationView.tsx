import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Gauge,
  Play,
  RotateCcw,
  ShieldAlert,
  Users,
  Zap,
} from 'lucide-react';

interface Scenario {
  id: string;
  label: string;
  description: string;
  client: string;
  supplier: string;
  accent: string;
  events: string[];
  gate: { confidence: number; margin: number; value: number; compliance: string };
  outcome: string;
}

const SCENARIOS: Scenario[] = [
  {
    id: 'aog',
    label: 'Urgent AOG',
    description: 'Clean RFQ, fast supplier response, policy-approved dispatch.',
    client: 'AOG Express Airlines',
    supplier: 'FastTrack Aero Parts',
    accent: 'blue',
    events: ['event.rfq.received', 'event.rfq.extracted', 'event.sourcing.requested', 'event.supplier.response', 'event.quote.generated', 'event.auto_dispatch.executed'],
    gate: { confidence: 0.98, margin: 0.25, value: 2500, compliance: 'APPROVED' },
    outcome: 'Auto-dispatch approved',
  },
  {
    id: 'margin',
    label: 'Low-margin counter',
    description: 'Bargain buyer counters below the margin threshold and enters HITL.',
    client: 'Bargain MRO Purchaser',
    supplier: 'FastTrack Aero Parts',
    accent: 'amber',
    events: ['event.rfq.received', 'event.quote.generated', 'event.client.counter_offer', 'event.escalated.human', 'event.quote.approved_by_human'],
    gate: { confidence: 0.98, margin: 0.124, value: 10200, compliance: 'APPROVED' },
    outcome: 'Sales Manager approval required',
  },
  {
    id: 'sanctions',
    label: 'Sanctions blocking',
    description: 'Supplier matches a denied-party signal; outbound communication stops.',
    client: 'Foreign Commercial Airline',
    supplier: 'Sanctioned Flag Distributor',
    accent: 'red',
    events: ['event.rfq.received', 'event.rfq.extracted', 'event.sourcing.requested', 'event.supplier.response', 'event.compliance.flagged'],
    gate: { confidence: 0.98, margin: 0.25, value: 1000, compliance: 'REJECTED' },
    outcome: 'Outbound pipeline halted',
  },
];

const sleep = (duration: number) => new Promise(resolve => window.setTimeout(resolve, duration));

export const SwarmSimulationView: React.FC = () => {
  const [selectedId, setSelectedId] = useState('aog');
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState(-1);
  const [runCount, setRunCount] = useState(0);
  const scenario = useMemo(() => SCENARIOS.find(item => item.id === selectedId) ?? SCENARIOS[0], [selectedId]);

  useEffect(() => {
    setStep(-1);
    setRunning(false);
  }, [selectedId]);

  const runScenario = async () => {
    if (running) return;
    setRunning(true);
    setStep(-1);
    for (let index = 0; index < scenario.events.length; index += 1) {
      await sleep(260);
      setStep(index);
    }
    setRunning(false);
    setRunCount(value => value + 1);
  };

  const reset = () => {
    setStep(-1);
    setRunning(false);
  };

  const completed = step >= scenario.events.length - 1;
  const gateChecks = [
    { label: 'Extraction confidence', value: `${Math.round(scenario.gate.confidence * 100)}%`, passed: scenario.gate.confidence >= 0.92 },
    { label: 'Gross margin', value: `${Math.round(scenario.gate.margin * 1000) / 10}%`, passed: scenario.gate.margin >= 0.18 },
    { label: 'Quote value', value: `$${scenario.gate.value.toLocaleString()}`, passed: scenario.gate.value <= 25000 },
    { label: 'Compliance', value: scenario.gate.compliance, passed: scenario.gate.compliance === 'APPROVED' },
  ];

  return (
    <section className="min-h-full bg-slate-50 px-5 py-6 text-slate-900 dark:bg-slate-950 dark:text-slate-100 lg:px-8">
      <div className="mx-auto max-w-[1440px]">
        <div className="flex flex-col justify-between gap-4 border-b border-slate-200 pb-5 dark:border-slate-800 md:flex-row md:items-end">
          <div>
            <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.22em] text-aero-blue">
              <Activity className="h-3.5 w-3.5" /> Simulation control panel
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight md:text-3xl">Swarm Test Runner</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-500 dark:text-slate-400">Run deterministic persona scenarios against the event-driven safety gates. No external messages are sent.</p>
          </div>
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
            <span className="h-2 w-2 rounded-full bg-emerald-500" /> Local simulation bus online
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 font-mono text-[10px] dark:border-slate-700 dark:bg-slate-900">{runCount} runs</span>
          </div>
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {SCENARIOS.map(item => (
            <button
              key={item.id}
              type="button"
              onClick={() => setSelectedId(item.id)}
              onKeyDown={event => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setSelectedId(item.id);
                }
              }}
              role="button"
              tabIndex={0}
              aria-pressed={selectedId === item.id}
              aria-label={`Select ${item.label} scenario`}
              className={`rounded-xl border p-4 text-left transition ${selectedId === item.id ? 'border-aero-blue bg-white shadow-md shadow-aero-blue/10 dark:bg-slate-900' : 'border-slate-200 bg-white/70 hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900/50'}`}
            >
              <div className="flex items-start justify-between gap-3">
                <span className={`h-2.5 w-2.5 rounded-full ${item.accent === 'red' ? 'bg-red-500' : item.accent === 'amber' ? 'bg-amber-500' : 'bg-aero-blue'}`} />
                <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">{item.id}</span>
              </div>
              <h2 className="mt-4 text-sm font-bold">{item.label}</h2>
              <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{item.description}</p>
            </button>
          ))}
        </div>

        <div className="mt-6 grid gap-5 xl:grid-cols-[1.35fr_0.8fr]">
          <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <div className="flex flex-col gap-3 border-b border-slate-200 p-5 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="flex items-center gap-2 text-sm font-bold"><Zap className="h-4 w-4 text-aero-blue" />{scenario.label}</div>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{scenario.client} <span className="px-1">/</span> {scenario.supplier}</p>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={reset} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"><RotateCcw className="h-3.5 w-3.5" /> Reset</button>
                <button type="button" onClick={() => void runScenario()} disabled={running} className="inline-flex items-center gap-2 rounded-lg bg-aero-blue px-3 py-2 text-xs font-bold text-white shadow-sm disabled:cursor-wait disabled:opacity-60"><Play className="h-3.5 w-3.5 fill-current" /> {running ? 'Running...' : 'Run scenario'}</button>
              </div>
            </div>
            <div className="p-5">
              <div className="mb-4 flex items-center justify-between text-[10px] font-bold uppercase tracking-wider text-slate-400"><span>Event bus trace</span><span>{Math.max(step + 1, 0)} / {scenario.events.length} events</span></div>
              <div className="space-y-2">
                {scenario.events.map((event, index) => {
                  const active = index <= step;
                  const current = index === step;
                  return <div key={event} className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 font-mono text-xs transition ${active ? 'border-aero-blue/30 bg-blue-50/70 text-slate-800 dark:bg-aero-blue/10 dark:text-slate-200' : 'border-slate-100 text-slate-400 dark:border-slate-800/80'}`}><span className={`h-2 w-2 rounded-full ${active ? current ? 'bg-aero-blue animate-pulse' : 'bg-emerald-500' : 'bg-slate-300 dark:bg-slate-700'}`} /><span className="flex-1">{event}</span>{active && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}</div>;
                })}
              </div>
              {running && <div role="status" aria-live="polite" aria-busy="true" className="mt-4 rounded-lg bg-blue-50 px-3 py-2.5 text-xs font-bold text-blue-700 dark:bg-blue-950/30 dark:text-blue-300">Running {scenario.label}...</div>}
              {completed && <div role="status" aria-live="polite" aria-busy="false" className={`mt-4 flex items-center gap-2 rounded-lg px-3 py-2.5 text-xs font-bold ${scenario.id === 'sanctions' ? 'bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300' : scenario.id === 'margin' ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300' : 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'}`}>{scenario.id === 'sanctions' ? <ShieldAlert className="h-4 w-4" /> : scenario.id === 'margin' ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}{scenario.outcome}</div>}
            </div>
          </div>

          <div className="space-y-5">
            <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
              <div className="flex items-center gap-2 text-sm font-bold"><Gauge className="h-4 w-4 text-aero-blue" /> Policy gate</div>
              <div className="mt-4 space-y-3">{gateChecks.map(check => <div key={check.label} className="flex items-center justify-between border-b border-slate-100 pb-2 text-xs last:border-0 last:pb-0 dark:border-slate-800"><span className="text-slate-500 dark:text-slate-400">{check.label}</span><span className={`inline-flex items-center gap-1.5 font-mono font-bold ${check.passed ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>{check.passed ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Circle className="h-3.5 w-3.5" />}{check.value}</span></div>)}</div>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
              <div className="flex items-center gap-2 text-sm font-bold"><Users className="h-4 w-4 text-aero-blue" /> Persona state</div>
              <div className="mt-4 space-y-3 text-xs"><div className="flex justify-between"><span className="text-slate-500">Client</span><span className="font-semibold">{scenario.client}</span></div><div className="flex justify-between"><span className="text-slate-500">Supplier</span><span className="font-semibold">{scenario.supplier}</span></div><div className="flex justify-between"><span className="text-slate-500">Human path</span><span className="font-semibold">{scenario.id === 'margin' ? 'Sales Manager' : scenario.id === 'sanctions' ? 'Compliance Officer' : 'Not required'}</span></div><div className="flex justify-between"><span className="text-slate-500">Outbound state</span><span className={`font-bold ${scenario.id === 'sanctions' ? 'text-red-600' : 'text-emerald-600'}`}>{scenario.id === 'sanctions' ? 'Blocked' : completed ? 'Simulated' : 'Pending'}</span></div></div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
