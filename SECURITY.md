# Security policy

## MemoryMap AI's security model, in short

MemoryMap AI is a **local-first, single-user app that runs on your own
machine.** It binds to `127.0.0.1` (localhost only), never exposes itself
to the network, and never sends your notes to the cloud. Your data lives
in a folder on your disk (`data/`), and access to the app is gated
behind a password you choose on first run (bcrypt-hashed, stored
locally).

Because of this design, the most important protections for your notes
are the ones your operating system already provides:

- **Encryption at rest.** The database is a plain SQLite file. If your
  notes are sensitive, enable full-disk encryption (BitLocker on
  Windows, FileVault on macOS, LUKS on Linux). SQLCipher is deliberately
  *not* bundled: it needs a native dependency on every platform for a
  single-user local file, and disk encryption covers the same threat
  more simply. See [`docs/PRIVACY.md`](docs/PRIVACY.md) for what the app
  encrypts on its own (private notes).
- **Backups.** The app takes a daily local snapshot into your data
  folder. Those snapshots are as sensitive as the database, keep them
  somewhere you trust.

## Supported versions

This is an actively developed `0.x` project; security fixes land on
`main`. Please run the latest `main`.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Instead, report privately using GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability):
go to the repository's **Security** tab, then **Report a vulnerability**.

When you report, please include:

- what the issue is and where in the code it lives, if you know;
- steps to reproduce; and
- the impact you think it has.

You'll get an acknowledgement, and we'll work with you on a fix and
disclosure timeline. Thanks for helping keep MemoryMap AI safe.

## Scope notes

Since the app is localhost-only and single-user, classic web-app threats
(CORS, cross-site attacks from other origins, multi-tenant data leaks)
largely don't apply. The areas most worth scrutiny are: the unlock and
auth flow, file upload handling, the opt-in web-search path (the only
outbound network feature), and anything that could let the agent's
tools act without the required confirmation.
