import unittest
from unittest.mock import MagicMock, patch

import services.firestore_client as fc


class TestFirestoreClient(unittest.TestCase):
    def test_get_history_paginated_handles_no_db(self):
        # Ensure it raises when DB not initialized
        with patch.object(fc, "_firestore_db", None, create=True):
            with self.assertRaises(RuntimeError):
                fc.get_history_paginated("room1")

    def test_add_message_calls_collection_add(self):
        mock_add = MagicMock()
        mock_collection = MagicMock()
        mock_collection.add = mock_add
        mock_db = MagicMock()
        mock_db.collection.return_value = mock_collection

        with patch.object(fc, "_firestore_db", mock_db, create=True):
            fc.add_message("room1", "user", "hello")
            mock_db.collection.assert_called_with("messages")
            mock_add.assert_called()


if __name__ == "__main__":
    unittest.main()
