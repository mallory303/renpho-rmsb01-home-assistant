"""Regression tests for Home Assistant's active-coordinator method contract."""

import ast
import unittest
from pathlib import Path

COORDINATOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "renpho_rmsb01"
    / "coordinator.py"
)


class CoordinatorContractTest(unittest.TestCase):
    def test_measurement_callback_does_not_override_ha_debouncer(self) -> None:
        """HA's own no-argument _async_poll must remain the debounce target."""
        tree = ast.parse(COORDINATOR_PATH.read_text())
        coordinator = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "RenphoCoordinator"
        )
        methods = {
            node.name: node for node in coordinator.body
            if isinstance(node, ast.AsyncFunctionDef)
        }
        self.assertNotIn("_async_poll", methods)
        self.assertIn("_async_measure", methods)
        self.assertEqual(
            [argument.arg for argument in methods["_async_measure"].args.args],
            ["self", "service_info"],
        )

        init = next(
            node for node in coordinator.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        )
        poll_keywords = [
            keyword for statement in ast.walk(init)
            if isinstance(statement, ast.Call)
            for keyword in statement.keywords
            if keyword.arg == "poll_method"
        ]
        self.assertEqual(len(poll_keywords), 1)
        callback = poll_keywords[0].value
        self.assertIsInstance(callback, ast.Attribute)
        self.assertEqual(callback.attr, "_async_measure")
        self.assertIsInstance(callback.value, ast.Name)
        self.assertEqual(callback.value.id, "self")


if __name__ == "__main__":
    unittest.main()
