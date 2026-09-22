import asyncio
import tempfile
import unittest
from pathlib import Path

from services.storage import AttachmentStorage


class TestAttachmentStorage(unittest.TestCase):
    def test_local_upload_and_download_url(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = AttachmentStorage(directory)
            key = asyncio.run(storage.upload_rfq_attachment(b"rfq-data", "quote.pdf", "application/pdf"))
            url = asyncio.run(storage.get_presigned_download_url(key))

            self.assertTrue(key.startswith("rfq/"))
            self.assertTrue(Path(directory, key).is_file())
            self.assertTrue(url.startswith("file:"))

    def test_s3_upload_and_presigned_url(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = AttachmentStorage(directory)
            storage.bucket_name = "rfq-bucket"
            calls = []

            class FakeS3:
                def put_object(self, **kwargs):
                    calls.append(("put_object", kwargs))

                def generate_presigned_url(self, *args, **kwargs):
                    calls.append(("generate_presigned_url", args, kwargs))
                    return "https://s3.example.test/presigned"

            storage._client = lambda: FakeS3()
            key = asyncio.run(storage.upload_rfq_attachment(b"rfq-data", "quote.pdf", "application/pdf"))
            url = asyncio.run(storage.get_presigned_download_url(key))

            self.assertEqual(url, "https://s3.example.test/presigned")
            self.assertEqual(calls[0][0], "put_object")
            self.assertEqual(calls[0][1]["Bucket"], "rfq-bucket")
            self.assertEqual(calls[0][1]["ContentType"], "application/pdf")
            self.assertEqual(calls[1][0], "generate_presigned_url")


if __name__ == "__main__":
    unittest.main()
