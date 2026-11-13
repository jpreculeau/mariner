"""The certificate Mariner's page is served with."""

import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

from pyexpect import expect

from mariner import config
from mariner.server import certificate, tls


@skipUnless(shutil.which("openssl"), "needs the openssl command")
class CertificateTest(TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def _made(self) -> tuple:
        made = certificate.self_signed(self.folder)
        assert made is not None
        return made

    def test_one_is_made_that_a_server_can_use(self) -> None:
        cert, key = self._made()
        tls.context(cert, key)
        expect(Path(cert).parent).to_equal(self.folder)

    def test_its_key_is_for_mariner_s_account_alone(self) -> None:
        _, key = self._made()
        expect(stat.S_IMODE(os.stat(key).st_mode)).to_equal(0o600)

    def test_it_names_the_computer_as_it_is_reached(self) -> None:
        with patch("socket.gethostname", return_value="saturn"):
            cert, _ = self._made()
        said = subprocess.run(
            ["openssl", "x509", "-noout", "-ext", "subjectAltName", "-in", cert],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for name in ("DNS:saturn", "DNS:saturn.local", "DNS:localhost"):
            expect(name in said).to_equal(True)
        expect("IP Address:127.0.0.1" in said).to_equal(True)

    def test_it_names_the_addresses_of_the_computer(self) -> None:
        with patch.object(certificate, "_addresses", return_value=["192.168.1.20"]):
            cert, _ = self._made()
        expect(
            "IP Address:192.168.1.20" in self._said(cert, "subjectAltName")
        ).to_equal(True)

    def test_it_does_not_last_longer_than_browsers_take(self) -> None:
        cert, _ = self._made()
        ends = subprocess.run(
            ["openssl", "x509", "-noout", "-checkend", str(398 * 86400), "-in", cert],
            capture_output=True,
        )
        # Run out by then.
        expect(ends.returncode).to_equal(1)

    def _said(self, cert: str, extension: str) -> str:
        return subprocess.run(
            ["openssl", "x509", "-noout", "-ext", extension, "-in", cert],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def test_a_key_of_the_owner_s_under_a_password_is_not_asked_for(self) -> None:
        # Nobody is there to type it when Mariner starts: said in the
        # log, and the page served with a certificate of Mariner's own.
        own = self.folder / "own"
        own.mkdir()
        cert, key = str(own / "c.pem"), str(own / "k.pem")
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:prime256v1",
                "-passout",
                "pass:secret",
                "-keyout",
                key,
                "-out",
                cert,
                "-days",
                "2",
                "-subj",
                "/CN=localhost",
            ],
            check=True,
            capture_output=True,
        )
        with patch.object(config, "get_https_certificate", return_value=cert):
            with patch.object(config, "get_https_key", return_value=key):
                with self.assertLogs(
                    "mariner.server.certificate", level="ERROR"
                ) as logged:
                    used = certificate.in_use(self.folder)
        expect(used == (cert, key)).to_equal(False)
        said = " ".join(logged.output)
        expect(key in said or cert in said).to_equal(True)

    def test_a_name_that_is_not_one_does_not_keep_it_from_being_made(self) -> None:
        with patch("socket.gethostname", return_value="my printer; rm -rf"):
            cert, key = self._made()
        tls.context(cert, key)

    def test_the_one_that_is_there_is_kept(self) -> None:
        # A browser told to trust it would be asked again at each start.
        cert, _ = self._made()
        first = Path(cert).read_bytes()
        again, _ = self._made()
        expect(Path(again).read_bytes()).to_equal(first)

    def test_one_whose_key_is_gone_is_made_again(self) -> None:
        cert, key = self._made()
        first = Path(cert).read_bytes()
        os.unlink(key)
        with self.assertLogs("mariner.server.certificate", level="WARNING"):
            cert, key = self._made()
        expect(Path(cert).read_bytes() == first).to_equal(False)
        tls.context(cert, key)

    def test_one_whose_key_is_another_s_is_made_again(self) -> None:
        cert, key = self._made()
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        _, another_key = certificate.self_signed(Path(other.name))  # type: ignore
        shutil.copyfile(another_key, key)
        with self.assertLogs("mariner.server.certificate", level="WARNING"):
            cert, key = self._made()
        tls.context(cert, key)

    def test_one_about_to_run_out_is_made_again(self) -> None:
        with patch.object(certificate, "_LASTS_DAYS", 2):
            cert, _ = self._made()
        first = Path(cert).read_bytes()
        with self.assertLogs("mariner.server.certificate", level="WARNING"):
            cert, _ = self._made()
        expect(Path(cert).read_bytes() == first).to_equal(False)

    def test_without_the_openssl_command_there_is_none(self) -> None:
        with patch("shutil.which", return_value=None):
            with self.assertLogs("mariner.server.certificate", level="WARNING"):
                expect(certificate.self_signed(self.folder)).to_equal(None)

    def test_the_owner_s_own_is_used_as_it_is(self) -> None:
        cert, key = self._made()
        with patch.object(config, "get_https_certificate", return_value=cert):
            with patch.object(config, "get_https_key", return_value=key):
                elsewhere = self.folder / "state"
                elsewhere.mkdir()
                expect(certificate.in_use(elsewhere)).to_equal((cert, key))
        expect(list(elsewhere.iterdir())).to_equal([])

    def test_the_owner_s_own_that_cannot_be_used_gives_way_to_one_made(self) -> None:
        # Said loudly, and the page stays encrypted.
        with patch.object(config, "get_https_certificate", return_value="/nowhere"):
            with patch.object(config, "get_https_key", return_value="/nowhere"):
                with self.assertLogs("mariner.server.certificate", level="ERROR"):
                    cert, key = certificate.in_use(self.folder)  # type: ignore
        tls.context(cert, key)
        expect(Path(cert).parent).to_equal(self.folder)

    def test_a_file_that_is_missing_is_not_said_to_be_under_a_password(self) -> None:
        with patch.object(config, "get_https_certificate", return_value="/nowhere"):
            with patch.object(config, "get_https_key", return_value="/nowhere"):
                with self.assertLogs(
                    "mariner.server.certificate", level="ERROR"
                ) as logged:
                    certificate.in_use(self.folder)
        said = " ".join(logged.output)
        expect("No such file" in said).to_equal(True)
        expect("must not be kept under a password" in said).to_equal(False)

    def test_switched_off_there_is_none(self) -> None:
        with patch.object(config, "get_https_enabled", return_value=False):
            expect(certificate.in_use(self.folder)).to_equal(None)
        expect(list(self.folder.iterdir())).to_equal([])
