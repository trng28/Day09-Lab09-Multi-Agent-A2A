from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.repository.olist import OlistRepository


MONEY = Decimal("0.01")


def money(value: Decimal | str | float) -> float:
    return float(Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP))


def timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class A2ATask(BaseModel):
    task_id: str
    case_id: str
    agent: str
    payload: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class A2AResult(BaseModel):
    task_id: str
    status: str = "completed"
    artifact: dict[str, Any]


class PolicyDecision(BaseModel):
    primary_issue: Literal[
        "canceled_order_paid",
        "unavailable_order_paid",
        "late_delivery_seller",
        "late_delivery_logistics",
        "valid_split_payment",
        "unsupported_late_claim",
    ]
    cause_code: Literal[
        "SELLER_HANDOFF_AFTER_LIMIT",
        "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "ORDER_CANCELED_AFTER_PAYMENT",
        "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "MULTIPLE_PAYMENTS_RECONCILED",
        "DELIVERY_WITHIN_ESTIMATE",
    ]
    party_type: Literal["platform", "seller", "logistics_provider"] | None = None
    party_id: str | None = None
    recommended_refund_brl: float = Field(ge=0)
    action: Literal[
        "issue_full_refund",
        "refund_freight",
        "explain_valid_split_payment",
        "reject_late_refund",
    ]
    confidence: float = Field(ge=0, le=1)


class OrderAgent:
    name = "order"

    def __init__(self, repository: OlistRepository) -> None:
        self.repository = repository

    def run(self, task: A2ATask) -> A2AResult:
        order_id = task.payload["order_id"]
        order = self.repository.order(order_id)
        items = self.repository.order_items(order_id)
        artifact = {
            "order": order,
            "items": items,
            "item_total_brl": money(sum(Decimal(row["price"]) for row in items)),
            "freight_total_brl": money(sum(Decimal(row["freight_value"]) for row in items)),
            "item_ids": [f'{order_id}:{row["order_item_id"]}' for row in items][:5],
            "seller_ids": list(dict.fromkeys(row["seller_id"] for row in items))[:5],
        }
        return A2AResult(task_id=task.task_id, artifact=artifact)


class PaymentAgent:
    name = "payment"

    def __init__(self, repository: OlistRepository) -> None:
        self.repository = repository

    def run(self, task: A2ATask) -> A2AResult:
        order_id = task.payload["order_id"]
        rows = self.repository.order_payments(order_id)
        artifact = {
            "payment_rows": rows,
            "payment_count": len(rows),
            "payment_total_brl": money(sum(Decimal(row["payment_value"]) for row in rows)),
            "payment_ids": [f'{order_id}:{row["payment_sequential"]}' for row in rows][:5],
        }
        return A2AResult(task_id=task.task_id, artifact=artifact)


class DeliveryAgent:
    name = "delivery"

    def run(self, task: A2ATask) -> A2AResult:
        order_result = task.context["order_result"]
        order = order_result["order"]
        delivered = timestamp(order.get("order_delivered_customer_date"))
        estimated = timestamp(order.get("order_estimated_delivery_date"))
        carrier = timestamp(order.get("order_delivered_carrier_date"))
        late = bool(delivered and estimated and delivered > estimated)
        late_sellers = []
        if late and carrier:
            late_sellers = list(
                dict.fromkeys(
                    row["seller_id"]
                    for row in order_result["items"]
                    if timestamp(row.get("shipping_limit_date"))
                    and carrier > timestamp(row["shipping_limit_date"])
                )
            )
        artifact = {
            "late": late,
            "seller_late": bool(late_sellers),
            "late_seller_ids": late_sellers[:5],
            "logistics_late": late and not late_sellers,
            "delivery_within_estimate": bool(delivered and estimated and delivered <= estimated),
        }
        return A2AResult(task_id=task.task_id, artifact=artifact)


class PolicyAgent:
    name = "policy"

    MODEL = "gpt-4o-mini"

    def __init__(self) -> None:
        self.model = ChatOpenAI(model=self.MODEL, temperature=0).with_structured_output(
            PolicyDecision,
            method="json_schema",
        )

    def run(self, task: A2ATask) -> A2AResult:
        order_result = task.context["order_result"]
        payment_result = task.context["payment_result"]
        delivery_result = task.context["delivery_result"]
        status = order_result["order"]["order_status"]
        payment = Decimal(str(payment_result["payment_total_brl"]))
        expected = Decimal(str(order_result["item_total_brl"])) + Decimal(
            str(order_result["freight_total_brl"])
        )
        payment_matches = abs(payment - expected) <= Decimal("0.10")

        if status == "canceled" and payment > 0:
            decision = ("canceled_order_paid", "ORDER_CANCELED_AFTER_PAYMENT", "platform", "OLIST_PLATFORM", payment, "issue_full_refund")
        elif status == "unavailable" and payment > 0:
            decision = ("unavailable_order_paid", "ORDER_UNAVAILABLE_AFTER_PAYMENT", "platform", "OLIST_PLATFORM", payment, "issue_full_refund")
        elif delivery_result["late"] and delivery_result["seller_late"]:
            decision = ("late_delivery_seller", "SELLER_HANDOFF_AFTER_LIMIT", "seller", delivery_result["late_seller_ids"][0], Decimal(str(order_result["freight_total_brl"])), "refund_freight")
        elif delivery_result["late"]:
            decision = ("late_delivery_logistics", "CARRIER_DELIVERED_AFTER_ESTIMATE", "logistics_provider", "LOGISTICS_PROVIDER", Decimal(str(order_result["freight_total_brl"])), "refund_freight")
        elif payment_result["payment_count"] >= 2 and payment_matches:
            decision = ("valid_split_payment", "MULTIPLE_PAYMENTS_RECONCILED", None, None, Decimal("0"), "explain_valid_split_payment")
        elif delivery_result["delivery_within_estimate"] and payment_matches:
            decision = ("unsupported_late_claim", "DELIVERY_WITHIN_ESTIMATE", None, None, Decimal("0"), "reject_late_refund")
        else:
            raise ValueError(f"No EC_POLICY_V1 rule matched order {order_result['order']['order_id']}")

        issue, cause, party_type, party_id, refund, action = decision
        facts = {
            "policy_version": "EC_POLICY_V1",
            "order_id": order_result["order"]["order_id"],
            "order_status": status,
            "item_total_brl": order_result["item_total_brl"],
            "freight_total_brl": order_result["freight_total_brl"],
            "payment_total_brl": payment_result["payment_total_brl"],
            "payment_count": payment_result["payment_count"],
            "payment_matches_item_plus_freight": payment_matches,
            **delivery_result,
        }
        model_decision = self.model.invoke(
            [
                (
                    "system",
                    "You are the EC_POLICY_V1 Policy Agent. Apply the rules in the exact "
                    "priority order supplied by the application. Use only the provided facts. "
                    "Never invent evidence, IDs, dates, or money values. Return one structured decision.",
                ),
                (
                    "human",
                    "Select the decision for these verified facts. The deterministic policy engine "
                    f"expects issue={issue}, cause={cause}, party_type={party_type}, "
                    f"party_id={party_id}, refund={money(refund)}, action={action}. Facts: {facts}",
                ),
            ]
        )

        # Financial values and IDs always come from the deterministic policy engine.
        # A model disagreement is recorded through lower confidence, never allowed to
        # corrupt auditable output.
        agrees = (
            model_decision.primary_issue == issue
            and model_decision.cause_code == cause
            and model_decision.action == action
        )
        artifact = {
            "primary_issue": issue,
            "cause_code": cause,
            "responsible_parties": [] if party_type is None else [{"party_type": party_type, "party_id": party_id}],
            "recommended_refund_brl": money(refund),
            "action": action,
            "confidence": min(model_decision.confidence, 0.99) if agrees else 0.75,
            "model": self.MODEL,
            "model_agreed_with_policy_engine": agrees,
        }
        return A2AResult(task_id=task.task_id, artifact=artifact)


class VerifierAgent:
    name = "verifier"

    def run(self, task: A2ATask) -> A2AResult:
        result = task.payload["result"]
        errors: list[str] = []
        limits = {
            "order_ids": 5,
            "item_ids": 5,
            "seller_ids": 5,
            "payment_ids": 5,
        }
        if not 0 <= result["assessment"]["confidence"] <= 1:
            errors.append("confidence must be in [0, 1]")
        for name, limit in limits.items():
            if len(result["affected_entities"][name]) > limit:
                errors.append(f"{name} exceeds {limit}")
        if len(result["evidence_ids"]) > 10:
            errors.append("evidence_ids exceeds 10")
        if len(result["root_cause_analysis"]["ranked_causes"]) > 3:
            errors.append("ranked_causes exceeds 3")
        if len(result["root_cause_analysis"]["responsible_parties"]) > 3:
            errors.append("responsible_parties exceeds 3")
        if len(result["resolution_actions"]) > 5:
            errors.append("resolution_actions exceeds 5")
        expected_status = "action_required" if result["financial_resolution"]["recommended_refund_brl"] > 0 else "no_action"
        if result["assessment"]["case_status"] != expected_status:
            errors.append("case_status and refund disagree")
        if errors:
            raise ValueError("Verification failed: " + "; ".join(errors))
        return A2AResult(task_id=task.task_id, artifact={"valid": True})
