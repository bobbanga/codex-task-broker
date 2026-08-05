# Security Policy

## Supported Versions

Only the latest `main` branch and the most recent release receive security
fixes. This project is alpha software.

## Reporting a Vulnerability

Report vulnerabilities privately through GitHub Security Advisories:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Describe the issue, affected version, and reproduction steps.

Please do not open a public issue for an unfixed vulnerability, and do not
include credentials, tokens, or private paths in your report.

You should get an initial response within a few days. Once a fix is available,
the advisory is published together with the release notes.

## Scope

The CLI is mock-only: it runs one explicitly configured local command with
`shell=false`, passes only allowlisted environment variables to child
processes, and never infers paths, commands, or credentials from its
environment. Reports that describe a way to bypass any of these boundaries are
in scope. Reports about a real executor adapter are out of scope, because no
real adapter is implemented.
