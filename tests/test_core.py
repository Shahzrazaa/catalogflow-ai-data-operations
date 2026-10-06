import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("catalogflow_server", str(ROOT / "server.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
server = importlib.util.module_from_spec(spec)
loader.exec_module(server)

class CatalogFlowCoreTests(unittest.TestCase):
    def test_number_normalization(self):
        self.assertEqual(server.num("$1,234.50"), 1234.5)
        self.assertIsNone(server.num("N/A"))

    def test_auto_mapping(self):
        headers = ["SKU", "Product Name", "Price", "Inventory Qty"]
        mapping = server.auto_map(headers)
        self.assertEqual(mapping["sku"], "SKU")
        self.assertEqual(mapping["name"], "Product Name")
        self.assertEqual(mapping["price"], "Price")
        self.assertEqual(mapping["stock"], "Inventory Qty")

    def test_quality_metrics(self):
        rows = [
            {"SKU": "A", "Product Name": "One"},
            {"SKU": "A", "Product Name": "One"},
            {"SKU": "B", "Product Name": ""},
        ]
        mapping = {"sku": "SKU", "name": "Product Name"}
        q = server.quality_metrics(rows, ["SKU", "Product Name"], mapping)
        self.assertEqual(q["duplicate_rows"], 1)
        self.assertEqual(q["missing_cells"], 1)

if __name__ == "__main__":
    unittest.main()
