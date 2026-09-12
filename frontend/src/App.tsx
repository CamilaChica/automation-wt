import React, { useState, useEffect } from 'react';
import { ViewMode, ThemeMode, AgentAuditLog } from './types';
import { TopBar } from './components/common/TopBar';
import { Sidebar } from './components/common/Sidebar';
import { AuditLogDrawer } from './components/common/AuditLogDrawer';
import { CustomerDashboard } from './components/views/CustomerDashboard';
import { SupplierSourcingView } from './components/views/SupplierSourcingView';
import { AeroProcurementView } from './components/views/AeroProcurementView';
import { TraceVaultView } from './components/views/TraceVaultView';
import { FulfillmentHubView } from './components/views/FulfillmentHubView';
import { SalesCommandView } from './components/views/SalesCommandView';
import { CustomerPortal } from './components/views/CustomerPortal';
import { AuthScreen } from './components/common/AuthScreen';
import { apiService } from './services/api';
import { AppRole, canAccessView, canUsePermission, getAvailableViews, getDefaultInternalView } from './auth/permissions';

const InternalApp: React.FC = () => {
  const [role, setRole] = useState<AppRole | null>(apiService.getStoredRole());
  const [authenticated, setAuthenticated] = useState(apiService.getRole() === 'internal');
  const [currentView, setCurrentView] = useState<ViewMode>(getDefaultInternalView(role));
  const [theme, setTheme] = useState<ThemeMode>('light');
  const [isAuditLogOpen, setIsAuditLogOpen] = useState(false);
  const availableViews = getAvailableViews(role);

  useEffect(() => {
    if (!canAccessView(role, currentView)) {
      setCurrentView(getDefaultInternalView(role));
    }
  }, [currentView, role]);

  const sampleLogs: AgentAuditLog[] = [
    {
      rfq_id: 'WT-29471',
      agent_name: 'RFQIntakeAgent',
      action_type: 'parse_unstructured_text',
      message: 'Extracted Customer: GLOBAL AIRLINES, P/N: 32-11-45-01, Qty: 1, Urgency: AOG (SLA 4h target).',
      status: 'SUCCESS',
      timestamp: new Date(Date.now() - 3600000).toISOString()
    },
    {
      rfq_id: 'WT-29471',
      agent_name: 'PartsIntelligenceAgent',
      action_type: 'catalog_search',
      message: 'Verified P/N 32-11-45-01 (Main Landing Gear Actuator, ATA Chapter 32). Confidence: 1.0 (Exact Match).',
      status: 'SUCCESS',
      timestamp: new Date(Date.now() - 3300000).toISOString()
    },
    {
      rfq_id: 'WT-29471',
      agent_name: 'InventoryAgent',
      action_type: 'warehouse_atp_check',
      message: 'Stock check: Found 3 units in MIA-BIN-A12. Available-to-Promise (ATP) satisfied.',
      status: 'SUCCESS',
      timestamp: new Date(Date.now() - 3000000).toISOString()
    },
    {
      rfq_id: 'WT-29471',
      agent_name: 'ComplianceAgent',
      action_type: 'trace_audit',
      message: 'FAA 8130-3 release tag verified. Caution: Tag Date verification flag present on SN-MLG-9840.',
      status: 'WARNING',
      timestamp: new Date(Date.now() - 2700000).toISOString()
    },
    {
      rfq_id: 'WT-29471',
      agent_name: 'PricingAgent',
      action_type: 'margin_calculator',
      message: 'Applied 20% target margin + Hot-Shot AOG shipping premium ($250). Final unit price: $14,200.00.',
      status: 'SUCCESS',
      timestamp: new Date(Date.now() - 2400000).toISOString()
    },
    {
      rfq_id: 'WT-29471',
      agent_name: 'CustomerCommunicationAgent',
      action_type: 'outbound_dispatch',
      message: 'Generated draft commercial quotation proposal QTE-29471. Awaiting human operator approval.',
      status: 'SUCCESS',
      timestamp: new Date(Date.now() - 2100000).toISOString()
    }
  ];

  // Sync theme with HTML class
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
      root.classList.remove('light');
    } else {
      root.classList.add('light');
      root.classList.remove('dark');
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'));
  };

  const onSelectView = (view: ViewMode) => {
    if (canAccessView(role, view)) {
      setCurrentView(view);
    }
  };

  if (!authenticated) {
    return <AuthScreen role="internal" onAuthenticated={() => {
      setRole(apiService.getStoredRole());
      setAuthenticated(true);
    }} />;
  }

  const renderActiveView = () => {
    if (!canAccessView(role, currentView)) {
      return (
        <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
          This workspace is restricted for your role. Select another authorized view from the sidebar.
        </div>
      );
    }
    switch (currentView) {
      case 'customer':
        return <CustomerDashboard role={role} />;
      case 'sourcing':
        return <SupplierSourcingView />;
      case 'aero-procurement':
        return <AeroProcurementView />;
      case 'trace-vault':
        return <TraceVaultView />;
      case 'fulfillment':
        return <FulfillmentHubView />;
      case 'sales':
        return (
          <SalesCommandView
            canIssueQuotes={canUsePermission(role, 'quote.issue')}
            canExportQuotes={canUsePermission(role, 'quote.export')}
          />
        );
      default:
        return <CustomerDashboard role={role} />;
    }
  };

  return (
    <div className={`min-h-screen flex flex-col font-sans transition-colors duration-200 ${
      theme === 'dark' ? 'bg-canvas-dark text-slate-100' : 'bg-canvas-light text-slate-900'
    }`}>
      {/* Global Top App Bar */}
      <TopBar
        currentView={currentView}
        role={role}
        theme={theme}
        onToggleTheme={toggleTheme}
        onSelectView={onSelectView}
        onOpenAuditLog={canUsePermission(role, 'audit.logs.view') ? () => setIsAuditLogOpen(true) : undefined}
      />

      {/* Main Content Layout (Sidebar + Active View) */}
      <div className="flex-1 flex overflow-hidden">
        <Sidebar
          role={role}
          availableViews={availableViews}
          currentView={currentView}
          onSelectView={onSelectView}
        />

        <main className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-950/60">
          {renderActiveView()}
        </main>
      </div>

      {/* Slide-over Agent Audit Log Drawer */}
      <AuditLogDrawer
        isOpen={isAuditLogOpen}
        onClose={() => setIsAuditLogOpen(false)}
        logs={sampleLogs}
        rfqId="WT-29471"
      />
    </div>
  );
};

const CustomerPortalRoute: React.FC = () => {
  const [authenticated, setAuthenticated] = useState(apiService.getRole() === 'customer');
  return authenticated ? <CustomerPortal /> : <AuthScreen role="customer" onAuthenticated={() => setAuthenticated(true)} />;
};

export const App: React.FC = () => (
  window.location.pathname === '/customer-portal' || window.location.pathname === '/portal'
    ? <CustomerPortalRoute />
    : <InternalApp />
);

export default App;
