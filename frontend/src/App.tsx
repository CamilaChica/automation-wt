import React, { useState, useEffect } from 'react';
import { ViewMode, ThemeMode, AgentAuditLog, AutomationEvent } from './types';
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
import { SwarmSimulationView } from './components/views/SwarmSimulationView';
import { AuthScreen } from './components/common/AuthScreen';
import { apiService } from './services/api';

const InternalApp: React.FC = () => {
  const [authenticated, setAuthenticated] = useState(apiService.getRole() === 'internal');
  const [currentView, setCurrentView] = useState<ViewMode>('customer');
  const [theme, setTheme] = useState<ThemeMode>('light');
  const [isAuditLogOpen, setIsAuditLogOpen] = useState(false);
  const [auditLogs, setAuditLogs] = useState<AgentAuditLog[]>([]);
  const [auditRfqId, setAuditRfqId] = useState('');
  const [isLiveAuditUnavailable, setIsLiveAuditUnavailable] = useState(false);

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

  useEffect(() => {
    let active = true;
    const loadAuditFeed = async () => {
      const rfqs = await apiService.getRFQs();
      if (!active) return;
      if (rfqs.length === 0) {
        setIsLiveAuditUnavailable(true);
        setAuditLogs(sampleLogs);
        setAuditRfqId('Cached sample data');
        return;
      }
      let events: AutomationEvent[] = [];
      try {
        events = await apiService.getAutomationEvents();
        if (active) setIsLiveAuditUnavailable(events.length === 0);
      } catch {
        if (active) {
          setIsLiveAuditUnavailable(true);
          setAuditLogs(sampleLogs);
          setAuditRfqId('WT-29471');
        }
        return;
      }
      const detail = await apiService.getRFQDetail(rfqs[0].id);
      if (active) {
        setAuditRfqId(rfqs[0].id);
        const eventLogs: AgentAuditLog[] = (events as AutomationEvent[]).map(event => ({
          rfq_id: event.entity_type === 'rfq' ? event.entity_id : rfqs[0].id,
          agent_name: `${event.event_type} automation`,
          action_type: event.status,
          message: event.error || event.result || `Automation event ${event.status.toLowerCase()}. Attempts: ${event.attempts}/${event.max_attempts}.`,
          status: event.status === 'FAILED' ? 'FAILURE' : event.status === 'SUCCEEDED' ? 'SUCCESS' : 'WARNING',
          timestamp: event.execution_time || event.created_at,
        }));
        setAuditLogs([...eventLogs, ...(detail.logs || [])]);
      }
    };

    void loadAuditFeed().catch(() => {
      if (active) {
        setIsLiveAuditUnavailable(true);
        setAuditLogs(sampleLogs);
        setAuditRfqId('WT-29471');
      }
    });
    const refresh = window.setInterval(() => {
      void loadAuditFeed().catch(() => undefined);
    }, 10000);
    return () => {
      active = false;
      window.clearInterval(refresh);
    };
  }, []);

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
      case 'swarm-simulation':
        return <SwarmSimulationView />;
      default:
        return <CustomerDashboard />;
    }
  };

  if (!authenticated) {
    return <AuthScreen role="internal" onAuthenticated={() => setAuthenticated(true)} />;
  }

  return (
    <div className={`min-h-screen flex flex-col font-sans transition-colors duration-200 ${
      theme === 'dark' ? 'bg-canvas-dark text-slate-100' : 'bg-canvas-light text-slate-900'
    }`}>
      {/* Global Top App Bar */}
      <TopBar
        currentView={currentView}
        theme={theme}
        onToggleTheme={toggleTheme}
        onSelectView={setCurrentView}
        onSearch={(query) => {
          const normalized = query.trim().toLowerCase();
          if (normalized.includes('supplier') || normalized.includes('part')) setCurrentView('sourcing');
          else if (normalized.includes('quote') || normalized.includes('sales')) setCurrentView('sales');
          else if (normalized.includes('trace') || normalized.includes('compliance')) setCurrentView('trace-vault');
          else if (normalized.includes('shipment') || normalized.includes('fulfillment')) setCurrentView('fulfillment');
        }}
        onOpenAuditLog={() => setIsAuditLogOpen(true)}
      />

      {/* Main Content Layout (Sidebar + Active View) */}
      <div className="flex-1 flex overflow-hidden">
        <Sidebar
          currentView={currentView}
          onSelectView={setCurrentView}
        />

        <main className="flex-1 overflow-y-auto bg-slate-50 dark:bg-slate-950/60">
          {renderActiveView()}
        </main>
      </div>

      {/* Slide-over Agent Audit Log Drawer */}
      <AuditLogDrawer
        isOpen={isAuditLogOpen}
        onClose={() => setIsAuditLogOpen(false)}
        logs={auditLogs.length ? auditLogs : sampleLogs}
        rfqId={auditRfqId || 'Live operations'}
        isLiveAuditUnavailable={isLiveAuditUnavailable}
      />
    </div>
  );
};

const CustomerPortalRoute: React.FC = () => {
  const [authenticated, setAuthenticated] = useState(apiService.getRole() === 'customer');
  return authenticated ? <CustomerPortal /> : <AuthScreen role="customer" onAuthenticated={() => setAuthenticated(true)} />;
};

export const App: React.FC = () => {
  const isCustomerPath =
    window.location.pathname.startsWith('/customer-portal') ||
    window.location.pathname.startsWith('/portal');
  const isInternalPath = window.location.pathname.startsWith('/internal');
  const isCustomerSession = apiService.getRole() === 'customer';
  const isInternalSession = apiService.getRole() === 'internal';
  if (isInternalPath || isInternalSession) return <InternalApp />;
  if (isCustomerPath || isCustomerSession || window.location.pathname === '/') return <CustomerPortalRoute />;
  return <CustomerPortalRoute />;
};

export default App;
