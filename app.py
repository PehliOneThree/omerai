import json
import os
import re
import subprocess
import sys
import tempfile

from flask import Flask, request, jsonify, send_from_directory

try:
    from rapidfuzz import process, fuzz
except ImportError:
    print("Run: pip install rapidfuzz")
    sys.exit()

try:
    from groq import Groq
except ImportError:
    print("Run: pip install groq")
    sys.exit()

# ─────────────────────────────────────────────
# PASTE YOUR GROQ KEY HERE:
GROQ_API_KEY = "paste-your-groq-key-here"
# ─────────────────────────────────────────────

CONFIDENCE      = 65
BRAIN_FILE      = "brain.json"
MAX_CODE_LINES  = 50
TIMEOUT_SECONDS = 5

BANNED = [
    "import os", "import sys", "import subprocess",
    "import shutil", "import socket",
    "__import__", "open(", "exec(", "eval(",
    "os.remove", "os.rmdir", "os.system",
    "shutil.rmtree", "shutdown", "reboot",
]

app   = Flask(__name__, static_folder="static")
brain = {}


def load_brain():
    global brain
    if os.path.exists(BRAIN_FILE):
        with open(BRAIN_FILE, "r", encoding="utf-8") as f:
            brain = json.load(f)


def save_brain():
    with open(BRAIN_FILE, "w", encoding="utf-8") as f:
        json.dump(brain, f, indent=4, ensure_ascii=False)


def find_answer(question):
    if not brain:
        return None
    result = process.extractOne(question, brain.keys(), scorer=fuzz.token_sort_ratio)
    if result is None:
        return None
    best, score, _ = result
    return brain[best] if score >= CONFIDENCE else None


def get_key():
    return os.environ.get("GROQ_API_KEY", GROQ_API_KEY)


def ask_groq(question):
    key = get_key()
    if key == "paste-your-new-groq-key-here":
        return None, "no_key"
    models = ["llama-3.3-70b-versatile", "llama3-70b-8192", "llama3-8b-8192", "mixtral-8x7b-32768"]
    client = Groq(api_key=key)
    for model in models:
        try:
            chat = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are OmerAI. Answer in 1-3 sentences. Plain text only."},
                    {"role": "user", "content": question}
                ],
                max_tokens=3000,
            )
            return chat.choices[0].message.content.strip(), None
        except Exception as e:
            err = str(e).lower()
            if "invalid api key" in err or "unauthorized" in err:
                return None, "bad_key"
            elif "model" in err or "not found" in err or "decommissioned" in err:
                continue
            else:
                return None, str(e)
    return None, "no_model"


def ask_groq_for_code(task):
    key = get_key()
    if key == "paste-your-new-groq-key-here":
        return None, "no_key"
    models = ["llama-3.3-70b-versatile", "llama3-70b-8192", "llama3-8b-8192"]
    client = Groq(api_key=key)
    for model in models:
        try:
            chat = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a Python code generator. Reply with ONLY raw Python code. No explanation, no markdown, no backticks. Use hardcoded values instead of input(). Always print output."},
                    {"role": "user", "content": "Write Python code for: " + task}
                ],
                max_tokens=800,
            )
            code = chat.choices[0].message.content.strip()
            if code.startswith("```"):
                lines = [l for l in code.split("\n") if not l.strip().startswith("```")]
                code = "\n".join(lines).strip()
            return code, None
        except Exception as e:
            err = str(e).lower()
            if "invalid api key" in err or "unauthorized" in err:
                return None, "bad_key"
            elif "model" in err or "not found" in err:
                continue
            else:
                return None, str(e)
    return None, "no_model"


def is_safe(code):
    for b in BANNED:
        if b.lower() in code.lower():
            return False, b
    return True, None


def run_python(code):
    safe, blocked = is_safe(code)
    if not safe:
        return None, "Blocked: '" + blocked + "' not allowed."
    if len(code.strip().splitlines()) > MAX_CODE_LINES:
        return None, "Code too long."
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(code)
        tmp_path = tmp.name
    try:
        result = subprocess.run([sys.executable, tmp_path], capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        out = result.stdout.strip()
        err = result.stderr.strip()
        if err:
            err = err.split("\n")[-1]
        return out or None, err or None
    except subprocess.TimeoutExpired:
        return None, "Code took too long."
    except Exception as e:
        return None, str(e)
    finally:
        os.unlink(tmp_path)


def is_code_request(text):
    t = text.lower()
    verbs = ["create", "make", "build", "write", "code", "generate", "develop"]
    nouns = ["calculator","game","program","script","app","tool","bot","timer","clock",
             "counter","quiz","password","generator","checker","converter","tracker",
             "function","code","python","table","pattern","sequence","fibonacci",
             "pyramid","star","temperature","currency","bmi","word","text","number"]
    return any(v in t for v in verbs) and any(n in t for n in nouns)


def try_auto_python(text):
    t = text.strip().lower()

    if any(k in t for k in ["today's date","what day is it","current date","what is today"]):
        return "from datetime import date\nprint(date.today().strftime('%A, %d %B %Y'))"

    if any(k in t for k in ["what time is it","current time"]):
        return "from datetime import datetime\nprint(datetime.now().strftime('%H:%M:%S'))"

    for trigger in ["what is ","calculate ","compute ","solve ","what's "]:
        s = t.replace(trigger,"",1).strip().rstrip("?").strip()
        chk = s.replace("**","").replace("//","")
        if re.match(r'^[\d\s\+\-\*\/\%\(\)\.\^]+$', chk) and any(c in s for c in "+-*/%^"):
            return "print(" + s.replace("^","**") + ")"

    m = re.search(r'is (\d+) (a )?prime', t)
    if m:
        n = m.group(1)
        return "n=" + n + "\nif n<2: print(str(n)+' is NOT prime')\nelse:\n p=all(n%i!=0 for i in range(2,int(n**0.5)+1))\n print(str(n)+(' IS prime' if p else ' is NOT prime'))"

    m = re.search(r'square root of (\d+\.?\d*)', t)
    if m:
        return "import math\nprint(math.sqrt(" + m.group(1) + "))"

    m = re.search(r'(-?\d+\.?\d*)\s*celsius\s*(to|in)\s*fahrenheit', t)
    if m:
        return "c=" + m.group(1) + "\nprint(str(c)+'C = '+str(round((c*9/5)+32,2))+'F')"

    m = re.search(r'(-?\d+\.?\d*)\s*fahrenheit\s*(to|in)\s*celsius', t)
    if m:
        return "f=" + m.group(1) + "\nprint(str(f)+'F = '+str(round((f-32)*5/9,2))+'C')"

    m = re.search(r'(-?\d+\.?\d*)\s*kg\s*(to|in)\s*lbs?', t)
    if m:
        return "kg=" + m.group(1) + "\nprint(str(kg)+' kg = '+str(round(kg*2.20462,3))+' lbs')"

    m = re.search(r'(-?\d+\.?\d*)\s*km\s*(to|in)\s*miles', t)
    if m:
        return "km=" + m.group(1) + "\nprint(str(km)+' km = '+str(round(km*0.621371,3))+' miles')"

    m = re.search(r'random number between (\d+) and (\d+)', t)
    if m:
        return "import random\nprint(random.randint(" + m.group(1) + "," + m.group(2) + "))"

    if "random number" in t:
        return "import random\nprint(random.randint(1,100))"

    return None


@app.route("/")
def index():
    load_brain()
    return send_from_directory("static", "index.html")


@app.route("/chat", methods=["POST"])
def chat_route():
    load_brain()
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"type": "error", "answer": "Invalid request."})

    raw = data.get("message", "").strip()
    if not raw:
        return jsonify({"type": "error", "answer": "Empty message."})

    low       = raw.lower().strip("?!.,")
    groq_ready = get_key() != "paste-your-new-groq-key-here"

    if is_code_request(raw) and groq_ready:
        code, err = ask_groq_for_code(raw)
        if code:
            out, run_err = run_python(code)
            return jsonify({"type": "code", "code": code, "output": out, "error": run_err})
        return jsonify({"type": "error", "answer": "Could not generate code: " + str(err)})

    code = try_auto_python(raw)
    if code:
        out, err = run_python(code)
        if out:
            return jsonify({"type": "python", "answer": out})
        if err:
            return jsonify({"type": "error", "answer": err})

    answer = find_answer(low)
    if answer:
        return jsonify({"type": "brain", "answer": answer})

    if groq_ready:
        answer, err = ask_groq(raw)
        if answer:
            brain[low] = answer
            save_brain()
            return jsonify({"type": "groq", "answer": answer})
        return jsonify({"type": "error", "answer": "AI error: " + str(err)})

    return jsonify({"type": "error", "answer": "Add your Groq API key to app.py!"})

@app.route("/brain")
def view_brain():
    load_brain()
    return jsonify(brain)

if __name__ == "__main__":
    load_brain()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
