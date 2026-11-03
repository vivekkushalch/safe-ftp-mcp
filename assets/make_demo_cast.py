"""Generate assets/demo.cast (asciicast v2) for the README animation.

Render it to an animated SVG with:
    pnpm dlx svg-term-cli --in assets/demo.cast --out assets/demo.svg --window
Each scene shows an agent conversation first, then the equivalent CLI command.
Text mirrors the tool's real messages; hashes and timestamps are made up.
"""
import json

R, G, Y, B, M, C, D, W = "31", "32", "33", "34", "35", "36", "90", "97"
RST = "\x1b[0m"
TOTAL = 5
t = 0.0
events = []


def c(code, s):
    return f"\x1b[{code}m{s}{RST}"


def out(s, dt=0.0):
    global t
    t += dt
    events.append([round(t, 3), "o", s])


def line(s="", dt=0.06):
    out(s + "\r\n", dt)


def typed(s, per=0.02):
    for ch in s:
        out(ch, per)
    out("\r\n", 0.3)


def clear(pause):
    out("\x1b[2J\x1b[H", pause)


def header(n, title):
    line(c("1;" + W, f"[{n} of {TOTAL}]") + " " + c(D, title), 0.3)
    line()


def you(msg):
    out(c("1;" + C, "> "), 0.2)
    typed(msg)


def agent_call(call):
    line()
    line(c(M, "● ") + c(D, call), 0.7)


def agent(text_lines):
    for i, tl in enumerate(text_lines):
        line("  " + tl, 0.9 if i == 0 else 0.08)


def by_hand(cmd_lines):
    line()
    line(c(D, "Or by hand:"), 0.6)
    out(c(G, "$ "), 0.2)
    for i, cl in enumerate(cmd_lines):
        if i < len(cmd_lines) - 1:
            typed(cl + " \\")
        else:
            typed(cl)


CMD = "safe-ftp-deploy deploy --local ./index.php --remote /public_html/index.php"

# 1 of 5: ask the agent, dry run
header(1, "Ask your agent to deploy. It dry-runs first.")
you("Deploy ./index.php to /public_html/index.php")
agent_call("deploy(execute=false)")
agent([
    c("1;" + M, "Dry run done.") + " Nothing changed on the server. I would rename the live",
    "index.php to a timestamped backup, then upload your local file.",
    c("1;" + W, "Deploy it?"),
])
by_hand([CMD])
clear(3.0)

# 2 of 5: confirm, execute, verify
header(2, "You confirm. It renames, uploads and verifies.")
you("Yes, deploy it. Note: fix checkout redirect")
agent_call("deploy(execute=true, message=\"fix checkout redirect\")")
agent([
    c("1;" + G, "Done.") + " The old file is saved as index_011126_103012_481516.php.",
    "I downloaded the upload again and the hashes match.",
])
by_hand([CMD + " --execute", '  -m "fix checkout redirect"'])
clear(3.0)

# 3 of 5: drift
header(3, "Someone edits the file on the server. Drift is caught.")
you("Deploy index.php again")
agent_call("deploy(execute=false)")
agent([
    c("1;" + Y, "Drift detected.") + " The server copy changed since the last deploy, so I stopped.",
    "Last known hash " + c(G, "a41f9c0e") + ", now " + c(R, "7be20d15") + ".",
    c("1;" + W, "Review it first, or force the overwrite?"),
])
by_hand(["safe-ftp-deploy status --remote /public_html/index.php"])
clear(3.0)

# 4 of 5: whitelist
header(4, "Paths outside the whitelist are refused.")
you("Upload ./config.php to /private/config.php")
agent_call("deploy(execute=false)")
agent([
    c("1;" + R, "Blocked.") + " /private/config.php is outside this site's allowed directories.",
    "I won't work around that. Ask whoever ran setup-site to allow it.",
])
by_hand(['safe-ftp-deploy setup-site --name mysite --allowed-dirs "/public_html/,/private/"'])
clear(3.0)

# 5 of 5: history and undo
header(5, "Every deploy is logged. Undo is a rename.")
you("What did we last deploy to index.php, and how do I roll back?")
agent_call("history(remote=\"/public_html/index.php\")")
agent([
    "Last deploy: \"fix checkout redirect\". Backup: index_011126_103012_481516.php.",
    "There is no rollback command. Rename that backup back to index.php in your",
    "FTP client.",
])
by_hand(["safe-ftp-deploy history --remote /public_html/index.php"])
out("", 4.5)

header_json = {"version": 2, "width": 100, "height": 14, "timestamp": 1793000000,
               "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"}}
with open("assets/demo.cast", "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(header_json) + "\n")
    for e in events:
        f.write(json.dumps(e) + "\n")
print(len(events), "events,", round(t, 1), "s")
