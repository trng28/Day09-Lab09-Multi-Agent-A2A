from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.coordinator import DisputeWorkflow
from src.agents.services import PolicyDecision


class TestDisputeWorkflow(unittest.TestCase):
    @patch("src.coordinator.workflow.OlistRepository")
    @patch("src.agents.services.ChatOpenAI")
    def test_workflow_run_success(self, mock_chat_openai, mock_repo_class) -> None:
        # Mock ChatOpenAI to return a mock model
        mock_model = MagicMock()
        mock_chat_openai.return_value.with_structured_output.return_value = mock_model
        
        # Define mock responses from the mock LLM
        mock_decision = PolicyDecision(
            primary_issue="late_delivery_seller",
            cause_code="SELLER_HANDOFF_AFTER_LIMIT",
            party_type="seller",
            party_id="seller_123",
            recommended_refund_brl=15.50,
            action="refund_freight",
            confidence=0.97
        )
        mock_model.invoke.return_value = mock_decision

        # Setup mock repository instances and methods
        mock_repo_instance = MagicMock()
        mock_repo_class.return_value = mock_repo_instance

        # Return mock order, items, payments
        mock_repo_instance.order.return_value = {
            "order_id": "order_xyz",
            "order_status": "delivered",
            "order_delivered_customer_date": "2018-10-15T12:00:00",
            "order_estimated_delivery_date": "2018-10-12T12:00:00",
            "order_delivered_carrier_date": "2018-10-09T12:00:00",
        }
        mock_repo_instance.order_items.return_value = [
            {
                "order_item_id": "1", 
                "price": "100.00", 
                "freight_value": "15.50", 
                "seller_id": "seller_123",
                "shipping_limit_date": "2018-10-08T12:00:00" # Shipping limit is before carrier handoff -> late delivery seller
            }
        ]
        mock_repo_instance.order_payments.return_value = [
            {
                "payment_sequential": "1", 
                "payment_value": "115.50"
            }
        ]

        # Instantiate workflow
        workflow = DisputeWorkflow(Path("/fake/data/dir"))

        # Create input case JSON
        case_input = {
            "case_id": "EC_TEST_001",
            "opened_at": "2018-10-18T00:00:00-03:00",
            "customer_request": {
                "language": "vi",
                "message": "Giao hàng trễ quá bạn ơi.",
                "claimed_order_id": "order_xyz"
            },
            "policy_version": "EC_POLICY_V1"
        }

        # Run workflow
        output, trace = workflow.run(case_input)

        # 1. Verify workflow output format and schema
        self.assertEqual(output["case_id"], "EC_TEST_001")
        self.assertEqual(output["assessment"]["primary_issue"], "late_delivery_seller")
        self.assertEqual(output["assessment"]["case_status"], "action_required")
        self.assertEqual(output["assessment"]["confidence"], 0.97)
        self.assertEqual(output["affected_entities"]["order_ids"], ["order_xyz"])
        self.assertEqual(output["affected_entities"]["item_ids"], ["order_xyz:1"])
        self.assertEqual(output["affected_entities"]["seller_ids"], ["seller_123"])
        self.assertEqual(output["affected_entities"]["payment_ids"], ["order_xyz:1"])
        self.assertEqual(output["root_cause_analysis"]["ranked_causes"], [{"cause_code": "SELLER_HANDOFF_AFTER_LIMIT", "rank": 1}])
        self.assertEqual(output["root_cause_analysis"]["responsible_parties"], [{"party_type": "seller", "party_id": "seller_123"}])
        self.assertEqual(output["financial_resolution"]["recommended_refund_brl"], 15.50)
        self.assertEqual(output["resolution_actions"], ["refund_freight"])
        self.assertIn("order:order_xyz", output["evidence_ids"])
        self.assertIn("policy:SELLER_HANDOFF_AFTER_LIMIT", output["evidence_ids"])

        # 2. Verify trace steps execution
        expected_steps = ["OrderAgent", "PaymentAgent", "DeliveryAgent", "PolicyAgent", "VerifierAgent"]
        executed_steps = [t["step"] for t in trace]
        self.assertEqual(executed_steps, expected_steps)
        for t in trace:
            self.assertEqual(t["status"], "completed")
            self.assertGreater(t["duration_ms"], 0)


if __name__ == "__main__":
    unittest.main()
