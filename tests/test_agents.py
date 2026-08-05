from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from src.agents.services import (
    A2ATask, OrderAgent, PaymentAgent, DeliveryAgent, VerifierAgent
)


class TestOrderAgent(unittest.TestCase):
    def test_run(self) -> None:
        mock_repo = MagicMock()
        mock_repo.order.return_value = {"order_id": "ord123", "order_status": "delivered"}
        mock_repo.order_items.return_value = [
            {"order_item_id": "1", "price": "100.50", "freight_value": "15.20", "seller_id": "sellerA"},
            {"order_item_id": "2", "price": "50.25", "freight_value": "5.10", "seller_id": "sellerB"},
        ]
        
        agent = OrderAgent(mock_repo)
        task = A2ATask(
            task_id="task1",
            case_id="case1",
            agent="order",
            payload={"order_id": "ord123"}
        )
        
        result = agent.run(task)
        self.assertEqual(result.task_id, "task1")
        self.assertEqual(result.status, "completed")
        artifact = result.artifact
        self.assertEqual(artifact["item_total_brl"], 150.75)
        self.assertEqual(artifact["freight_total_brl"], 20.30)
        self.assertEqual(artifact["item_ids"], ["ord123:1", "ord123:2"])
        self.assertEqual(artifact["seller_ids"], ["sellerA", "sellerB"])


class TestPaymentAgent(unittest.TestCase):
    def test_run(self) -> None:
        mock_repo = MagicMock()
        mock_repo.order_payments.return_value = [
            {"payment_sequential": "1", "payment_value": "100.00"},
            {"payment_sequential": "2", "payment_value": "71.05"},
        ]
        
        agent = PaymentAgent(mock_repo)
        task = A2ATask(
            task_id="task2",
            case_id="case1",
            agent="payment",
            payload={"order_id": "ord123"}
        )
        
        result = agent.run(task)
        self.assertEqual(result.task_id, "task2")
        artifact = result.artifact
        self.assertEqual(artifact["payment_count"], 2)
        self.assertEqual(artifact["payment_total_brl"], 171.05)
        self.assertEqual(artifact["payment_ids"], ["ord123:1", "ord123:2"])


class TestDeliveryAgent(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = DeliveryAgent()

    def test_delivery_within_estimate(self) -> None:
        context = {
            "order_result": {
                "order": {
                    "order_id": "ord123",
                    "order_delivered_customer_date": "2018-10-10T12:00:00",
                    "order_estimated_delivery_date": "2018-10-12T12:00:00",
                    "order_delivered_carrier_date": "2018-10-05T12:00:00",
                },
                "items": []
            }
        }
        task = A2ATask(task_id="task3", case_id="case1", agent="delivery", context=context)
        result = self.agent.run(task)
        self.assertFalse(result.artifact["late"])
        self.assertTrue(result.artifact["delivery_within_estimate"])

    def test_late_delivery_seller(self) -> None:
        # Carrier handoff is after shipping_limit_date
        context = {
            "order_result": {
                "order": {
                    "order_id": "ord123",
                    "order_delivered_customer_date": "2018-10-15T12:00:00",
                    "order_estimated_delivery_date": "2018-10-12T12:00:00",
                    "order_delivered_carrier_date": "2018-10-09T12:00:00",
                },
                "items": [
                    {"seller_id": "sellerA", "shipping_limit_date": "2018-10-08T12:00:00"}
                ]
            }
        }
        task = A2ATask(task_id="task3", case_id="case1", agent="delivery", context=context)
        result = self.agent.run(task)
        self.assertTrue(result.artifact["late"])
        self.assertTrue(result.artifact["seller_late"])
        self.assertEqual(result.artifact["late_seller_ids"], ["sellerA"])

    def test_late_delivery_logistics(self) -> None:
        # Carrier handoff is before shipping_limit_date
        context = {
            "order_result": {
                "order": {
                    "order_id": "ord123",
                    "order_delivered_customer_date": "2018-10-15T12:00:00",
                    "order_estimated_delivery_date": "2018-10-12T12:00:00",
                    "order_delivered_carrier_date": "2018-10-07T12:00:00",
                },
                "items": [
                    {"seller_id": "sellerA", "shipping_limit_date": "2018-10-08T12:00:00"}
                ]
            }
        }
        task = A2ATask(task_id="task3", case_id="case1", agent="delivery", context=context)
        result = self.agent.run(task)
        self.assertTrue(result.artifact["late"])
        self.assertFalse(result.artifact["seller_late"])
        self.assertTrue(result.artifact["logistics_late"])


class TestVerifierAgent(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = VerifierAgent()
        self.order_result = {
            "order": {"order_id": "ord123"},
            "item_total_brl": 100.00,
            "freight_total_brl": 15.00,
            "item_ids": ["ord123:1"],
            "seller_ids": ["sellerA"]
        }
        self.payment_result = {
            "payment_total_brl": 115.00,
            "payment_ids": ["ord123:1"]
        }
        self.delivery_result = {
            "late": True,
            "seller_late": True,
            "late_seller_ids": ["sellerA"]
        }
        self.policy_result = {
            "primary_issue": "late_delivery_seller",
            "cause_code": "SELLER_HANDOFF_AFTER_LIMIT",
            "recommended_refund_brl": 15.00,
            "responsible_parties": [{"party_type": "seller", "party_id": "sellerA"}],
            "action": "refund_freight"
        }
        self.valid_result = {
            "case_id": "case1",
            "assessment": {
                "primary_issue": "late_delivery_seller",
                "case_status": "action_required",
                "confidence": 0.95
            },
            "affected_entities": {
                "order_ids": ["ord123"],
                "item_ids": ["ord123:1"],
                "seller_ids": ["sellerA"],
                "payment_ids": ["ord123:1"]
            },
            "root_cause_analysis": {
                "ranked_causes": [{"cause_code": "SELLER_HANDOFF_AFTER_LIMIT", "rank": 1}],
                "responsible_parties": [{"party_type": "seller", "party_id": "sellerA"}]
            },
            "evidence_ids": [
                "order:ord123",
                "item:ord123:1",
                "payment:ord123:1",
                "seller:sellerA",
                "policy:SELLER_HANDOFF_AFTER_LIMIT"
            ],
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": 100.00,
                "freight_total_brl": 15.00,
                "payment_total_brl": 115.00,
                "recommended_refund_brl": 15.00
            },
            "resolution_actions": ["refund_freight"]
        }

    def test_verification_success(self) -> None:
        context = {
            "order_result": self.order_result,
            "payment_result": self.payment_result,
            "delivery_result": self.delivery_result,
            "policy_result": self.policy_result
        }
        task = A2ATask(
            task_id="task4",
            case_id="case1",
            agent="verifier",
            payload={"result": self.valid_result},
            context=context
        )
        res = self.agent.run(task)
        self.assertTrue(res.artifact["valid"])

    def test_verification_failure_confidence(self) -> None:
        bad_result = dict(self.valid_result)
        bad_result["assessment"] = dict(bad_result["assessment"])
        bad_result["assessment"]["confidence"] = 1.5  # Invalid: > 1
        
        context = {
            "order_result": self.order_result,
            "payment_result": self.payment_result,
            "delivery_result": self.delivery_result,
            "policy_result": self.policy_result
        }
        task = A2ATask(
            task_id="task4",
            case_id="case1",
            agent="verifier",
            payload={"result": bad_result},
            context=context
        )
        with self.assertRaises(ValueError) as exc:
            self.agent.run(task)
        self.assertIn("confidence must be in [0, 1]", str(exc.exception))

    def test_verification_failure_mismatched_refund_status(self) -> None:
        bad_result = dict(self.valid_result)
        bad_result["assessment"] = dict(bad_result["assessment"])
        bad_result["assessment"]["case_status"] = "no_action"  # Disagrees with refund > 0
        
        context = {
            "order_result": self.order_result,
            "payment_result": self.payment_result,
            "delivery_result": self.delivery_result,
            "policy_result": self.policy_result
        }
        task = A2ATask(
            task_id="task4",
            case_id="case1",
            agent="verifier",
            payload={"result": bad_result},
            context=context
        )
        with self.assertRaises(ValueError) as exc:
            self.agent.run(task)
        self.assertIn("case_status and refund disagree", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
