## [unreleased]

<!-- This section is written by hand and states the behaviour as it now is.
     Regenerating it from the commit subjects would lose that. -->

### 🚀 Features

- Add support for SDCP
- Serve the page over HTTPS. Mariner speaks TLS itself, on port 5443 (`[https] port`), with a certificate it makes at its first start (the `openssl` command of the system; EC P-256, thirteen months, made again in its last month) or one of the owner's (`[https] certificate` and `key`): the password and everything else no longer cross the network in the clear, and nothing else has to be installed. The port in the clear stays for slicers, which speak nothing else, and sends browsers on to HTTPS; nothing of the page's own is answered there any more (`403` `https_required`), a file included, which is refused before any of it is taken in. Over HTTPS the session's cookie is `Secure` and named `__Host-mariner_session`: a browser signed in before has to sign in again, once. `[https] enabled = false` leaves the page in the clear, for a relay that encrypts in front of Mariner; without the `openssl` command the page stays in the clear and the log says so. A page left open at the address in the clear moves to HTTPS by itself; a browser given `http://` with the port of HTTPS is told so, and one given `https://` with the port in the clear is hung up on at once. A port another program holds is said in one line of the log. Over HTTPS a script signs in as before, without a `Referer`
- Ask for a password. One password opens Mariner's page and everything the page does (files, print commands, shutting down, settings); it is chosen at the first visit and kept as a hash (scrypt) that does not give it away. Who is signed in stays so for a month from the last visit, through restarts; changing the password signs every other page out. After a few wrong passwords the next attempt waits, up to half a minute. A file sent by who is not signed in is refused before any of it is taken in. The interfaces slicers speak (UVtools, SDCP) know nothing of passwords and are not behind this one: each has a switch
- A password that is lost is cleared, not read back: `sudo mariner reset-password`, or a file named `reset-password` on the card's boot drive, obeyed at the next start. The next visit chooses a new one
- `sudo mariner set-password` chooses or replaces the password from a terminal, so that nobody else on the network gets to choose it first; the commands about the password no longer load the server
- Signing in also gives the page a key of its own, sent with each request: the session's cookie, which a browser sends to every program served from the same computer whatever its port, opens nothing without it (except the picture of a file)
- Changing the password makes a new key for sessions: nothing signed with the old one, or forged from a copy of the state directory, is taken. A program that is sent the cookie without the page's key can neither sign the reader out, nor use up their attempts, nor put another of their sessions in front of this one
- Signing out ends the session for good: its cookie is of no use afterwards, and an answer that was on its way no longer signs the browser back in (the cookie is sent again only when the session changes)
- When the state directory cannot be used (it belongs to another account, the drive is read-only), the page says so and lets nobody in, and the slicers' interfaces stay off, instead of offering whoever comes first to choose a password
- Of several passwords chosen at the same moment at the first visit, one is kept and only who chose it is signed in; of several attempts sent together after wrong ones, one is looked at; wrong passwords are counted for each computer (a few of them, the rest together), so that those sent from one do not keep the owner waiting on another; the few passwords everybody tries first are refused
- A slicer interface that is switched off is sent no file either: a large body for UVtools is refused before any of it is taken in. Where no state directory can be made at all, the slicers' interfaces stay off as they do when it cannot be used
- `mariner reset-password` run by an account that may not look into the state directory says so, instead of saying that no password was set; `mariner set-password` run without `sudo` beside the service no longer keeps a password in that account's home, where the service would never read it
- After `mariner set-password` or `mariner reset-password` run while Mariner is running, who signs in next stays signed in through the next restart; the form to sign in left open while the password was cleared offers to choose one instead of saying "wrong password" for ever
- A password or a setting that cannot be kept because the state directory cannot be written (drive full or read-only) is said as that (`state_not_written`), and is not counted as a wrong password
- The page: an answer that refuses, after a restart from the page, is Mariner being back; a page that is open shows that Mariner is shut when what it keeps goes out of reach; a slow answer asked for before signing in no longer puts the form back; a refusal sent again is announced again; the session being over is said once
- A state directory given to another account while Mariner runs, or a password in it that cannot be read (put back from a copy with other rights), shuts the page with the reason, instead of "wrong password" for ever to who types the right one
- A state directory that goes while Mariner runs (moved aside for a copy to be put back) is not made again, empty: the page shuts until Mariner is restarted. Mariner and the commands about the password go by one rule for the folder they use, a folder reached through a link included
- A state directory that can no longer be written while Mariner runs (a card gone read-only during a print) does not shut the page: the password is still read, the print can still be watched and stopped, and what cannot be kept is said when keeping it is asked for
- The page's own panels ("Mariner cannot be reached", "The files could not be listed", "The settings could not be fetched") are not shown for a refusal that the screen replacing the page explains; nothing fetched under a page that went is drawn again when it opens; focus has a place whichever screen gives way to another
- `mariner set-password` left at its prompt (Ctrl-C, Ctrl-D) says that nothing was changed
- The page says once, in the screen that replaces it, that the session is over, that the password was cleared or that Mariner is shut, whatever was being done; a failure that is about no field (Mariner out of reach, a drive that is full) marks no field as wrong; focus has a place when the page shuts, and goes back to "Try again" when Mariner is still not reached
- Settings that can be changed from the page, once signed in (`/api/settings`): the printer's name, the two slicer interfaces, and taking a printer that does not answer for switched off without asking. They are kept in the state directory and come before `config.toml`. Mariner can be restarted from the page where it runs as a service
- A cookie of the same name set by another program on the same computer (they go by host name, not by port) no longer signs everyone out or keeps the page from acting: every cookie of that name is tried, only one Mariner signed is taken, and one that is signed in comes before one that is not

### 🐛 Bug Fixes

File names and paths

- Refuse to make a folder more than 16 deep (`folder_too_deep`), and go through folders nested to any depth without failing: a long chain of folders, made a request at a time, kept Mariner from starting again
- Keep uploaded file and folder names instead of rewriting them, and refuse those that cannot be used safely: a quote, a control character or line separator anywhere (ends included, instead of trimming it), text that is not valid Unicode, and names the printer's FAT filesystem cannot store
- Validate the file name before a print is started, from every interface, and send the printer the path it knows whatever form the client used
- Check the file extension before printing from UVtools, and trim an uploaded file's name before looking at its extension on every interface
- Keep every client-supplied path inside the files directory, on every route
- Delete or replace a symbolic link itself, not what it points to, including a link whose target is gone; do not read or show what a link leads to outside the files directory
- Keep listings whole when they hold a dangling link, a link that leads back to itself or a file that cannot be parsed, and quick in large folders
- Answer 404 instead of 500 for a missing folder, an unknown printer command, or a file or folder that disappears during a deletion or an upload
- Refuse to upload a file onto the name of a folder
- Let a leftover whose name is no longer allowed be deleted from every interface
- Keep line breaks out of the logs, whether they come in a client-supplied name or value, in the path of a request, or in the name of a file already on the drive

Uploads

- Write each upload to its own temporary file and move it into place in one step, so that a failed or refused upload leaves the previous file intact; remove leftovers at startup
- Keep transfers in progress out of reach of every route, whatever the case of their name, and check once more right before a removal
- Refuse to delete a folder over SDCP while a file is being uploaded into it
- Keep SDCP transfers apart by client address as well as id; refuse a chunk that names another file or size, or that comes from the middle of a transfer that is not under way; let a client end its own transfer only
- Validate the upload id and the declared MD5 of SDCP transfers
- Abandon an SDCP transfer that has received nothing for five minutes, with or without a client connected, and leave nothing behind after a refused, failed or abandoned one
- Refuse an SDCP transfer whose last bytes could not be stored, instead of replacing the previous file with a short one
- Treat a bare string in an SDCP delete request as one path, and report entries that are not paths as failures
- Accept files up to 2 GB by default, from the web page and from slicers, and make the limit a setting (`max_upload_size_mb`); before, the web page and UVtools stopped at 1 GB, and SDCP had no limit
- Refuse an SDCP transfer that announces no size: it could never be complete, and was written without end
- Keep a file on a drive while it arrives (`spool_directory`, `/var/tmp` by default) instead of in `/tmp`, which on current systems is held in memory
- Write a file sent by UVtools as it arrives instead of holding it whole in memory

Printer and prints

- Let only one request at a time talk to the printer's serial port
- Refuse to replace or delete the file being printed, or a folder holding it, however the print was started
- Protect a file from the moment its print is started through Mariner, for half a minute or until the printer reports the print; not when the print cannot have started
- Refuse to start a print while the printer reports one, or until it reports the one Mariner just started (`print_in_progress`, `print_just_started`)
- Check that the file can be printed at the moment the command is sent, with file changes held off
- Leave existing files alone unless the printer says clearly that it is not reading them; new names are always accepted
- Tell apart a printer that answers unclearly from one that sends nothing at all, late answers included, and ask again a moment later after an unclear answer
- Let a web API client override the refusal only for a printer that was asked and stayed silent, once the user has confirmed that it is switched off
- Handle a failure of the serial line, of any kind, in every printer command, while the port is being opened and while it is being closed
- Keep the dashboard working when the file being printed cannot be read
- Check that the computer accepted a shutdown or restart asked for from the web page, and say so when it did not (`host_command_refused`), instead of answering that all went well
- Pass over an SDCP message that is valid JSON but not an object, instead of dropping the client
- Read the firmware version from boards that end lines with CRLF, and treat undecodable bytes from the printer as a bad answer instead of crashing
- Answer the SDCP discovery broadcast without waiting on the printer, with the firmware version read when the service starts

Requests from the web

- Refuse, on the web API and SDCP, what a page of another web site has a browser send when the browser says where it comes from (`cross_site_request`): a form posted, a WebSocket, a request whose answer a script reads. Such a page could start, stop or delete without anyone asking
- Refuse browsers on the UVtools routes, which act on a plain GET (`browser_not_served`): a link or a picture on any page was enough to start or stop a print or delete a file, and over plain HTTP a browser says nothing of where such a request comes from. Programs that send what browsers and media players send are refused too; a script that calls itself a browser, as PowerShell does, must give itself another name
- Answer only to an IP address or a name of the local network, unless told otherwise (`allowed_hosts`), so that a web site pointing its own name at the printer cannot read or drive it (`host_not_allowed`); a browser is shown what to add to the configuration
- Send with Mariner's answers the headers that keep the page from being shown inside another site, its scripts to Mariner's own, and its data and pictures from being loaded by other sites. Mariner can therefore no longer be embedded in another page, a home automation dashboard for one
- Add a setting to switch the UVtools routes off (`[uvtools] enabled`), beside the one SDCP has; a switch set to anything but `true` or `false` counts as off, and settings that are passed over are named in the logs at start
- Keep what went wrong inside out of error answers: no call trace for a printer error (`printer_error`), a plain answer for an error nobody planned for (`internal_error`), debug mode off; the cause goes to the logs
- Say that a file could not be stored (`upload_not_stored`) when an upload fails for want of room, on the printer's drive or where uploads wait. An upload that announces a size larger than the room where uploads wait, less 64 MB left to the system, is refused before any of it is taken in; the file itself is counted too where files are kept on that same drive
- Refuse a request with a body as soon as its headers are in when it comes under a foreign name or from another site, whatever address it is sent to, or when it is too large for the room: the web server used to take in and store the whole body first, up to the largest size allowed, before anything was checked. Only the addresses files are sent to take a body over 512 KB (`request_too_large`)
- Close a connection that has said nothing for a minute or so (it was two to two and a half), and name at start the entries of `allowed_hosts` and `allowed_origins` that are plainly malformed
- Add `[http] allowed_origins` for a relay in front of Mariner that asks it under another name or port than the browser used. A name in `allowed_hosts` no longer makes pages served under it Mariner's own
- Keep the page out of caches, and the cookie that goes with its token out of what other sites have the browser post or load (it still goes with a link followed to Mariner, and with anything asked by a page served from the printer's own address on another port)
- Show a file's preview where it is asked for instead of sending it as a download, so that another site cannot tell from a download starting whether a file of a given name exists
- Write refused requests to the log, with who sent them, what they asked for and what they said, once a minute at most for the same client and reason, which bounds what a web page can have written, not a device of the network
- Keep a page left open able to act: its token was refused after an hour, so that a page open on a long print could no longer pause or stop it until reloaded. The token now lasts until Mariner restarts (or a month), and the page then asks for a new one by itself and sends its request again (before sending a file it makes sure of its token first); if that fails it says to reload (`token_refused`)

Reading files

- Show the details and preview of the file that is there now, after one was replaced by another of the same name
- Keep starting up when a stored file cannot be read, and prepare every other file, those in folders included
- Check every size, count and position a file states about itself against the size of the file before acting on it
- Limit the preview picture to the size of a thumbnail and to the bytes such a picture can need, decode it in a fraction of the memory, and render one at a time, so that a damaged or crafted file costs a request about ten megabytes at most
- List a file whose transfer stopped part of the way as one that cannot be printed, so that the web page does not offer to print it; that covers every anti-aliasing pass of a `.cbddlp` or `.photon` file, and a file that holds no layer
- Find out once per version of a file that it cannot be read, and log the reason then, instead of at every listing
- Keep one remembered entry of each kind per file, replaced with the file; before, every version of a file added entries, and past 500 of them files were read again at every listing
- Start from an empty cache, keep it near 64 MB and 4096 entries by dropping the oldest, and keep working when it cannot be written
- Read the layer table of a file in blocks, and of each layer only what is needed: the longest table allowed took seconds, during which other requests waited
- Do not use a cache folder that is reached through a link, is where the models are, or belongs to another account; use a folder of the service's own instead. The folders above it are not checked: keep the cache directory out of places other accounts can write to
- Let requests that arrive together for the same file share one read
- Do not remember what was read of a file that was replaced during the read
- Compare the signature of an encrypted CTB file in full
- Refuse a file whose layer height, height or bed size is not a number: the status of its print answered with an error at every request
- Name the preview download of a file whose name has characters outside Latin-1; it answered with an error
- Answer 422 with the code `file_unreadable` for the details or preview of a file that cannot be read, 400 for a kind of file Mariner does not read and 404 for a file removed meanwhile, instead of 500; a read that fails for another reason answers 500 with the code `file_read_failed` and no internal detail
- Read `.cbddlp` and `.photon` files of the first format version, which have no slicer settings
- Leave the companion files macOS writes (`._name`) out of the start-up reading

Web interface

- Show why an upload or a deletion was refused
- Ask before deleting or replacing a file while the printer does not answer; withdraw the question when another file is shown
- Take one upload at a time
- Serve the page's typefaces with the page instead of fetching them from Google Fonts: nothing is asked of another site any more, which told it who opened the printer's page and left the page without its typeface where there is no way out to the internet
- Set the page in Atkinson Hyperlegible, drawn so that letters and digits that look alike are told apart, and let the reader choose OpenDyslexic instead (palette button, "Typeface"); both are free (SIL Open Font License), and their licences are shipped under `/licenses/`
- Keep the page working in a browser set to keep nothing: it showed a blank page
- Read the page in English or French: the browser's language at first, the reader's choice afterwards (palette button, "Language"). What the server refuses is said in the page's language too
- Ask before cancelling a print, naming the file and how far it is, and before deleting a file; set the button that cancels apart from the one that pauses
- Say how every action went: a command the printer did not take, a print that could not be started, a list of files that could not be fetched no longer pass in silence. Tell "Mariner cannot be reached" from "the printer does not answer", and say what to check for each
- Show how far an upload is, say that it is being finished once all of it is sent, and say when the file is in. Any file can be picked: some phones offered none when told which kinds the printer takes, and the server says which it does
- Send a command once however often its button is pressed, and say that it is under way
- Say why a folder could not be made (`folder_exists`, `name_not_allowed`, `folder_not_created`, `folder_too_deep`) and why a file was not taken or cannot be printed (`name_not_allowed`, `type_not_supported`, listing the kinds that are)
- Say that a file is no longer there when it was removed since the list was shown (`file_gone`), close its dialog and fetch the list again; offer the way up from a folder that cannot be listed
- Say that the printer did not answer when it sent nothing back to an order to stop, instead of taking the print for cancelled
- Do not ask again, three times over, what the server has refused
- Leave a dialog open when a message shown above it is dismissed
- No longer offer to give up an upload once the whole file has gone: the server stores it then, and the page said "upload cancelled" of a file that was there
- Do not send a file whose name or kind the server would plainly refuse: it was told so only once all of it had been sent
- Stop waiting after five minutes (more for a large file) for the answer to a file that has all gone, say that it may be there, and fetch the list again
- Say what the printer did not take in the page's own words in English too, instead of "unexpected response: ''"
- Shutting down or restarting: when nothing answers, say that the computer may be going down or may not have been asked, instead of that it is going down; ask once however often the button is pressed, and say that it is being asked
- Say that a folder is no longer there (`folder_gone`) instead of "error 404", and that a folder has the name a file was sent under (`name_is_a_folder`)
- Show messages at the top of a phone's screen: at the bottom they sat on the buttons they were about
- Close the messages with Escape from anywhere in the page, show all of them rather than a stack whose hidden ones took focus unseen, set them in the typeface the reader chose, and move on to the next when one of several is closed
- Keep the name of a file being sent readable on a narrow screen: the button to give up goes under it
- Put focus back where it was when the last message is closed, name the place of the page that shows a file being sent, and let a long message be scrolled on a short screen
- Break a long file name in a question rather than let it push the question and its buttons off a phone's screen
- Close a message shown above a dialog with Escape, before the dialog: the keyboard could not reach it, and it could cover the dialog's buttons. Show where the keyboard is on the button that closes a message
- Give focus a place to go when what it was on goes away: the upload bar, the buttons of a print that is over, a list that could not be fetched; and put it back on the name of a folder that was refused
- Let the browser keep the page's scripts, styles and typefaces for good (their names change with their content), and carry OpenDyslexic in one form instead of two
- Call the two times of a print what they are: estimates
- Make the page usable without seeing it: name every button and link at every width of screen, announce the state of the printer and what is loading, label the field of a new folder, give the page a main area, a link to skip to it, a title of its own in the browser's tab, and say which page and which choices are the current ones other than by colour
- Make it readable: text, the red of errors and the Elegoo Mars theme are set apart from their ground (4.5:1), the edge of fields can be seen (3:1), no text is smaller than 12 px, and dialogs and menus are dark like the page they open on
- Stop what turns or pulses without end for a reader who asked their system for stillness
- Keep the keyboard's place: focus goes back to what opened a dialog when it closes, stays on a button while its command lasts, goes to the content when another page is shown and to the list when a folder is opened, and is not left under the bar at the top
- Let dialogs and menus scroll when the screen is too low for them (a phone held sideways, a zoomed page), with the choice that destroys nothing first
- Keep an error on screen until it is closed; say why a folder could not be made by the field it is about; say aloud that the power menu wants a second press, and that the computer is going down
- Go on showing an upload on whichever page is shown, say how far it is a quarter at a time to those who cannot see the bar, let it be given up, and warn before the page is left while it lasts
- Write durations, percentages and decimals as each language does
- Sign-in and first-visit screens, a Settings page (printer's name, slicers' switches, the question about a silent printer, changing the password, signing out, restarting Mariner), in English and French; the page asks for the password again by itself when its session is over

Installation and what is kept

- Keep the key that signs sessions from one start to the next (`[state] directory`, `/var/lib/mariner` by default, for Mariner's account alone): a page left open goes on working after Mariner or the computer restarts, without asking for a new token
- Keep the cache out of `/tmp` (`/var/cache/mariner` by default), where any account could make its folder before Mariner did; the history of prints shown to slicers moves to the state directory and now outlasts a restart
- Service: give it its two folders (`StateDirectory`, `CacheDirectory`), start it again when it stops, put a ceiling on what it writes to the log (300 lines per 30 seconds: any device of the network can have lines written), and keep it from what it has no use for (`NoNewPrivileges`, `ProtectSystem=full`, `ProtectHome=read-only`, `PrivateTmp` and others). The serial port, the network and the folder of files are left as they are
- Docker: `/var/lib/mariner` is a volume
- The service reads users' homes without writing to them: a `files_directory`, `spool_directory` or state directory under `/home` needs a drop-in with `ReadWritePaths=` (see "Password and Settings")
- Build and release workflows name every action they run by its commit rather than by a tag that can be moved

### 🚜 Refactor

- Share one path and file name check between the web API, UVtools and SDCP
- Read the printer status in one place for the web API, UVtools and SDCP
- Share bounded reading and preview decoding between the CTB, FDG and Photon parsers
- Remove two unused cipher classes

### 📚 Documentation

- Add "Password and Settings": choosing the password, what it does not cover, what to do when it is lost, the settings changed from the page, where all of it is kept, signing in from a script
- Update changelog
- Update readme

### ⚙️ Miscellaneous Tasks

- Fixing pyre issues
## [0.6.1] - 2026-09-06

### ⚙️ Miscellaneous Tasks

- Fix package binding problem
## [0.6.0] - 2026-09-05

### 🚀 Features

- Add support for network transfer (#15)

### ⚙️ Miscellaneous Tasks

- Redesign packages page
## [0.5.3] - 2026-04-23

### ⚙️ Miscellaneous Tasks

- *(release)* Debian codename APT suites and stable bookworm alias (#13)
- *(fix)* 💚 restore build
## [0.5.2] - 2026-04-21

### 🚀 Features

- Add support for armbian
## [0.5.0] - 2026-04-20

### 🚜 Refactor

- Remove m4000 troubleshooting code
## [0.4.13] - 2026-04-19

### 🐛 Bug Fixes

- Use z layer for progress estimation
- Restore pre-commit hooks
- Run pyre and fix issues
## [0.4.12] - 2026-04-19

### 🚀 Features

- Add power menu in navigation

### 🐛 Bug Fixes

- More connection issues.
## [0.4.11] - 2026-04-16

### 🐛 Bug Fixes

- Correct ca issues
- *(printer)* Degrade unreadable M4000 polls to CLOSED state
- *(printer)* Handle serial disconnect errors as CLOSED status
## [0.4.10] - 2026-04-15

### 🐛 Bug Fixes

- *(printer)* Harden M4000 status parsing against keepalive noise
## [0.4.9] - 2026-04-14

### 🐛 Bug Fixes

- *(logs)* Add log level flag
## [0.4.8] - 2026-04-13

### 🚀 Features

- Add favicon
- *(printer)* Optional M4000 debug logging for progress troubleshooting
## [0.4.7] - 2026-04-12

### 🚀 Features

- Add support for folders (#11)
- *(printer)* M4000 ratio progress modes and encrypted CTB parsing fixes
## [0.4.5] - 2026-04-12

### 🐛 Bug Fixes

- Encrypted CTB layer table + end offsets; stabilize print_status tests

### ⚙️ Miscellaneous Tasks

- Fix amd64 build
## [0.4.4] - 2026-04-12

### 🐛 Bug Fixes

- *(api)* 🐛 correct print progress when M4000 reports bytes remaining
- *(frontend)* 🐛 use Rollup WASM build for reliable Docker armv7
## [0.4.3] - 2026-04-12

### 🐛 Bug Fixes

- *(package)* 🐛 remove python package dependencies
## [0.4.2] - 2026-04-10

### 🚀 Features

- ✨ add setup automation
## [0.4.1] - 2026-04-01

### ⚙️ Miscellaneous Tasks

- ✨ add release page
## [0.4.0] - 2026-04-01

### 🚀 Features

- ✨ add dark mode (#4)
- *(frontend)* 💄 modernize ui (#9)

### 🐛 Bug Fixes

- 🐛 fix api calls (#8)

### 📚 Documentation

- Attribution edits
- Update documentation

### ⚙️ Miscellaneous Tasks

- ⬆️ upgrade actions to latest supported versions (#5)
- 💚 fix build (#6)
- 💚 refactor ci/cd (#10)
- 💚 fix release pipeline
## [0.3.0-1] - 2024-08-25

### 💼 Other

- Ignore resource fork files left by OSX (#436)
## [0.1.0-1] - 2020-10-11
