import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import png
from pyexpect import expect

from mariner.server import utils
from mariner.server.utils import retry


class RetryTest(TestCase):
    num_attempts: int = 0

    def setUp(self) -> None:
        self.sleep_patcher = patch("mariner.server.utils.time.sleep")
        self.sleep_patcher.start()

    def tearDown(self) -> None:
        self.sleep_patcher.stop()

    def test_fail_all_retries(self) -> None:
        def _always_fail() -> None:
            self.num_attempts += 1
            raise Exception()

        self.num_attempts = 0
        with self.assertRaises(Exception):
            retry(
                _always_fail,
                Exception,
                num_retries=2,
            )
        self.assertEqual(self.num_attempts, 3)

    def test_catch_a_different_exception(self) -> None:
        class A(Exception): ...  # noqa: E701

        class B(Exception): ...  # noqa: E701

        def _always_fail_with_b() -> None:
            self.num_attempts += 1
            raise B()

        self.num_attempts = 0
        with self.assertRaises(B):
            retry(
                _always_fail_with_b,
                A,
                num_retries=2,
            )
        self.assertEqual(self.num_attempts, 1)

    def test_success_fully_returns_after_two_attempts(self) -> None:
        def _fails_sometimes() -> int:
            self.num_attempts += 1
            if self.num_attempts == 1:
                raise Exception()
            return 42

        self.num_attempts = 0
        ret = retry(
            _fails_sometimes,
            Exception,
            num_retries=1,
        )
        self.assertEqual(self.num_attempts, 2)
        self.assertEqual(ret, 42)


class _CountingFormat:
    """Stands for a file format: says what the file holds, and counts reads."""

    reads = 0

    @classmethod
    def read(cls, path: Path) -> str:
        cls.reads += 1
        return path.read_bytes().decode()

    @classmethod
    def read_preview(cls, path: Path) -> png.Image:
        cls.reads += 1
        shade = len(path.read_bytes())
        return png.from_array([[shade, shade], [shade, shade]], "L")


class CachedReadsTest(TestCase):
    """A file is parsed once, and again whenever it is no longer the same file."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "model.ctb"
        self.path.write_bytes(b"first")
        _CountingFormat.reads = 0
        patcher = patch(
            "mariner.server.utils.get_file_format", return_value=_CountingFormat
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        utils.cache.clear()
        self.addCleanup(utils.cache.clear)

    def test_a_file_is_parsed_once(self) -> None:
        expect(utils.read_cached_sliced_model_file(self.path)).to_equal("first")
        expect(utils.read_cached_sliced_model_file(self.path)).to_equal("first")
        expect(_CountingFormat.reads).to_equal(1)

    def test_a_file_replaced_under_the_same_name_is_parsed_again(self) -> None:
        # A new slice of the same model, sent under the same name.
        utils.read_cached_sliced_model_file(self.path)
        self.path.write_bytes(b"second, longer")
        expect(utils.read_cached_sliced_model_file(self.path)).to_equal(
            "second, longer"
        )
        expect(_CountingFormat.reads).to_equal(2)

    def test_a_file_of_the_same_size_but_another_date_is_parsed_again(self) -> None:
        utils.read_cached_sliced_model_file(self.path)
        self.path.write_bytes(b"other")
        os.utime(self.path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        expect(utils.read_cached_sliced_model_file(self.path)).to_equal("other")

    def test_a_preview_follows_its_file_too(self) -> None:
        first = utils.read_cached_preview(self.path)
        expect(utils.read_cached_preview(self.path)).to_equal(first)
        expect(_CountingFormat.reads).to_equal(1)
        self.path.write_bytes(b"second, longer")
        expect(utils.read_cached_preview(self.path) == first).to_equal(False)
        expect(_CountingFormat.reads).to_equal(2)

    def test_a_missing_file_is_reported_as_missing(self) -> None:
        # Not by an assertion, which disappears when Python runs optimised.
        with self.assertRaises(FileNotFoundError):
            utils.read_cached_sliced_model_file(Path(self.directory.name) / "gone.ctb")
        with self.assertRaises(FileNotFoundError):
            utils.read_cached_preview(Path(self.directory.name))
        expect(_CountingFormat.reads).to_equal(0)

    def test_the_uncached_read_parses_every_time(self) -> None:
        expect(utils.read_sliced_model_file(self.path)).to_equal("first")
        expect(utils.read_sliced_model_file(self.path)).to_equal("first")
        expect(_CountingFormat.reads).to_equal(2)
