from unittest import TestCase

from pyexpect import expect

from mariner.exceptions import (
    CommandNotSent,
    FileNotSelected,
    MarinerException,
    PrintAlreadyRunning,
    PrintJustStarted,
    UnexpectedPrinterResponse,
)


class ExceptionsTest(TestCase):
    def test_every_error_can_be_shown(self) -> None:
        # The web API answers any of them with its title and description.
        errors = (
            UnexpectedPrinterResponse("garbage"),
            FileNotSelected("garbage"),
            CommandNotSent("garbage"),
            PrintAlreadyRunning(),
            PrintJustStarted(),
        )
        for error in errors:
            expect(isinstance(error, MarinerException)).to_equal(True)
            expect(bool(error.get_title())).to_equal(True)
            expect(bool(error.get_description())).to_equal(True)

    def test_the_two_refusals_to_print_say_different_things(self) -> None:
        expect(PrintAlreadyRunning().get_description()).not_to_equal(
            PrintJustStarted().get_description()
        )
