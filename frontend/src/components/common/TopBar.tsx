import React, { useState, useEffect } from 'react';
import { ViewMode, ThemeMode } from '../../types';
import { Search, Sun, Moon, Bell, ShieldCheck, UserCheck, AlertTriangle, Bot, Menu } from 'lucide-react';
import { BrandMark } from './BrandMark';

interface TopBarProps {
  currentView: ViewMode;
  theme: ThemeMode;
  onToggleTheme: () => void;
  onSelectView: (view: ViewMode) => void;
  onSearch?: (query: string) => void;
  onOpenAuditLog?: () => void;
  onOpenSidebar?: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  currentView,
  theme,
  onToggleTheme,
  onSelectView,
  onSearch,
  onOpenAuditLog,
  onOpenSidebar,
}) => {
  const [timeString, setTimeString] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeString(now.toLocaleTimeString('en-US', { hour12: true, timeZoneName: 'short' }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const getViewTitle = () => {
    switch (currentView) {
      case 'customer':
        return 'CUSTOMER DASHBOARD | GLOBAL AIRLINES (MRO OPS)';
      case 'sourcing':
        return 'WINGED TYCOONS | PROC COMMAND CENTER | SUPPLIER & PART SOURCING';
      case 'aero-procurement':
        return 'WINGED TYCOONS | AERO-PROCUREMENT COMMAND CENTER';
      case 'trace-vault':
        return 'WINGED TYCOONS | PROC COMMAND CENTER | TRACE VAULT & COMPLIANCE';
      case 'fulfillment':
        return 'CORE UI MODULES & VISUAL ANATOMY | FULFILLMENT COMMAND HUB (FCH)';
      case 'sales':
        return 'WINGED TYCOONS | SALES COMMAND CENTER | GLOBAL FLEET SOLUTIONS';
      default:
        return 'WINGED TYCOONS | COMMAND CENTER';
    }
  };

  const getOperatorName = () => {
    switch (currentView) {
      case 'customer': return 'ALEX R. (MRO OPS)';
      case 'sourcing': return 'ELIZA C. (PROC OPERATIONS)';
      case 'trace-vault': return 'MARIA G. (QUALITY OPERATIONS)';
      case 'fulfillment': return 'MARCUS D. (OPS LEAD)';
      default: return 'ALEX R. (MRO SALES)';
    }
  };

  return (
    <header className="min-h-14 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-card-dark px-2 md:px-4 py-2 flex items-center justify-between gap-2 text-xs font-sans select-none transition-colors overflow-hidden">
      {/* Brand & Page Title */}
      <div className="flex min-w-0 items-center space-x-2 md:space-x-3">
        <button type="button" aria-label="Open navigation menu" onClick={onOpenSidebar} className="min-h-11 min-w-11 rounded-xl border border-slate-200 bg-slate-100 p-2 dark:border-slate-700 dark:bg-slate-800 lg:hidden">
          <Menu className="mx-auto h-5 w-5" aria-hidden="true" />
        </button>
        <a
          href="/"
          aria-label="Winged Tycoons Executive Dashboard"
          className="flex items-center space-x-2 bg-slate-100 dark:bg-slate-900 px-2.5 py-1 rounded-lg border border-slate-200 dark:border-slate-700/80 hover:border-aero-blue transition-colors"
        >
          <BrandMark compact />
          <span className="hidden font-display font-bold text-sm tracking-wider text-slate-900 dark:text-slate-100 sm:inline">
            WINGED TYCOONS
          </span>
        </a>
        <div className="h-4 w-px bg-slate-300 dark:bg-slate-700" />
        <span className="hidden sm:inline font-display font-semibold text-slate-700 dark:text-slate-300 tracking-wide uppercase truncate max-w-xl">
          {getViewTitle()}
        </span>
      </div>

      {/* Center Search & AOG Badge */}
      <div className="hidden lg:flex items-center space-x-4">
        {/* AOG Priority Badge */}
        <div className="flex items-center space-x-2 bg-red-50 dark:bg-aog-red/10 border border-red-200 dark:border-aog-red/40 text-aog-red px-3 py-1 rounded-full font-mono text-[11px] font-semibold aog-pulse-badge">
          <AlertTriangle className="w-3.5 h-3.5 animate-bounce" />
          <span>AOG ALERTS: 3 ACTIVE</span>
        </div>

        {/* Global Omnibar */}
        <div className="relative w-72">
          <Search className="w-3.5 h-3.5 absolute left-3 top-2.5 text-slate-400" />
          <input
            type="text"
            aria-label="Global Search"
            name="search"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              onSearch?.(e.target.value);
            }}
            placeholder="Search P/N, NSN, S/N, CAGE... [Cmd + K]"
            className="w-full bg-slate-100 dark:bg-slate-900/80 border border-slate-200 dark:border-slate-700 rounded-xl pl-9 pr-3 py-1.5 text-slate-900 dark:text-slate-200 placeholder-slate-400 focus:ring-2 focus:ring-aero-blue focus:outline-none transition-colors font-mono text-[11px]"
          />
        </div>
      </div>

      {/* Right Controls: Telemetry, Theme, Notifications & User */}
      <div className="ml-auto flex shrink-0 items-center space-x-1.5 md:space-x-4">
        {/* Sub-header status tags */}
        <div className="hidden lg:flex items-center space-x-3 text-[11px] font-mono text-slate-600 dark:text-slate-400">
          <span className="flex items-center space-x-1 text-emerald-600 dark:text-emerald-400 font-semibold">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>SPEED. TRACEABILITY. RELIABILITY.</span>
          </span>
          <span className="text-slate-300 dark:text-slate-600">|</span>
          <span className="font-semibold text-slate-800 dark:text-slate-200">{timeString}</span>
        </div>

        {/* Agent Audit Log Drawer Trigger */}
        <button
          onClick={onOpenAuditLog}
          aria-label="Open agent logs"
          className="p-2 md:px-3 md:py-1.5 rounded-xl border border-blue-200 dark:border-aero-blue/40 bg-blue-50 dark:bg-aero-blue/10 text-aero-blue hover:bg-aero-blue hover:text-white font-mono text-[10px] font-bold flex items-center space-x-1.5 transition-all shadow-sm"
        >
          <Bot className="w-3.5 h-3.5" />
          <span className="hidden md:inline">AGENT LOGS</span>
        </button>

        {/* Theme Toggle Switch */}
        <button
          onClick={onToggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
          className="p-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800/80 text-slate-700 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white hover:border-aero-blue transition-all"
        >
          {theme === 'dark' ? (
            <Sun className="w-4 h-4 text-amber-400" />
          ) : (
            <Moon className="w-4 h-4 text-indigo-600" />
          )}
        </button>

        {/* Notification Bell */}
        <div className="relative">
          <button
            onClick={onOpenAuditLog}
            aria-label="Open operational notifications"
            className="p-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800/80 text-slate-700 dark:text-slate-300 hover:text-slate-900 hover:border-aero-blue transition-all"
          >
            <Bell className="w-4 h-4" />
          </button>
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-aero-blue text-white font-mono text-[9px] font-bold rounded-full flex items-center justify-center shadow">
            4
          </span>
        </div>

        {/* Operator Profile Context */}
        <div className="hidden sm:flex items-center space-x-2 bg-slate-100 dark:bg-slate-800/90 border border-slate-200 dark:border-slate-700 px-2.5 py-1 rounded-xl">
          <div className="w-6 h-6 rounded-full bg-blue-100 dark:bg-slate-700 flex items-center justify-center text-aero-blue font-bold font-mono">
            <UserCheck className="w-3.5 h-3.5" />
          </div>
          <div className="flex flex-col text-[11px] leading-tight">
            <span className="font-semibold text-slate-900 dark:text-slate-100">{getOperatorName()}</span>
            <span className="text-[9px] font-mono text-emerald-600 dark:text-emerald-400 flex items-center space-x-1 font-bold">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
              <span>ONLINE</span>
            </span>
          </div>
        </div>
      </div>
    </header>
  );
};
