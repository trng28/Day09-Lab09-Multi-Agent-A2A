from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
    VOTE_RUNS = 3
    VOTE_WORKERS = 3

    def __init__(self) -> None:
        self.model = ChatOpenAI(
            model=self.MODEL,
            temperature=0.2,
            timeout=60,
            max_retries=3,
        ).with_structured_output(
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
        messages = [
            (
                "system",
                "You are the EC_POLICY_V1 Policy Agent. Apply these rules in exact priority order: "
                    "(1) canceled status and payment>0 => canceled_order_paid, "
                    "ORDER_CANCELED_AFTER_PAYMENT, platform/OLIST_PLATFORM, full payment refund, "
                    "issue_full_refund; (2) unavailable status and payment>0 => unavailable_order_paid, "
                    "ORDER_UNAVAILABLE_AFTER_PAYMENT, platform/OLIST_PLATFORM, full payment refund, "
                    "issue_full_refund; (3) late and seller_late => late_delivery_seller, "
                    "SELLER_HANDOFF_AFTER_LIMIT, responsible seller, freight refund, refund_freight; "
                    "(4) late without seller_late => late_delivery_logistics, "
                    "CARRIER_DELIVERED_AFTER_ESTIMATE, logistics_provider/LOGISTICS_PROVIDER, freight "
                    "refund, refund_freight; (5) payment_count>=2 and payment reconciles => "
                    "valid_split_payment, MULTIPLE_PAYMENTS_RECONCILED, no responsible party, zero "
                    "refund, explain_valid_split_payment; (6) delivery within estimate and payment "
                    "reconciles => unsupported_late_claim, DELIVERY_WITHIN_ESTIMATE, no responsible "
                    "party, zero refund, reject_late_refund. Use only provided facts. Never invent IDs, "
                    "dates, evidence, or money values. Return exactly one structured decision.",
            ),
            (
                "human",
                "Evaluate rules 1 through 6 in order and stop immediately at the first true "
                    "condition. In particular, rule 5 (multiple reconciled payments) has priority "
                    "over rule 6 (delivery within estimate). For canceled or unavailable paid "
                    "orders, recommended_refund_brl must equal payment_total_brl even when there "
                    "are no item rows and item_total_brl is zero. Select the highest-priority decision "
                    f"for these verified facts: {facts}",
            ),
        ]

        # Independent structured decisions are sampled concurrently, then reduced
        # by deterministic majority voting. A small temperature creates useful
        # diversity while the policy guard prevents an incorrect winner escaping.
        with ThreadPoolExecutor(max_workers=self.VOTE_WORKERS) as executor:
            decisions = list(executor.map(lambda _: self.model.invoke(messages), range(self.VOTE_RUNS)))

        def signature(candidate: PolicyDecision) -> tuple[str, str, str, str | None, str | None, float]:
            candidate_party_id = candidate.party_id.strip() if candidate.party_id else None
            return (
                candidate.primary_issue,
                candidate.cause_code,
                candidate.action,
                candidate.party_type,
                candidate_party_id,
                money(candidate.recommended_refund_brl),
            )

        vote_counts = Counter(signature(candidate) for candidate in decisions)
        expected_signature = (issue, cause, action, party_type, party_id, money(refund))
        # Prefer the policy-consistent signature only when vote counts are tied.
        winning_signature = max(
            vote_counts,
            key=lambda value: (vote_counts[value], value == expected_signature),
        )
        model_decision = next(candidate for candidate in decisions if signature(candidate) == winning_signature)
        winning_votes = vote_counts[winning_signature]

        # Financial values and IDs always come from the deterministic policy engine.
        # A model disagreement is recorded through lower confidence, never allowed to
        # corrupt auditable output.
        model_party_id = model_decision.party_id.strip() if model_decision.party_id else None
        decision_agrees = (
            model_decision.primary_issue == issue
            and model_decision.cause_code == cause
            and model_decision.action == action
        )
        details_agree = (
            model_decision.party_type == party_type
            and model_party_id == party_id
            and abs(
                Decimal(str(model_decision.recommended_refund_brl))
                - Decimal(str(money(refund)))
            )
            <= Decimal("0.01")
        )
        fully_agrees = decision_agrees and details_agree
        artifact = {
            "primary_issue": issue,
            "cause_code": cause,
            "responsible_parties": [] if party_type is None else [{"party_type": party_type, "party_id": party_id}],
            "recommended_refund_brl": money(refund),
            "action": action,
            # The decision is supported independently by both the model and the
            # deterministic policy engine. Keep high confidence only on agreement.
            "confidence": min(model_decision.confidence, 0.99) if decision_agrees else 0.75,
            "model": self.MODEL,
            "model_agreed_with_policy_engine": decision_agrees,
            "model_fully_agreed_with_policy_engine": fully_agrees,
            "model_decision": model_decision.model_dump(),
            "vote_runs": self.VOTE_RUNS,
            "winning_votes": winning_votes,
            "vote_share": winning_votes / self.VOTE_RUNS,
            "vote_distribution": [
                {
                    "primary_issue": vote[0],
                    "cause_code": vote[1],
                    "action": vote[2],
                    "party_type": vote[3],
                    "party_id": vote[4],
                    "recommended_refund_brl": vote[5],
                    "votes": count,
                }
                for vote, count in vote_counts.most_common()
            ],
        }
        return A2AResult(task_id=task.task_id, artifact=artifact)


class VerifierAgent:
    name = "verifier"

    def run(self, task: A2ATask) -> A2AResult:
        result = task.payload["result"]
        order_result = task.context["order_result"]
        payment_result = task.context["payment_result"]
        delivery_result = task.context["delivery_result"]
        policy_result = task.context["policy_result"]
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
        if result["assessment"]["primary_issue"] != policy_result["primary_issue"]:
            errors.append("primary_issue disagrees with Policy Agent")
        expected_entities = {
            "order_ids": [order_result["order"]["order_id"]],
            "item_ids": order_result["item_ids"],
            "seller_ids": order_result["seller_ids"],
            "payment_ids": payment_result["payment_ids"],
        }
        if result["affected_entities"] != expected_entities:
            errors.append("affected entities disagree with source artifacts")
        expected_financial = {
            "currency": "BRL",
            "item_total_brl": order_result["item_total_brl"],
            "freight_total_brl": order_result["freight_total_brl"],
            "payment_total_brl": payment_result["payment_total_brl"],
            "recommended_refund_brl": policy_result["recommended_refund_brl"],
        }
        if result["financial_resolution"] != expected_financial:
            errors.append("financial resolution disagrees with source artifacts")
        causes = result["root_cause_analysis"]["ranked_causes"]
        if causes != [{"cause_code": policy_result["cause_code"], "rank": 1}]:
            errors.append("root cause disagrees with Policy Agent")
        if result["root_cause_analysis"]["responsible_parties"] != policy_result["responsible_parties"]:
            errors.append("responsible parties disagree with Policy Agent")
        if result["resolution_actions"] != [policy_result["action"]]:
            errors.append("resolution action disagrees with Policy Agent")

        evidence = set(result["evidence_ids"])
        order_id = order_result["order"]["order_id"]
        if f"order:{order_id}" not in evidence:
            errors.append("missing order evidence")
        if f"policy:{policy_result['cause_code']}" not in evidence:
            errors.append("missing policy evidence")
        valid_ids = {f"order:{order_id}", f"policy:{policy_result['cause_code']}"}
        valid_ids.update(f"item:{value}" for value in order_result["item_ids"])
        valid_ids.update(f"payment:{value}" for value in payment_result["payment_ids"])
        valid_ids.update(f"seller:{value}" for value in order_result["seller_ids"])
        if not evidence <= valid_ids:
            errors.append("evidence contains IDs outside source artifacts")
        if policy_result["primary_issue"] == "late_delivery_seller":
            expected_sellers = set(delivery_result["late_seller_ids"])
            submitted_sellers = {value.removeprefix("seller:") for value in evidence if value.startswith("seller:")}
            if submitted_sellers != expected_sellers:
                errors.append("seller evidence disagrees with late sellers")
        if errors:
            raise ValueError("Verification failed: " + "; ".join(errors))
        return A2AResult(task_id=task.task_id, artifact={"valid": True})
