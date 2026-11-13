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

        # Not in /tmp: any account can make a folder there before Mariner
        # does, and what is there is gone at each restart.
        expect(config.get_cache_directory()).to_equal("/var/cache/mariner")
        expect(config.get_state_directory()).to_equal("/var/lib/mariner")
        # Kept with what lasts, unless a place is named for it.
        expect(config.get_sdcp_history_path()).to_equal(None)

        expect(config.get_max_upload_bytes()).to_equal(2048 * 1024 * 1024)
        expect(config.get_spool_directory()).to_equal("/var/tmp")

        # The page is encrypted unless it is said not to be.
        expect(config.get_https_enabled()).to_equal(True)
        expect(config.get_https_port()).to_equal(5443)
        expect(config.get_https_certificate()).to_equal(None)
        expect(config.get_https_key()).to_equal(None)

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

    def test_one_address_of_mariner_s_page_can_be_given_alone(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents='[http]\nallowed_origins = "https://printer.example.org"\n',
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

    def test_can_customize_https_settings(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[https]
enabled = false
port = 443
certificate = "/etc/ssl/printer.pem"
key = "/etc/ssl/private/printer.key"
            """,
        )
        expect(config.get_https_enabled()).to_equal(False)
        expect(config.get_https_port()).to_equal(443)
        expect(config.get_https_certificate()).to_equal("/etc/ssl/printer.pem")
        expect(config.get_https_key()).to_equal("/etc/ssl/private/printer.key")

    def test_https_settings_that_are_passed_over_are_named(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[https]
enabled = "no"
certificate = "/etc/ssl/printer.pem"
            """,
        )
        # Not switched off by something that is neither true nor false:
        # the page would go in the clear without anyone having said so.
        expect(config.get_https_enabled()).to_equal(True)
        said = " ".join(config.ignored_settings())
        expect("[https] enabled" in said).to_equal(True)
        # One without the other is of no use.
        expect(config.get_https_certificate()).to_equal(None)
        expect("[https] certificate" in said).to_equal(True)

    def test_nothing_is_said_of_the_internet_by_default(self) -> None:
        expect(config.get_local_networks()).to_equal([])
        expect(config.get_not_local()).to_equal([])
        expect(config.get_host_commands_from_internet()).to_equal(False)

    def test_can_say_what_is_local_and_what_is_not(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[internet]
local_networks = ["203.0.113.0/24"]
not_local = ["192.168.1.1", "127.0.0.0/8"]
host_commands = true
            """,
        )
        expect(config.get_local_networks()).to_equal(["203.0.113.0/24"])
        expect(config.get_not_local()).to_equal(["192.168.1.1", "127.0.0.0/8"])
        expect(config.get_host_commands_from_internet()).to_equal(True)
        expect(config.ignored_settings()).to_equal([])

    def test_internet_settings_that_are_passed_over_are_named(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[internet]
local_networks = ["203.0.113.0/24", "everything"]
not_local = "192.168.1.1"
host_commands = "yes"
            """,
        )
        # What can be read is used, the rest is said.
        expect(config.get_local_networks()).to_equal(["203.0.113.0/24"])
        expect(config.get_not_local()).to_equal([])
        # Not allowed by something that is neither true nor false.
        expect(config.get_host_commands_from_internet()).to_equal(False)
        said = " ".join(config.ignored_settings())
        expect("[internet] local_networks" in said).to_equal(True)
        expect("'everything'" in said).to_equal(True)
        expect("[internet] not_local" in said).to_equal(True)
        expect("[internet] host_commands" in said).to_equal(True)

    def test_a_port_for_https_that_is_not_one_is_the_default(self) -> None:
        for given in ('"abc"', "70000", "0", "true"):
            config._get_config.cache_clear()
            self.fs.create_file(
                "/etc/mariner/config.toml", contents=f"[https]\nport = {given}\n"
            )
            expect(config.get_https_port()).to_equal(5443)
            expect("[https] port" in " ".join(config.ignored_settings())).to_equal(True)
            self.fs.remove("/etc/mariner/config.toml")

    def test_can_say_where_things_are_kept(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[state]
directory = "/srv/mariner"

[sdcp]
history_path = "/srv/history.json"
            """,
        )
        expect(config.get_state_directory()).to_equal("/srv/mariner")
        expect(config.get_sdcp_history_path()).to_equal(Path("/srv/history.json"))

    def test_can_customize_cache_settings(self) -> None:
        self.fs.create_file(
            "/etc/mariner/config.toml",
            contents="""
[cache]
directory = "/dev/shm/mariner/"
            """,
        )
        expect(config.get_cache_directory()).to_equal("/dev/shm/mariner/")
