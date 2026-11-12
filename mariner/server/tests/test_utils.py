import os
import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import png
from pyexpect import expect

from mariner.file_formats.reading import MalformedFile
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

    lock_was_held = False

    @classmethod
    def _act_out(cls, path: Path) -> None:
        """Some contents stand for something happening during the read."""
        contents = path.read_bytes()
        if contents == b"MALFORMED":
            raise MalformedFile("it says so")
        if contents == b"IOERROR":
            raise OSError(5, "Input/output error")
        if contents == b"REPLACED MEANWHILE":
            path.write_bytes(b"the one that replaced it")
        if contents == b"SLOW":
            time.sleep(0.05)
        if contents.startswith(b"CHANGES EVERY TIME"):
            path.write_bytes(contents + b"!")
        if contents == b"IS THE LOCK HELD":
            cls.lock_was_held = utils._rendering.locked()

    @classmethod
    def read(cls, path: Path) -> str:
        cls.reads += 1
        contents = path.read_bytes().decode()
        cls._act_out(path)
        return contents

    @classmethod
    def read_preview(cls, path: Path) -> png.Image:
        cls.reads += 1
        cls._act_out(path)
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
        utils.empty_cache()
        self.addCleanup(utils.empty_cache)
        # Room is made after every write here; in use, every so many.
        self.every_write = patch.object(utils, "_WRITES_PER_SCAN", 1)
        self.every_write.start()
        self.addCleanup(patch.stopall)

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

    def test_a_file_of_the_same_date_but_another_size_is_parsed_again(self) -> None:
        utils.read_cached_sliced_model_file(self.path)
        date = os.stat(self.path).st_mtime_ns
        self.path.write_bytes(b"longer than the first")
        os.utime(self.path, ns=(date, date))
        expect(utils.read_cached_sliced_model_file(self.path)).to_equal(
            "longer than the first"
        )

    def test_a_date_is_told_apart_below_the_second(self) -> None:
        date = 1_700_000_000_000_000_000
        os.utime(self.path, ns=(date, date))
        utils.read_cached_sliced_model_file(self.path)
        self.path.write_bytes(b"other")
        os.utime(self.path, ns=(date + 1_000_000, date + 1_000_000))
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

    def test_a_file_that_cannot_be_read_is_refused_once_per_version(self) -> None:
        # Finding out can take as long as reading a good file. The listing
        # status of a print asks again every few seconds.
        self.path.write_bytes(b"MALFORMED")
        for _ in range(3):
            with self.assertRaises(MalformedFile) as raised:
                utils.read_cached_sliced_model_file(self.path)
            expect(str(raised.exception)).to_equal("it says so")
        expect(_CountingFormat.reads).to_equal(1)

        self.path.write_bytes(b"sent again, whole")
        expect(utils.read_cached_sliced_model_file(self.path)).to_equal(
            "sent again, whole"
        )

    def test_a_preview_that_cannot_be_made_is_refused_once_per_version(self) -> None:
        self.path.write_bytes(b"MALFORMED")
        for _ in range(3):
            with self.assertRaises(MalformedFile):
                utils.read_cached_preview(self.path)
        expect(_CountingFormat.reads).to_equal(1)

    def test_the_reason_is_logged_once_with_the_name_quoted(self) -> None:
        odd = self.path.with_name("a\u2028b.ctb")
        odd.write_bytes(b"MALFORMED")
        with self.assertLogs("mariner.server.utils", level="WARNING") as logs:
            for _ in range(2):
                with self.assertRaises(MalformedFile):
                    utils.read_cached_sliced_model_file(odd)
        messages = [record.getMessage() for record in logs.records]
        expect(messages).to_equal(["Could not read 'a\\u2028b.ctb': it says so"])

    def test_another_failure_is_not_remembered(self) -> None:
        # A read error of the drive may not happen next time.
        self.path.write_bytes(b"IOERROR")
        for _ in range(2):
            with self.assertRaises(OSError):
                utils.read_cached_sliced_model_file(self.path)
        expect(_CountingFormat.reads).to_equal(2)

    def test_a_file_replaced_while_it_was_read_is_read_again(self) -> None:
        # What was read must not be remembered as the file that is there
        # once the read is over.
        self.path.write_bytes(b"REPLACED MEANWHILE")
        expect(utils.read_cached_sliced_model_file(self.path)).to_equal(
            "the one that replaced it"
        )
        expect(_CountingFormat.reads).to_equal(2)
        expect(utils.read_cached_sliced_model_file(self.path)).to_equal(
            "the one that replaced it"
        )
        expect(_CountingFormat.reads).to_equal(2)

    def _entries(self) -> int:
        return len(os.listdir(utils.cache.cache._path))

    def test_a_replaced_file_takes_the_place_of_the_one_before(self) -> None:
        # What is remembered must not grow with every new slice sent under
        # the same name: past its limit the cache drops entries, and what
        # it drops is then read again at every listing.
        utils.read_cached_sliced_model_file(self.path)
        utils.read_cached_preview(self.path)
        entries = self._entries()
        for round in range(20):
            self.path.write_bytes(b"x" * (round + 10))
            utils.read_cached_sliced_model_file(self.path)
            utils.read_cached_preview(self.path)
        expect(self._entries()).to_equal(entries)

    def test_a_refusal_takes_the_place_of_the_file_before_and_back(self) -> None:
        utils.read_cached_sliced_model_file(self.path)
        entries = self._entries()
        self.path.write_bytes(b"MALFORMED")
        with self.assertRaises(MalformedFile):
            utils.read_cached_sliced_model_file(self.path)
        self.path.write_bytes(b"whole again")
        expect(utils.read_cached_sliced_model_file(self.path)).to_equal("whole again")
        expect(self._entries()).to_equal(entries)

    def test_many_files_stay_remembered(self) -> None:
        # More than the 500 entries the cache library keeps unless told.
        paths = [self.path.with_name(f"{number}.ctb") for number in range(300)]
        for path in paths:
            path.write_bytes(b"x")
            utils.read_cached_sliced_model_file(path)
            utils.read_cached_preview(path)
        _CountingFormat.reads = 0
        for path in paths:
            utils.read_cached_sliced_model_file(path)
            utils.read_cached_preview(path)
        expect(_CountingFormat.reads).to_equal(0)

    def test_requests_arriving_together_share_one_read(self) -> None:
        self.path.write_bytes(b"SLOW")
        for read in (utils.read_cached_preview, utils.read_cached_sliced_model_file):
            _CountingFormat.reads = 0
            threads = [
                threading.Thread(target=read, args=(self.path,)) for _ in range(4)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            expect(_CountingFormat.reads).to_equal(1)

    def test_a_file_that_never_stops_changing_is_not_blamed(self) -> None:
        # It is being written. Not a file to send again: one to wait for.
        self.path.write_bytes(b"CHANGES EVERY TIME")
        with self.assertRaises(OSError) as raised:
            utils.read_cached_sliced_model_file(self.path)
        expect(isinstance(raised.exception, MalformedFile)).to_equal(False)
        expect(_CountingFormat.reads).to_equal(3)

    def test_each_name_and_each_kind_has_its_own_entry(self) -> None:
        folder = Path(self.directory.name)
        key = utils._key("details", self.path)
        expect(key).to_equal(utils._key("details", Path(str(self.path))))
        expect(key).not_to_equal(utils._key("preview", self.path))
        # Names are not folded together in any way: what one filesystem
        # holds for the same name, another holds for two files, and one
        # file answered for with what was read of another is the worse
        # mistake. A name spelled in another case costs one more read.
        for other in ("MODEL.CTB", "modeL.ctb", "mode\u017f.ctb", "\u212aodel.ctb"):
            expect(key).not_to_equal(utils._key("details", folder / other))
        expect(utils._key("details", folder / "Maße.ctb")).not_to_equal(
            utils._key("details", folder / "Masse.ctb")
        )
        # A name that is not valid text still has a key.
        utils._key("details", folder / os.fsdecode(b"\xff\xfe.ctb"))

    def test_small_entries_count_for_the_room_they_take(self) -> None:
        # A few bytes written take a whole block of the drive, or of memory.
        paths = [self.path.with_name(f"{number}.ctb") for number in range(12)]
        with patch.object(utils, "MAX_CACHE_BYTES", 3 * 4096):
            for path in paths:
                path.write_bytes(b"x")
                utils.read_cached_sliced_model_file(path)
                expect(self._count() <= 3).to_equal(True)

    def test_the_number_of_entries_is_limited(self) -> None:
        paths = [self.path.with_name(f"{number}.ctb") for number in range(12)]
        with patch.object(utils, "MAX_CACHE_ENTRIES", 5):
            for path in paths:
                path.write_bytes(b"x")
                utils.read_cached_sliced_model_file(path)
                expect(self._count() <= 5).to_equal(True)
        expect(utils.MAX_CACHE_ENTRIES <= 4096).to_equal(True)

    def test_the_folder_is_not_gone_through_at_every_write(self) -> None:
        # With thousands of files that alone took minutes at start.
        self.every_write.stop()
        paths = [self.path.with_name(f"{number}.ctb") for number in range(32)]
        with patch.object(utils, "_entries", wraps=utils._entries) as scans:
            for path in paths:
                path.write_bytes(b"x")
                utils.read_cached_sliced_model_file(path)
        expect(scans.call_count).to_equal(32 // utils._WRITES_PER_SCAN)

    def _count(self) -> int:
        return len(os.listdir(utils.cache.cache._path))

    def _size(self) -> int:
        folder = utils.cache.cache._path
        return sum(os.path.getsize(os.path.join(folder, n)) for n in os.listdir(folder))

    def test_what_is_remembered_is_limited_in_size(self) -> None:
        # Whatever leaves entries behind: files deleted since, or sent only
        # to fill the place, which by default is in memory.
        paths = [self.path.with_name(f"{number}.ctb") for number in range(12)]
        with patch.object(utils, "MAX_CACHE_BYTES", 4 * 4096):
            for path in paths:
                path.write_bytes(b"x" * 500)
                utils.read_cached_sliced_model_file(path)
                expect(self._count() <= 4).to_equal(True)
                # So that one entry is plainly older than the next.
                time.sleep(0.002)
            # The latest are those kept.
            _CountingFormat.reads = 0
            for path in paths[-3:]:
                utils.read_cached_sliced_model_file(path)
            expect(_CountingFormat.reads).to_equal(0)
            utils.read_cached_sliced_model_file(paths[0])
            expect(_CountingFormat.reads).to_equal(1)

    def test_a_cache_that_cannot_be_written_does_not_cost_a_read_each_time(
        self,
    ) -> None:
        # A full drive, say. The status is asked for every few seconds.
        with patch.object(utils.cache, "set", return_value=False), self.assertLogs(
            "mariner.server.utils", level="WARNING"
        ) as logs:
            for _ in range(3):
                expect(utils.read_cached_sliced_model_file(self.path)).to_equal("first")
            self.path.write_bytes(b"second, longer")
            expect(utils.read_cached_sliced_model_file(self.path)).to_equal(
                "second, longer"
            )
        expect(_CountingFormat.reads).to_equal(2)
        # Said once, not at every request.
        expect(len(logs.records)).to_equal(1)

    def test_an_entry_of_the_version_before_does_not_hide_what_is_kept_here(
        self,
    ) -> None:
        utils.read_cached_sliced_model_file(self.path)
        with patch.object(utils.cache, "set", return_value=False), self.assertLogs(
            "mariner.server.utils", level="WARNING"
        ):
            self.path.write_bytes(b"second, longer")
            for _ in range(3):
                expect(utils.read_cached_sliced_model_file(self.path)).to_equal(
                    "second, longer"
                )
        expect(_CountingFormat.reads).to_equal(2)

    def test_a_cache_that_fails_is_left_alone_for_a_while(self) -> None:
        # Each failed write logs at length and can leave a file behind.
        folder = Path(utils.cache.cache._path)
        (folder / "tmpabc.__wz_cache").write_bytes(b"")
        paths = [self.path.with_name(f"{number}.ctb") for number in range(3)]
        for path in paths:
            path.write_bytes(b"x")
        with patch.object(utils.cache, "set", return_value=False) as stored, patch(
            "mariner.server.utils.time.monotonic", return_value=1000.0
        ) as clock, self.assertLogs("mariner.server.utils", level="WARNING") as logs:
            for path in paths:
                utils.read_cached_sliced_model_file(path)
            # Twice for the first file, and no more.
            expect(stored.call_count).to_equal(2)
            expect(os.listdir(folder)).to_equal([])
            clock.return_value = 1000.0 + utils._CACHE_RETRY_SECS
            self.path.write_bytes(b"later")
            utils.read_cached_sliced_model_file(self.path)
            expect(stored.call_count).to_equal(4)
        # And it is said once, not each time it is tried again.
        expect(len(logs.records)).to_equal(1)

    def test_what_is_kept_here_is_little(self) -> None:
        # A parsed file can weigh megabytes in memory.
        expect(utils._MAX_KEPT_HERE <= 32).to_equal(True)

    def test_the_entry_just_written_is_not_the_one_dropped(self) -> None:
        # Should the clock have stepped back since the others were written.
        utils.read_cached_sliced_model_file(self.path)
        folder = utils.cache.cache._path
        ahead = time.time_ns() + 86_400 * 10**9
        for name in os.listdir(folder):
            os.utime(os.path.join(folder, name), ns=(ahead, ahead))
        other = self.path.with_name("other.ctb")
        other.write_bytes(b"x" * 500)
        with patch.object(utils, "MAX_CACHE_BYTES", self._size() + 10):
            utils.read_cached_sliced_model_file(other)
            _CountingFormat.reads = 0
            utils.read_cached_sliced_model_file(other)
            expect(_CountingFormat.reads).to_equal(0)

    def test_a_cache_folder_that_went_missing_is_made_again(self) -> None:
        folder = utils.cache.cache._path
        utils.read_cached_sliced_model_file(self.path)
        for name in os.listdir(folder):
            os.remove(os.path.join(folder, name))
        os.rmdir(folder)
        self.addCleanup(os.makedirs, folder, exist_ok=True)
        utils.read_cached_sliced_model_file(self.path)
        expect(len(os.listdir(folder))).to_equal(1)

    def test_emptying_removes_everything_kept_there(self) -> None:
        folder = Path(utils.cache.cache._path)
        utils.read_cached_sliced_model_file(self.path)
        # What a write that failed leaves behind.
        (folder / "tmpabc.__wz_cache").write_bytes(b"x")
        utils.empty_cache()
        expect(os.listdir(folder)).to_equal([])

    def test_what_is_remembered_does_not_expire(self) -> None:
        with patch.object(utils.cache, "set", wraps=utils.cache.set) as stored:
            utils.read_cached_sliced_model_file(self.path)
            utils.read_cached_preview(self.path)
        expect([call.kwargs["timeout"] for call in stored.call_args_list]).to_equal(
            [0, 0]
        )

    def test_emptying_leaves_the_files_directory_alone(self) -> None:
        # Should the cache be set to a place that holds the models.
        models = Path(self.directory.name)
        inside = models / "parsed"
        inside.mkdir()
        (inside / "model.ctb").write_bytes(b"x")
        for folder in (models, inside):
            with patch.dict(utils.app.config, {"CACHE_DIR": str(folder)}), patch(
                "mariner.config.get_files_directory", return_value=models
            ), self.assertLogs("mariner.server.utils", level="WARNING"):
                utils.empty_cache()
        expect(sorted(os.listdir(models))).to_equal(["model.ctb", "parsed"])
        expect(os.listdir(inside)).to_equal(["model.ctb"])

    def test_emptying_does_not_follow_a_link(self) -> None:
        elsewhere = Path(self.directory.name) / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "kept").write_bytes(b"x")
        link = Path(self.directory.name) / "link"
        os.symlink(elsewhere, link)
        with patch.dict(utils.app.config, {"CACHE_DIR": str(link)}), self.assertLogs(
            "mariner.server.utils", level="WARNING"
        ):
            utils.empty_cache()
        expect(os.listdir(elsewhere)).to_equal(["kept"])

    def test_emptying_a_folder_that_is_not_there_is_not_an_error(self) -> None:
        gone = str(Path(self.directory.name) / "gone")
        with patch.dict(utils.app.config, {"CACHE_DIR": gone}):
            utils.empty_cache()

    def test_previews_are_rendered_one_at_a_time(self) -> None:
        self.path.write_bytes(b"IS THE LOCK HELD")
        utils.read_cached_preview(self.path)
        expect(_CountingFormat.lock_was_held).to_equal(True)
        expect(utils._rendering.locked()).to_equal(False)

    def test_the_uncached_read_parses_every_time(self) -> None:
        expect(utils.read_sliced_model_file(self.path)).to_equal("first")
        expect(utils.read_sliced_model_file(self.path)).to_equal("first")
        expect(_CountingFormat.reads).to_equal(2)
