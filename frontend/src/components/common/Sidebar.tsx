import React from 'react';
import { ViewMode } from '../../types';
import { apiService } from '../../services/api';
import { 
  LayoutDashboard, 
  FileText, 
  Search, 
  ShieldCheck, 
  Package, 
  Truck, 
  TrendingUp, 
  LogOut,
  FlaskConical,
} from 'lucide-react';

interface SidebarProps {
  currentView: ViewMode;
  onSelectView: (view: ViewMode) => void;
  isMobileOpen?: boolean;
  onCloseMobile?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ currentView, onSelectView, isMobileOpen = false, onCloseMobile }) => {
  const navItems = [
    {
      id: 'customer' as ViewMode,
      label: 'Dashboard',
      icon: LayoutDashboard,
      badge: null
    },
    {
      id: 'sourcing' as ViewMode,
      label: 'Sourcing Matrix',
      icon: Search,
      badge: '18'
    },
    {
      id: 'aero-procurement' as ViewMode,
      label: 'Proc Command',
      icon: FileText,
      badge: '14'
    },
    {
      id: 'trace-vault' as ViewMode,
      label: 'Trace Vault',
      icon: ShieldCheck,
      badge: '42'
    },
    {
      id: 'fulfillment' as ViewMode,
      label: 'Fulfillment (FCH)',
      icon: Package,
      badge: null
    },
    {
      id: 'sales' as ViewMode,
      label: 'Sales Command',
      icon: TrendingUp,
      badge: '9'
    },
    {
      id: 'swarm-simulation' as ViewMode,
      label: 'Swarm Runner',
      icon: FlaskConical,
      badge: null
    }
  ];

  return (
    <>
      {isMobileOpen && <button type="button" aria-label="Close navigation menu" className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={onCloseMobile} />}
      <aside className={`${isMobileOpen ? 'translate-x-0' : '-translate-x-full'} fixed inset-y-0 left-0 z-50 w-64 bg-white dark:bg-card-dark border-r border-slate-200 dark:border-slate-800 flex flex-col justify-between select-none transition-transform lg:static lg:z-auto lg:w-56 lg:translate-x-0`}>
      <div className="py-4 px-3">
          <div className="hidden px-2 mb-3 text-[10px] font-mono font-bold tracking-widest text-slate-400 dark:text-slate-500 uppercase md:block">
          Command Hub
        </div>

        <nav className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentView === item.id;

            return (
              <button
                key={item.id}
                onClick={() => { onSelectView(item.id); onCloseMobile?.(); }}
                aria-label={item.label}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-semibold transition-all group ${
                  isActive
                    ? 'bg-aero-blue text-white shadow-md shadow-aero-blue/20 font-bold'
                    : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/60 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                <div className="flex items-center space-x-3">
                  <Icon className={`w-4 h-4 transition-transform group-hover:scale-110 ${
                    isActive ? 'text-white' : 'text-slate-500 dark:text-slate-400'
                  }`} />
                  <span className="hidden truncate md:inline">{item.label}</span>
                </div>

                {item.badge && (
                  <span className={`hidden px-2 py-0.5 text-[10px] font-mono font-bold rounded-full md:inline ${
                    isActive
                      ? 'bg-white/20 text-white'
                      : 'bg-blue-50 text-aero-blue dark:bg-aero-blue/20 dark:text-aero-blue'
                  }`}>
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Secondary section */}
        <div className="hidden mt-8 px-2 mb-2 text-[10px] font-mono font-bold tracking-widest text-slate-400 dark:text-slate-500 uppercase md:block">
          System Utility
        </div>
        <div className="space-y-1">
          <button
            onClick={() => { onSelectView('fulfillment'); onCloseMobile?.(); }}
            aria-label="Open Logistics API"
            className="w-full flex items-center space-x-3 px-3 py-2 text-xs text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800/50 rounded-xl transition-colors"
          >
            <Truck className="w-4 h-4 text-slate-400" />
            <span className="hidden md:inline">Logistics API</span>
          </button>
          <a href="/customer-portal" className="w-full flex items-center space-x-3 px-3 py-2 text-xs text-aero-blue hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800/50 rounded-xl transition-colors">
            <Search className="w-4 h-4" />
            <span className="hidden md:inline">Open Customer Portal</span>
          </a>
        </div>
      </div>

      {/* Footer System Integrity Status */}
      <div className="hidden p-3 border-t border-slate-200 dark:border-slate-800 md:block">
        <div className="bg-slate-50 dark:bg-slate-900/90 rounded-xl p-2.5 border border-slate-200 dark:border-slate-800">
          <div className="flex items-center justify-between text-[11px] font-mono font-semibold mb-1">
            <span className="text-slate-600 dark:text-slate-400">SYSTEM HEALTH</span>
            <span className="text-emerald-600 dark:text-emerald-400">99.9%</span>
          </div>
          <div className="w-full bg-slate-200 dark:bg-slate-800 h-1.5 rounded-full overflow-hidden">
            <div className="bg-emerald-500 h-full w-[99.9%]" />
          </div>
          <div className="mt-2 flex items-center justify-between text-[9px] font-mono text-slate-500">
            <span>FASTAPI MVP</span>
            <span>v1.0.0</span>
          </div>
        </div>

        <button
          onClick={() => {
            void apiService.signOut();
            window.location.href = '/internal';
          }}
          className="mt-2 w-full flex items-center justify-center space-x-2 py-1.5 rounded text-xs text-slate-400 hover:text-aog-red transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" />
          <span>Exit Command Center</span>
        </button>
      </div>
      </aside>
    </>
  );
};
