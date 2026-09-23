import React from 'react';
import { CheckCircle2, Clock, AlertTriangle, ChevronRight } from 'lucide-react';

interface WorkflowStepperProps {
  currentStepIndex?: number;
  onSelectStep?: (index: number) => void;
}

export const WorkflowStepper: React.FC<WorkflowStepperProps> = ({
  currentStepIndex = 4,
  onSelectStep
}) => {
  const steps = [
    { label: '1. Received', status: 'COMPLETE' },
    { label: '2. Parsing', status: 'COMPLETE' },
    { label: '3. Inventory Lookup', status: 'COMPLETE' },
    { label: '4. Sourcing', status: 'COMPLETE' },
    { label: '5. Compliance Check', status: 'IN_PROGRESS' },
    { label: '6. Pricing', status: 'PENDING' },
    { label: '7. Approval (HITL)', status: 'PENDING' },
    { label: '8. Quote Sent', status: 'PENDING' }
  ];

  return (
    <div className="bg-white dark:bg-card-dark border border-slate-200 dark:border-slate-800 rounded-2xl p-3.5 shadow-sm select-none">
      <div className="flex items-center justify-between overflow-x-auto font-mono text-[10px] space-x-1">
        {steps.map((step, idx) => {
          const isComplete = idx < currentStepIndex;
          const isCurrent = idx === currentStepIndex;

          return (
            <React.Fragment key={idx}>
              <button
                type="button"
                onClick={() => onSelectStep?.(idx)}
                disabled={!onSelectStep}
                aria-current={isCurrent ? 'step' : undefined}
                className={`flex items-center space-x-1.5 ${onSelectStep ? 'cursor-pointer' : 'cursor-default'} py-1.5 px-3 rounded-xl transition-all whitespace-nowrap focus:outline-none focus-visible:ring-2 focus-visible:ring-aero-blue ${
                  isCurrent
                    ? 'bg-aero-blue text-white font-bold shadow-md shadow-aero-blue/20 ring-1 ring-aero-blue'
                    : isComplete
                    ? 'text-emerald-600 dark:text-emerald-400 font-semibold hover:bg-slate-100 dark:hover:bg-slate-800'
                    : 'text-slate-400 dark:text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-800/40'
                }`}
              >
                {isComplete ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                ) : isCurrent ? (
                  <Clock className="w-3.5 h-3.5 text-white animate-spin shrink-0" />
                ) : (
                  <span className="w-3.5 h-3.5 rounded-full border border-slate-300 dark:border-slate-600 flex items-center justify-center text-[8px] shrink-0">
                    {idx + 1}
                  </span>
                )}
                <span>{step.label}</span>
              </button>

              {idx < steps.length - 1 && (
                <ChevronRight className="w-3 h-3 text-slate-300 dark:text-slate-700 shrink-0" />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};
