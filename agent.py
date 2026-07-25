#!/usr/bin/env python3
"""
Terminal-controlling agent for Unraid.

Connects via SSH, gives an LLM (local Ollama) the goal + running shell
transcript, lets it choose the next command, executes it, feeds output
back. Loops until the LLM emits DONE or a step/turn limit is hit.

Usage:
    python3 agent.py "install and start a plex docker container"
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import paramiko
import requests

import config

UNATTENDED = not sys.stdin.isatty()
MAX_ASKS_UNATTENDED = 2


SYSTEM_PROMPT = """You control a live SSH terminal on an Unraid server via
an operator. You do not run commands yourself -- you tell the operator
exactly one shell command at a time, see its output, then decide the next
step.

Rules:
- Reply with ONLY one of:
  CMD: <single shell command to run next>
  DONE: <final summary of what was accomplished>
  ASK: <question to ask the human, when you are blocked or unsure>
- One command per turn. No explanations, no markdown, no code fences.
- Prefer non-interactive flags (-y, --yes) so commands do not hang waiting
  for input.
- Never run destructive commands (rm -rf, mkfs, dd to a disk, docker
  system prune -a, deleting arrays/shares) without first sending an ASK
  to confirm with the human.
- If a command fails, read the error and adjust; do not repeat the exact
  same failing command.
- Keep commands short and single-purpose so output stays readable.
- Avoid `docker inspect -f '{{...}}'` Go-template syntax; prefer plain
  `docker ps --filter status=running`, `docker ps -a --format
  "{{.Names}}: {{.Status}}"` (one flat field, no range/if blocks), or
  grep/awk on plain `docker ps` output instead.
"""


def call_llm(history):
    resp = requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={
            "model": config.OLLAMA_MODEL,
            "messages": history,
            "stream": False,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def parse_reply(reply):
    m = re.match(r"^(CMD|DONE|ASK):\s*(.*)$", reply, re.DOTALL)
    if not m:
        return "ASK", f"Could not parse model reply: {reply!r}"
    return m.group(1), m.group(2).strip()


def run_ssh_command(ssh, cmd, timeout=60):
    # ai-agent has no docker-group access to the raw socket anymore.
    # Route any docker command through the read/start/stop/restart-only
    # proxy at 127.0.0.1:2375 instead. Using export (not a one-off
    # VAR=val prefix) so it also applies to docker invocations further
    # down a pipeline, e.g. `docker ps | xargs docker inspect`.
    if re.search(r"\bdocker\b", cmd):
        cmd = f"export DOCKER_HOST=tcp://127.0.0.1:{config.DOCKER_PROXY_PORT}; {cmd}"
    try:
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err
    except Exception as e:
        return 1, "", str(e)


def confirm(prompt):
    if UNATTENDED:
        print(f"[CONFIRM-unattended, auto-declined] {prompt}")
        return False
    ans = input(f"[CONFIRM] {prompt}\nProceed? [y/N] ").strip().lower()
    return ans == "y"


def audit(log_path, event):
    event["ts"] = datetime.now(timezone.utc).isoformat()
    with open(log_path, "a") as f:
        f.write(json.dumps(event) + "\n")


DESTRUCTIVE_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bmkfs\b",
    r"\bdd\s+.*of=/dev/",
    r"\bdocker\s+system\s+prune\s+-a\b",
    r"\bzpool\s+destroy\b",
]

# Phase 1: read-only. Only these command prefixes are allowed; anything
# else is refused before it ever reaches the SSH connection.
PHASE1_ALLOWED = [
    r"^docker\s+ps\b", r"^docker\s+inspect\b", r"^docker\s+logs\b",
    r"^docker\s+stats\b", r"^docker\s+images\b", r"^docker\s+top\b",
    r"^df\b", r"^du\b", r"^free\b", r"^uptime\b", r"^top\b", r"^htop\b",
    r"^cat\b", r"^tail\b", r"^head\b", r"^ls\b", r"^grep\b",
    r"^uname\b", r"^lsblk\b", r"^smartctl\b", r"^sensors\b",
    r"^mdcmd\s+status\b", r"^vmstat\b", r"^ps\b", r"^systemctl\s+status\b",
]

# Phase 2 adds these on top of phase 1 (no delete/remove/prune).
PHASE2_ALLOWED = PHASE1_ALLOWED + [
    r"^docker\s+start\b", r"^docker\s+stop\b", r"^docker\s+restart\b",
    r"^docker\s+compose\s+up\b", r"^docker\s+compose\s+restart\b",
    r"^docker\s+pull\b", r"^systemctl\s+restart\b",
]


def looks_destructive(cmd):
    return any(re.search(p, cmd) for p in DESTRUCTIVE_PATTERNS)


# Only containers named with this prefix may be started/stopped/restarted/
# pulled/killed -- everything else on Tower (Plex, arr-stack, etc.) is
# completely untouchable by this agent regardless of phase. Read-only
# inspection (docker ps/logs/inspect) is unaffected -- it can still see
# everything, it just can't change anything outside this prefix.
CONTAINER_SCOPE_PREFIX = config.CONTAINER_SCOPE_PREFIX

WRITE_TARGET_PATTERN = re.compile(
    r"^docker\s+(?:start|stop|restart|kill)\s+(.+)$"
)


def out_of_scope_target(cmd):
    """Returns the offending container name if a write command targets
    something outside CONTAINER_SCOPE_PREFIX, else None."""
    m = WRITE_TARGET_PATTERN.match(cmd.strip())
    if not m:
        return None
    targets = m.group(1).split()
    # Flags that take a following value argument (e.g. `-t 5`), which
    # must not be mistaken for a container name.
    flags_with_value = {"-t", "--time", "-s", "--signal"}
    skip_next = False
    for t in targets:
        if skip_next:
            skip_next = False
            continue
        if t in flags_with_value:
            skip_next = True
            continue
        if t.startswith("-"):
            continue  # flag without a value, e.g. --rm
        if not t.startswith(CONTAINER_SCOPE_PREFIX):
            return t
    return None


def phase_allows(cmd, phase):
    if phase >= 3:
        return True
    whitelist = PHASE1_ALLOWED if phase == 1 else PHASE2_ALLOWED
    return any(re.search(p, cmd.strip()) for p in whitelist)


# Commands that actually change system state, for the per-goal action
# budget -- separate from MAX_STEPS, which counts every LLM turn
# (inspection included).
STATE_CHANGING_PATTERNS = [
    r"^docker\s+(start|stop|restart|pull|kill)\b",
    r"^docker\s+compose\s+(up|restart)\b",
    r"^systemctl\s+restart\b",
]


def is_state_changing(cmd):
    return any(re.search(p, cmd.strip()) for p in STATE_CHANGING_PATTERNS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("goal", help="task for the agent to accomplish")
    parser.add_argument("--max-steps", type=int, default=config.MAX_STEPS)
    parser.add_argument("--max-actions", type=int, default=config.MAX_ACTIONS)
    args = parser.parse_args()

    if not config.UNRAID_HOST:
        print("[error] UNRAID_HOST is not set. Copy .env.example to .env, "
              "fill in your server's IP, and pass --env-file .env to docker run.")
        sys.exit(1)
    if not config.UNRAID_KEY_PATH and not config.UNRAID_PASSWORD:
        print("[error] Neither UNRAID_KEY_PATH nor UNRAID_PASSWORD is set. "
              "SSH key auth is strongly recommended -- see README.md.")
        sys.exit(1)

    log_path = config.AUDIT_LOG_PATH
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=config.UNRAID_HOST,
        port=config.UNRAID_PORT,
        username=config.UNRAID_USER,
        key_filename=config.UNRAID_KEY_PATH or None,
        password=config.UNRAID_PASSWORD or None,
        timeout=15,
    )
    print(f"[connected] {config.UNRAID_USER}@{config.UNRAID_HOST}:{config.UNRAID_PORT}")
    audit(log_path, {
        "event": "connected", "goal": args.goal, "phase": config.PHASE,
        "host": config.UNRAID_HOST, "user": config.UNRAID_USER,
    })

    phase_note = {
        1: "Phase 1: read-only. You may only inspect (docker ps/inspect/logs, "
           "df, du, top, cat, etc). Nothing that changes state.",
        2: "Phase 2: controlled automation. You may start/stop/restart "
           "containers, pull images, docker compose up. No delete/remove.",
        3: "Phase 3: unrestricted. Destructive commands still require confirm.",
    }[config.PHASE]
    scope_note = (
        f"Container scope: you may start/stop/restart/kill ONLY containers "
        f"whose name starts with '{CONTAINER_SCOPE_PREFIX}'. Every other "
        f"container on this server (Plex, the arr-stack, etc.) is off-limits "
        f"for write actions, in every phase, no exceptions. You can still "
        f"read/inspect anything for context."
    )

    history = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + phase_note + "\n\n" + scope_note},
        {"role": "user", "content": f"Goal: {args.goal}"},
    ]

    actions_taken = 0
    asks_seen = 0

    for step in range(1, args.max_steps + 1):
        reply = call_llm(history)
        history.append({"role": "assistant", "content": reply})
        kind, body = parse_reply(reply)
        audit(log_path, {"event": "llm_reply", "step": step, "kind": kind, "body": body})

        if kind == "DONE":
            print(f"[done] {body}")
            audit(log_path, {"event": "done", "summary": body, "actions_taken": actions_taken})
            break

        if kind == "ASK":
            asks_seen += 1
            if UNATTENDED:
                if asks_seen > MAX_ASKS_UNATTENDED:
                    print(f"[unattended] too many ASKs ({asks_seen}), stopping")
                    audit(log_path, {"event": "unattended_ask_limit", "question": body, "asks_seen": asks_seen})
                    break
                answer = (
                    "No human is available (unattended run, e.g. cron). "
                    "Do not ask further questions. Make your best judgement "
                    "with what you already know and finish now with DONE, "
                    "summarizing findings and noting what needs a human to decide."
                )
                print(f"[agent asks] {body}\n[unattended-auto-answer] {answer}")
            else:
                answer = input(f"[agent asks] {body}\n> ")
            audit(log_path, {"event": "ask", "question": body, "answer": answer, "unattended": UNATTENDED})
            history.append({"role": "user", "content": f"Human answer: {answer}"})
            continue

        # kind == CMD
        cmd = body

        offender = out_of_scope_target(cmd)
        if offender:
            print(f"[blocked: out of scope] $ {cmd}")
            audit(log_path, {"event": "blocked_scope", "cmd": cmd, "target": offender})
            history.append({
                "role": "user",
                "content": (
                    f"Blocked: '{offender}' is not managed by this agent. "
                    f"You may only start/stop/restart containers named with "
                    f"the '{CONTAINER_SCOPE_PREFIX}' prefix. This restriction "
                    "cannot be lifted by raising the phase -- do not ASK about it."
                ),
            })
            continue

        if not phase_allows(cmd, config.PHASE):
            print(f"[blocked: phase {config.PHASE}] $ {cmd}")
            audit(log_path, {"event": "blocked_phase", "cmd": cmd, "phase": config.PHASE})
            history.append({
                "role": "user",
                "content": (
                    f"Blocked: '{cmd}' is not permitted at phase {config.PHASE}. "
                    "Choose a command within your current permission level, "
                    "or ASK the human to raise the phase."
                ),
            })
            continue

        if is_state_changing(cmd):
            if actions_taken >= args.max_actions:
                print(f"[blocked: action budget {args.max_actions} reached] $ {cmd}")
                audit(log_path, {"event": "blocked_budget", "cmd": cmd, "limit": args.max_actions})
                history.append({
                    "role": "user",
                    "content": (
                        f"Blocked: state-changing action budget ({args.max_actions}) "
                        "reached for this goal. Wrap up with DONE, summarizing what "
                        "was completed and what remains."
                    ),
                })
                continue
            actions_taken += 1

        if looks_destructive(cmd):
            approved = confirm(f"Model wants to run a destructive command:\n  {cmd}")
            audit(log_path, {"event": "destructive_confirm", "cmd": cmd, "approved": approved})
            if not approved:
                history.append({
                    "role": "user",
                    "content": "Human declined to run that command. Choose a different approach.",
                })
                continue

        print(f"[step {step}] $ {cmd}")
        code, out, err = run_ssh_command(ssh, cmd)
        output = (out + err).strip()
        if config.SELF_CONTAINER_NAME and re.search(r"\bdocker\b", cmd):
            output = "\n".join(
                line for line in output.splitlines()
                if config.SELF_CONTAINER_NAME not in line
            )
        audit(log_path, {
            "event": "cmd_run", "step": step, "cmd": cmd,
            "exit_code": code, "output": output[:4000],
            "state_changing": is_state_changing(cmd),
        })
        if len(output) > 4000:
            output = output[:4000] + "\n...[truncated]..."
        print(output)

        history.append({
            "role": "user",
            "content": f"exit_code={code}\nstdout+stderr:\n{output}",
        })
    else:
        print("[stopped] max steps reached")
        audit(log_path, {"event": "stopped_max_steps", "actions_taken": actions_taken})

    ssh.close()


if __name__ == "__main__":
    sys.exit(main())
