import json
import os
import re
import statistics
import sys
import time
from email import policy
from email.parser import BytesParser
from unittest.mock import patch

import pytest

from schemas.extraction import ExtractedField
from services.document_parser import extract_attachment_text
from services.email_intelligence import (
    EmailIntelligenceExtraction,
    ExtractedEmailItem,
    extract_email_intelligence,
    is_valid_extracted_part_number,
)
from services.llm_provider import LLMProvider, LLMRequest, LLMResponse, LLMRouter
from services.supplier_ingestion_service import SupplierEmailIngestionService


SAMPLE_EMAILS = {
    "clean_rfq.eml": """From: Buyer One <buyer@example.test>
To: sales@example.test
Subject: Request for quotation
Message-ID: <clean-rfq@example.test>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Hello,
Company: Example Maintenance
Part Number: 060-1234-00
Quantity: 2 EA
Condition: NE
Please quote this request.
""",
    "missing_certificate_quote.eml": """From: Supplier One <quotes@example.test>
To: purchasing@example.test
Subject: Quote for requested part
Message-ID: <missing-cert@example.test>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Part Number: 060-1234-00
Quantity: 2 EA
Condition: NE
Unit price: $125 USD
Lead time: 5 days
""",
    "non_usd_quote.eml": """From: Supplier Two <quotes@euro-example.test>
To: purchasing@example.test
Subject: Quotation in EUR
Message-ID: <non-usd@example.test>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Part Number: 060-1234-00
Quantity: 2 EA
Condition: NE
Unit price: EUR 115.00
Currency: EUR
Lead time: 7 days
FAA 8130-3 certificate included.
""",
    "quote_reference_and_part.eml": """From: Supplier Three <quotes@parts-example.test>
To: purchasing@example.test
Subject: Quotation QTE-70042
Message-ID: <reference-vs-part@example.test>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Quote reference: QTE-70042
Part Number: 822-1287-121
Quantity: 1 EA
Condition: NE
Unit price: $410 USD
Lead time: 3 days
EASA Form 1 certificate included.
""",
}


class FixtureProvider(LLMProvider):
    name = "openai"

    def __init__(self, outputs):
        self.outputs = list(outputs)

    def complete(self, request: LLMRequest) -> LLMResponse:
        output = self.outputs.pop(0)
        return LLMResponse(
            provider=self.name,
            model=request.model or "gpt-4o-mini",
            text=json.dumps(output),
            raw={"usage": {"prompt_tokens": 110, "completion_tokens": 35}},
        )


def _body(filename: str) -> str:
    message = BytesParser(policy=policy.default).parsebytes(SAMPLE_EMAILS[filename].encode("utf-8"))
    return message.get_body(preferencelist=("plain",)).get_content()


def _field(value: str | None, snippet: str | None) -> dict:
    return {"value": value, "source_snippet": snippet}


def _extraction_payload(source: str, *, confidence: float = 0.97, cert: str | None = None, currency: str = "USD", part_number: str = "060-1234-00", part_snippet: str | None = None) -> dict:
    def find(pattern: str, group: int = 0) -> str | None:
        match = re.search(pattern, source, re.IGNORECASE)
        return match.group(group) if match else None

    quantity_snippet = find(r"Quantity:\s*\d+\s*EA")
    condition_snippet = find(r"Condition:\s*[A-Z]+")
    price_snippet = find(r"Unit price:\s*(?:EUR\s*)?\$?[0-9.,]+\s*(?:USD|EUR)?")
    currency_snippet = find(r"(?:Currency:\s*(?:USD|EUR)|Unit price:\s*(?:EUR\s*)?\$?[0-9.,]+\s*(?:USD|EUR)?)")
    lead_snippet = find(r"Lead time:\s*\d+\s*days")
    certificate = cert or find(r"(?:FAA 8130-3|EASA Form 1) certificate included\.")
    item = {
        "part_number": _field(part_number, part_snippet or find(r"Part Number:\s*[A-Z0-9-]+")),
        "quantity": _field(find(r"Quantity:\s*(\d+)\s*EA", 1), quantity_snippet),
        "condition_code": _field(find(r"Condition:\s*([A-Z]+)", 1), condition_snippet),
        "target_price": _field(find(r"Unit price:\s*(?:EUR\s*)?\$?([0-9.]+)", 1), price_snippet),
        "lead_time_days": _field(find(r"Lead time:\s*(\d+\s*days)", 1), lead_snippet),
        "unit_of_measure": _field("EA" if quantity_snippet else None, quantity_snippet),
        "currency": _field(currency if currency_snippet else None, currency_snippet),
        "missing_fields": [],
        "needs_escalation": False,
        "escalation_reason": None,
        "resolution_hypotheses": [],
        "description": "Aircraft component",
        "availability_location": None,
        "warranty_terms": None,
        "trace_documents": [certificate] if certificate else [],
    }
    return {
        "email_type": "supplier_quote",
        "customer_name": None,
        "customer_company": None,
        "customer_email": None,
        "supplier_name": "Example Supplier",
        "supplier_email": None,
        "items": [item],
        "missing_fields": [],
        "confidence_score": confidence,
    }


def _router(*outputs):
    provider = FixtureProvider(outputs)
    return LLMRouter({"openai": provider}), provider


def _pdf_bytes(lines: list[str]) -> bytes:
    escaped_lines = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    commands = ["BT", "/F1 11 Tf", "40 760 Td"]
    for index, line in enumerate(escaped_lines):
        if index:
            commands.append("0 -16 Td")
        commands.append(f"({line}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode())
    return bytes(pdf)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]


def _calibrate_threshold(samples: list[tuple[float, bool, bool]]) -> float:
    candidates = sorted({score for score, _is_correct, _unsafe in samples})
    eligible = [
        threshold for threshold in candidates
        if not any(score >= threshold and unsafe for score, _correct, unsafe in samples)
    ]
    if not eligible:
        return 1.0
    return min(eligible)


def test_fixture_pdf_is_readable_and_missing_certificate_stays_abstained(monkeypatch):
    monkeypatch.setenv("LLM_LIVE_ENABLED", "true")
    source = _body("missing_certificate_quote.eml")
    pdf = _pdf_bytes([
        "Part Number: 060-1234-00",
        "Quantity: 2 EA",
        "Condition: NE",
        "Unit price: $125 USD",
        "Lead time: 5 days",
    ])
    extracted_pdf = extract_attachment_text("quote.pdf", "application/pdf", pdf)
    assert "Part Number: 060-1234-00" in extracted_pdf

    attachments = [{"filename": "quote.pdf", "content_type": "application/pdf", "content": pdf}]
    combined = source + "\n\nAttachment quote.pdf:\n" + extracted_pdf
    payload = _extraction_payload(combined)
    router, _provider = _router(payload, payload)
    with patch("services.email_intelligence.operations_store.enqueue_operator_review", return_value="REV-CALIBRATION") as enqueue:
        result = extract_email_intelligence(
            source,
            task="supplier_quote_extraction",
            router=router,
            attachments=attachments,
        )

    assert result.pending_human_review is True
    assert "trace_documents" in result.missing_fields
    enqueue.assert_called_once()
    assert "Part Number: 060-1234-00" in enqueue.call_args.kwargs["source_text"]


def test_unreadable_pdf_and_quote_reference_are_not_treated_as_evidence(monkeypatch):
    monkeypatch.setenv("LLM_LIVE_ENABLED", "true")
    source = _body("quote_reference_and_part.eml")
    unreadable_pdf = {"filename": "unreadable.pdf", "content_type": "application/pdf", "content": b"%PDF-broken"}
    payload = _extraction_payload(source, part_number="QTE-70042", part_snippet="Quote reference: QTE-70042")
    safe_payload = _extraction_payload(source, part_number="822-1287-121")
    router, _provider = _router(payload, safe_payload)
    with patch("services.email_intelligence.operations_store.enqueue_operator_review", return_value="REV-REFERENCE"):
        result = extract_email_intelligence(
            source,
            task="supplier_quote_extraction",
            router=router,
            attachments=[unreadable_pdf],
        )

    assert result.items[0].part_number.value == "822-1287-121"
    assert is_valid_extracted_part_number("QTE-70042") is False
    assert result.pending_human_review is True


def test_non_usd_quotes_are_written_to_operator_queue(monkeypatch):
    monkeypatch.setenv("LLM_LIVE_ENABLED", "true")
    source = _body("non_usd_quote.eml")
    payload = _extraction_payload(source, currency="EUR")
    extraction = EmailIntelligenceExtraction.model_validate(payload)
    extraction._telemetry = {"pending_human_review": False, "model_calls": ["gpt-4o-mini"]}
    service = SupplierEmailIngestionService()
    with (
        patch("services.supplier_ingestion_service.extract_email_intelligence", return_value=extraction),
        patch("services.supplier_ingestion_service.supplier_db.save_email"),
        patch("services.supplier_ingestion_service.supplier_db.save_supplier_offer") as save_offer,
        patch("services.supplier_ingestion_service.operations_store.enqueue_operator_review", return_value="REV-EUR") as enqueue,
    ):
        result = service.ingest_email(source, message_id="calibration-non-usd")

    assert result["status"] == "Pending_Human_Review"
    assert result["unsupported_currencies"] == ["EUR"]
    save_offer.assert_not_called()
    enqueue.assert_called_once()
    assert "non-USD currency: EUR" in enqueue.call_args.kwargs["hold_flags"]


def test_calibration_metrics_and_threshold_report(monkeypatch):
    monkeypatch.setenv("LLM_LIVE_ENABLED", "true")
    samples = [
        ("clean_rfq.eml", 0.97, True, False),
        ("missing_certificate_quote.eml", 0.89, True, True),
        ("non_usd_quote.eml", 0.96, True, True),
        ("quote_reference_and_part.eml", 0.94, True, False),
    ]
    latencies: list[float] = []
    costs: list[float] = []
    model_call_counts: list[int] = []
    input_token_counts: list[int] = []
    output_token_counts: list[int] = []
    routing_by_case: dict[str, dict] = {}
    correct = 0
    auto_processed = 0
    abstention_true_positive = 0
    abstention_false_positive = 0
    predicted_abstentions = 0
    calibration_rows = []

    for filename, confidence, expected_correct, unsafe in samples:
        body = _body(filename)
        task = "rfq_extraction" if filename == "clean_rfq.eml" else "supplier_quote_extraction"
        expected_part_number = "822-1287-121" if filename == "quote_reference_and_part.eml" else "060-1234-00"
        output = _extraction_payload(
            body,
            confidence=confidence,
            part_number=expected_part_number,
            currency="EUR" if filename == "non_usd_quote.eml" else "USD",
        )
        router, _provider = _router(output, output) if unsafe else _router(output)
        started = time.perf_counter()
        with patch("services.email_intelligence.operations_store.enqueue_operator_review", return_value="REV-BENCH"):
            result = extract_email_intelligence(body, task=task, router=router)
        latencies.append((time.perf_counter() - started) * 1000)
        costs.append(result.telemetry["estimated_cost_usd"])
        model_call_counts.append(len(result.telemetry["model_calls"]))
        token_usage = result.telemetry["token_usage"]
        input_token_counts.append(token_usage["input_tokens"])
        output_token_counts.append(token_usage["output_tokens"])
        routing_by_case[filename] = {
            "models": result.telemetry["model_calls"],
            "review_reason": result.telemetry["escalation_reason"],
            "missing_fields": result.missing_fields,
        }
        expected_part = "060-1234-00" if filename != "quote_reference_and_part.eml" else "822-1287-121"
        case_correct = bool(result.items and result.items[0].part_number.value == expected_part)
        correct += int(case_correct == expected_correct)
        held = result.pending_human_review
        if filename == "non_usd_quote.eml":
            service = SupplierEmailIngestionService()
            with (
                patch("services.supplier_ingestion_service.extract_email_intelligence", return_value=result),
                patch("services.supplier_ingestion_service.supplier_db.save_email"),
                patch("services.supplier_ingestion_service.supplier_db.save_supplier_offer") as save_offer,
                patch("services.supplier_ingestion_service.operations_store.enqueue_operator_review", return_value="REV-BENCH") as enqueue,
                patch("services.supplier_ingestion_service.operations_store.add_operator_review_flags", return_value=True) as augment,
            ):
                ingestion_result = service.ingest_email(body, message_id=f"benchmark-{filename}")
            held = ingestion_result["status"] == "Pending_Human_Review"
            assert ingestion_result["unsupported_currencies"] == ["EUR"]
            save_offer.assert_not_called()
            assert enqueue.called or augment.called
        predicted_abstentions += int(held)
        abstention_true_positive += int(held and unsafe)
        abstention_false_positive += int(held and not unsafe)
        calibration_rows.append((confidence, case_correct, unsafe))

    threshold = _calibrate_threshold(calibration_rows)
    for confidence, _case_correct, unsafe in calibration_rows:
        auto_processed += int(confidence >= threshold and not unsafe)
    extraction_accuracy = correct / len(samples)
    abstention_precision = abstention_true_positive / max(predicted_abstentions, 1)
    latency_p95_ms = _p95(latencies)
    mean_cost = statistics.mean(costs)
    report = {
        "fixture_count": len(samples),
        "extraction_accuracy": extraction_accuracy,
        "abstention_precision": abstention_precision,
        "latency_p95_ms": round(latency_p95_ms, 3),
        "token_cost_per_ingestion_usd": round(mean_cost, 8),
        "mean_model_calls_per_ingestion": round(statistics.mean(model_call_counts), 2),
        "input_tokens_total": sum(input_token_counts),
        "output_tokens_total": sum(output_token_counts),
        "routing_by_case": routing_by_case,
        "calibrated_min_confidence": threshold,
        "auto_processed_safe_samples": auto_processed,
        "unsafe_samples_held": abstention_true_positive,
        "false_abstentions": abstention_false_positive,
        "provider_mode": "deterministic_fixture_provider",
    }
    print(json.dumps(report, sort_keys=True))

    assert extraction_accuracy == 1.0
    assert abstention_precision == 1.0
    assert abstention_false_positive == 0
    assert latency_p95_ms >= 0
    assert mean_cost > 0
    assert threshold == 0.97
    assert auto_processed == 1


def test_live_telemetry_calibration(request, monkeypatch):
    if not request.config.getoption("--live-telemetry", default=False):
        pytest.skip("Pass --live-telemetry to run the optional live endpoint check.")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured; live telemetry check was not run.")

    monkeypatch.setenv("LLM_LIVE_ENABLED", "true")
    samples = [
        ("clean_rfq.eml", "rfq_extraction", "060-1234-00", False),
        ("missing_certificate_quote.eml", "supplier_quote_extraction", "060-1234-00", True),
        ("non_usd_quote.eml", "supplier_quote_extraction", "060-1234-00", True),
        ("quote_reference_and_part.eml", "supplier_quote_extraction", "822-1287-121", False),
    ]
    latencies: list[float] = []
    costs: list[float] = []
    input_tokens = 0
    output_tokens = 0
    correct = 0
    abstention_true_positive = 0
    abstention_false_positive = 0
    routing = {}
    threshold_rows = []

    for index, (filename, task, expected_part, unsafe) in enumerate(samples):
        source = _body(filename)
        attachments = (
            [{"filename": "unreadable.pdf", "content_type": "application/pdf", "content": b"%PDF-broken"}]
            if filename == "missing_certificate_quote.eml" else None
        )
        started = time.perf_counter()
        result = extract_email_intelligence(source, task=task, attachments=attachments)
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)
        costs.append(result.telemetry["estimated_cost_usd"])
        input_tokens += result.telemetry["token_usage"]["input_tokens"]
        output_tokens += result.telemetry["token_usage"]["output_tokens"]
        case_correct = bool(result.items and result.items[0].part_number.value == expected_part)
        correct += int(case_correct)
        held = result.pending_human_review
        if filename == "non_usd_quote.eml":
            held = held and result.escalation_reason == "non_usd_currency"
            assert "gpt-4o" not in result.telemetry["model_calls"], "Non-USD holds must remain deterministic."
        abstention_true_positive += int(held and unsafe)
        abstention_false_positive += int(held and not unsafe)
        routing[filename] = {
            "models": result.telemetry["model_calls"],
            "latency_ms": round(latency, 3),
            "estimated_cost_usd": result.telemetry["estimated_cost_usd"],
            "token_usage": result.telemetry["token_usage"],
            "review_reason": result.telemetry["escalation_reason"],
        }
        threshold_rows.append((result.confidence_score, case_correct, unsafe))

    predicted_abstentions = abstention_true_positive + abstention_false_positive
    report = {
        "provider_mode": "live_openai",
        "fixture_count": len(samples),
        "extraction_accuracy": correct / len(samples),
        "abstention_precision": abstention_true_positive / max(predicted_abstentions, 1),
        "latency_p95_ms": round(_p95(latencies), 3),
        "input_tokens_total": input_tokens,
        "output_tokens_total": output_tokens,
        "token_cost_per_ingestion_usd": round(statistics.mean(costs), 8),
        "calibrated_min_confidence": _calibrate_threshold(threshold_rows),
        "false_abstentions": abstention_false_positive,
        "routing_by_case": routing,
    }
    print(json.dumps(report, sort_keys=True))
    assert all("gpt-4o-mini" in result["models"] for result in routing.values())
    assert routing["non_usd_quote.eml"]["models"] == ["gpt-4o-mini"]


def pytest_addoption(parser):
    parser.addoption(
        "--live-telemetry",
        action="store_true",
        default=False,
        help="Run the extraction calibration cases against live OpenAI endpoints.",
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, *sys.argv[1:]], plugins=[sys.modules[__name__]]))
