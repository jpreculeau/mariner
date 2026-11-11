from abc import ABC, abstractmethod


class MarinerException(Exception, ABC):
    @abstractmethod
    def get_title(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_description(self) -> str:
        raise NotImplementedError


class UnexpectedPrinterResponse(MarinerException):
    def __init__(self, response: str) -> None:
        self.response = response

    def get_title(self) -> str:
        return "Unexpected Printer Response"

    def get_description(self) -> str:
        return f"The printer returned an unexpected response: {repr(self.response)}"


class FileNotSelected(UnexpectedPrinterResponse):
    """The printer did not confirm selecting a file.

    Raised instead of the plain UnexpectedPrinterResponse so that callers can
    tell a print that cannot have started (the file was never selected) from
    one whose start command was sent.
    """


class CommandNotSent(UnexpectedPrinterResponse):
    """The line failed before any of a command was written to it.

    Raised instead of the plain UnexpectedPrinterResponse so that callers
    can tell a command the printer cannot have received from one whose
    answer was lost.
    """


class PrintAlreadyRunning(MarinerException):
    """A print was asked for while the printer reports one under way."""

    def __str__(self) -> str:
        return "The printer is already printing."


class PrintJustStarted(PrintAlreadyRunning):
    """A print was asked for a moment after Mariner started another.

    The printer has yet to report that first print, so there is nothing to
    cancel: the way out is to wait for the printer to report it, or for
    half a minute if it never does.
    """

    def __str__(self) -> str:
        return "A print was started a moment ago."


class UnexpectedResponseLineNumber(MarinerException):
    def __init__(self, response: str, expected: str) -> None:
        self.response = response
        self.expected = expected

    def get_title(self) -> str:
        return "Incorrect Response Line Number"

    def get_description(self) -> str:
        return (
            "The printer returned response for command "
            + f"{repr(self.response)} when Mariner3D "
            + "expected Line"
            + "Number {self.expected}"
        )
