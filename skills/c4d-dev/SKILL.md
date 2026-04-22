---
name: c4d-dev
description: Day-to-day development for deadline-cloud-for-cinema-4d. Use when building, testing, linting, debugging, or running integration tests with Cinema 4D, Redshift, Arnold, or V-Ray. Covers submitter iteration, adaptor debugging, and project structure.
tags: [skill, deadline-cloud, deadline-cloud-for-cinema-4d, deadline-cloud-for-c4d, build, test, lint, integration, redshift, arnold, vray, adaptor, submitter]
---

# Cinema 4D Dev

## Overview

Development companion for building, testing, and debugging the `deadline-cloud-for-cinema-4d` project.

This project provides:
- **Cinema 4D Adaptor**: Runs Cinema 4D renders on Deadline Cloud workers (`cinema4d-openjd` CLI)
- **Cinema 4D Submitter**: Extension for submitting jobs from Cinema 4D to Deadline Cloud
- **Cinema4DClient**: Runs inside Cinema 4D, facilitating communication between the adaptor and Cinema 4D process

For project structure and component details, see:
- [`AGENTS.md`](../../AGENTS.md) — High-level architecture and build commands
- [`src/deadline/cinema4d_submitter/AGENTS.md`](../../src/deadline/cinema4d_submitter/AGENTS.md) — Submitter internals
- [`src/deadline/cinema4d_adaptor/AGENTS.md`](../../src/deadline/cinema4d_adaptor/AGENTS.md) — Adaptor and client internals
- [`test/AGENTS.md`](../../test/AGENTS.md) — Test structure and scenes

## Usage

Use this skill when:
- Building, testing, or linting the project
- Iterating on submitter or adaptor code
- Running integration tests
- Debugging renderer-specific issues (Redshift, Arnold, V-Ray)

## Prerequisites

- Python 3.10+ (Cinema 4D 2026 uses Python 3.11; 2024–2025 uses Python 3.10)
- Cinema 4D 2024, 2025, or 2026 installed
- Hatch: `pip install hatch`
- Windows or macOS for submitter development
- Windows or Linux for adaptor development
- Windows for integration tests

## Quick Commands

### Build
```bash
hatch build
```

### Lint & Format
```bash
hatch run fmt    # Format code (black + ruff)
hatch run lint   # Run linter + type checker
hatch run typing # Type checking only (mypy)
```

### Unit Tests
```bash
hatch run test                                    # All unit tests
hatch run test test/unit/path/to/test.py          # Specific file
hatch run test -k "test_redshift"                 # Pattern match
hatch run all:test                                # All supported Python versions
```

### Integration Tests (Windows Only)

Integration tests require Cinema 4D installed with licensing configured.

```powershell
$env:C4D_LOCATION = "C:\Program Files\Maxon Cinema 4D 2026\"
hatch run integ:test
```

See [references/integration-testing.md](references/integration-testing.md) for setup details and [`test/AGENTS.md`](../../test/AGENTS.md) for test structure.

### Build Installer
```bash
hatch run installer:build-installer --local-dev --platform <windows|macos>
```

## Detailed Guides

- [references/build-and-test.md](references/build-and-test.md) — Complete build and test workflow
- [references/dev-guide.md](references/dev-guide.md) — Development conventions and workflows
- [references/integration-testing.md](references/integration-testing.md) — Running integration tests (Windows only)
- [references/troubleshooting.md](references/troubleshooting.md) — Common issues and solutions

## Supported Renderers

| Renderer | OS Support | Notes |
|----------|-----------|-------|
| Redshift | Windows, Linux | Bundled with Cinema 4D 2024+, default renderer |
| Arnold (C4DtoA) | Windows, Linux | Requires separate plugin install |
| V-Ray | Windows, macOS | Requires separate plugin install |
| Physical/Standard | Windows, Linux, macOS | Built-in Cinema 4D renderer |
| Cargo | Windows, macOS | No special fleet config needed |
| X-Particles (INSYDIUM) | Windows, macOS | Requires queue environment |
| Red Giant | Windows | Requires host config scripts |

## Known Issues

- **Linux Adobe Substance Materials**: Crash at "Baking Substance Materials" step on Amazon Linux 2023. Works on RHEL 9/10.
- **Linux Redshift Freezing**: Sporadic freezes during rendering. Workaround: set timeouts via submitter.
- **C4DtoA Linux 2026**: Crashes due to GPU driver version mismatch. Requires c4dtoa 4.8.6.2+ with driver 580.127+.
