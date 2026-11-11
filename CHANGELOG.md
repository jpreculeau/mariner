## [unreleased]

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
- Refuse file names the printer's FAT filesystem cannot store
- Give each upload its own temporary file and remove leftovers at startup
- Send the printer the path it knows when a print is started with another form of it, from any interface
- Check the file extension before printing from UVtools
- Treat a bare string in an SDCP delete request as one path, and report entries that are not paths as failures
- Answer the SDCP discovery broadcast without waiting on the printer
- Refuse names that are not valid Unicode instead of dropping the SDCP connection
- Protect a file from the moment its print is started through Mariner
- Show in the web interface why an upload or a deletion was refused
- Keep overlapping SDCP transfers apart, even when they share an id
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
