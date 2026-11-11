## [unreleased]

<!-- This section is written by hand, one line per change in behaviour.
     Regenerating it from the commit subjects would lose that detail. -->

### 🚀 Features

- Add support for SDCP

### 🐛 Bug Fixes

- Validate the file name before a print is started from the web API
- Validate the upload id of network (SDCP) transfers
- Keep uploaded file and folder names instead of rewriting them
- Write uploads to a temporary file and move them into place
- Answer 404 instead of 500 for a missing folder or an unknown printer command
- List a folder that contains a dangling symbolic link
- Let only one request at a time talk to the printer's serial port
- Refuse to replace or delete the file being printed, however the print was started
- Leave existing files alone while the printer does not answer; new names are still accepted
- Let a web API client override that refusal when the user confirms the printer is switched off
- Ask in the web interface before deleting or replacing a file while the printer does not answer
- Tell a printer that answers unclearly from one that does not answer, and allow the override for the latter only
- Do not protect a file whose print the printer refused to start
- Refuse to delete a folder over SDCP while a file is being uploaded into it
- Recognise the names reserved for transfers in progress whatever their case
- Keep line breaks in client-supplied names out of the logs
- Answer 404 when a file or folder disappears during a deletion or an upload
- Refuse to start a print while the printer reports one under way
- Treat a terminal failure on the serial line like any other line failure, in every printer command
- Refuse, over SDCP too, a name with a line break at either end instead of trimming it
- Trim an uploaded file's name before looking at its extension, as UVtools and SDCP do
- Follow only symbolic links when listing a folder, so that large folders list quickly
- Check once more that a folder is not a transfer folder right before removing it over SDCP
- Do not let a link named like the SDCP transfer folder lead transfers elsewhere
- Do not ask the printer about a stray SDCP chunk
- Read the firmware version when the SDCP service starts, so that discovery announces it from the first reply
- Refuse to start a second print until the printer reports the first, with its own explanation (`print_just_started`)
- Check that the file can be printed at the moment the command is sent, with file changes held off
- Count as silence only a printer from which not one byte came, late answers included
- Ask again a moment later after an unclear answer, instead of keeping it for half a minute
- Refuse a file name with a line break at either end instead of trimming it
- Let a slicer delete a symbolic link to a folder; the folder itself stays
- Check once more that an entry is not a transfer in progress right before removing it
- Keep listings whole when they hold a symbolic link that leads back to itself
- Remove what an SDCP transfer received even when moving it into place fails unexpectedly
- Explain apart a file whose print was only just started (`print_just_started`)
- Allow the "printer is off" override only when the printer was asked and stayed silent, not when the serial port could not be used or failed
- Withdraw the "delete anyway" question when another file is shown, and ignore an answer that comes back for a file no longer on screen
- Take one upload at a time in the web interface
- Refuse an SDCP chunk from the middle of a transfer that is not under way, and let a client end its own transfer only
- Drop unfinished SDCP transfers with no client connected
- Keep an SDCP listing whole when it holds a link whose target is gone
- Answer a UVtools command the printer turned down, or an upload that cannot be stored, instead of leaving it unhandled
- Keep SDCP transfers apart by client address as well as id, and refuse a chunk that names another file or size
- Abandon an SDCP transfer that has received nothing for five minutes
- Refuse a declared MD5 that is not one
- Leave no empty transfer folder behind after a refused or failed SDCP transfer
- Replace a symbolic link itself, not its target, when a file is uploaded onto it from UVtools or SDCP
- Do not read or show what a symbolic link leads to outside the files directory or in a transfer in progress
- Refuse a deletion name containing a NUL byte or invalid Unicode instead of failing
- Refuse file names containing C1 control characters or Unicode line separators
- Refuse file names the printer's FAT filesystem cannot store
- Give each upload its own temporary file and remove leftovers at startup
- Send the printer the path it knows when a print is started with another form of it, from any interface
- Check the file extension before printing from UVtools
- Treat a bare string in an SDCP delete request as one path, and report entries that are not paths as failures
- Answer the SDCP discovery broadcast without waiting on the printer
- Refuse names that are not valid Unicode instead of dropping the SDCP connection
- Protect a file from the moment its print is started through Mariner
- Show in the web interface why an upload or a deletion was refused
- Give each SDCP transfer its own temporary file, even when ids are reused
- Refuse to upload a file onto the name of a folder
- Keep transfers in progress out of reach of every file route
- Delete a symbolic link itself, not the file it points to, including a link whose target is gone
- Keep the dashboard working when the file being printed cannot be read
- Read the firmware version from boards that end lines with CRLF
- Treat undecodable bytes from the printer as a bad answer instead of crashing

### 🚜 Refactor

- Share one path and file name check between the web API, UVtools and SDCP
- Read the printer status in one place for the web API, UVtools and SDCP

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
