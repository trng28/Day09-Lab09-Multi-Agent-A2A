from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
from src.agents.services import A2ATask, PolicyAgent, PolicyDecision


class TestPolicyAgent(unittest.TestCase):
    @patch("src.agents.services.ChatOpenAI")
    def setUp(self, mock_chat_openai) -> None:
        # Mock ChatOpenAI and the chained with_structured_output
        self.mock_model = MagicMock()
        mock_chat_openai.return_value.with_structured_output.return_value = self.mock_model
        self.agent = PolicyAgent()

    def _create_task(self, order_status: str, item_total: float, freight_total: float, 
                     payment_total: float, payment_count: int, delivery_artifact: dict) -> A2ATask:
        order_result = {
            "order": {"order_id": "ord123", "order_status": order_status},
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "item_ids": ["ord123:1"],
            "seller_ids": ["sellerA"]
        }
        payment_result = {
            "payment_total_brl": payment_total,
            "payment_count": payment_count,
            "payment_ids": ["ord123:1"]
        }
        context = {
            "order_result": order_result,
            "payment_result": payment_result,
            "delivery_result": delivery_artifact
        }
        return A2ATask(task_id="task_policy", case_id="case1", agent="policy", context=context)

    def test_policy_canceled_order_paid(self) -> None:
        # 1. Canceled paid order
        task = self._create_task(
            order_status="canceled",
            item_total=100.0,
            freight_total=15.0,
            payment_total=115.0,
            payment_count=1,
            delivery_artifact={"late": False, "seller_late": False, "late_seller_ids": [], "delivery_within_estimate": True}
        )
        
        # Mock LLM votes to return the correct decision
        expected_decision = PolicyDecision(
            primary_issue="canceled_order_paid",
            cause_code="ORDER_CANCELED_AFTER_PAYMENT",
            party_type="platform",
            party_id="OLIST_PLATFORM",
            recommended_refund_brl=115.0,
            action="issue_full_refund",
            confidence=0.99
        )
        self.mock_model.invoke.return_value = expected_decision
        
        res = self.agent.run(task)
        artifact = res.artifact
        self.assertEqual(artifact["primary_issue"], "canceled_order_paid")
        self.assertEqual(artifact["cause_code"], "ORDER_CANCELED_AFTER_PAYMENT")
        self.assertEqual(artifact["recommended_refund_brl"], 115.0)
        self.assertEqual(artifact["action"], "issue_full_refund")
        self.assertEqual(artifact["responsible_parties"], [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}])
        self.assertTrue(artifact["model_fully_agreed_with_policy_engine"])
        self.assertEqual(artifact["confidence"], 0.99)

    def test_policy_late_delivery_seller(self) -> None:
        # 2. Late delivery caused by seller
        task = self._create_task(
            order_status="delivered",
            item_total=100.0,
            freight_total=15.0,
            payment_total=115.0,
            payment_count=1,
            delivery_artifact={"late": True, "seller_late": True, "late_seller_ids": ["sellerA"], "delivery_within_estimate": False}
        )
        
        expected_decision = PolicyDecision(
            primary_issue="late_delivery_seller",
            cause_code="SELLER_HANDOFF_AFTER_LIMIT",
            party_type="seller",
            party_id="sellerA",
            recommended_refund_brl=15.0,
            action="refund_freight",
            confidence=0.95
        )
        self.mock_model.invoke.return_value = expected_decision
        
        res = self.agent.run(task)
        artifact = res.artifact
        self.assertEqual(artifact["primary_issue"], "late_delivery_seller")
        self.assertEqual(artifact["cause_code"], "SELLER_HANDOFF_AFTER_LIMIT")
        self.assertEqual(artifact["recommended_refund_brl"], 15.0)
        self.assertEqual(artifact["action"], "refund_freight")
        self.assertEqual(artifact["responsible_parties"], [{"party_type": "seller", "party_id": "sellerA"}])

    def test_policy_majority_voting(self) -> None:
        # Test that majority voting selects the winner when there are mixed LLM responses
        task = self._create_task(
            order_status="delivered",
            item_total=100.0,
            freight_total=15.0,
            payment_total=115.0,
            payment_count=1,
            delivery_artifact={"late": True, "seller_late": False, "late_seller_ids": [], "delivery_within_estimate": False}
        )
        
        # Expected issue: late_delivery_logistics, refund 15.0
        decision_correct = PolicyDecision(
            primary_issue="late_delivery_logistics",
            cause_code="CARRIER_DELIVERED_AFTER_ESTIMATE",
            party_type="logistics_provider",
            party_id="LOGISTICS_PROVIDER",
            recommended_refund_brl=15.0,
            action="refund_freight",
            confidence=0.98
        )
        decision_wrong = PolicyDecision(
            primary_issue="unsupported_late_claim",
            cause_code="DELIVERY_WITHIN_ESTIMATE",
            party_type=None,
            party_id=None,
            recommended_refund_brl=0.0,
            action="reject_late_refund",
            confidence=0.90
        )
        
        # Let's say 7 votes are correct, 3 are wrong
        self.mock_model.invoke.side_effect = [decision_correct] * 7 + [decision_wrong] * 3
        
        res = self.agent.run(task)
        artifact = res.artifact
        self.assertEqual(artifact["primary_issue"], "late_delivery_logistics")
        self.assertEqual(artifact["winning_votes"], 7)
        self.assertEqual(artifact["vote_share"], 0.7)
        # Winning vote corresponds to correct decision, so confidence should align (capped at 0.99)
        self.assertEqual(artifact["confidence"], 0.98)

    def test_policy_disagreement_confidence_drop(self) -> None:
        # Test that model disagreement falls back to lower confidence (0.75)
        task = self._create_task(
            order_status="delivered",
            item_total=100.0,
            freight_total=15.0,
            payment_total=115.0,
            payment_count=1,
            delivery_artifact={"late": False, "seller_late": False, "late_seller_ids": [], "delivery_within_estimate": True}
        )
        
        # Expected: unsupported_late_claim, refund 0
        # However, model votes for something else entirely: canceled_order_paid
        decision_wrong = PolicyDecision(
            primary_issue="canceled_order_paid",
            cause_code="ORDER_CANCELED_AFTER_PAYMENT",
            party_type="platform",
            party_id="OLIST_PLATFORM",
            recommended_refund_brl=115.0,
            action="issue_full_refund",
            confidence=0.95
        )
        self.mock_model.invoke.return_value = decision_wrong
        
        res = self.agent.run(task)
        artifact = res.artifact
        # The output must STILL use the correct deterministic logic (unsupported_late_claim)
        self.assertEqual(artifact["primary_issue"], "unsupported_late_claim")
        self.assertEqual(artifact["recommended_refund_brl"], 0.0)
        # But agreed is False, so confidence is lowered to 0.75
        self.assertFalse(artifact["model_agreed_with_policy_engine"])
        self.assertEqual(artifact["confidence"], 0.75)


if __name__ == "__main__":
    unittest.main()
