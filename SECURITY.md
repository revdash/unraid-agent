# Security Policy

This tool executes commands on your infrastructure via an LLM, and
can be configured to interact with financial credentials (via the
optional dashboard integrations). Security issues here can have real
consequences -- please report responsibly.

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, report privately via [GitHub Security Advisories](../../security/advisories/new)
on this repo, or email: security@[YOUR_DOMAIN]

Include:
- A description of the issue and its potential impact
- Steps to reproduce, if possible
- The version/commit you tested against

## What to expect

- Acknowledgement within 5 business days
- An assessment of severity and a rough timeline for a fix
- Credit in the release notes, if you'd like it (or anonymity, if
  you'd prefer)

## Scope

In scope:
- The agent's command-execution and permission logic
  (`agent.py`, `config.py`)
- The Docker socket proxy configuration
  (`haproxy.cfg.template`)
- The installer (`install.sh`)

Out of scope:
- Vulnerabilities in third-party dependencies (Ollama, Docker,
  Unraid itself, `tecnativa/docker-socket-proxy`) -- please report
  those upstream, though we'll still want to know if they affect
  this project's default configuration
- Issues that require an attacker to already have root access to
  your Unraid server

## Since this is self-hosted, not SaaS

There's no way for us to push a fix to your installation -- when a
security release goes out, you need to update manually. Watch the
repo (or check the CHANGELOG) and update promptly when a release is
flagged as a security fix. Pin to a specific tagged release rather
than tracking `main`, so you control exactly when you update.
