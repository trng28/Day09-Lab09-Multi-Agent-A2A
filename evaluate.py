from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
EXPECTED_CASES = [f"EC_{index:03d}" for index in range(1, 51)]
TRACE_STEPS = ["OrderAgent", "PaymentAgent", "DeliveryAgent", "PolicyAgent", "VerifierAgent"]
WEIGHTS = {
    "primary_issue": Decimal("0.20"),
    "affected_entities": Decimal("0.20"),
    "root_cause_analysis": Decimal("0.15"),
    "evidence_ids": Decimal("0.15"),
    "financial_resolution": Decimal("0.20"),
    "resolution_actions": Decimal("0.10"),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def money(value: Decimal | str | float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def set_f1(actual: list[Any], expected: list[Any]) -> float:
    actual_set, expected_set = set(map(json_key, actual)), set(map(json_key, expected))
    if not actual_set and not expected_set:
        return 1.0
    if not actual_set or not expected_set:
        return 0.0
    overlap = len(actual_set & expected_set)
    precision = overlap / len(actual_set)
    recall = overlap / len(expected_set)
    return 2 * precision * recall / (precision + recall) if overlap else 0.0


def json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


class Oracle:
    """Independent ground-truth generator; does not import workflow agent code."""

    def __init__(self, data_dir: Path) -> None:
        self.orders = {row["order_id"]: row for row in read_csv(data_dir / "olist_orders_dataset.csv")}
        self.items: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.payments: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in read_csv(data_dir / "olist_order_items_dataset.csv"):
            self.items[row["order_id"]].append(row)
        for row in read_csv(data_dir / "olist_order_payments_dataset.csv"):
            self.payments[row["order_id"]].append(row)

    def expected(self, case: dict[str, Any]) -> dict[str, Any]:
        case_id = case["case_id"]
        order_id = case["customer_request"]["claimed_order_id"]
        order = self.orders[order_id]
        items = self.items.get(order_id, [])
        payments = self.payments.get(order_id, [])
        item_total = money(sum(Decimal(row["price"]) for row in items))
        freight_total = money(sum(Decimal(row["freight_value"]) for row in items))
        payment_total = money(sum(Decimal(row["payment_value"]) for row in payments))
        payment_matches = abs(Decimal(str(payment_total)) - Decimal(str(item_total + freight_total))) <= Decimal("0.10")
        delivered = timestamp(order.get("order_delivered_customer_date"))
        estimated = timestamp(order.get("order_estimated_delivery_date"))
        carrier = timestamp(order.get("order_delivered_carrier_date"))
        late = bool(delivered and estimated and delivered > estimated)
        late_sellers = list(dict.fromkeys(
            row["seller_id"] for row in items
            if late and carrier and timestamp(row.get("shipping_limit_date"))
            and carrier > timestamp(row["shipping_limit_date"])
        ))

        status = order["order_status"]
        if status == "canceled" and payment_total > 0:
            issue, cause, parties, refund, action = "canceled_order_paid", "ORDER_CANCELED_AFTER_PAYMENT", [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}], payment_total, "issue_full_refund"
        elif status == "unavailable" and payment_total > 0:
            issue, cause, parties, refund, action = "unavailable_order_paid", "ORDER_UNAVAILABLE_AFTER_PAYMENT", [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}], payment_total, "issue_full_refund"
        elif late and late_sellers:
            issue, cause, parties, refund, action = "late_delivery_seller", "SELLER_HANDOFF_AFTER_LIMIT", [{"party_type": "seller", "party_id": late_sellers[0]}], freight_total, "refund_freight"
        elif late:
            issue, cause, parties, refund, action = "late_delivery_logistics", "CARRIER_DELIVERED_AFTER_ESTIMATE", [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}], freight_total, "refund_freight"
        elif len(payments) >= 2 and payment_matches:
            issue, cause, parties, refund, action = "valid_split_payment", "MULTIPLE_PAYMENTS_RECONCILED", [], 0.0, "explain_valid_split_payment"
        elif delivered and estimated and delivered <= estimated and payment_matches:
            issue, cause, parties, refund, action = "unsupported_late_claim", "DELIVERY_WITHIN_ESTIMATE", [], 0.0, "reject_late_refund"
        else:
            raise ValueError(f"No policy rule matched {order_id}")

        item_ids = [f'{order_id}:{row["order_item_id"]}' for row in items][:5]
        seller_ids = list(dict.fromkeys(row["seller_id"] for row in items))[:5]
        payment_ids = [f'{order_id}:{row["payment_sequential"]}' for row in payments][:5]
        evidence = [f"order:{order_id}"]
        if issue in {"late_delivery_seller", "late_delivery_logistics", "valid_split_payment", "unsupported_late_claim"}:
            evidence += [f"item:{value}" for value in item_ids]
        evidence += [f"payment:{value}" for value in payment_ids]
        if issue == "late_delivery_seller":
            evidence += [f"seller:{value}" for value in seller_ids if value in late_sellers]
        evidence += [f"policy:{cause}"]
        evidence = evidence[:9] + [evidence[-1]] if len(evidence) > 10 else evidence
        return {
            "case_id": case_id,
            "assessment": {"primary_issue": issue, "case_status": "action_required" if refund > 0 else "no_action"},
            "affected_entities": {"order_ids": [order_id], "item_ids": item_ids, "seller_ids": seller_ids, "payment_ids": payment_ids},
            "root_cause_analysis": {"ranked_causes": [{"cause_code": cause, "rank": 1}], "responsible_parties": parties},
            "evidence_ids": evidence,
            "financial_resolution": {"currency": "BRL", "item_total_brl": item_total, "freight_total_brl": freight_total, "payment_total_brl": payment_total, "recommended_refund_brl": money(refund)},
            "resolution_actions": [action],
        }


def hard_gate(actual: Any, expected_case_id: str, valid_evidence: set[str]) -> list[str]:
    errors: list[str] = []
    if not isinstance(actual, dict):
        return ["root must be an object"]
    required = {"case_id", "assessment", "affected_entities", "root_cause_analysis", "evidence_ids", "financial_resolution", "resolution_actions"}
    missing = required - actual.keys()
    if missing:
        return [f"missing fields: {sorted(missing)}"]
    if actual["case_id"] != expected_case_id:
        errors.append("case_id mismatch")
    try:
        confidence = actual["assessment"]["confidence"]
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            errors.append("confidence must be numeric and in [0, 1]")
        entities = actual["affected_entities"]
        for field in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
            if not isinstance(entities[field], list) or len(entities[field]) > 5:
                errors.append(f"invalid {field}")
        if not isinstance(actual["evidence_ids"], list) or len(actual["evidence_ids"]) > 10:
            errors.append("invalid evidence_ids")
        invalid = set(actual["evidence_ids"]) - valid_evidence
        if invalid:
            errors.append(f"invalid evidence: {sorted(invalid)}")
        root = actual["root_cause_analysis"]
        if len(root["ranked_causes"]) > 3 or len(root["responsible_parties"]) > 3:
            errors.append("root cause limits exceeded")
        if not isinstance(actual["resolution_actions"], list) or len(actual["resolution_actions"]) > 5:
            errors.append("invalid resolution_actions")
        financial = actual["financial_resolution"]
        for field in ("item_total_brl", "freight_total_brl", "payment_total_brl", "recommended_refund_brl"):
            value = financial[field]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or money(value) != value:
                errors.append(f"invalid money field {field}")
        status = "action_required" if financial["recommended_refund_brl"] > 0 else "no_action"
        if actual["assessment"]["case_status"] != status:
            errors.append("case_status disagrees with refund")
    except (KeyError, TypeError) as exc:
        errors.append(f"invalid nested schema: {exc}")
    return errors


def score_case(actual: dict[str, Any], expected: dict[str, Any]) -> dict[str, float]:
    issue = float(
        actual["assessment"]["primary_issue"] == expected["assessment"]["primary_issue"]
        and actual["assessment"]["case_status"] == expected["assessment"]["case_status"]
    )
    entity_scores = [set_f1(actual["affected_entities"][field], expected["affected_entities"][field]) for field in ("order_ids", "item_ids", "seller_ids", "payment_ids")]
    cause_score = set_f1(actual["root_cause_analysis"]["ranked_causes"], expected["root_cause_analysis"]["ranked_causes"])
    party_score = set_f1(actual["root_cause_analysis"]["responsible_parties"], expected["root_cause_analysis"]["responsible_parties"])
    actual_money, expected_money = actual["financial_resolution"], expected["financial_resolution"]
    money_fields = ("item_total_brl", "freight_total_brl", "payment_total_brl", "recommended_refund_brl")
    financial_checks = [actual_money.get("currency") == "BRL"] + [abs(Decimal(str(actual_money[field])) - Decimal(str(expected_money[field]))) <= Decimal("0.01") for field in money_fields]
    components = {
        "primary_issue": issue,
        "affected_entities": sum(entity_scores) / len(entity_scores),
        "root_cause_analysis": (cause_score + party_score) / 2,
        "evidence_ids": set_f1(actual["evidence_ids"], expected["evidence_ids"]),
        "financial_resolution": sum(financial_checks) / len(financial_checks),
        "resolution_actions": set_f1(actual["resolution_actions"], expected["resolution_actions"]),
    }
    weighted = sum(float(WEIGHTS[name]) * score for name, score in components.items())
    return {**components, "weighted_score": weighted}


def evaluate_trace(path: Path, expected_cases: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {"valid": False, "errors": ["trace file not found"]}
    events_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
            events_by_case[event["case_id"]].append(event)
        except (json.JSONDecodeError, KeyError) as exc:
            errors.append(f"line {line_number}: {exc}")
    complete = 0
    durations: list[float] = []
    for case_id in expected_cases:
        events = events_by_case.get(case_id, [])
        steps = [event.get("step") for event in events]
        if steps == TRACE_STEPS and all(event.get("status") == "completed" for event in events):
            complete += 1
        else:
            errors.append(f"{case_id}: expected {TRACE_STEPS}, got {steps}")
        durations.append(sum(float(event.get("duration_ms", 0)) for event in events))
    durations_sorted = sorted(durations)
    median_latency = statistics.median(durations) if durations else 0.0
    p95_index = max(0, min(len(durations_sorted) - 1, int(round(len(durations_sorted) * 0.95 + 0.5)) - 1))
    p95_latency = durations_sorted[p95_index] if durations_sorted else 0.0
    return {
        "valid": not errors,
        "workflow_completion_rate": complete / len(expected_cases),
        "event_count": sum(map(len, events_by_case.values())),
        "average_case_latency_ms": round(sum(durations) / len(durations), 3),
        "median_case_latency_ms": round(float(median_latency), 3),
        "p95_case_latency_ms": round(float(p95_latency), 3),
        "errors": errors,
    }


def summarize_case_metrics(report: dict[str, Any]) -> dict[str, Any]:
    cases = report["cases"]
    failed_cases = [case for case in cases if case["hard_gate_errors"]]
    top_errors = Counter()
    passed_scores = [case["scores"]["weighted_score"] for case in cases if not case["hard_gate_errors"]]
    for case in cases:
        top_errors.update(case["hard_gate_errors"])
    return {
        "hard_gate_pass_rate": report["passed_hard_gate"] / report["case_count"],
        "failed_case_count": len(failed_cases),
        "top_hard_gate_errors": top_errors.most_common(5),
        "score_spread": {
            "best_case": max((case["scores"]["weighted_score"] for case in cases), default=0.0),
            "worst_case": min((case["scores"]["weighted_score"] for case in cases), default=0.0),
            "average_passed_case": round(sum(passed_scores) / len(passed_scores) * 100, 4) if passed_scores else 0.0,
        },
    }


def make_valid_evidence(oracle: Oracle, cases: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for case in cases:
        order_id = case["customer_request"]["claimed_order_id"]
        result.add(f"order:{order_id}")
        result.update(
            f'item:{order_id}:{row["order_item_id"]}'
            for row in oracle.items.get(order_id, [])
        )
        result.update(
            f'payment:{order_id}:{row["payment_sequential"]}'
            for row in oracle.payments.get(order_id, [])
        )
        result.update(
            f'seller:{row["seller_id"]}' for row in oracle.items.get(order_id, [])
        )
        cause = oracle.expected(case)["root_cause_analysis"]["ranked_causes"][0]["cause_code"]
        result.add(f"policy:{cause}")
    return result


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    trace = report["trace"]
    summary = report["summary"]
    lines = [
        "# Evaluation Report",
        "",
        f"- Final score: **{report['final_score_percent']:.2f}/100**",
        f"- Passed hard gate: **{report['passed_hard_gate']}/{report['case_count']}**",
        f"- Trace completion: **{report['trace']['workflow_completion_rate']:.2%}**",
        f"- Average latency: **{trace['average_case_latency_ms']:.3f} ms**",
        f"- Median latency: **{trace['median_case_latency_ms']:.3f} ms**",
        f"- P95 latency: **{trace['p95_case_latency_ms']:.3f} ms**",
        "",
        "| Component | Average |",
        "|---|---:|",
    ]
    lines += [f"| `{name}` | {value:.4f} |" for name, value in report["component_averages"].items()]
    lines += [
        "",
        "## Summary",
        "",
        f"- Hard-gate pass rate: **{summary['hard_gate_pass_rate']:.2%}**",
        f"- Failed cases: **{summary['failed_case_count']}**",
        f"- Best case score: **{summary['score_spread']['best_case']:.4f}**",
        f"- Worst case score: **{summary['score_spread']['worst_case']:.4f}**",
        f"- Average passed-case score: **{summary['score_spread']['average_passed_case']:.2f}/100**",
        "",
        "## Issue Distribution",
        "",
    ]
    lines += [f"- `{issue}`: {count}" for issue, count in report["issue_distribution"].items()] or ["None."]
    if summary["top_hard_gate_errors"]:
        lines += ["", "### Top hard-gate errors", ""]
        lines += [f"- `{error}`: {count}" for error, count in summary["top_hard_gate_errors"]]
    failed = [case for case in report["cases"] if case["hard_gate_errors"]]
    lines += ["", "## Hard-gate failures", ""]
    lines += [f"- `{case['case_id']}`: {'; '.join(case['hard_gate_errors'])}" for case in failed] or ["None."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Olist dispute-resolution outputs")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--trace", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output_dir = args.output.resolve() if args.output else root / "output"
    trace_path = args.trace.resolve() if args.trace else root / "trace.jsonl"
    cases = [json.loads((root / "input" / f"{case_id}.json").read_text(encoding="utf-8")) for case_id in EXPECTED_CASES]
    oracle = Oracle(root / "data")
    valid_evidence = make_valid_evidence(oracle, cases)
    case_reports: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    passed = 0
    for case in cases:
        case_id = case["case_id"]
        path = output_dir / f"{case_id}.json"
        try:
            actual = json.loads(path.read_text(encoding="utf-8"))
            errors = hard_gate(actual, case_id, valid_evidence)
        except (OSError, json.JSONDecodeError) as exc:
            actual, errors = None, [str(exc)]
        scores = {name: 0.0 for name in (*WEIGHTS, "weighted_score")}
        if not errors:
            scores = score_case(actual, oracle.expected(case))
            passed += 1
        totals.update(scores)
        case_reports.append({"case_id": case_id, "hard_gate_errors": errors, "scores": scores})
    averages = {name: totals[name] / len(cases) for name in WEIGHTS}
    report = {
        "case_count": len(cases),
        "passed_hard_gate": passed,
        "final_score_percent": round(totals["weighted_score"] / len(cases) * 100, 4),
        "component_averages": averages,
        "issue_distribution": dict(Counter(oracle.expected(case)["assessment"]["primary_issue"] for case in cases)),
        "trace": evaluate_trace(trace_path, EXPECTED_CASES),
        "cases": case_reports,
    }
    report["summary"] = summarize_case_metrics(report)
    json_path = root / "evaluation_report.json"
    markdown_path = root / "evaluation_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(markdown_path, report)
    print(f"Score: {report['final_score_percent']:.2f}/100")
    print(f"Hard gate: {passed}/{len(cases)} passed")
    print(f"Trace completion: {report['trace']['workflow_completion_rate']:.2%}")
    print(f"Reports: {json_path.name}, {markdown_path.name}")


if __name__ == "__main__":
    main()
