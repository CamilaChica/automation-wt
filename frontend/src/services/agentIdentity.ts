export interface AgentIdentity {
  name: string;
  role: string;
}

const identities: Record<string, AgentIdentity> = {
  RFQIntakeAgent: { name: 'Milo', role: 'RFQ Intake' },
  PartsIntelligenceAgent: { name: 'Nova', role: 'Parts Intelligence' },
  InventoryAgent: { name: 'Orin', role: 'Inventory Operations' },
  ComplianceAgent: { name: 'Luna', role: 'Compliance' },
  PricingAgent: { name: 'Kael', role: 'Pricing' },
  DynamicPricingAgent: { name: 'Kael', role: 'Pricing' },
  CustomerCommunicationAgent: { name: 'Aria', role: 'Customer Communication' },
  OrchestratorAgent: { name: 'Rhea', role: 'Workflow Orchestration' },
  SupplierDiscoveryAgent: { name: 'Zane', role: 'Supplier Discovery' },
  QuoteGenerationAgent: { name: 'Kael', role: 'Quote Generation' },
};

export function getAgentIdentity(agentId: string): AgentIdentity {
  return identities[agentId] ?? { name: 'Rhea', role: agentId.replace(/Agent$/, '').replace(/([a-z])([A-Z])/g, '$1 $2') || 'Operations' };
}
