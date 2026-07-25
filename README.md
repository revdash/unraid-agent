# unraid-agent

A local, self-hosted AI agent that manages Docker containers on your
Unraid server through SSH -- using your own Ollama instance, not a
cloud API. Nothing about your server or its data leaves your network.

## What it does

Give it a goal in plain English:

    ./agent.sh "check container health"
    ./agent.sh "restart the backend service" --phase 2

It decides shell commands one at a time, runs them over SSH, reads
the output, and adjusts -- a real agentic loop, not a fixed script.

## Safety model

This is the part that matters most, so read it before installing:

- **Dedicated non-root SSH user.** The agent never has your root
  credentials.
- **No raw Docker socket access.** All Docker commands route through
  a locked-down proxy that only allows read operations and
  start/stop/restart -- DELETE and PUT are blocked at the proxy
  config level, not by a flag that could be misconfigured.
- **Container scope.** The agent can only start/stop/restart
  containers whose name starts with your chosen prefix (default
  `agent-`). Everything else on your server -- Plex, your NAS
  shares, anything -- is permanently off-limits, in every phase.
- **Three-phase permission model.** Phase 1 (read-only) is the
  default. Phase 2 adds start/stop/restart. Phase 3 is unrestricted
  but still confirms destructive-looking commands.
- **Full audit log.** Every decision, command, and outcome is
  recorded to `logs/agent_audit.jsonl`.

## Setup

Requirements: an Unraid server, Docker, and an Ollama instance
reachable from it (local or LAN).

1. Copy this whole folder onto your Unraid server, e.g.
   `/mnt/user/appdata/unraid-agent/`

2. Run the installer as root, on the server itself:

       cd /mnt/user/appdata/unraid-agent
       ./install.sh

   This creates a dedicated SSH user, generates a key, configures
   sshd (and persists that across reboots), and deploys the locked-
   down Docker proxy. Safe to re-run -- it skips anything already
   done.

3. Review the generated `.env` -- it should have your server's IP
   and the new SSH key path filled in already. Set
   `CONTAINER_SCOPE_PREFIX` to whatever prefix you'll use for
   containers you want the agent to manage.

4. Test it:

       ./agent.sh healthcheck

## Usage

    ./agent.sh healthcheck              # phase 1, read-only
    ./agent.sh repair                   # phase 2, start/stop/restart
    ./agent.sh "your own goal here" --phase 2

## Scheduling

To run a daily unattended health check with a notification only when
something looks wrong, see `daily_healthcheck.sh` -- point it at your
own notification mechanism (Unraid's built-in `notify` script works
out of the box; swap in anything else you use).

## License

Source-available for personal and internal business use. You may
not resell, rehost as a paid service, or redistribute this as your
own product. See LICENSE.

Provided as-is, no warranty. This tool executes commands on your
infrastructure via an LLM -- review what phase you're running it at
and understand the scope restriction before granting it write access.
