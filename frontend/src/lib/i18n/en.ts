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
  "title.signIn": "Sign in",
  "title.choosePassword": "Choose a password",
  "title.settings": "Settings",
  "nav.settings": "Settings",

  "access.checking": "Opening Mariner…",
  "access.refused.title": "Mariner did not open its page",
  "access.shut.title": "Mariner cannot open its page",
  "access.shut.text":
    "It cannot use the folder it keeps its password in, or the password kept there, so it lets nobody in rather than anybody. On the computer it runs on, Mariner's log says which folder: give it and what it holds to the account Mariner runs under, make sure it can be written, and restart Mariner. This page then opens by itself.",
  "signIn.signedOut": "Your session is over. Sign in again.",
  "signIn.heading": "Sign in to Mariner",
  "signIn.password": "Password",
  "signIn.submit": "Sign in",
  "signIn.submitting": "Signing in…",
  "signIn.lost":
    "Password lost? On the computer Mariner runs on, run “sudo mariner reset-password”, or put an empty file named “reset-password” on the boot drive of its card and restart it. A new one is then chosen here.",
  "signIn.code": "One-time code",
  "signIn.code.hint": "The six digits your phone gives.",
  "signIn.code.missing": "Type the code your phone gives.",
  "signIn.wrongEither":
    "This is not the password, or not the code of the moment.",
  "internet.noCode.heading": "Signing in from the Internet is not set up",
  "internet.noCode.text":
    "From the Internet, Mariner asks for a one-time code besides the password, and none is set up. Sign in from the local network and set it up in the settings.",
  "internet.notSetUp.heading": "Mariner is not set up yet",
  "internet.notSetUp.text":
    "Its password is chosen from the local network, not from the Internet.",
  "choose.heading": "Choose a password",
  "choose.intro":
    "It will be asked of anyone who opens this page. Slicers (UVtools, ChiTuBox) send files without it: their access can be switched off in the settings.",
  "choose.cleared": "Mariner's password was cleared. Choose a new one.",
  "choose.new": "New password",
  "choose.hint": "At least 14 characters. A few words make a good one.",
  "choose.repeat": "Repeat the password",
  "choose.submit": "Set the password",
  "choose.submitting": "Setting the password…",
  "choose.mismatch": "The two passwords are not the same.",

  "settings.heading": "Settings",
  "settings.loading": "Fetching the settings…",
  "settings.loadError": "The settings could not be fetched",
  "settings.saved": "Saved",
  "settings.printer": "Printer",
  "settings.name": "Name shown for the printer",
  "settings.name.hint":
    "Shown on the dashboard. Leave it empty to use the name in the configuration file.",
  "settings.name.save": "Save the name",
  "settings.slicers": "Slicers",
  "settings.slicers.intro":
    "Slicers send files and start prints over the network without the password: they cannot give one. Switch off what you do not use.",
  "settings.uvtools": "UVtools",
  "settings.uvtools.hint":
    "Files and commands sent by UVtools, on the port Mariner keeps in the clear for slicers.",
  "settings.sdcp": "ChiTuBox (SDCP)",
  "settings.sdcp.hint":
    "The network printing ChiTuBox speaks: discovery, files and commands on ports 3000 and 3030.",
  "settings.files": "Files",
  "settings.assumeOff": "Do not ask when the printer does not answer",
  "settings.assumeOff.hint":
    "Replacing or deleting a file then goes ahead when the printer is silent, as if you had confirmed that it is switched off. A file being printed is still protected when the printer does answer.",
  "settings.restartNeeded":
    "This change takes effect when Mariner is started again.",
  "settings.restartByHand":
    "Restart Mariner the way it was started for it to take effect.",
  "settings.restart": "Restart Mariner",
  "settings.restarting": "Restarting…",
  "settings.restarted":
    "Mariner is restarting. This page comes back by itself.",
  "settings.back": "Mariner is back.",
  "settings.notBack":
    "Mariner is not back yet. Check that it is running, then reload this page.",
  "settings.code": "One-time code",
  "settings.code.none":
    "None is set up: nobody can sign in from the Internet. On the local network the password is enough.",
  "settings.code.set":
    "A one-time code is set up: it is asked for, besides the password, when signing in from the Internet.",
  "settings.code.localOnly":
    "It is set up and removed from the local network alone.",
  "settings.code.setUp": "Set up a one-time code",
  "settings.code.again": "Set it up on another phone",
  "settings.code.remove": "Remove the one-time code",
  "settings.code.how":
    "In an application that gives one-time codes (Aegis, FreeOTP, Google Authenticator…), add an account with this key, then type the code it gives.",
  "settings.code.open": "Open in the phone's application",
  "settings.code.given": "Code given by the phone",
  "settings.code.given.hint": "Six digits, new every half minute.",
  "settings.code.confirm": "Confirm",
  "settings.code.cancel": "Cancel",
  "settings.code.done": "The one-time code is set up.",
  "settings.code.remove.what":
    "Without it, nobody signs in from the Internet any more. Type the password to remove it.",
  "settings.code.remove.confirm": "Remove it",
  "settings.code.removed": "The one-time code was removed.",
  "settings.journal": "Recent sign-ins",
  "journal.caption": "Recent sign-ins and attempts",
  "journal.loading": "Reading…",
  "journal.unread": "The journal could not be read.",
  "journal.none": "Nothing yet.",
  "journal.when": "When",
  "journal.what": "What",
  "journal.where": "Where from",
  "journal.local": "Local network ({address})",
  "journal.internet": "Internet ({address})",
  "journal.tried.one":
    "{count} wrong password was sent since your previous visit.",
  "journal.tried.many":
    "{count} wrong passwords were sent since your previous visit.",
  "journal.signed_in": "Signed in",
  "journal.wrong_password": "Wrong password",
  "journal.sign_in_closed": "Sign-in closed from the Internet",
  "journal.password_chosen": "Password chosen",
  "journal.password_changed": "Password changed",
  "journal.code_set": "One-time code set up",
  "journal.code_removed": "One-time code removed",
  "settings.password": "Password",
  "settings.password.current": "Current password",
  "settings.password.repeat": "Repeat the new password",
  "settings.password.change": "Change the password",
  "settings.password.changed":
    "Password changed. Other browsers were signed out.",
  "settings.signOut": "Sign out",

  // Appearance menu
  "appearance.open": "Appearance",
  "appearance.theme": "Printer theme",
  "appearance.typeface": "Typeface",
  "appearance.language": "Language",
  "font.hyperlegible.hint": "Letters drawn to be told apart",
  "font.opendyslexic.hint": "Weighted letters, for dyslexic readers",

  // Power menu
  "power.open": "Shut down or restart",
  "power.localOnly":
    "The computer is shut down or restarted from the local network alone.",
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
  "power.rebootAsking": "Restarting…",
  "power.shutdownAsking": "Shutting down…",
  "power.noAnswer":
    "Mariner did not answer: the computer may be going down, or may not have been asked. Check before unplugging it.",

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
  "files.uploadRegion": "File being sent",
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
  "error.wrong_password": "This is not the password.",
  "error.too_many_attempts":
    "Too many wrong passwords. Try again in {seconds} s.",
  "error.code_not_set":
    "Signing in from the Internet takes a one-time code besides the password, and none is set up. Set it up from the local network, in Mariner's settings.",
  "error.wrong_code":
    "This is not the code of the moment. Check that the phone took the key in, and that its clock is right.",
  "error.sign_in_closed":
    "Too many wrong passwords were sent from the Internet. Signing in from there is closed for {minutes} min; it works from the local network.",
  "error.password_too_common":
    "This password is among the first anyone would try. Choose another.",
  "error.state_unavailable":
    "Mariner cannot use the folder it keeps its password in, or the password kept there, so its page stays shut.",
  "error.password_too_short": "A password has at least 14 characters.",
  "error.password_too_long": "A password has at most 1024 characters.",
  "error.password_missing": "No password was given.",
  "error.password_already_set":
    "A password has already been chosen. Sign in with it.",
  "error.password_not_set": "No password has been chosen yet.",
  "error.https_required":
    "Mariner's page is served over HTTPS, and answers nothing of its own in the clear. Open it at its https:// address.",
  "error.local_network_only":
    "This is done from the local network alone, not from the Internet.",
  "error.state_not_written":
    "Mariner could not keep this: the folder it keeps its password and settings in cannot be written. The drive may be full or read-only. Nothing was changed.",
  "error.login_required": "Sign in first.",
  "error.setting_not_valid": "This setting was not taken.",
  "error.restart_not_available":
    "Mariner is not run as a service here: restart it the way it was started.",
  "error.token_refused": "This page is out of date. Reload it and try again.",
  "error.file_too_large": "This file is larger than Mariner accepts.",
  "error.request_too_large": "This request is larger than Mariner accepts.",
  "error.upload_not_stored":
    "There is not enough space to store this file. Free some space and send it again.",
  "error.folder_too_deep": "Folders cannot be nested any deeper than this.",
  "error.folder_exists": "A folder or a file of this name is already there.",
  "error.name_not_allowed":
    'This name cannot be used. Leave out apostrophes, slashes and the characters \\ : * ? " < > |, do not end it with a dot, and keep it under 255 characters.',
  "error.name_is_a_folder":
    "A folder already has this name: a file cannot take its place.",
  "error.upload_unanswered":
    "Mariner did not answer after the file was sent. Look at the list: the file may be there.",
  "error.type_not_supported":
    "This is not a file the printer can print. Mariner takes: {kinds}.",
  "error.folder_gone":
    "This folder is no longer there: it was removed or renamed since the list was shown.",
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
