/**
 * Every text of the page, in English: the language the others are
 * translated from. `{name}` marks a blank filled when the text is shown.
 */
export const en = {
  // Around every page
  "app.skipToContent": "Skip to content",
  "nav.main": "Main navigation",
  "nav.dashboard": "Dashboard",
  "nav.files": "Files",
  "title.dashboard": "Dashboard",
  "title.files": "Files",
  "title.notFound": "Page not found",

  // Appearance menu
  "appearance.open": "Appearance",
  "appearance.theme": "Printer theme",
  "appearance.typeface": "Typeface",
  "appearance.language": "Language",
  "font.hyperlegible.hint": "Letters drawn to be told apart",
  "font.opendyslexic.hint": "Weighted letters, for dyslexic readers",

  // Power menu
  "power.open": "Shut down or restart",
  "power.heading": "Computer running Mariner",
  "power.reboot": "Restart",
  "power.rebootConfirm": "Confirm restart?",
  "power.shutdown": "Shut down",
  "power.shutdownConfirm": "Confirm shutdown?",
  "power.rebootAgain": "Press again to restart the computer.",
  "power.shutdownAgain": "Press again to shut the computer down.",
  "power.rebooting":
    "The computer is restarting. This page comes back by itself.",
  "power.shuttingDown": "The computer is shutting down.",

  // Printer state
  "status.idle": "Ready",
  "status.printing": "Printing",
  "status.paused": "Paused",
  "status.offline": "Offline",
  "status.label": "Printer: {status}",

  // Dashboard
  "dashboard.heading": "Printer dashboard",
  "dashboard.connecting": "Connecting to the printer…",
  "dashboard.unreachable.title": "Mariner cannot be reached",
  "dashboard.unreachable.text":
    "Check that the computer running Mariner is switched on and on the network. This page tries again by itself.",
  "dashboard.idle.title": "Ready to print",
  "dashboard.idle.text": "Choose a file on the Files page to start a print.",
  "dashboard.idle.open": "See the files",
  "dashboard.offline.title": "Printer not answering",
  "dashboard.offline.text":
    "Check that the printer is switched on and that its cable to the computer running Mariner is plugged in.",

  // A print under way
  "print.progress": "Print progress",
  "print.currentLayer": "Current layer",
  "print.totalLayers": "Total layers",
  "print.elapsed": "Elapsed (estimate)",
  "print.remaining": "Remaining (estimate)",
  "print.file": "File being printed",
  "print.pause": "Pause",
  "print.resume": "Resume",
  "print.cancel": "Cancel print",
  "print.pausing": "Pausing…",
  "print.resuming": "Resuming…",
  "print.cancelling": "Cancelling…",
  "print.cancel.title": "Cancel this print?",
  "print.cancel.text":
    "{file} is {progress} done. A cancelled print cannot be resumed: it has to be started again from the first layer.",
  "print.cancel.textNoFile":
    "This print is {progress} done. A cancelled print cannot be resumed: it has to be started again from the first layer.",
  "print.cancel.keep": "Do not cancel",
  "print.cancel.confirm": "Cancel the print",
  "print.paused": "Print paused",
  "print.resumed": "Print resumed",
  "print.cancelled": "Print cancelled",
  "print.started": "Print started",

  // Files
  "files.heading": "Files",
  "files.folder": "Folder: {path}",
  "files.newFolder": "New folder",
  "files.upload": "Upload a file",
  "files.uploading": "Uploading {file}: {percent}",
  "files.finishing": "Finishing {file}…",
  "files.uploadProgress": "Upload progress",
  "files.uploaded": "{file} uploaded",
  "files.uploadCancel": "Cancel the upload",
  "files.uploadCancelled": "Upload cancelled",
  "files.loading": "Loading files…",
  "files.error.title": "The files could not be listed",
  "files.error.retry": "Try again",
  "files.empty": "This folder is empty.",
  "files.up": "Up to the folder above",
  "files.openFolder": "Open folder {name}",
  "files.printable": "Printable",
  "files.printTime": "Print time: {time}",
  "files.newFolder.in": "Create a folder in {path}.",
  "files.newFolder.name": "Folder name",
  "files.newFolder.create": "Create",
  "files.newFolder.creating": "Creating…",
  "files.newFolder.created": "Folder created",

  // One file
  "file.details.printable": "Details of a file that can be printed",
  "file.details.other": "Details of a file",
  "file.preview": "Preview of the print",
  "file.layers": "Layers",
  "file.time": "Print time",
  "file.height": "Height",
  "file.delete": "Delete",
  "file.deleting": "Deleting…",
  "file.print": "Start print",
  "file.starting": "Starting…",
  "file.delete.title": "Delete this file?",
  "file.delete.text": "{file} will be deleted for good.",
  "file.delete.confirm": "Delete the file",
  "file.deleted": "{file} deleted",

  // Printer not answering: the reader decides
  "printerOff.title": "Printer not answering",
  "printerOff.text":
    "Go ahead only if the printer is switched off. If it is printing this file, the print will be ruined.",
  "printerOff.replace": "Replace anyway",
  "printerOff.delete": "Delete anyway",

  // Shared
  "common.cancel": "Cancel",
  "common.close": "Close",
  "toasts.region": "Messages",

  // Page not found
  "notFound.heading": "Page not found",
  "notFound.text": "There is nothing at this address.",
  "notFound.home": "Back to the dashboard",

  // What went wrong, by the code the server gives
  "error.network":
    "Mariner cannot be reached. Check that the computer running it is switched on and on the network.",
  "error.unknown": "Something went wrong (error {status}).",
  "error.token_refused": "This page is out of date. Reload it and try again.",
  "error.file_too_large": "This file is larger than Mariner accepts.",
  "error.request_too_large": "This request is larger than Mariner accepts.",
  "error.upload_not_stored":
    "There is not enough space to store this file. Free some space and send it again.",
  "error.folder_too_deep": "Folders cannot be nested any deeper than this.",
  "error.folder_exists": "A folder or a file of this name is already there.",
  "error.name_not_allowed":
    'This name cannot be used. Leave out apostrophes, slashes and the characters \\ : * ? " < > |, do not start or end it with a dot, and keep it under 255 characters.',
  "error.type_not_supported": "This is not a file the printer can print.",
  "error.file_gone":
    "This file is no longer there: it was removed or renamed since the list was shown.",
  "error.folder_not_created":
    "The folder could not be made: its name may be too long, or the drive full.",
  "error.printer_not_answering":
    "The printer did not answer, so Mariner cannot tell whether this file is being printed. It was left untouched.",
  "error.printer_answer_unclear":
    "Mariner could not get a clear answer from the printer, so this file was left untouched. Try again in a moment.",
  "error.host_command_refused":
    "The computer running Mariner did not accept the command.",
  "error.print_in_progress":
    "The printer is already printing. Wait for the print to finish, or cancel it first.",
  "error.print_just_started":
    "A print was started a moment ago. Files are protected for half a minute after a print starts, even if it was cancelled. Try again in a moment.",
  "error.file_in_use":
    "This file is being printed: it cannot be changed until the print is over.",
  "error.print_file_unknown":
    "The printer is printing but does not say which file, so this one was left untouched. Try again in a moment.",
  "error.browser_not_served":
    "This address is for slicers, not for a web browser.",
  "error.printer_error":
    "The printer did not accept the command. Check that it is switched on and that its cable is plugged in.",
  "error.file_unreadable": "This file cannot be read as a file to print.",
  "error.file_read_failed": "This file could not be read from the drive.",
  "error.internal_error": "Mariner ran into an error. Its log says more.",
  "error.cross_site_request":
    "Mariner refused this request as coming from another site.",
  "error.host_not_allowed":
    "Mariner does not answer to the name this page was opened under.",
} as const;

export type TextKey = keyof typeof en;
