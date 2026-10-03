import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from api.auth import current_user
from api.main import app
from agents.base_agent import AgentResponse
from agents.orchestrator_agent import OrchestratorAgent
from services.llm_tool_orchestrator import (
    AgentTool,
    AgentToolError,
    AgentToolRegistry,
    LLMToolOrchestrator,
    create_default_agent_tool_orchestrator,
    tool,
)


class PartArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: str = Field(min_length=3, max_length=80)


class FakeRouter:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.requests = []

    def extract_structured_with_response(self, request, schema):
        self.requests.append(request)
        return schema.model_validate(self.decisions.pop(0)), SimpleNamespace()


def make_orchestrator(router, handler, *, allowed_roles=frozenset({"ROLE_MANAGER"}), confirmation=False, max_steps=5):
    registry = AgentToolRegistry([
        AgentTool(
            name="lookup_part",
            description="Look up a part.",
            arguments_model=PartArguments,
            handler=handler,
            allowed_roles=allowed_roles,
            required_permissions=frozenset({"read_catalog"}),
            requires_confirmation=confirmation,
        )
    ])
    return LLMToolOrchestrator(router, registry, max_steps=max_steps)


class TestLLMToolOrchestration(unittest.TestCase):
    def test_query_tool_results_and_final_answer_redact_credentials(self):
        secret = "sk-" + "a" * 24
        router = FakeRouter([
            {
                "action": "call_tool",
                "tool_name": "lookup_part",
                "arguments": {"part_number": "PN-123"},
                "answer": None,
            },
            {
                "action": "final",
                "tool_name": None,
                "arguments": {},
                "answer": f"The stored key is {secret}.",
            },
        ])

        def lookup(_arguments):
            return {"api_key": secret, "result": "Bearer " + "b" * 30}

        result = asyncio.run(make_orchestrator(router, lookup).run(
            f"Look up PN-123; my API_KEY={secret}",
            role="ROLE_MANAGER",
            permissions={"read_catalog"},
        ))

        self.assertNotIn(secret, router.requests[0].user_prompt)
        self.assertNotIn(secret, router.requests[1].user_prompt)
        self.assertNotIn(secret, result.answer)
        self.assertEqual(result.steps[0].result["api_key"], "[SECRET REDACTED]")
        self.assertIn("[SECRET REDACTED]", result.steps[0].result["result"])

    def test_tool_decorator_registers_explicit_pydantic_schema_and_permissions(self):
        @tool(
            name="decorated_lookup",
            description="Look up a part using a strict schema.",
            arguments_model=PartArguments,
            allowed_roles=frozenset({"ROLE_MANAGER"}),
            required_permissions=frozenset({"read_catalog"}),
        )
        def handler(arguments):
            return {"part_number": arguments["part_number"]}

        registry = AgentToolRegistry.from_decorated(handler)

        self.assertEqual(registry.get("decorated_lookup").arguments_model, PartArguments)
        self.assertEqual(registry.get("decorated_lookup").required_permissions, {"read_catalog"})
        self.assertEqual(
            registry.descriptions()[0]["arguments"]["properties"]["part_number"]["maxLength"],
            80,
        )

    def test_sql_lookup_uses_allowlisted_entities_and_omits_sensitive_fields(self):
        fake_database = SimpleNamespace(
            get_rfq=lambda rfq_id: SimpleNamespace(
                id=rfq_id,
                status="Intake",
                workflow_state="NEW_RFQ",
                part_number="PN-123",
                customer_email="buyer@example.com",
                raw_text="sensitive source content",
                thread_id="private-thread",
            ),
            get_supplier_offers_for_part=lambda part_number: [{
                "part_number": part_number,
                "supplier_name": "Aero Supply",
                "quantity_available": 3,
                "unit_cost": 120.0,
                "supplier_email": "quotes@example.com",
            }],
        )
        orchestrator = create_default_agent_tool_orchestrator(
            router=FakeRouter([]),
            database=fake_database,
            rag_pipeline=SimpleNamespace(),
        )
        rfq_tool = orchestrator.registry.get("query_rfq")
        offers_tool = orchestrator.registry.get("query_supplier_offers")

        rfq = rfq_tool.handler({"rfq_id": "RFQ-123"})
        offers = offers_tool.handler({"part_number": "PN-123", "limit": 1})

        self.assertEqual(rfq["rfq"]["id"], "RFQ-123")
        self.assertNotIn("customer_email", rfq["rfq"])
        self.assertNotIn("raw_text", rfq["rfq"])
        self.assertNotIn("supplier_email", offers["offers"][0])
        self.assertEqual(offers["offers"][0]["supplier_name"], "Aero Supply")
        with self.assertRaises(ValidationError):
            rfq_tool.arguments_model.model_validate({
                "rfq_id": "RFQ-123",
                "sql": "DROP TABLE rfqs",
            })

    def test_sql_and_rag_tools_are_restricted_to_admin_and_manager_roles(self):
        registry = create_default_agent_tool_orchestrator(
            router=FakeRouter([]),
            rag_pipeline=SimpleNamespace(),
            database=SimpleNamespace(),
        ).registry

        for tool_name, permission in (
            ("query_rfq", "read_business_records"),
            ("query_supplier_offers", "read_business_records"),
            ("search_knowledge", "search_knowledge"),
        ):
            orchestrator = LLMToolOrchestrator(
                FakeRouter([{
                    "action": "call_tool",
                    "tool_name": tool_name,
                    "arguments": (
                        {"rfq_id": "RFQ-123"}
                        if tool_name == "query_rfq"
                        else {"part_number": "PN-123"}
                        if tool_name == "query_supplier_offers"
                        else {"query": "Search private knowledge"}
                    ),
                    "answer": None,
                }]),
                registry,
            )
            with self.assertRaisesRegex(AgentToolError, "not authorized"):
                asyncio.run(orchestrator.run(
                    "Use a restricted data tool.",
                    role="ROLE_SALES",
                    permissions={permission},
                ))

    def test_rag_tool_returns_schema_validated_answer_and_citations_without_raw_chunks(self):
        class FakeRAGPipeline:
            async def query(self, query, *, top_k):
                from schemas.rag import RAGClaim, RAGResponse, RetrievedChunk

                self.query_text = query
                self.top_k = top_k
                return RAGResponse(
                    status="answered",
                    answer="Part PN-123 is documented; contact buyer@example.com.",
                    claims=[RAGClaim(
                        statement="Part PN-123 is documented.",
                        source_ids=["chunk-1"],
                    )],
                    retrieved_chunks=[RetrievedChunk(
                        id="chunk-1",
                        text="Never return this raw excerpt.",
                        metadata={"document_type": "aircraft_parts_catalog"},
                        index=0,
                        score=0.9,
                    )],
                )

        rag = FakeRAGPipeline()
        orchestrator = create_default_agent_tool_orchestrator(
            router=FakeRouter([]),
            rag_pipeline=rag,
            database=SimpleNamespace(),
        )
        result = asyncio.run(orchestrator.registry.get("search_knowledge").handler({
            "query": "Is PN-123 documented?",
        }))

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["citations"], ["chunk-1"])
        self.assertIn("[EMAIL REDACTED]", result["answer"])
        self.assertNotIn("Never return this raw excerpt.", str(result))
        self.assertEqual(rag.top_k, 5)

    def test_model_selects_tool_generates_arguments_and_uses_results_for_next_decision(self):
        router = FakeRouter([
            {
                "action": "call_tool",
                "tool_name": "lookup_part",
                "arguments": {"part_number": "060-1234-00"},
                "answer": None,
            },
            {
                "action": "final",
                "tool_name": None,
                "arguments": {},
                "answer": "The catalog found the requested part.",
            },
        ])
        calls = []

        async def lookup(arguments):
            calls.append(arguments)
            return {"found": True, "part_number": arguments["part_number"]}

        result = asyncio.run(make_orchestrator(router, lookup).run(
            "Check whether part 060-1234-00 is listed.",
            role="ROLE_MANAGER",
            permissions={"read_catalog"},
        ))

        self.assertEqual(result.answer, "The catalog found the requested part.")
        self.assertEqual(calls, [{"part_number": "060-1234-00"}])
        self.assertTrue(result.steps[0].result["found"])
        self.assertIn("060-1234-00", router.requests[1].user_prompt)

    def test_app_response_mode_returns_schema_validated_structured_output(self):
        router = FakeRouter([{
            "action": "call_tool",
            "tool_name": "lookup_part",
            "arguments": {"part_number": "PN-123"},
            "answer": None,
        }, {
            "action": "final",
            "tool_name": None,
            "arguments": {},
            "answer": None,
            "structured_output": {
                "status": "complete",
                "summary": "The part is available.",
                "findings": [{
                    "title": "Catalog",
                    "detail": "The requested part is listed.",
                    "source_tool": "lookup_part",
                    "citations": [],
                }],
                "missing_information": [],
                "next_steps": [],
            },
        }])

        result = asyncio.run(make_orchestrator(
            router,
            lambda arguments: {"found": arguments["part_number"]},
        ).run(
            "Check availability.",
            role="ROLE_MANAGER",
            permissions={"read_catalog"},
            response_mode="app",
        ))

        self.assertIsNone(result.answer)
        self.assertEqual(result.response_mode, "app")
        self.assertEqual(result.structured_output.status, "complete")
        self.assertEqual(result.structured_output.findings[0].source_tool, "lookup_part")
        self.assertIn('"response_mode": "app"', router.requests[1].user_prompt)

    def test_human_response_mode_returns_descriptive_prose(self):
        router = FakeRouter([{
            "action": "final",
            "tool_name": None,
            "arguments": {},
            "answer": "The inventory lookup found three available units. The request can proceed.",
        }])

        result = asyncio.run(make_orchestrator(
            router,
            lambda arguments: {"query": arguments.get("query")},
        ).run(
            "Check availability.",
            role="ROLE_MANAGER",
            permissions={"read_catalog"},
            response_mode="human",
        ))

        self.assertEqual(result.response_mode, "human")
        self.assertIn("three available units", result.answer)
        self.assertIsNone(result.structured_output)

    def test_model_cannot_execute_a_tool_without_role_authorization(self):
        router = FakeRouter([{
            "action": "call_tool",
            "tool_name": "lookup_part",
            "arguments": {"part_number": "PN-123"},
            "answer": None,
        }])
        calls = []

        async def lookup(arguments):
            calls.append(arguments)
            return {}

        with self.assertRaisesRegex(AgentToolError, "not authorized"):
            asyncio.run(make_orchestrator(router, lookup).run(
                "Look up PN-123.",
                role="ROLE_CUSTOMER",
                permissions={"read_catalog"},
            ))
        self.assertFalse(calls)

    def test_invalid_model_arguments_are_not_executed_and_model_can_recover(self):
        router = FakeRouter([
            {
                "action": "call_tool",
                "tool_name": "lookup_part",
                "arguments": {"part_number": "x", "unexpected": "value"},
                "answer": None,
            },
            {
                "action": "call_tool",
                "tool_name": "lookup_part",
                "arguments": {"part_number": "PN-123"},
                "answer": None,
            },
            {
                "action": "final",
                "tool_name": None,
                "arguments": {},
                "answer": "The part lookup completed.",
            },
        ])
        calls = []

        async def lookup(arguments):
            calls.append(arguments)
            return {}

        result = asyncio.run(make_orchestrator(router, lookup).run(
            "Look up a part.",
            role="ROLE_MANAGER",
            permissions={"read_catalog"},
        ))
        self.assertEqual(calls, [{"part_number": "PN-123"}])
        self.assertIn("no tool action was executed", result.steps[0].result["error"])
        self.assertIn("no tool action was executed", router.requests[1].user_prompt)

    def test_sensitive_tool_requires_server_supplied_human_confirmation(self):
        router = FakeRouter([{
            "action": "call_tool",
            "tool_name": "lookup_part",
            "arguments": {"part_number": "PN-123"},
            "answer": None,
        }])
        calls = []

        async def lookup(arguments):
            calls.append(arguments)
            return {}

        with self.assertRaisesRegex(AgentToolError, "Human confirmation"):
            asyncio.run(make_orchestrator(router, lookup, confirmation=True).run(
                "Run the sensitive action.",
                role="ROLE_MANAGER",
                permissions={"read_catalog"},
            ))
        self.assertFalse(calls)

    def test_tool_loop_stops_at_the_configured_step_limit(self):
        router = FakeRouter([
            {"action": "call_tool", "tool_name": "lookup_part", "arguments": {"part_number": "PN-1"}, "answer": None},
            {"action": "call_tool", "tool_name": "lookup_part", "arguments": {"part_number": "PN-2"}, "answer": None},
            {"action": "call_tool", "tool_name": "lookup_part", "arguments": {"part_number": "PN-3"}, "answer": None},
        ])
        calls = []

        async def lookup(arguments):
            calls.append(arguments)
            return {"found": True}

        result = asyncio.run(make_orchestrator(router, lookup, max_steps=2).run(
            "Compare these parts.",
            role="ROLE_MANAGER",
            permissions={"read_catalog"},
        ))

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(result.steps), 2)
        self.assertTrue(result.stopped_at_step_limit)

    def test_orchestrator_agent_requires_authenticated_context_for_tool_requests(self):
        router = FakeRouter([{
            "action": "call_tool",
            "tool_name": "lookup_part",
            "arguments": {"part_number": "PN-123"},
            "answer": None,
        }])
        calls = []

        async def lookup(arguments):
            calls.append(arguments)
            return {"found": True}

        agent = OrchestratorAgent(tool_orchestrator=make_orchestrator(router, lookup))
        response = asyncio.run(agent.execute({"query": "Look up PN-123."}))

        self.assertIsInstance(response, AgentResponse)
        self.assertFalse(response.success)
        self.assertIn("authenticated role", response.error_message or "")
        self.assertFalse(calls)

    def test_orchestrator_agent_preserves_app_json_contract(self):
        router = FakeRouter([{
            "action": "final",
            "tool_name": None,
            "arguments": {},
            "answer": None,
            "structured_output": {
                "status": "complete",
                "summary": "The request is complete.",
                "findings": [],
                "missing_information": [],
                "next_steps": [],
            },
        }])
        agent = OrchestratorAgent(
            tool_orchestrator=make_orchestrator(router, lambda arguments: arguments)
        )

        response = asyncio.run(agent.execute(
            {"query": "Summarize the result.", "response_mode": "app"},
            {"role": "ROLE_MANAGER", "permissions": {"read_catalog"}},
        ))

        self.assertTrue(response.success)
        self.assertEqual(response.data["response_mode"], "app")
        self.assertEqual(response.data["structured_output"]["status"], "complete")
        self.assertNotIn("log_message", response.data)

    def test_orchestrator_agent_preserves_human_prose_contract(self):
        router = FakeRouter([{
            "action": "final",
            "tool_name": None,
            "arguments": {},
            "answer": "The catalog lookup confirms the requested part is listed.",
        }])
        agent = OrchestratorAgent(
            tool_orchestrator=make_orchestrator(router, lambda arguments: arguments)
        )

        response = asyncio.run(agent.execute(
            {"query": "Summarize the result.", "response_mode": "human"},
            {"role": "ROLE_MANAGER", "permissions": {"read_catalog"}},
        ))

        self.assertTrue(response.success)
        self.assertEqual(response.data["response_mode"], "human")
        self.assertIn("requested part is listed", response.data["log_message"])
        self.assertNotIn("structured_output", response.data)


class TestAgentOrchestrationEndpoint(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_MANAGER",
            "email": "manager@wingedtycoons.com",
        }
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_internal_endpoint_passes_authenticated_role_and_server_permissions(self):
        expected = AgentResponse(success=True, data={
            "response_mode": "app",
            "next_step": "COMPLETED",
            "is_complete": True,
            "needs_approval": False,
            "structured_output": {
                "status": "complete",
                "summary": "Inventory checked.",
                "findings": [],
                "missing_information": [],
                "next_steps": [],
            },
            "tool_calls": [],
            "tool_limit_reached": False,
        })
        with patch("api.main.OrchestratorAgent") as agent_class:
            agent_class.return_value.execute = AsyncMock(return_value=expected)
            response = self.client.post(
                "/api/internal/agents/orchestrate",
                json={"query": "Check inventory for part PN-123."},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["structured_output"]["summary"], "Inventory checked.")
        call_args = agent_class.return_value.execute.await_args
        self.assertEqual(call_args.args[0], {
            "query": "Check inventory for part PN-123.",
            "response_mode": "app",
        })
        self.assertEqual(call_args.args[1]["role"], "ROLE_MANAGER")
        self.assertEqual(call_args.args[1]["permissions"], {
            "read_catalog",
            "read_inventory",
            "query_suppliers",
            "calculate_prices",
            "read_business_records",
            "search_knowledge",
        })

    def test_customer_cannot_access_internal_agent_tools(self):
        app.dependency_overrides[current_user] = lambda: {
            "role": "ROLE_CUSTOMER",
            "email": "buyer@example.com",
        }
        with patch("api.main.OrchestratorAgent") as agent_class:
            response = self.client.post(
                "/api/internal/agents/orchestrate",
                json={"query": "Check inventory for part PN-123."},
            )

        self.assertEqual(response.status_code, 403)
        agent_class.assert_not_called()

    def test_endpoint_accepts_human_response_mode(self):
        expected = AgentResponse(success=True, data={
            "response_mode": "human",
            "next_step": "COMPLETED",
            "is_complete": True,
            "needs_approval": False,
            "log_message": "The inventory lookup found three available units.",
            "tool_calls": [],
            "tool_limit_reached": False,
        })
        with patch("api.main.OrchestratorAgent") as agent_class:
            agent_class.return_value.execute = AsyncMock(return_value=expected)
            response = self.client.post(
                "/api/internal/agents/orchestrate",
                json={
                    "query": "Check inventory.",
                    "response_mode": "human",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["response_mode"], "human")
        self.assertIn("three available units", response.json()["data"]["log_message"])
        self.assertEqual(
            agent_class.return_value.execute.await_args.args[0]["response_mode"],
            "human",
        )
