#!/bin/bash
# ============================================================
#  Review Week  —  weekly to-do extractor for Cowork
#
#  Double-click  ............  auto-picks the LATEST WO-* folder you
#                              haven't reviewed yet (no output page yet)
#  bash "Review Week.command" "/path/to/WO-YYMMDD"   reviews that folder
#  bash "Review Week.command" --pick                 always show picker
#
#  It reads every transcript, email, and document in the
#  folder, bundles the text into _review_bundle.txt, and
#  prints a prompt to paste into Cowork to rebuild the
#  to-do page.
#
#  ("Reviewed" = a file named  Week To-Do - <FolderName>.html
#   already exists in this WEEK PREP folder.)
# ============================================================

set -euo pipefail

# --- locate this script's folder (the WEEK PREP folder) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- helper: native macOS folder picker ------------------------------
pick_folder(){
  osascript -e 'try
    set f to choose folder with prompt "Pick the week folder to review (e.g. WO-260608):" default location (POSIX file "'"$SCRIPT_DIR"'")
    POSIX path of f
  on error
    return ""
  end try' 2>/dev/null || true
}

# a folder counts as "already reviewed" once it has a todo-state.json
is_reviewed(){ [ -f "$1/todo-state.json" ]; }

# --- choose the folder to review -------------------------------------
ARG="${1:-}"
FOLDER=""

if [ "$ARG" = "--pick" ]; then
  FOLDER="$(pick_folder)"
elif [ -n "$ARG" ]; then
  FOLDER="$ARG"                       # explicit path passed in
else
  # No argument (e.g. double-clicked): auto-find the LATEST UNREVIEWED
  # WO-* folder. Folder names are dated (WO-YYMMDD), so reverse-sorting
  # by name puts the most recent first.
  AUTO=""
  while IFS= read -r d; do
    [ -d "$d" ] || continue
    if ! is_reviewed "$d"; then AUTO="$d"; break; fi
  done < <(find "$SCRIPT_DIR" -maxdepth 1 -type d -name 'WO-*' | sort -r)

  if [ -n "$AUTO" ]; then
    FOLDER="$AUTO"
    echo ">> Auto-selected latest unreviewed folder: $(basename "$FOLDER")"
  else
    # none unreviewed — let the user choose (or re-review one)
    NEWEST="$(find "$SCRIPT_DIR" -maxdepth 1 -type d -name 'WO-*' | sort -r | head -n1 || true)"
    if [ -n "$NEWEST" ]; then
      echo ">> No unreviewed WO-* folders found (latest is $(basename "$NEWEST"))."
      echo ">> Opening the folder picker so you can choose / re-review one..."
    else
      echo ">> No WO-* folders found here. Opening the folder picker..."
    fi
    FOLDER="$(pick_folder)"
  fi
fi

if [ -z "$FOLDER" ] || [ ! -d "$FOLDER" ]; then
  echo "No valid folder selected. Exiting."
  read -n1 -r -p "Press any key to close..." _ || true
  exit 1
fi

FOLDER="${FOLDER%/}"
BUNDLE="$FOLDER/_review_bundle.txt"

echo ""
echo "Reviewing:  $FOLDER"
echo "Extracting text from .txt, .eml, .docx and .pdf files..."
echo ""

# --- pick a python ---------------------------------------------------
PY="$(command -v python3 || command -v /usr/bin/python3 || true)"
if [ -z "$PY" ]; then
  echo "python3 not found. Please install it (xcode-select --install)."
  read -n1 -r -p "Press any key to close..." _ || true
  exit 1
fi

# --- extract -----------------------------------------------------------
"$PY" - "$FOLDER" "$BUNDLE" "$SCRIPT_DIR" <<'PYEOF'
import sys, os, glob, zipfile, re, shutil, subprocess, json
from email import policy
from email.parser import BytesParser

folder, out_path = sys.argv[1], sys.argv[2]
script_dir = sys.argv[3] if len(sys.argv) > 3 else folder

def read_txt(p):
    for enc in ("utf-8","latin-1"):
        try:
            return open(p, encoding=enc).read()
        except Exception:
            continue
    return ""

def read_eml(p):
    with open(p,"rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    head = "From: %s\nTo: %s\nDate: %s\nSubject: %s\n" % (
        msg.get("from",""), msg.get("to",""), msg.get("date",""), msg.get("subject",""))
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type()=="text/plain":
                try: body += part.get_content()
                except Exception: pass
        if not body:
            for part in msg.walk():
                if part.get_content_type()=="text/html":
                    try: body += re.sub("<[^<]+?>"," ", part.get_content())
                    except Exception: pass
    else:
        try: body = msg.get_content()
        except Exception: body = ""
    return head + "\n" + body

def read_docx(p):
    # stdlib only: unzip and strip tags from document.xml
    try:
        with zipfile.ZipFile(p) as z:
            xml = z.read("word/document.xml").decode("utf-8","ignore")
        xml = xml.replace("</w:p>", "\n")
        return re.sub("<[^>]+>", "", xml)
    except Exception as e:
        return "[could not read docx: %s]" % e

def read_pdf(p):
    # Prefer poppler's pdftotext if installed, else try python libs, else skip.
    if shutil.which("pdftotext"):
        try:
            return subprocess.check_output(["pdftotext","-q",p,"-"]).decode("utf-8","ignore")
        except Exception:
            pass
    for mod in ("pdfplumber","PyPDF2","pypdf"):
        try:
            if mod=="pdfplumber":
                import pdfplumber
                with pdfplumber.open(p) as pdf:
                    return "\n".join((pg.extract_text() or "") for pg in pdf.pages)
            else:
                m = __import__(mod)
                rdr = m.PdfReader(p)
                return "\n".join((pg.extract_text() or "") for pg in rdr.pages)
        except Exception:
            continue
    return "[PDF text not extracted — no pdftotext/pdfplumber available. Open the PDF directly if needed.]"

handlers = {".txt":read_txt, ".eml":read_eml, ".docx":read_docx, ".pdf":read_pdf}
chunks, counts = [], {}
for path in sorted(glob.glob(os.path.join(folder,"*"))):
    name = os.path.basename(path)
    if name.startswith("_") or name.startswith("."):
        continue
    ext = os.path.splitext(name)[1].lower()
    if ext not in handlers:
        continue
    try:
        text = handlers[ext](path)
    except Exception as e:
        text = "[error: %s]" % e
    chunks.append("\n\n===== %s (%s) =====\n%s" % (name, ext, text.strip()))
    counts[ext] = counts.get(ext,0)+1

# --- collect any exported feedback (items the user marked not relevant) ---
fb_lines, fb_count = [], 0
seen = set()
for base in (folder, script_dir):
    for fp in sorted(glob.glob(os.path.join(base, "todo-feedback-*.json"))):
        if fp in seen: continue
        seen.add(fp)
        try:
            data = json.load(open(fp, encoding="utf-8"))
            for d in data.get("dismissed", []):
                fb_lines.append("  - %s  (reason: %s)" % (d.get("item",""), d.get("reason","")))
                fb_count += 1
        except Exception as e:
            fb_lines.append("  [could not read %s: %s]" % (os.path.basename(fp), e))

with open(out_path,"w",encoding="utf-8") as f:
    f.write("WEEK REVIEW BUNDLE\nFolder: %s\n" % folder)
    f.write("Files: " + ", ".join("%d%s"%(v,k) for k,v in sorted(counts.items())) + "\n")
    if fb_lines:
        f.write("\nUSER FEEDBACK — items previously marked NOT RELEVANT.\n")
        f.write("Do NOT re-create these or close variants; learn from the reasons:\n")
        f.write("\n".join(fb_lines) + "\n")
    f.write("".join(chunks))

print("  Bundled %d files (%s)" % (sum(counts.values()),
      ", ".join("%d %s"%(v,k) for k,v in sorted(counts.items()))))
if fb_count:
    print("  Included %d feedback item(s) to avoid re-surfacing." % fb_count)
print("  Wrote: %s" % out_path)
PYEOF

echo ""
echo "============================================================"
echo "  NEXT STEP — hand it to Cowork"
echo "============================================================"
echo "  1) Open Cowork (Claude desktop) on the WEEK PREP folder."
echo "  2) Paste this prompt:"
echo ""
echo "     Review _review_bundle.txt in $(basename "$FOLDER") and"
echo "     create $(basename "$FOLDER")/todo-state.json (same schema as"
echo "     the last week). The folder name WO-YYMMDD is that work week's"
echo "     Monday — set \"label\" to \"Week of <Mon D>–<Fri D>\" (the week"
echo "     I'm prepping for, not the dates of the notes inside)."
echo "     Extract my action items, AND carry over any"
echo "     unfinished items from the previous week's todo-state.json"
echo "     (tag carriedFrom + carryAge; skip done / not-doing / removed)."
echo "     Tag each item's \"project\" using projects.json (match on the"
echo "     keywords); carry projects forward. Honour the USER FEEDBACK"
echo "     section — don't re-surface items I marked not relevant."
echo ""
echo "  Cowork writes todo-state.json into this folder; your Home.html"
echo "  app picks it up automatically as the new week."
echo "============================================================"
echo ""

# open the folder in Finder for convenience
open "$FOLDER" 2>/dev/null || true

read -n1 -r -p "Done. Press any key to close..." _ || true
