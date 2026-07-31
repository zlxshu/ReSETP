"""Read-only Zotero lookup: map item keys -> stored PDF paths, extract page text.

Usage:
  python zot_lookup.py find <keyword>          # search titles
  python zot_lookup.py pdf <itemKey>           # print stored pdf path(s)
  python zot_lookup.py pages <itemKey> a b     # dump text of pdf pages [a,b]
"""
import os, sqlite3, subprocess, sys

DB = os.environ.get("ZOT_DB", os.path.expanduser("~/Zotero/zotero.sqlite"))
STORAGE = os.path.expanduser("~/Zotero/storage")


def conn():
    return sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)


def title_of(c, item_id):
    r = c.execute(
        "SELECT iv.value FROM itemData id JOIN itemDataValues iv ON iv.valueID=id.valueID "
        "JOIN fields f ON f.fieldID=id.fieldID WHERE id.itemID=? AND f.fieldName='title'",
        (item_id,)).fetchone()
    return r[0] if r else ""


def find(kw):
    c = conn()
    for item_id, key in c.execute("SELECT itemID, key FROM items"):
        t = title_of(c, item_id)
        if kw.lower() in (t or "").lower():
            print(key, "|", t)


def pdfs(key):
    c = conn()
    row = c.execute("SELECT itemID FROM items WHERE key=?", (key,)).fetchone()
    if not row:
        return []
    out = []
    q = ("SELECT a.key, ia.path FROM itemAttachments ia JOIN items a ON a.itemID=ia.itemID "
         "WHERE ia.parentItemID=? AND ia.contentType='application/pdf'")
    for att_key, path in c.execute(q, (row[0],)):
        if path and path.startswith("storage:"):
            out.append(os.path.join(STORAGE, att_key, path[len("storage:"):]))
    # the key itself may be a standalone attachment
    r2 = c.execute("SELECT path FROM itemAttachments WHERE itemID=? AND contentType='application/pdf'",
                   (row[0],)).fetchone()
    if r2 and r2[0] and r2[0].startswith("storage:"):
        out.append(os.path.join(STORAGE, key, r2[0][len("storage:"):]))
    return out


def pages(key, a, b):
    for p in pdfs(key):
        if not os.path.exists(p):
            print("MISSING", p)
            continue
        print("===", p)
        subprocess.run(["pdftotext", "-f", str(a), "-l", str(b), "-layout", p, "-"])
        break


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "find":
        find(sys.argv[2])
    elif cmd == "pdf":
        for p in pdfs(sys.argv[2]):
            print(("OK  " if os.path.exists(p) else "MISS"), p)
    elif cmd == "pages":
        pages(sys.argv[2], sys.argv[3], sys.argv[4])
