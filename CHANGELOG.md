## [unreleased]

<!-- This section is written by hand and states the behaviour as it now is.
     Regenerating it from the commit subjects would lose that. -->

### 🚀 Features

- Add support for SDCP

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
- Refuse browsers on the UVtools routes, which act on a plain GET: a link or a picture on any page was enough to start or stop a print or delete a file, and over plain HTTP a browser says nothing of where such a request comes from
- Answer only to an IP address or a name of the local network, unless told otherwise (`allowed_hosts`), so that a web site pointing its own name at the printer cannot read or drive it (`host_not_allowed`); a browser is shown what to add to the configuration
- Send with Mariner's answers the headers that keep the page from being shown inside another site, its scripts to Mariner's own, and its data and pictures from being loaded by other sites. Mariner can therefore no longer be embedded in another page, a home automation dashboard for one
- Add a setting to switch the UVtools routes off (`[uvtools] enabled`), beside the one SDCP has; a switch set to anything but `true` or `false` counts as off, and settings that are passed over are named in the logs at start
- Keep what went wrong inside out of error answers: no call trace for a printer error (`printer_error`), a plain answer for an error nobody planned for (`internal_error`), debug mode off; the cause goes to the logs
- Say that a file could not be stored (`upload_not_stored`) when an upload fails for want of room, on the printer's drive or where uploads wait, and refuse beforehand an upload larger than that room

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

### 🚜 Refactor

- Share one path and file name check between the web API, UVtools and SDCP
- Read the printer status in one place for the web API, UVtools and SDCP
- Share bounded reading and preview decoding between the CTB, FDG and Photon parsers
- Remove two unused cipher classes

### 📚 Documentation

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
