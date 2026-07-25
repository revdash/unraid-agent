import os

# No sensible default -- every Unraid box has a different LAN IP.
# Must be set via env var; agent.py fails fast with a clear message
# if this is left blank.
UNRAID_HOST = os.environ.get("UNRAID_HOST", "")
UNRAID_PORT = int(os.environ.get("UNRAID_PORT", "22"))
# Use a dedicated non-root user, not "root". Create one on Unraid first
# and grant it only the access each phase needs (docker group for phase 2+).
UNRAID_USER = os.environ.get("UNRAID_USER", "ai-agent")
UNRAID_KEY_PATH = os.environ.get("UNRAID_KEY_PATH", "")
UNRAID_PASSWORD = os.environ.get("UNRAID_PASSWORD", "")

# Docker hostname works if this script runs inside the same Docker network
# as your Ollama container. If it runs from a Mac/laptop instead, that
# hostname won't resolve -- use the IP there.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

MAX_STEPS = int(os.environ.get("MAX_STEPS", "25"))

# Separate cap on state-changing actions (start/stop/restart/pull) per
# goal -- MAX_STEPS also counts read-only inspection turns, this doesn't.
MAX_ACTIONS = int(os.environ.get("MAX_ACTIONS", "8"))

# Append-only JSON-lines audit log: every LLM decision, command run,
# confirm/deny, and ASK exchange.
AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "/app/logs/agent_audit.jsonl")

# 1 = read-only (inspect/logs/health only, nothing that changes state)
# 2 = controlled automation (start/stop/update containers, confirm on delete)
# 3 = unrestricted (still confirms destructive patterns, no whitelist)
PHASE = int(os.environ.get("AGENT_PHASE", "1"))

# This container's own --name, set by agent.sh, so agent.py can filter
# itself out of docker ps/inspect output. Hostname detection doesn't
# work here because --network host makes the container inherit the
# Unraid host's hostname instead of its own container ID.
SELF_CONTAINER_NAME = os.environ.get("SELF_CONTAINER_NAME", "")

# Only containers named with this prefix can be started/stopped/
# restarted/killed by the agent, in any phase -- everything else on
# the server is off-limits for write actions. Change this to whatever
# prefix you use for the containers you want the agent to manage.
CONTAINER_SCOPE_PREFIX = os.environ.get("CONTAINER_SCOPE_PREFIX", "agent-")

# Port the locked-down Docker socket proxy listens on (set up by
# install.sh). Must match DOCKER_PROXY_PORT used at install time.
DOCKER_PROXY_PORT = os.environ.get("DOCKER_PROXY_PORT", "2375")
