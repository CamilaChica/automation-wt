import React, { useState, useEffect } from 'react';
import { ViewMode, ThemeMode, AgentAuditLog, UserRole, ROLE_ALLOWED_VIEWS } from './types';
import { TopBar } from './components/common/TopBar';
import { Sidebar } from './components/common/Sidebar';
import { AuditLogDrawer } from './components/common/AuditLogDrawer';
import { CustomerDashboard } from './components/views/CustomerDashboard';
import { SupplierSourcingView } from './components/views/SupplierSourcingView';
import { AeroProcurementView } from './components/views/AeroProcurementView';
import { TraceVaultView } from './components/views/TraceVaultView';
import { FulfillmentHubView } from './components/views/FulfillmentHubView';
import { SalesCommandView } from './components/views/SalesCommandView';
import { AdminView } from './components/views/AdminView';

export const App: React.FC = () => {
  const [userRole, setUserRole] = useState<UserRole>('admin');
  const [currentView, setCurrentView] = useState<ViewMode>('customer');
  const [theme, setTheme] = useState<ThemeMode>('light');
  const [isAuditLogOpen, setIsAuditLogOpen] = useState(false);

  // Keep the active view valid whenever the signed-in role changes so a
  // user can never land on (or stay on) an interface outside their role.
  useEffect(() => {
    const allowed = ROLE_ALLOWED_VIEWS[userRole];
    if (!allowed.includes(currentView)) {
      setCurrentView(allowed[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userRole]);

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

  const renderActiveView = () => {
    switch (currentView) {
      case 'customer':
        return <CustomerDashboard />;
      case 'sourcing':
        return <SupplierSourcingView />;
      case 'aero-procurement':
        return <AeroProcurementView />;
      case 'trace-vault':
        return <TraceVaultView />;
      case 'fulfillment':
        return <FulfillmentHubView />;
      case 'sales':
        return <SalesCommandView />;
      case 'admin':
        return <AdminView />;
      default:
        return <CustomerDashboard />;
    }
  };

  return (
    <div className={`brand-shell min-h-screen flex flex-col font-sans transition-colors duration-200 ${
      theme === 'dark' ? 'bg-canvas-dark text-slate-100' : 'bg-canvas-light text-slate-900'
    }`}>
      {/* Global Top App Bar */}
      <TopBar
        currentView={currentView}
        theme={theme}
        onToggleTheme={toggleTheme}
        onSelectView={setCurrentView}
        onOpenAuditLog={() => setIsAuditLogOpen(true)}
        userRole={userRole}
        onChangeRole={setUserRole}
      />

      {/* Main Content Layout (Sidebar + Active View) */}
      <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
        <Sidebar
          currentView={currentView}
          onSelectView={setCurrentView}
          userRole={userRole}
        />

        <main className="flex-1 min-w-0 overflow-y-auto bg-transparent">
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

export default App;
