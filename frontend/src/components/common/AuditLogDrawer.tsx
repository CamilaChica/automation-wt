import React from 'react';
import { AgentAuditLog, getAgentProfile } from '../../types';
import { X, CheckCircle, AlertTriangle, XCircle, Bot, Cpu, ShieldCheck, DollarSign, Send, Search } from 'lucide-react';

interface AuditLogDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  logs: AgentAuditLog[];
  rfqId: string;
}

export const AuditLogDrawer: React.FC<AuditLogDrawerProps> = ({
  isOpen,
  onClose,
  logs,
  rfqId
}) => {
  if (!isOpen) return null;

  const getAgentIcon = (name: string) => {
    switch (name) {
      case 'RFQIntakeAgent': return <Bot className="w-4 h-4 text-aero-blue" />;
      case 'PartsIntelligenceAgent': return <Search className="w-4 h-4 text-cyan-400" />;
      case 'InventoryAgent': return <Cpu className="w-4 h-4 text-indigo-400" />;
      case 'ComplianceAgent': return <ShieldCheck className="w-4 h-4 text-emerald-400" />;
      case 'PricingAgent': return <DollarSign className="w-4 h-4 text-amber-400" />;
      case 'CustomerCommunicationAgent': return <Send className="w-4 h-4 text-emerald-400" />;
      default: return <Bot className="w-4 h-4 text-aero-blue" />;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'SUCCESS':
        return (
          <span className="flex items-center space-x-1 text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded font-mono text-[9px] font-bold">
            <CheckCircle className="w-3 h-3" />
            <span>SUCCESS</span>
          </span>
        );
      case 'WARNING':
        return (
          <span className="flex items-center space-x-1 text-amber-400 bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 rounded font-mono text-[9px] font-bold">
            <AlertTriangle className="w-3 h-3" />
            <span>ESCALATION</span>
          </span>
        );
      case 'FAILURE':
        return (
          <span className="flex items-center space-x-1 text-aog-red bg-aog-red/10 border border-aog-red/30 px-2 py-0.5 rounded font-mono text-[9px] font-bold">
            <XCircle className="w-3 h-3" />
            <span>HALTED</span>
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-md bg-white dark:bg-card-dark border-l border-slate-200 dark:border-slate-800 h-full flex flex-col justify-between shadow-2xl font-sans">
        {/* Header */}
        <div className="p-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between bg-slate-50 dark:bg-slate-900/90">
          <div>
            <h3 className="font-display font-bold text-sm text-slate-900 dark:text-slate-100 uppercase flex items-center space-x-2">
              <Bot className="w-4 h-4 text-aero-blue" />
              <span>MULTI-AGENT REASONING TIMELINE</span>
            </h3>
            <p className="text-[10px] font-mono text-slate-500 dark:text-slate-400">Target RFQ: {rfqId}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg bg-white dark:bg-slate-800 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white border border-slate-200 dark:border-slate-700"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable Audit Log List */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 font-mono text-xs">
          {logs.map((log, idx) => (
            <div
              key={idx}
              className={`p-3.5 rounded-xl border transition-all ${
                log.status === 'WARNING'
                  ? 'bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/40 text-amber-900 dark:text-amber-200'
                  : log.status === 'FAILURE'
                  ? 'bg-red-50 dark:bg-aog-red/10 border-red-200 dark:border-aog-red/40 text-red-900 dark:text-red-200'
                  : 'bg-slate-50 dark:bg-slate-900/80 border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-200 hover:border-slate-300 dark:hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center space-x-2 font-bold">
                  {getAgentIcon(log.agent_name)}
                  <span className="text-slate-900 dark:text-slate-100">
                    {getAgentProfile(log.agent_name).callSign}
                    <span className="ml-1.5 font-normal text-slate-400 dark:text-slate-500 text-[10px]">
                      {getAgentProfile(log.agent_name).role}
                    </span>
                  </span>
                </div>
                {getStatusBadge(log.status)}
              </div>

              <div className="text-[11px] leading-relaxed text-slate-600 dark:text-slate-300 font-sans">
                {log.message}
              </div>

              <div className="mt-2 flex items-center justify-between text-[9px] text-slate-400 dark:text-slate-500 pt-1 border-t border-slate-200/60 dark:border-slate-800/60">
                <span>ACTION: {log.action_type}</span>
                <span>{new Date(log.timestamp).toLocaleTimeString()}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900 text-center font-mono text-[10px] text-slate-500">
          Autonomous Agent Execution Log • Human-in-the-Loop Safe
        </div>
      </div>
    </div>
  );
};
