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

    def test_addresses_of_mariner_s_page_can_be_listed(self) -> None:
        expect(config.get_http_allowed_origins()).to_equal([])
        config._get_config.cache_clear()
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents='[http]\nallowed_origins = ["https://printer.example.org"]\n',
        )
        expect(config.get_http_allowed_origins()).to_equal(
            ["https://printer.example.org"]
        )

    def test_slicer_interfaces_can_be_switched_off(self) -> None:
        expect(config.get_uvtools_enabled()).to_equal(True)
        expect(config.get_sdcp_enabled()).to_equal(True)
        config._get_config.cache_clear()
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="[uvtools]\nenabled = false\n[sdcp]\nenabled = false\n",
        )
        expect(config.get_uvtools_enabled()).to_equal(False)
        expect(config.get_sdcp_enabled()).to_equal(False)

    def test_a_switch_set_to_something_else_than_true_or_false_is_off(self) -> None:
        # Written "false" between quotes, it would otherwise count as on.
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents='[uvtools]\nenabled = "false"\n[sdcp]\nenabled = "no"\n',
        )
        expect(config.get_uvtools_enabled()).to_equal(False)
        expect(config.get_sdcp_enabled()).to_equal(False)

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

    def test_settings_that_are_passed_over_are_named(self) -> None:
        expect(config.ignored_settings()).to_equal([])
        config._get_config.cache_clear()
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents='[http]\nmax_upload_size_mb = "4096"\n'
            '[uvtools]\nenabled = "false"\n[sdcp]\nenabled = 1\n',
        )
        named = " ".join(config.ignored_settings())
        for setting in ("max_upload_size_mb", "[uvtools] enabled", "[sdcp] enabled"):
            expect(setting in named).to_equal(True)

    def test_names_and_addresses_that_can_never_match_are_named(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="[http]\n"
            'allowed_hosts = ["good.example.org", "*", "evil.com:5000", '
            '"*.evil.com", "http://evil.com"]\n'
            'allowed_origins = ["https://good.example.org:8443", '
            '"printer.example.org", "*"]\n',
        )
        named = config.ignored_settings()
        expect(len(named)).to_equal(5)
        text = " ".join(named)
        for entry in ("evil.com:5000", "*.evil.com", "http://evil.com"):
            expect(f"allowed_hosts entry {entry!r}" in text).to_equal(True)
        for entry in ("printer.example.org", "*"):
            expect(f"allowed_origins entry {entry!r}" in text).to_equal(True)

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
