import unittest

from demo.search import LocalDemoStore


class LocalHybridSearchTests(unittest.TestCase):
    def setUp(self):
        self.store = LocalDemoStore()
        self.store.seed()

    def tearDown(self):
        self.store.close()

    def test_exact_identifier_is_top_result(self):
        results = self.store.search("ORDER-BRAVO", customer_id="customer-a")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].order_id, "ORDER-BRAVO")

    def test_semantic_delivery_issue_finds_case(self):
        results = self.store.search("marked delivered but missing", customer_id="customer-a")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].order_id, "ORDER-ALPHA")

    def test_semantic_damage_issue_finds_case(self):
        results = self.store.search("shoes arrived damaged", customer_id="customer-a")
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].order_id, "ORDER-BRAVO")

    def test_customer_filter_prevents_cross_customer_result(self):
        results = self.store.search("tracking says delivered but nothing came", customer_id="customer-a")
        self.assertTrue(all(r.customer_id == "customer-a" for r in results))
        self.assertNotIn("ORDER-CHARLIE", [r.order_id for r in results])


if __name__ == "__main__":
    unittest.main()
