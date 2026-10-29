import hashlib
import importlib
import os
import subprocess
import sys

WINDOWS = os.name == "nt"
MAC = sys.platform == "darwin"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VENV = os.path.join(ROOT, ".venv")
VENV_PY = (os.path.join(VENV, "Scripts", "python.exe") if WINDOWS
           else os.path.join(VENV, "bin", "python3"))
STAMP = os.path.join(VENV, ".requirements-stamp")
LOG = os.path.join(ROOT, "setup-log.txt")
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
if WINDOWS:
    LAUNCH, SETUP = "Launch.bat", "Setup.bat"
elif MAC:
    LAUNCH, SETUP = "Launch.command", "Setup.command"
else:
    LAUNCH, SETUP = "Launch.sh", "Setup.sh"

if WINDOWS:
    MUST_IMPORT = ["cv2", "numpy", "mss", "keyboard"]
elif MAC:
    MUST_IMPORT = ["cv2", "numpy", "mss", "pynput", "Quartz", "AppKit"]
else:
    MUST_IMPORT = ["cv2", "numpy", "mss", "pynput", "Xlib"]


def say(msg):
    print(" " + msg, flush=True)


def requirements_hash():
    with open(REQUIREMENTS, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run(args, **kw):
    return subprocess.call(args, cwd=ROOT, **kw)


def run_logged(args):
    with open(LOG, "a", encoding="utf-8", errors="replace") as log:
        log.write("\n$ " + " ".join(args) + "\n")
        log.flush()
        proc = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace")
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
        return proc.wait()


def python_info():
    v = sys.version_info
    bits = 64 if sys.maxsize > 2 ** 32 else 32
    return "Python %d.%d.%d (%d-bit) at %s" % (v.major, v.minor, v.micro, bits,
                                             sys.executable)


def tk_ok():
    try:
        importlib.import_module("tkinter")
        return True
    except Exception:
        return False


def explain_failure():
    say("")
    say("Install failed. The full output is in setup-log.txt next to %s." % LAUNCH)
    say(python_info())
    say("")
    low = ROOT.lower()
    if WINDOWS and "onedrive" in low:
        say("* This folder is inside OneDrive. OneDrive locks files while it syncs")
        say("  them, which breaks the install. Move the folder somewhere OneDrive")
        say("  does not watch (for example C:\\Games\\fishing) and run it again.")
    if sys.version_info >= (3, 14):
        say("* This Python is very new. Some of the packages may not have builds")
        say("  for it yet. Installing Python 3.12 from python.org alongside it")
        say("  is the sure fix; %s picks the newest one it can use." % LAUNCH)
    if WINDOWS:
        say("* Antivirus or Windows 'Controlled folder access' can block writes to")
        say("  .venv. Look for 'Access is denied' or 'WinError 5' in the log.")
    if not WINDOWS and not MAC:
        say("* On Linux the packages need a C compiler only when no wheel exists;")
        say("  a python.org / distro Python 3.10-3.13 on x86_64 always has wheels.")
    say("* If the log ends in a download or SSL error, that one really is the")
    say("  connection, a proxy, or a firewall.")
    say("")
    say("Run %s to try again; send setup-log.txt if it still fails." % SETUP)


def ensure_venv():
    if os.path.exists(VENV_PY):
        return True
    say("Building a private Python environment in .venv (first time only, ~20s)...")
    code = run_logged([sys.executable, "-m", "venv", VENV])
    if code != 0 or not os.path.exists(VENV_PY):
        say("Could not create .venv. See setup-log.txt next to %s." % LAUNCH)
        if WINDOWS:
            say("On some Python installs the 'venv' part is a tick box in the")
            say("installer under Optional Features; run the installer again and tick it.")
        else:
            say("On Debian/Ubuntu: sudo apt install python3-venv")
        return False
    return True


def packages_ok():
    if not os.path.exists(STAMP):
        return False
    with open(STAMP) as f:
        if f.read().strip() != requirements_hash():
            return False
    probe = "import " + ", ".join(MUST_IMPORT)
    return run([VENV_PY, "-c", probe],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def install_packages():
    say("Installing packages (first time only, a minute or two)...")
    print(flush=True)
    run_logged([VENV_PY, "-m", "pip", "install", "--upgrade", "pip", "--quiet",
                "--disable-pip-version-check"])
    code = run_logged([VENV_PY, "-m", "pip", "install", "-r", REQUIREMENTS,
                       "--only-binary=:all:", "--disable-pip-version-check"])
    print(flush=True)
    if code != 0:
        explain_failure()
        return False
    probe = "import " + ", ".join(MUST_IMPORT)
    if run_logged([VENV_PY, "-c", probe]) != 0:
        say("Packages installed but something will not import. See setup-log.txt.")
        return False
    with open(STAMP, "w") as f:
        f.write(requirements_hash())
    say("Packages installed.")
    return True


def platform_notes():
    if MAC:
        say("macOS: the first run asks for Accessibility, Input Monitoring and")
        say("Screen Recording for Terminal (System Settings > Privacy & Security).")
        say("Allow all three, then start the macro again.")
    elif not WINDOWS:
        say("Linux: the macro needs an X11 session (Wayland cannot share the")
        say("screen or send input). Pick 'Ubuntu on Xorg' at the login screen.")


def main():
    if os.path.exists(LOG):
        os.remove(LOG)
    if not tk_ok():
        say("This Python has no tkinter (the window toolkit).")
        if WINDOWS:
            say("Run the python.org installer again and tick 'tcl/tk and IDLE'.")
        elif MAC:
            say("Install Python from python.org; it ships with tkinter.")
        else:
            say("Debian/Ubuntu: sudo apt install python3-tk   Fedora: sudo dnf install python3-tkinter")
        return 1
    if not ensure_venv():
        return 1
    if not packages_ok() and not install_packages():
        return 1
    if os.path.exists(LOG):
        os.remove(LOG)
    args = sys.argv[1:]
    script = "main.py"
    if args and args[0].endswith(".py"):
        script, args = args[0], args[1:]
    if args and args[0] == "--check":
        platform_notes()
        return 0
    return run([VENV_PY, os.path.join(HERE, script)] + args)


if __name__ == "__main__":
    sys.exit(main())
