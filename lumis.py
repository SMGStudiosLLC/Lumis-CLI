#!/usr/bin/env python3
"""Lumis CLI - AI-Powered Terminal Agent | Designed by Tobias Schmidt Services LLC"""

import os, sys, json, subprocess, re, requests, time, threading, signal, hashlib
from pathlib import Path
from datetime import datetime

# Terminal handling
try:
    import termios, tty, select, fcntl
    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False

# Key constants
KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT = 'UP', 'DOWN', 'LEFT', 'RIGHT'
KEY_ENTER, KEY_ESC, KEY_TAB, KEY_BACKSPACE = 'ENTER', 'ESC', 'TAB', 'BACKSPACE'

# Colors
NAVY, BLUE, LBLUE = "\033[38;5;17m", "\033[38;5;33m", "\033[38;5;75m"
WHITE, GRAY, CYAN = "\033[97m", "\033[90m", "\033[96m"
GREEN, RED, YELLOW = "\033[92m", "\033[91m", "\033[93m"
BOLD, DIM, ITALIC, UNDERLINE = "\033[1m", "\033[2m", "\033[3m", "\033[4m"
RESET, CLEAR_LINE = "\033[0m", "\033[2K\r"

def set_terminal_title(title):
    """Set terminal window/tab title"""
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()

CONFIG_DIR = Path.home() / ".lumis"
KEYS_FILE = CONFIG_DIR / "api_keys.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
HISTORY_FILE = CONFIG_DIR / "history.json"

MAX_CONTEXT_MESSAGES = 40
MAX_FILE_SIZE = 500000
MAX_TOOL_LOOPS = 15

MODELS = {
    "codex": ("GPT-5.2-Codex", "$", "Fast coding"),
    "grok": ("Grok-4.1-Fast-Reasoning", "$", "Quick reasoning"),
    "haiku": ("Claude-Haiku-4.5", "$", "Lightweight"),
    "gpt": ("GPT-5.2-Instant", "$$", "Premium GPT"),
    "sonnet": ("Claude-Sonnet-4.5", "$$", "Advanced"),
    "opus": ("Claude-Opus-4.5", "$$$", "Most capable"),
    "gemini": ("Gemini-3-Pro", "$$", "Google's best")
}

OLLAMA_URL = "http://localhost:11434"

COMMANDS = {
    "/help": "Show all commands",
    "/model": "Switch AI model",
    "/models": "List available models",
    "/local": "Switch to Ollama (local)",
    "/cloud": "Switch to Poe (cloud)",
    "/doctor": "System diagnostics",
    "/clear": "Clear screen",
    "/history": "Conversation history",
    "/reset": "Reset conversation",
    "/experiments": "Toggle features",
    "/status": "Current settings",
    "/save": "Save conversation",
    "/load": "Load conversation",
    "/exit": "Exit Lumis"
}

EXPERIMENTS = {
    "reasoning": ("Enhanced Thinking", "Deep reasoning mode for supported models"),
    "planning": ("Smart Planning", "Model creates visual TODO lists for multi-step tasks"),
    "verbose": ("Verbose Output", "Model thinks more deeply and checks its own work"),
    "details": ("Details", "Shows model, tokens, and timing at bottom of responses")
}

SYSTEM_PROMPT = """You are Lumis, an elite AI terminal agent designed by Tobias Schmidt Services LLC.

TOOLS AVAILABLE (use JSON format):

1. read_file - Read file contents (supports line ranges for large files)
   {"tool": "read_file", "path": "/path/to/file", "start_line": 1, "end_line": 100}

2. write_file - Create/overwrite file
   {"tool": "write_file", "path": "/path/to/file", "content": "content here"}

3. edit_file - Surgical edits (find/replace pairs)
   {"tool": "edit_file", "path": "/path/to/file", "edits": [{"find": "old", "replace": "new"}]}

4. patch_file - Line-based edits (for precise changes)
   {"tool": "patch_file", "path": "/path/to/file", "patches": [{"line": 10, "action": "replace", "content": "new line"}]}
   Actions: "replace", "insert_after", "insert_before", "delete"

5. run_command - Execute shell commands
   {"tool": "run_command", "command": "ls -la"}

6. list_dir - List directory (with depth)
   {"tool": "list_dir", "path": "/path", "depth": 1}

7. search_file - Search for pattern in file
   {"tool": "search_file", "path": "/path/to/file", "pattern": "search term"}

8. delete_file - Delete file (requires permission)
   {"tool": "delete_file", "path": "/path/to/file"}

9. todo - Create and manage a visual task list (use for multi-step tasks)
   Create: {"tool": "todo", "action": "create", "title": "My Plan", "tasks": ["Step 1", "Step 2", "Step 3"]}
   Check off: {"tool": "todo", "action": "check", "indices": [1, 2]}
   Show: {"tool": "todo", "action": "show"}
   Clear: {"tool": "todo", "action": "clear"}

TOOL FORMAT - Output JSON in a code block:
```json
{"tool": "tool_name", ...params}
```

RULES:
- For files larger than 400KB, use 'search_file' to locate relevant code, then 'read_file' with line ranges.
- Use edit_file for small changes, write_file for new/complete rewrites
- Use patch_file for line-specific edits
- Destructive operations need user permission
- After tool results, continue or respond
- Chain tools as needed
- Be concise but thorough
- For complex multi-step tasks, create a TODO list first, then check off items as you complete them"""

# Global state
trust_session = False
verbose_mode = False
details_mode = False
current_plan = None
stop_event = None
session_todo = None  # Interactive TODO list for the session

def estimate_tokens(text):
    """Rough token estimate (4 chars per token)"""
    return len(text) // 4 if text else 0

def log_verbose(msg, category="info"):
    """Print verbose output if enabled - subtle and dim"""
    if not verbose_mode:
        return
    # Keep it minimal and dim so it doesn't distract
    print(f"  {DIM}· {msg}{RESET}")

def is_tty():
    """Check if running in a real terminal"""
    try:
        return os.isatty(sys.stdin.fileno())
    except:
        return False

KEY_HOME, KEY_END, KEY_DELETE = 'HOME', 'END', 'DELETE'
KEY_CTRL_U, KEY_CTRL_W, KEY_CTRL_A, KEY_CTRL_E = 'CTRL_U', 'CTRL_W', 'CTRL_A', 'CTRL_E'

def getch():
    """Get single keypress - robust handling for all terminal types"""
    if not HAS_TERMIOS or not is_tty():
        try:
            line = input()
            return line[0] if line else KEY_ENTER
        except (EOFError, KeyboardInterrupt):
            raise KeyboardInterrupt
    fd = sys.stdin.fileno()
    old = None
    try:
        old = termios.tcgetattr(fd)
    except termios.error:
        try:
            return input()[:1] or KEY_ENTER
        except (EOFError, KeyboardInterrupt):
            raise KeyboardInterrupt
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if not ch:
            return ''
        if ch == '\x1b':
            old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            try:
                fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)
                seq = ''
                try:
                    seq = sys.stdin.read(5)
                except (IOError, BlockingIOError):
                    pass
            finally:
                fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)
            esc_map = {
                '[A': KEY_UP, '[B': KEY_DOWN, '[C': KEY_RIGHT, '[D': KEY_LEFT,
                '[H': KEY_HOME, '[F': KEY_END, '[3~': KEY_DELETE,
                '[1~': KEY_HOME, '[4~': KEY_END, 'OH': KEY_HOME, 'OF': KEY_END
            }
            return esc_map.get(seq, KEY_ESC)
        if ch == '\x03':
            raise KeyboardInterrupt
        if ch == '\x04':
            raise EOFError
        ctrl_map = {
            '\x01': KEY_CTRL_A, '\x05': KEY_CTRL_E,
            '\x15': KEY_CTRL_U, '\x17': KEY_CTRL_W
        }
        if ch in ctrl_map:
            return ctrl_map[ch]
        return {'\r': KEY_ENTER, '\n': KEY_ENTER, '\t': KEY_TAB, '\x7f': KEY_BACKSPACE, '\x08': KEY_BACKSPACE}.get(ch, ch)
    except (IOError, OSError):
        return ''
    finally:
        if old:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except termios.error:
                pass

def shimmer_thinking(text="Thinking"):
    """Animated shimmer, returns stop event"""
    stop = threading.Event()
    def run():
        chars = f"◆ {text}..."
        i = 0
        try:
            while not stop.is_set():
                out = ""
                for j, c in enumerate(chars):
                    d = abs(j - (i % (len(chars) + 6)))
                    out += f"{WHITE}{BOLD}{c}{RESET}" if d == 0 else f"{LBLUE}{c}{RESET}" if d <= 2 else f"{GRAY}{c}{RESET}"
                sys.stdout.write(f"{CLEAR_LINE}  {out}")
                sys.stdout.flush()
                if stop.wait(0.1):
                    break
                i += 1
        except (IOError, OSError):
            pass
        finally:
            try:
                sys.stdout.write(CLEAR_LINE)
                sys.stdout.flush()
            except (IOError, OSError):
                pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return stop

def arrow_select(options, title="Select"):
    """Arrow key menu selection - handles empty lists and edge cases"""
    if not options:
        return -1, None
    idx = 0
    print(f"\n{BLUE}{BOLD}{title}{RESET}")
    def render():
        for i, opt in enumerate(options):
            name, desc = (opt[0], opt[1] if len(opt) > 1 else "") if isinstance(opt, tuple) else (str(opt), "")
            if i == idx:
                print(f"  {CYAN}▸ {WHITE}{BOLD}{name}{RESET} {GRAY}{desc}{RESET}")
            else:
                print(f"    {GRAY}{name} {DIM}{desc}{RESET}")
    render()
    while True:
        try:
            ch = getch()
        except (KeyboardInterrupt, EOFError):
            ch = KEY_ESC
        if not ch:
            continue
        print(f"\033[{len(options)}A", end="", flush=True)
        if ch == KEY_UP:
            idx = (idx - 1) % len(options)
        elif ch == KEY_DOWN:
            idx = (idx + 1) % len(options)
        elif ch == KEY_ENTER:
            for _ in range(len(options)):
                print(CLEAR_LINE)
            print(f"\033[{len(options)}A", end="", flush=True)
            opt = options[idx]
            return idx, opt[0] if isinstance(opt, tuple) else opt
        elif ch == KEY_ESC or ch == 'q':
            for _ in range(len(options)):
                print(CLEAR_LINE)
            print(f"\033[{len(options)}A", end="", flush=True)
            return -1, None
        for _ in range(len(options)):
            print(CLEAR_LINE, end="\n")
        print(f"\033[{len(options)}A", end="", flush=True)
        render()

def permission_prompt(action, target=None):
    """Permission check for destructive ops"""
    global trust_session
    if trust_session:
        return True
    msg = f"{action}" + (f" → {target}" if target else "")
    idx, choice = arrow_select([("Yes", "Allow"), ("Trust", "Allow all"), ("No", "Deny")], f"⚠ {msg}")
    if choice == "Trust":
        trust_session = True
        return True
    return choice == "Yes"

def format_markdown(text):
    """Format markdown for terminal - handles nested formatting"""
    if not text:
        return ""
    # Code blocks first (protect from other formatting)
    blocks = {}
    def save_block(m):
        key = f"\x00BLOCK{len(blocks)}\x00"
        blocks[key] = f"\n{GRAY}─────{RESET}\n{LBLUE}{m.group(2)}{RESET}{GRAY}─────{RESET}\n"
        return key
    text = re.sub(r'```(\w*)\n(.*?)```', save_block, text, flags=re.DOTALL)
    
    # Inline code (protect from other formatting)
    codes = {}
    def save_code(m):
        key = f"\x00CODE{len(codes)}\x00"
        codes[key] = f'{LBLUE}{m.group(1)}{RESET}'
        return key
    text = re.sub(r'`([^`]+)`', save_code, text)
    
    # Bold and italic
    text = re.sub(r'\*\*([^*]+)\*\*', f'{BOLD}{WHITE}\\1{RESET}', text)
    text = re.sub(r'\*([^*]+)\*', f'{ITALIC}\\1{RESET}', text)
    
    # Headers
    text = re.sub(r'^### (.+)$', f'{BLUE}\\1{RESET}', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$', f'{BLUE}{BOLD}\\1{RESET}', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$', f'{BLUE}{BOLD}\\1{RESET}', text, flags=re.MULTILINE)
    
    # Lists
    text = re.sub(r'^- (.+)$', f'  {CYAN}•{RESET} \\1', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\. (.+)$', f'  {CYAN}▸{RESET} \\1', text, flags=re.MULTILINE)
    
    # Restore protected content
    for key, val in codes.items():
        text = text.replace(key, val)
    for key, val in blocks.items():
        text = text.replace(key, val)
    
    return text

def input_line(prompt, history_list=None):
    """Input with cursor movement, history, and command suggestions"""
    if not is_tty():
        print(prompt, end="", flush=True)
        try:
            return input()
        except EOFError:
            raise KeyboardInterrupt
    
    buf, cursor = "", 0
    hist = (history_list or [])[:]
    hist_idx = len(hist)
    
    # Get terminal width
    def get_width():
        try:
            return os.get_terminal_size().columns
        except OSError:
            return 80
    
    # Calculate visible length (strip ANSI codes)
    def visible_len(s):
        return len(re.sub(r'\033\[[0-9;]*m', '', s))
    
    prompt_len = visible_len(prompt)
    
    def get_hint():
        if buf.startswith("/") and len(buf) > 1:
            matches = [c for c in COMMANDS if c.startswith(buf) and c != buf]
            if matches:
                return matches[0][len(buf):]
        return ""
    
    def redraw():
        hint = get_hint()
        width = get_width()
        total_len = prompt_len + len(buf) + len(hint)
        lines_used = (total_len + width - 1) // width  # Ceiling division
        
        # Move to start: go up to first line, then carriage return
        if lines_used > 1:
            sys.stdout.write(f"\033[{lines_used - 1}A")
        sys.stdout.write("\r")
        
        # Clear from cursor to end of screen
        sys.stdout.write("\033[J")
        
        # Redraw
        sys.stdout.write(f"{prompt}{buf}")
        if hint:
            sys.stdout.write(f"{GRAY}{hint}{RESET}")
        
        # Position cursor
        cursor_pos = prompt_len + cursor
        target_line = cursor_pos // width
        target_col = cursor_pos % width
        current_line = total_len // width
        
        # Move cursor to correct position
        if current_line > target_line:
            sys.stdout.write(f"\033[{current_line - target_line}A")
        if target_col > 0:
            sys.stdout.write(f"\r\033[{target_col}C")
        else:
            sys.stdout.write("\r")
        
        sys.stdout.flush()
    
    sys.stdout.write(prompt)
    sys.stdout.flush()
    
    while True:
        try:
            ch = getch()
        except (KeyboardInterrupt, EOFError):
            sys.stdout.write("\n")
            sys.stdout.flush()
            raise KeyboardInterrupt
        if not ch:
            continue
        if ch == KEY_ENTER:
            # Clear and reprint without hint
            width = get_width()
            total_len = prompt_len + len(buf) + len(get_hint())
            lines_used = (total_len + width - 1) // width
            if lines_used > 1:
                sys.stdout.write(f"\033[{lines_used - 1}A")
            sys.stdout.write("\r\033[J")
            sys.stdout.write(f"{prompt}{buf}\n")
            sys.stdout.flush()
            return buf
        elif ch == KEY_BACKSPACE:
            if cursor > 0:
                buf = buf[:cursor-1] + buf[cursor:]
                cursor -= 1
                redraw()
        elif ch == KEY_DELETE:
            if cursor < len(buf):
                buf = buf[:cursor] + buf[cursor+1:]
                redraw()
        elif ch == KEY_LEFT:
            if cursor > 0:
                cursor -= 1
                redraw()
        elif ch == KEY_RIGHT:
            hint = get_hint()
            if cursor < len(buf):
                cursor += 1
                redraw()
            elif hint:
                buf += hint[0]
                cursor = len(buf)
                redraw()
        elif ch in (KEY_HOME, KEY_CTRL_A):
            if cursor > 0:
                cursor = 0
                redraw()
        elif ch in (KEY_END, KEY_CTRL_E):
            if cursor < len(buf):
                cursor = len(buf)
                redraw()
        elif ch == KEY_CTRL_U:
            if buf:
                buf, cursor = "", 0
                redraw()
        elif ch == KEY_CTRL_W:
            if cursor > 0:
                i = cursor - 1
                while i > 0 and buf[i-1] == ' ':
                    i -= 1
                while i > 0 and buf[i-1] != ' ':
                    i -= 1
                buf = buf[:i] + buf[cursor:]
                cursor = i
                redraw()
        elif ch == KEY_UP:
            if hist and hist_idx > 0:
                hist_idx -= 1
                buf, cursor = hist[hist_idx], len(hist[hist_idx])
                redraw()
        elif ch == KEY_DOWN:
            if hist_idx < len(hist) - 1:
                hist_idx += 1
                buf, cursor = hist[hist_idx], len(hist[hist_idx])
                redraw()
            else:
                hist_idx = len(hist)
                buf, cursor = "", 0
                redraw()
        elif ch == KEY_TAB:
            hint = get_hint()
            if hint:
                buf += hint
                cursor = len(buf)
                redraw()
        elif ch == KEY_ESC:
            pass
        elif isinstance(ch, str) and len(ch) == 1 and ch.isprintable():
            buf = buf[:cursor] + ch + buf[cursor:]
            cursor += 1
            redraw()

def load_keys():
    try:
        if KEYS_FILE.exists():
            data = json.loads(KEYS_FILE.read_text())
            keys = data.get("keys", [])
            return [k for k in keys if isinstance(k, str) and k]
        return []
    except (json.JSONDecodeError, OSError):
        return []

def save_keys(keys):
    CONFIG_DIR.mkdir(exist_ok=True)
    KEYS_FILE.write_text(json.dumps({"keys": keys[:5]}, indent=2))

def load_settings():
    default = {"model": "codex", "mode": "cloud", "ollama_model": "llama3", 
               "experiments": {"reasoning": False, "planning": False, "verbose": False, "details": False}}
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text())
            if isinstance(data, dict):
                for k in ("model", "mode", "ollama_model"):
                    if k in data and isinstance(data[k], str):
                        default[k] = data[k]
                if isinstance(data.get("experiments"), dict):
                    for k in default["experiments"]:
                        if k in data["experiments"] and isinstance(data["experiments"][k], bool):
                            default["experiments"][k] = data["experiments"][k]
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return default

def save_settings(s):
    CONFIG_DIR.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))

def save_conversation(messages, name=None):
    """Save conversation to file"""
    CONFIG_DIR.mkdir(exist_ok=True)
    name = name or datetime.now().strftime("%Y%m%d_%H%M%S")
    path = CONFIG_DIR / f"conv_{name}.json"
    path.write_text(json.dumps(messages, indent=2))
    return path

def load_conversation(name):
    """Load conversation from file"""
    path = CONFIG_DIR / f"conv_{name}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list) and all(isinstance(m, dict) for m in data):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return None

def list_conversations():
    """List saved conversations"""
    if not CONFIG_DIR.exists():
        return []
    return sorted([f.stem.replace("conv_", "") for f in CONFIG_DIR.glob("conv_*.json")])

def banner():
    print(f"""
{BLUE}{BOLD}    ██╗     ██╗   ██╗███╗   ███╗██╗███████╗
    ██║     ██║   ██║████╗ ████║██║██╔════╝
    ██║     ██║   ██║██╔████╔██║██║███████╗
    ██║     ██║   ██║██║╚██╔╝██║██║╚════██║
    ███████╗╚██████╔╝██║ ╚═╝ ██║██║███████║
    ╚══════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝╚══════╝{RESET}
{GRAY}    ─────────────────────────────────────
{WHITE}         AI Terminal Agent  {DIM}v2.1{RESET}
{GRAY}    ─────────────────────────────────────{RESET}
""")

def show_help():
    print(f"\n{BLUE}{BOLD}Commands{RESET}")
    for cmd, desc in COMMANDS.items():
        print(f"  {WHITE}{cmd:14}{GRAY}{desc}{RESET}")
    print()

def show_status(settings):
    print(f"\n{BLUE}{BOLD}Status{RESET}")
    mode = settings.get("mode", "cloud")
    if mode == "local":
        print(f"  {WHITE}Mode        {CYAN}Local (Ollama){RESET}")
        print(f"  {WHITE}Model       {CYAN}{settings.get('ollama_model', 'llama3')}{RESET}")
    else:
        m = MODELS.get(settings.get('model', 'codex'), (settings.get('model'),))
        print(f"  {WHITE}Mode        {CYAN}Cloud (Poe){RESET}")
        print(f"  {WHITE}Model       {CYAN}{m[0]}{RESET}")
    exps = [k for k, v in settings.get('experiments', {}).items() if v]
    print(f"  {WHITE}Experiments {GRAY}{', '.join(exps) if exps else 'None'}{RESET}")
    print()

def model_selector(settings):
    """Model selection menu"""
    if settings.get("mode") == "local":
        models = get_ollama_models()
        if not models:
            print(f"{YELLOW}No Ollama models. Install: ollama pull <model>{RESET}\n")
            return
        idx, choice = arrow_select([(m, "") for m in models], "Ollama Model")
        if choice:
            settings["ollama_model"] = choice
            save_settings(settings)
            set_terminal_title(f"Lumis • {choice}")
            print(f"{GREEN}✓ {choice}{RESET}\n")
    else:
        opts = [(k, f"{v[0]} {GREEN if v[1]=='$' else YELLOW}{v[1]}{RESET} {GRAY}{v[2]}") for k, v in MODELS.items()]
        idx, choice = arrow_select(opts, "Select Model")
        if choice:
            settings["model"] = choice
            save_settings(settings)
            set_terminal_title(f"Lumis • {MODELS[choice][0]}")
            print(f"{GREEN}✓ {MODELS[choice][0]}{RESET}\n")

def experiment_selector(settings):
    """Experiment toggle menu"""
    while True:
        opts = []
        for k, (name, desc) in EXPERIMENTS.items():
            on = settings["experiments"].get(k, False)
            opts.append((k, f"{GREEN}ON{RESET} {GRAY}{name}{RESET}" if on else f"{GRAY}OFF {DIM}{name}{RESET}"))
        opts.append(("Done", "Return"))
        idx, choice = arrow_select(opts, "Experiments")
        if choice == "Done" or idx == -1:
            break
        if choice in EXPERIMENTS:
            settings["experiments"][choice] = not settings["experiments"].get(choice, False)
            save_settings(settings)

def doctor():
    print(f"\n{BLUE}{BOLD}Diagnostics{RESET}")
    keys = load_keys()
    print(f"  {WHITE}API Keys    {GREEN if keys else RED}{'●' if keys else '○'} {len(keys)}/5{RESET}")
    print(f"  {WHITE}Config      {CYAN}{CONFIG_DIR}{RESET}")
    print(f"  {WHITE}Python      {GRAY}{sys.version.split()[0]}{RESET}")
    ollama_ok = check_ollama()
    print(f"  {WHITE}Ollama      {GREEN if ollama_ok else GRAY}{'● Running' if ollama_ok else '○ Not running'}{RESET}")
    if keys:
        stop = shimmer_thinking("Testing API")
        try:
            r = requests.post("https://api.poe.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {keys[0]}", "Content-Type": "application/json"},
                json={"model": "GPT-5.1-Codex-Mini", "messages": [{"role": "user", "content": "hi"}]}, timeout=10)
            stop.set()
            time.sleep(0.15)
            print(f"  {WHITE}Poe API     {GREEN if r.ok else YELLOW}{'● Connected' if r.ok else '○ Issue'}{RESET}")
        except:
            stop.set()
            time.sleep(0.15)
            print(f"  {WHITE}Poe API     {RED}○ Failed{RESET}")
    print()

def check_ollama():
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=2).ok
    except:
        return False

def get_ollama_models():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return [m["name"] for m in r.json().get("models", [])] if r.ok else []
    except:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL EXTRACTION & EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

def extract_tool_calls(text):
    """Robust tool extraction - handles multiple formats, deduplicates"""
    if not text:
        return []
    
    tools = []
    seen = set()
    
    def add_tool(data):
        if isinstance(data, dict) and data.get("tool"):
            key = json.dumps(data, sort_keys=True)
            if key not in seen:
                seen.add(key)
                tools.append(data)
    
    # Pattern 1: ```json blocks (highest priority)
    for m in re.finditer(r'```(?:json)?\s*(\{.+?\})\s*```', text, re.DOTALL):
        try:
            add_tool(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass
    
    # Pattern 2: <tool> tags
    for m in re.finditer(r'<tool>\s*(\{.+?\})\s*</tool>', text, re.DOTALL):
        try:
            add_tool(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass
    
    # Pattern 3: Standalone JSON (only if nothing found yet)
    if not tools:
        for m in re.finditer(r'(?<![`\w])(\{"tool"\s*:\s*"[^"]+".+?\})(?![`\w])', text, re.DOTALL):
            try:
                candidate = m.group(1)
                # Balance braces
                depth = 0
                end = 0
                for i, c in enumerate(candidate):
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end > 0:
                    add_tool(json.loads(candidate[:end]))
            except json.JSONDecodeError:
                pass
    
    log_verbose(f"Extracted {len(tools)} tool call(s)", "tool")
    return tools

def execute_tool(call):
    """Execute a single tool call with validation"""
    if not isinstance(call, dict):
        return {"ok": False, "error": "Invalid tool format"}
    
    tool = call.get("tool", "")
    path = call.get("path", "")
    start = time.time()
    
    log_verbose(f"Executing: {tool}" + (f" on {path}" if path else ""), "tool")
    
    # Permission check
    destructive = tool in ("delete_file", "write_file", "edit_file", "patch_file", "run_command")
    if destructive:
        target = path or call.get("command", "")[:60]
        if not permission_prompt(f"{tool}", target):
            return {"ok": False, "error": "Denied by user", "tool": tool}
    
    try:
        result = _execute_tool_inner(tool, call)
        elapsed = time.time() - start
        log_verbose(f"Completed in {elapsed:.2f}s", "time")
        return result
    except Exception as e:
        return {"ok": False, "error": str(e), "tool": tool}

def _execute_tool_inner(tool, call):
    """Inner tool execution logic"""
    path = call.get("path", "")
    
    if tool == "read_file":
        if not path:
            return {"ok": False, "error": "No path"}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"Not found: {p}"}
        if p.is_dir():
            return {"ok": False, "error": f"Is directory: {p}"}
        
        start_line = call.get("start_line")
        end_line = call.get("end_line")
        
        try:
            size = p.stat().st_size
            # Intelligent Mode for large files
            if size > 400000 and start_line is None:
                return {
                    "ok": False, 
                    "error": "File > 400KB. Intelligent Mode: Use 'search_file' to locate relevant code, then 'read_file' with start_line/end_line to read specific sections."
                }
            
            # Read all or specific lines
            content = p.read_text(errors='replace')
            lines = content.splitlines(keepends=True)
            
            if start_line is not None:
                start = max(0, int(start_line) - 1)
                end = min(len(lines), int(end_line)) if end_line is not None else len(lines)
                if start >= len(lines):
                    return {"ok": False, "error": f"Start line {start_line} out of range (max {len(lines)})"}
                selected = "".join(lines[start:end])
                return {"ok": True, "result": selected, "lines": f"{start+1}-{end}"}
                
            if size > MAX_FILE_SIZE:
                return {"ok": True, "result": content[:MAX_FILE_SIZE], "truncated": True, "size": size}
                
            return {"ok": True, "result": content}
        except UnicodeDecodeError:
            return {"ok": False, "error": "Binary file, cannot read as text"}
        except PermissionError:
            return {"ok": False, "error": f"Permission denied: {p}"}
    
    elif tool == "write_file":
        if not path:
            return {"ok": False, "error": "No path"}
        content = call.get("content")
        if content is None:
            return {"ok": False, "error": "No content"}
        p = Path(path).expanduser().resolve()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(content))
            return {"ok": True, "result": f"Written: {p} ({len(str(content))} bytes)"}
        except PermissionError:
            return {"ok": False, "error": f"Permission denied: {p}"}
        except OSError as e:
            return {"ok": False, "error": f"Write failed: {e}"}
    
    elif tool == "edit_file":
        if not path:
            return {"ok": False, "error": "No path"}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"Not found: {p}"}
        edits = call.get("edits", [])
        if not edits:
            return {"ok": False, "error": "No edits"}
        try:
            content = p.read_text(errors='replace')
        except PermissionError:
            return {"ok": False, "error": f"Permission denied: {p}"}
        changes = 0
        for e in edits:
            if not isinstance(e, dict):
                continue
            find = e.get("find", "")
            if find and find in content:
                content = content.replace(find, str(e.get("replace", "")), 1)
                changes += 1
        if changes == 0:
            return {"ok": False, "error": "No matches found"}
        try:
            p.write_text(content)
        except PermissionError:
            return {"ok": False, "error": f"Permission denied: {p}"}
        return {"ok": True, "result": f"Edited: {p} ({changes} changes)"}
    
    elif tool == "patch_file":
        if not path:
            return {"ok": False, "error": "No path"}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"Not found: {p}"}
        patches = call.get("patches", [])
        if not patches:
            return {"ok": False, "error": "No patches"}
        try:
            content = p.read_text(errors='replace')
        except PermissionError:
            return {"ok": False, "error": f"Permission denied: {p}"}
        lines = content.splitlines(keepends=True)
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        patches = sorted(patches, key=lambda x: x.get("line", 0), reverse=True)
        changes = 0
        for patch in patches:
            line_num = patch.get("line", 0) - 1
            action = patch.get("action", "replace")
            pcontent = patch.get("content", "")
            if pcontent and not pcontent.endswith("\n"):
                pcontent += "\n"
            if action == "delete":
                if 0 <= line_num < len(lines):
                    lines.pop(line_num)
                    changes += 1
            elif 0 <= line_num < len(lines):
                if action == "replace":
                    lines[line_num] = pcontent
                    changes += 1
                elif action == "insert_after":
                    lines.insert(line_num + 1, pcontent)
                    changes += 1
                elif action == "insert_before":
                    lines.insert(line_num, pcontent)
                    changes += 1
            elif action in ("insert_after", "insert_before") and line_num == len(lines):
                lines.append(pcontent)
                changes += 1
        try:
            p.write_text("".join(lines))
        except PermissionError:
            return {"ok": False, "error": f"Permission denied: {p}"}
        return {"ok": True, "result": f"Patched: {p} ({changes} changes)"}
    
    elif tool == "run_command":
        cmd = call.get("command", "")
        if not cmd:
            return {"ok": False, "error": "No command"}
        timeout = min(call.get("timeout", 60), 120)
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=Path.home())
            output = (r.stdout + r.stderr).strip()
            if len(output) > 10000:
                output = output[:10000] + "\n... (truncated)"
            return {"ok": r.returncode == 0, "result": output or "(no output)", "code": r.returncode}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Timeout ({timeout}s)"}
        except OSError as e:
            return {"ok": False, "error": f"Command failed: {e}"}
    
    elif tool == "list_dir":
        p = Path(path or ".").expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"Not found: {p}"}
        if not p.is_dir():
            return {"ok": False, "error": f"Not a directory: {p}"}
        depth = min(call.get("depth", 1), 3)
        items = []
        def walk(dir_path, current_depth, prefix=""):
            if current_depth > depth:
                return
            try:
                entries = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                for entry in entries[:100]:
                    icon = "📁" if entry.is_dir() else "  "
                    items.append(f"{prefix}{icon} {entry.name}")
                    if entry.is_dir() and current_depth < depth:
                        walk(entry, current_depth + 1, prefix + "  ")
            except PermissionError:
                items.append(f"{prefix}⚠ (permission denied)")
        walk(p, 1)
        return {"ok": True, "result": "\n".join(items[:200]) or "(empty)"}
    
    elif tool == "search_file":
        if not path:
            return {"ok": False, "error": "No path"}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"Not found: {p}"}
        pattern = call.get("pattern", "")
        if not pattern:
            return {"ok": False, "error": "No pattern"}
        try:
            content = p.read_text(errors='replace')
        except PermissionError:
            return {"ok": False, "error": f"Permission denied: {p}"}
        lines = content.splitlines()
        matches = []
        pattern_lower = pattern.lower()
        for i, line in enumerate(lines, 1):
            if pattern_lower in line.lower():
                matches.append(f"{i}: {line[:120]}")
        if not matches:
            return {"ok": True, "result": "No matches"}
        return {"ok": True, "result": "\n".join(matches[:50])}
    
    elif tool == "delete_file":
        if not path:
            return {"ok": False, "error": "No path"}
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"ok": False, "error": f"Not found: {p}"}
        if p.is_dir():
            return {"ok": False, "error": "Cannot delete directory"}
        try:
            p.unlink()
        except PermissionError:
            return {"ok": False, "error": f"Permission denied: {p}"}
        return {"ok": True, "result": f"Deleted: {p}"}
    
    elif tool == "todo":
        action = call.get("action", "")
        tasks = call.get("tasks", [])
        indices = call.get("indices", [])
        title = call.get("title", "")
        return todo_tool(action, tasks, indices, title)
    
    return {"ok": False, "error": f"Unknown tool: {tool}"}

def format_tool_result(result):
    """Format tool result for display"""
    if not result.get("ok"):
        return f"{RED}✗ {result.get('error', 'Failed')}{RESET}"
    text = result.get("result", "")
    lines = text.split("\n")
    if len(lines) > 12:
        return "\n".join(lines[:10]) + f"\n{DIM}... ({len(lines)-10} more lines){RESET}"
    return text


# ═══════════════════════════════════════════════════════════════════════════════
# API & CHAT
# ═══════════════════════════════════════════════════════════════════════════════

def chat_ollama(messages, model):
    """Chat via local Ollama"""
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat",
            json={"model": model, "messages": messages, "stream": False}, timeout=180)
        if r.ok:
            try:
                data = r.json()
                content = data.get("message", {}).get("content", "")
                return {"ok": True, "content": content}
            except (json.JSONDecodeError, KeyError):
                return {"ok": False, "error": "Invalid response from Ollama"}
        return {"ok": False, "error": f"Ollama error: {r.status_code}"}
    except requests.Timeout:
        return {"ok": False, "error": "Timeout"}
    except requests.ConnectionError:
        return {"ok": False, "error": "Ollama not running (ollama serve)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def chat_poe(messages, settings):
    """Chat via Poe API with retries and experimental features"""
    keys = load_keys()
    if not keys:
        return {"ok": False, "error": "No API keys configured"}
    
    model_key = settings.get("model", "codex")
    model = MODELS.get(model_key, ("GPT-5.1-Codex-Mini",))[0]
    experiments = settings.get("experiments", {})
    
    msgs = [m.copy() for m in messages]
    if msgs and msgs[-1].get("role") == "user" and experiments.get("reasoning"):
        flags = []
        if model_key in ("codex", "gpt"):
            flags.append("--reasoning_effort high")
        elif model_key == "opus":
            flags.extend(["--thinking_budget 24000", "--web_search true"])
        elif model_key == "sonnet":
            flags.extend(["--thinking_budget 16000", "--web_search true"])
        elif model_key == "haiku":
            flags.extend(["--thinking_budget 8000", "--web_search true"])
        if flags:
            msgs[-1]["content"] = f"{msgs[-1]['content']} {' '.join(flags)}"
            log_verbose(f"Applied reasoning flags: {', '.join(flags)}", "api")
    
    if experiments.get("verbose") and msgs and msgs[-1].get("role") == "user":
        verbose_prompt = "\n\n[Think carefully. Take your time. Verify your work before responding.]"
        msgs[-1]["content"] = msgs[-1]["content"] + verbose_prompt
    
    errors = []
    for i, key in enumerate(keys):
        log_verbose(f"Trying key {i+1}/{len(keys)}", "api")
        try:
            start = time.time()
            r = requests.post("https://api.poe.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": msgs}, timeout=180)
            
            if r.ok:
                try:
                    data = r.json()
                    if data.get("choices"):
                        elapsed = time.time() - start
                        content = data["choices"][0].get("message", {}).get("content", "")
                        return {"ok": True, "content": content, "model": model, "time": elapsed, "tokens": estimate_tokens(content)}
                    errors.append(f"Key {i+1}: Invalid response format")
                except (json.JSONDecodeError, KeyError, IndexError):
                    errors.append(f"Key {i+1}: Malformed JSON")
            else:
                errors.append(f"Key {i+1}: HTTP {r.status_code}")
                if r.status_code == 429:
                    time.sleep(1) # Extra wait for rate limits
        except requests.Timeout:
            errors.append(f"Key {i+1}: Timeout")
        except requests.ConnectionError:
            errors.append(f"Key {i+1}: Connection failed")
        except Exception as e:
            errors.append(f"Key {i+1}: {str(e)}")
            
        # If we are here, something failed. Log and try next.
        log_verbose(f"Key {i+1} failed. Switching to next...", "api")
        time.sleep(0.5) # Brief pause before transfer
    
    return {"ok": False, "error": "; ".join(errors[-3:]) if errors else "All keys exhausted"}

def chat(messages, settings):
    """Main chat function - routes to appropriate backend"""
    if settings.get("mode") == "local":
        return chat_ollama(messages, settings.get("ollama_model", "llama3"))
    return chat_poe(messages, settings)

def trim_context(messages, max_msgs=MAX_CONTEXT_MESSAGES):
    """Trim conversation to stay within context limits"""
    if len(messages) <= max_msgs:
        return messages
    system = [m for m in messages if m.get("role") == "system"]
    others = [m for m in messages if m.get("role") != "system"]
    keep = max(max_msgs - len(system), 2)
    log_verbose(f"Trimmed context: {len(others)} → {keep} messages", "info")
    return system + others[-keep:]

# ═══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE TODO SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

def display_todo(title=None):
    """Display the session TODO list with stylized box"""
    global session_todo
    if not session_todo or not session_todo.get("tasks"):
        return
    
    title = title or session_todo.get("title", "TODO")
    tasks = session_todo["tasks"]
    
    # Strip ANSI codes for width calculation
    def visible_len(s):
        return len(re.sub(r'\033\[[0-9;]*m', '', s))
    
    max_len = max(visible_len(t.get("task", "")[:45]) for t in tasks) if tasks else 10
    width = max(max_len + 8, visible_len(title) + 6, 35)
    
    print(f"\n{BLUE}╭─ {BOLD}{WHITE}{title}{RESET}{BLUE} {'─' * (width - visible_len(title) - 4)}╮{RESET}")
    
    done_count = sum(1 for t in tasks if t.get("done"))
    for i, t in enumerate(tasks, 1):
        done = t.get("done", False)
        task = t.get("task", "")[:45]
        task_vis_len = visible_len(task)
        if done:
            mark = f"{GREEN}✓{RESET}"
            style = DIM
        else:
            mark = f"{GRAY}○{RESET}"
            style = WHITE
        padding = " " * max(0, width - task_vis_len - 6)
        print(f"{BLUE}│{RESET} {mark} {style}{i}. {task}{RESET}{padding}{BLUE}│{RESET}")
    
    progress = done_count / len(tasks) if tasks else 0
    bar_width = width - 4
    filled = int(progress * bar_width)
    bar = f"{GREEN}{'█' * filled}{GRAY}{'░' * (bar_width - filled)}{RESET}"
    print(f"{BLUE}├{'─' * width}┤{RESET}")
    print(f"{BLUE}│{RESET} {bar} {BLUE}│{RESET}")
    print(f"{BLUE}╰{'─' * width}╯{RESET}\n")

def todo_tool(action, tasks=None, indices=None, title=None):
    """Handle TODO tool calls from the model"""
    global session_todo
    
    if action == "create":
        if not tasks:
            return {"ok": False, "error": "No tasks provided"}
        session_todo = {
            "title": title or "Task Plan",
            "tasks": [{"task": t, "done": False} for t in tasks[:8]]
        }
        display_todo()
        return {"ok": True, "result": f"Created TODO with {len(session_todo['tasks'])} tasks"}
    
    elif action == "check":
        if not session_todo:
            return {"ok": False, "error": "No TODO list exists"}
        if not indices:
            return {"ok": False, "error": "No indices provided"}
        checked = 0
        for idx in indices:
            if 0 < idx <= len(session_todo["tasks"]):
                session_todo["tasks"][idx - 1]["done"] = True
                checked += 1
        display_todo()
        return {"ok": True, "result": f"Checked off {checked} task(s)"}
    
    elif action == "show":
        if not session_todo:
            return {"ok": True, "result": "No TODO list"}
        display_todo()
        return {"ok": True, "result": "Displayed TODO"}
    
    elif action == "clear":
        session_todo = None
        return {"ok": True, "result": "Cleared TODO list"}
    
    return {"ok": False, "error": f"Unknown action: {action}"}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def handle_command(cmd, args, settings, messages, history):
    """Handle slash commands, returns (should_continue, messages, history)"""
    global trust_session, verbose_mode, session_todo, details_mode
    
    if cmd == "/exit":
        print(f"{GRAY}Goodbye!{RESET}")
        return False, messages, history
    elif cmd == "/help":
        show_help()
    elif cmd in ("/model", "/models"):
        model_selector(settings)
    elif cmd == "/local":
        if check_ollama():
            settings["mode"] = "local"
            save_settings(settings)
            print(f"{GREEN}✓ Switched to Ollama{RESET}")
            models = get_ollama_models()
            if models:
                print(f"  {GRAY}Models: {', '.join(models[:5])}{RESET}")
            print()
        else:
            print(f"{YELLOW}Ollama not running. Start: ollama serve{RESET}\n")
    elif cmd == "/cloud":
        settings["mode"] = "cloud"
        save_settings(settings)
        print(f"{GREEN}✓ Switched to Poe{RESET}\n")
    elif cmd == "/doctor":
        doctor()
    elif cmd == "/clear":
        os.system("clear")
        banner()
    elif cmd == "/history":
        if history:
            for h in history[-10:]:
                print(f"  {GRAY}▸ {h[:60]}{'...' if len(h)>60 else ''}{RESET}")
        else:
            print(f"  {GRAY}No history{RESET}")
        print()
    elif cmd == "/reset":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        history = []
        trust_session = False
        session_todo = None
        print(f"{GREEN}✓ Reset{RESET}\n")
    elif cmd == "/experiments":
        experiment_selector(settings)
        verbose_mode = settings.get("experiments", {}).get("verbose", False)
        details_mode = settings.get("experiments", {}).get("details", False)
    elif cmd == "/status":
        show_status(settings)
    elif cmd == "/save":
        name = args[0] if args else None
        path = save_conversation(messages, name)
        print(f"{GREEN}✓ Saved: {path.name}{RESET}\n")
    elif cmd == "/load":
        convs = list_conversations()
        if not convs:
            print(f"{GRAY}No saved conversations{RESET}\n")
        elif args:
            loaded = load_conversation(args[0])
            if loaded:
                messages = loaded
                print(f"{GREEN}✓ Loaded{RESET}\n")
            else:
                print(f"{RED}Not found{RESET}\n")
        else:
            opts = [(c, "") for c in convs[-10:]]
            idx, choice = arrow_select(opts, "Load Conversation")
            if choice:
                loaded = load_conversation(choice)
                if loaded:
                    messages = loaded
                    print(f"{GREEN}✓ Loaded{RESET}\n")
    else:
        print(f"{GRAY}Unknown command. Try /help{RESET}\n")
    
    return True, messages, history

def agent_loop(user_input, messages, settings):
    """Main agent loop - handles tool calls and responses"""
    global verbose_mode, details_mode
    
    for loop_i in range(MAX_TOOL_LOOPS):
        log_verbose(f"Agent loop iteration {loop_i + 1}", "info")
        
        # Trim context if needed
        messages = trim_context(messages)
        
        # Get response
        stop = shimmer_thinking()
        result = chat(messages, settings)
        stop.set()
        time.sleep(0.15)
        
        if not result.get("ok"):
            print(f"\n{RED}Error: {result.get('error', 'Unknown')}{RESET}\n")
            return messages
        
        response = result.get("content", "")
        
        # Extract and execute tools
        tools = extract_tool_calls(response)
        
        if tools:
            # Execute each tool
            tool_results = []
            for tool_call in tools:
                tool_name = tool_call.get("tool", "action")
                print(f"  {CYAN}⚡ {tool_name}{RESET}")
                
                tool_result = execute_tool(tool_call)
                formatted = format_tool_result(tool_result)
                
                # Show result
                for line in formatted.split('\n')[:8]:
                    print(f"  {DIM}{line[:80]}{RESET}")
                if formatted.count('\n') > 8:
                    print(f"  {DIM}...{RESET}")
                print()
                
                # Collect result
                if tool_result.get("ok"):
                    tool_results.append(f"[{tool_name}] Success:\n{tool_result.get('result', '')}")
                else:
                    tool_results.append(f"[{tool_name}] Error: {tool_result.get('error', 'Failed')}")
            
            # Add to conversation
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": "Tool results:\n" + "\n\n".join(tool_results)})
        else:
            # No tools - final response
            formatted = format_markdown(response)
            print(f"\n{WHITE}{formatted}{RESET}")
            
            # Show details at bottom if enabled
            if details_mode:
                model = result.get("model", "unknown")
                resp_time = result.get("time", 0)
                tokens = result.get("tokens", estimate_tokens(response))
                ctx_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
                print(f"{DIM}─────────────────────────────────────────{RESET}")
                print(f"{DIM}{model} | {tokens} tokens | {resp_time:.1f}s | ctx: {ctx_tokens}{RESET}")
            print()
            
            messages.append({"role": "assistant", "content": response})
            return messages
    
    print(f"{YELLOW}Max iterations reached{RESET}\n")
    return messages

MAX_HISTORY = 500

def main():
    global trust_session, verbose_mode, details_mode
    
    def handle_sigint(sig, frame):
        print(f"\n{GRAY}Interrupted{RESET}")
        sys.exit(0)
    signal.signal(signal.SIGINT, handle_sigint)
    
    os.system("clear")
    set_terminal_title("Lumis")
    banner()
    
    settings = load_settings()
    verbose_mode = settings.get("experiments", {}).get("verbose", False)
    details_mode = settings.get("experiments", {}).get("details", False)
    
    # Set title with current model
    if settings.get("mode") == "local":
        set_terminal_title(f"Lumis • {settings.get('ollama_model', 'llama3')}")
    else:
        model_name = MODELS.get(settings.get('model', 'codex'), ('codex',))[0]
        set_terminal_title(f"Lumis • {model_name}")
    
    if not load_keys():
        print(f"{YELLOW}  No API keys found! Cloud mode requires a Poe API key in:{RESET}")
        print(f"{GRAY}  {KEYS_FILE}{RESET}\n")
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    history = []
    
    print(f"{GRAY}  Type {WHITE}/help{GRAY} for commands • Tab to autocomplete{RESET}\n")
    
    while True:
        try:
            user_input = input_line(f"{BLUE}❯{RESET} ", history).strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{GRAY}Goodbye!{RESET}")
            break
        
        if not user_input:
            continue
        
        if user_input.startswith("/"):
            first_word = user_input.split()[0]
            if first_word.lower() in COMMANDS:
                parts = user_input.split()
                cmd = parts[0].lower()
                args = parts[1:]
                cont, messages, history = handle_command(cmd, args, settings, messages, history)
                if not cont:
                    break
                continue
        
        # Limit history size
        if len(history) >= MAX_HISTORY:
            history = history[-MAX_HISTORY//2:]
        history.append(user_input)
        
        msg = user_input
        if settings.get("experiments", {}).get("planning"):
            msg = f"{user_input}\n\n[If this is a multi-step task, create a TODO list first using the todo tool, then check off items as you complete them.]"
        
        messages.append({"role": "user", "content": msg})
        messages = agent_loop(user_input, messages, settings)

if __name__ == "__main__":
    main()
