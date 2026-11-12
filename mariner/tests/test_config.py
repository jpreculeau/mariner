from pathlib import Path

from pyexpect import expect
from pyfakefs.fake_filesystem_unittest import TestCase

from mariner import config


class ConfigurationTest(TestCase):
    def setUp(self) -> None:
        config._get_config.cache_clear()
        self.setUpPyfakefs()

    def test_default_values(self) -> None:
        expect(config.get_files_directory()).to_equal(Path("/mnt/usb_share"))

        expect(config.get_printer_display_name()).to_equal(None)
        expect(config.get_printer_serial_port()).to_equal("/dev/serial0")
        expect(config.get_printer_baudrate()).to_equal(115200)

        expect(config.get_http_host()).to_equal("0.0.0.0")
        expect(config.get_http_port()).to_equal(5050)

        expect(config.get_cache_directory()).to_equal("/tmp/mariner/")

        expect(config.get_max_upload_bytes()).to_equal(2048 * 1024 * 1024)
        expect(config.get_spool_directory()).to_equal("/var/tmp")

    def test_can_customize_the_upload_limit_and_where_uploads_wait(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[http]
max_upload_size_mb = 300
spool_directory = "/srv/spool"
            """,
        )
        expect(config.get_max_upload_bytes()).to_equal(300 * 1024 * 1024)
        expect(config.get_spool_directory()).to_equal("/srv/spool")

    def test_host_names_can_be_allowed(self) -> None:
        expect(config.get_http_allowed_hosts()).to_equal([])
        config._get_config.cache_clear()
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents='[http]\nallowed_hosts = ["printer.example.org", "*"]\n',
        )
        expect(config.get_http_allowed_hosts()).to_equal(["printer.example.org", "*"])
        self.fs.remove("/etc/mariner/config.toml")
        config._get_config.cache_clear()
        # One name given without the brackets is one name.
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents='[http]\nallowed_hosts = "printer.example.org"\n',
        )
        expect(config.get_http_allowed_hosts()).to_equal(["printer.example.org"])

    def test_an_upload_limit_that_makes_no_sense_is_the_default(self) -> None:
        for number, value in enumerate(("0", "-5", '"big"', "1.5", "true")):
            config._get_config.cache_clear()
            self.fs.create_file(
                "/etc/mariner/config.toml",
                contents=f"[http]\nmax_upload_size_mb = {value}\n",
            )
            expect(config.get_max_upload_bytes()).to_equal(2048 * 1024 * 1024)
            self.fs.remove("/etc/mariner/config.toml")

    def test_can_customize_files_directory(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
files_directory = "/var/mariner"
            """,
        )
        expect(config.get_files_directory()).to_equal(Path("/var/mariner"))

    def test_can_customize_printer_settings(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[printer]
display_name = "Elegoo Mars"
serial_port = "/dev/ttyUSB0"
baudrate = 9600
            """,
        )
        expect(config.get_printer_display_name()).to_equal("Elegoo Mars")
        expect(config.get_printer_serial_port()).to_equal("/dev/ttyUSB0")
        expect(config.get_printer_baudrate()).to_equal(9600)

    def test_can_customize_http_settings(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[http]
host = "127.0.0.1"
port = 80
            """,
        )
        expect(config.get_http_host()).to_equal("127.0.0.1")
        expect(config.get_http_port()).to_equal(80)

    def test_can_customize_cache_settings(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[cache]
directory = "/dev/shm/mariner/"
            """,
        )
        expect(config.get_cache_directory()).to_equal("/dev/shm/mariner/")
