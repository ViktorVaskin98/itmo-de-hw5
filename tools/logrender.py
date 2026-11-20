import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

ESC, OPEN, CLOSE = "¤", "¦", "¢"
WRAP = 118

PROMPT = re.compile(r"^PS> ")
NOTE = re.compile(r"^# ")


@dataclass
class Block:
    command: list[str] = field(default_factory=list)
    output: list[str] = field(default_factory=list)


@dataclass
class Note:
    text: str


def escape_braces(text: str) -> str:
    return text.replace("{", f"{ESC}textbraceleft{OPEN}{CLOSE}").replace("}", f"{ESC}textbraceright{OPEN}{CLOSE}")


def color(name: str, text: str) -> str:
    if not text:
        return ""
    return f"{ESC}c{name[1:]}{OPEN}{escape_braces(text)}{CLOSE}"


def parse_log(path: Path) -> list[Block | Note]:
    items: list[Block | Note] = []
    current: Block | None = None
    in_command = False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.rstrip()
        if line == "System.Management.Automation.RemoteException":
            continue
        if NOTE.match(line):
            items.append(Note(line[2:]))
            current, in_command = None, False
        elif PROMPT.match(line):
            current = Block(command=[line[4:]])
            items.append(current)
            in_command = True
        elif current is None:
            if line.strip():
                current = Block()
                items.append(current)
                in_command = False
                current.output.append(line)
        else:
            if in_command and (line.startswith("    ") or line.startswith("}")):
                current.command.append(line)
            else:
                in_command = False
                current.output.append(line)
    for item in items:
        if isinstance(item, Block):
            while item.output and not item.output[0].strip():
                item.output.pop(0)
            while item.output and not item.output[-1].strip():
                item.output.pop()
    return items


def blocks(path: Path) -> list[Block]:
    return [i for i in parse_log(path) if isinstance(i, Block)]


def find(path: Path, pattern: str, nth: int = 0) -> Block:
    hits = [b for b in blocks(path) if re.search(pattern, " ".join(b.command))]
    return hits[nth]


GOOD = (
    "Completed",
    "condition met",
    "Complete",
    "MATCH",
    "identical",
    "checksums match",
    " ok",
    "Running",
    "created",
    "successfully rolled out",
    "OK ",
    "True",
)
BAD = (
    "OOMKilled",
    "out of memory",
    "oom-kill",
    "invoked oom-killer",
    "exceeded quota",
    "forbidden",
    "Forbidden",
    "FailedScheduling",
    "Insufficient cpu",
    "Preempted",
    "PreemptionByScheduler",
    "preempted",
    "MISMATCH",
    "DIFFERENT",
    "Failed",
    "exit code 137",
    "Error",
)
WARN = ("Pending", "FailedCreate", "throttled", "memory.peak", "Terminating", "nominated", "PodFailurePolicy")


def tone(text: str) -> str:
    if any(k in text for k in BAD):
        return "tBad"
    if any(k in text for k in WARN):
        return "tParity"
    if any(k in text for k in GOOD):
        return "tGood"
    return "tText"


def style_output(line: str) -> str:
    if line.startswith("[exit code") or "Traceback" in line:
        return color("tBad", line)
    if line.rstrip().endswith(" MATCH") and "MISMATCH" not in line:
        head, _, tail = line.rpartition("MATCH")
        return color("tText", head) + color("tGood", "MATCH") + color("tText", tail)
    if line.startswith("RESULT:"):
        return color("tGood" if "identical" in line else "tBad", line)
    if line.startswith(("NAME ", "POD ", "NODE ", "JOB ", "LAST ", "PV ", "PVC ", "pod ", "stack ", "times in")):
        return color("tVerb", line)
    return color(tone(line), line)


EMOJI = re.compile("[\U00010000-\U0010FFFF️☀-➿]")


def wrap_plain(line: str) -> list[str]:
    line = EMOJI.sub("", line).rstrip()
    if len(line) <= WRAP:
        return [line]
    return textwrap.wrap(line, WRAP, subsequent_indent="  ", break_long_words=True, break_on_hyphens=False) or [line]


NOISE = (
    " 2>&1 | ForEach-Object { \"$_\" } | Where-Object { $_ -notmatch '^Installed' }",
    ' 2>&1 | ForEach-Object { "$_" }',
    " 2>&1 | Where-Object { $_ -notmatch 'NoSuchKey' }",
)


def clean_command(line: str) -> str:
    for noise in NOISE:
        line = line.replace(noise, "")
    return line.replace('"$Root\\', '"').replace("$Root\\", "")


def render_block(
    block: Block,
    max_output: int | None = None,
    head_tail: tuple[int, int] | None = None,
    max_command: int | None = None,
) -> str:
    out: list[str] = []
    command = [clean_command(c) for c in block.command]
    if max_command is not None and len(command) > max_command:
        command = command[:max_command] + ["    # ... (тело скрипта сокращено)"]
    for i, cmd in enumerate(command):
        prefix = "PS> " if i == 0 else "    "
        body = cmd.strip() if i == 0 else cmd[4:] if cmd.startswith("    ") else cmd
        pieces = textwrap.wrap(
            body, WRAP - 4, subsequent_indent="    ", break_long_words=True, break_on_hyphens=False
        ) or [body]
        out.append(color("tPrompt", prefix) + color("tCmd", pieces[0]))
        out.extend(color("tPrompt", "    ") + color("tCmd", p.strip() if False else p) for p in pieces[1:])
    lines = block.output
    if head_tail:
        h, t = head_tail
        if len(lines) > h + t:
            lines = lines[:h] + ["..."] + (lines[-t:] if t else [])
    elif max_output is not None and len(lines) > max_output:
        lines = lines[:max_output] + ["..."]
    for line in lines:
        for piece in wrap_plain(line):
            out.append(style_output(piece))
    return "\n".join(out)


def write_snippet(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
