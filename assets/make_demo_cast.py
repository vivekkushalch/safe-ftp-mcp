"""Generate assets/demo.cast (asciicast v2) for the README animation.

Render it to an animated SVG with:
    pnpm dlx svg-term-cli --in assets/demo.cast --out assets/demo.svg --window
Output text mirrors the tool's real messages; hashes and timestamps are made up.
"""
import json

R, G, Y, B, M, D, W = "31", "32", "33", "34", "35", "90", "97"
RST = "\x1b[0m"
t = 0.0
events = []


def c(code, s):
    return f"\x1b[{code}m{s}{RST}"


def out(s, dt=0.0):
    global t
    t += dt
    events.append([round(t, 3), "o", s])


def line(s, dt=0.05):
    out(s + "\r\n", dt)


def prompt():
    out(c(G, "$ "), 0.3)


def typed(cmd, per=0.035):
    for ch in cmd:
        out(ch, per)
    out("\r\n", 0.35)


def clear(pause):
    out("\x1b[2J\x1b[H", pause)


CMD = "safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php"
HDR = c("1;" + W, "Deploy: ") + "./index.php -> /public_html/index.php"

# Scene 1: dry run
line(c(D, "# 1. Dry run is the default. Nothing changes on the server."), 0.4)
prompt()
typed(CMD)
line("", 0.5)
line(HDR)
line(c("1;" + M, "DRY RUN") + " - Would rename remote '/public_html/index.php' -> '/public_html/index_<timestamp>.php',", 0.1)
line("          then upload local './index.php' as '/public_html/index.php'.")
line("          Re-run with " + c(B, "--execute") + " to apply.")
clear(3.2)

# Scene 2: execute
line(c(D, "# 2. Add --execute. The old file is renamed, the new one uploaded and verified."), 0.2)
prompt()
typed(CMD + ' --execute -m "fix checkout redirect"')
line("", 0.9)
line(HDR)
line(c("1;" + G, "SUCCESS") + " - Backed up old file to '/public_html/index_011126_103012_481516.php'", 0.1)
line("          and uploaded new version to '/public_html/index.php'. Verified upload integrity.")
clear(3.2)

# Scene 3: drift
line(c(D, "# 3. Someone edits index.php on the server. The next deploy is refused."), 0.2)
prompt()
typed(CMD + " --execute")
line("", 0.9)
line(HDR)
line(c("1;" + Y, "DRIFT DETECTED") + " - The file on the server has changed since the last deploy", 0.1)
line("                 through this tool. " + c(R, "Refusing to overwrite.") + " Review the server's version,")
line("                 or re-run with " + c(B, "--force") + " once you are sure.")
line(c(D, "- Last known hash:      ") + c(G, "a41f9c0e"))
line(c(D, "- Current remote hash:  ") + c(R, "7be20d15"))
out("", 4.0)

header = {"version": 2, "width": 100, "height": 9, "timestamp": 1793000000,
          "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"}}
with open("assets/demo.cast", "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(header) + "\n")
    for e in events:
        f.write(json.dumps(e) + "\n")
print(len(events), "events,", round(t, 1), "s")
