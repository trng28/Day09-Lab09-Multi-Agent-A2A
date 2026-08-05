from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from src.agents import DeliveryAgent, OrderAgent, PaymentAgent, PolicyAgent, VerifierAgent
from src.agents.services import A2ATask
from src.repository.olist import OlistRepository


class WorkflowState(TypedDict, total=False):
    case: dict[str, Any]
    order_result: dict[str, Any]
    payment_result: dict[str, Any]
    delivery_result: dict[str, Any]
    policy_result: dict[str, Any]
    output: dict[str, Any]
    trace: list[dict[str, Any]]


class DisputeWorkflow:
    """Coordinator-only orchestration; business decisions remain in domain agents."""

    def __init__(self, data_dir: Path) -> None:
        load_dotenv(data_dir.parent / ".env")
        repository = OlistRepository(data_dir)
        self.order_agent = OrderAgent(repository)
        self.payment_agent = PaymentAgent(repository)
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent()
        self.verifier_agent = VerifierAgent()
        self.graph = self._build_graph()

    @staticmethod
    def _task(case: dict[str, Any], agent: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> A2ATask:
        return A2ATask(
            task_id=f"{case['case_id']}-{agent}-{uuid.uuid4().hex[:8]}",
            case_id=case["case_id"],
            agent=agent,
            payload=payload,
            context=context or {},
        )

    @staticmethod
    def _trace(state: WorkflowState, agent: str, task_id: str, started: float) -> list[dict[str, Any]]:
        events = list(state.get("trace", []))
        events.append(
            {
                "case_id": state["case"]["case_id"],
                "step": agent,
                "task_id": task_id,
                "status": "completed",
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        )
        return events

    def _invoke(self, state: WorkflowState, agent: Any, payload: dict[str, Any], context: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        task = self._task(state["case"], agent.name, payload, context)
        started = time.perf_counter()
        artifact = agent.run(task).artifact
        return artifact, self._trace(state, agent.__class__.__name__, task.task_id, started)

    def _order(self, state: WorkflowState) -> dict[str, Any]:
        order_id = state["case"]["customer_request"]["claimed_order_id"]
        result, trace = self._invoke(state, self.order_agent, {"order_id": order_id})
        return {"order_result": result, "trace": trace}

    def _payment(self, state: WorkflowState) -> dict[str, Any]:
        order_id = state["case"]["customer_request"]["claimed_order_id"]
        result, trace = self._invoke(state, self.payment_agent, {"order_id": order_id})
        return {"payment_result": result, "trace": trace}

    def _delivery(self, state: WorkflowState) -> dict[str, Any]:
        context = {"order_result": state["order_result"]}
        result, trace = self._invoke(state, self.delivery_agent, {}, context)
        return {"delivery_result": result, "trace": trace}

    def _policy(self, state: WorkflowState) -> dict[str, Any]:
        context = {
            "order_result": state["order_result"],
            "payment_result": state["payment_result"],
            "delivery_result": state["delivery_result"],
        }
        result, trace = self._invoke(state, self.policy_agent, {}, context)
        trace[-1]["model"] = result["model"]
        trace[-1]["model_agreed_with_policy_engine"] = result["model_agreed_with_policy_engine"]
        return {"policy_result": result, "trace": trace}

    def _assemble(self, state: WorkflowState) -> dict[str, Any]:
        case = state["case"]
        order_id = case["customer_request"]["claimed_order_id"]
        order = state["order_result"]
        payment = state["payment_result"]
        policy = state["policy_result"]
        cause = policy["cause_code"]
        issue = policy["primary_issue"]
        evidence = [f"order:{order_id}"]
        if issue in {"late_delivery_seller", "late_delivery_logistics", "valid_split_payment", "unsupported_late_claim"}:
            evidence.extend(f"item:{item_id}" for item_id in order["item_ids"])
        evidence.extend(f"payment:{payment_id}" for payment_id in payment["payment_ids"])
        if issue == "late_delivery_seller":
            late_sellers = set(state["delivery_result"]["late_seller_ids"])
            evidence.extend(
                f"seller:{seller_id}"
                for seller_id in order["seller_ids"]
                if seller_id in late_sellers
            )
        evidence.append(f"policy:{cause}")
        # Keep policy evidence and cap the list at the schema limit.
        evidence = evidence[:9] + [evidence[-1]] if len(evidence) > 10 else evidence
        output = {
            "case_id": case["case_id"],
            "assessment": {
                "primary_issue": policy["primary_issue"],
                "case_status": "action_required" if policy["recommended_refund_brl"] > 0 else "no_action",
                "confidence": policy["confidence"],
            },
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": order["item_ids"],
                "seller_ids": order["seller_ids"],
                "payment_ids": payment["payment_ids"],
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": cause, "rank": 1}],
                "responsible_parties": policy["responsible_parties"],
            },
            "evidence_ids": evidence,
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": order["item_total_brl"],
                "freight_total_brl": order["freight_total_brl"],
                "payment_total_brl": payment["payment_total_brl"],
                "recommended_refund_brl": policy["recommended_refund_brl"],
            },
            "resolution_actions": [policy["action"]],
        }
        return {"output": output}

    def _verify(self, state: WorkflowState) -> dict[str, Any]:
        _, trace = self._invoke(state, self.verifier_agent, {"result": state["output"]})
        return {"trace": trace}

    def _build_graph(self):
        graph = StateGraph(WorkflowState)
        nodes: list[tuple[str, Callable[[WorkflowState], dict[str, Any]]]] = [
            ("order", self._order),
            ("payment", self._payment),
            ("delivery", self._delivery),
            ("policy", self._policy),
            ("assemble", self._assemble),
            ("verify", self._verify),
        ]
        for name, handler in nodes:
            graph.add_node(name, handler)
        graph.add_edge(START, "order")
        graph.add_edge("order", "payment")
        graph.add_edge("payment", "delivery")
        graph.add_edge("delivery", "policy")
        graph.add_edge("policy", "assemble")
        graph.add_edge("assemble", "verify")
        graph.add_edge("verify", END)
        return graph.compile()

    def run(self, case: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if case.get("policy_version") != "EC_POLICY_V1":
            raise ValueError(f"Unsupported policy: {case.get('policy_version')}")
        state = self.graph.invoke({"case": case, "trace": []})
        return state["output"], state["trace"]


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
