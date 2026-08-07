"""Add markdown preprocessing to markdown_to_docx.py to handle inline headings."""
import sys

filepath = "/home/youyeetoo/InNet_box/backend/app/services/markdown_to_docx.py"

with open(filepath, 'r') as f:
    content = f.read()

# Target: after the text normalization line, before "lines = text.split"
old_block = '''    text = (markdown or "").replace("\\r\\n", "\\n").replace("\\r", "\\n")
    lines = text.split("\\n")
    index = 0
    emitted_title = False'''

new_block = '''    text = (markdown or "").replace("\\r\\n", "\\n").replace("\\r", "\\n")
    # Normalize: ensure markdown headings start on their own line (fixes 35B output)
    text = re.sub(r"([^\\n])(#{1,3}\\s)", r"\\1\\n\\n\\2", text)
    # Strip leading natural-language intro before first # heading
    first_heading = re.search(r"^#{1,3}\\s", text, re.MULTILINE)
    if first_heading and first_heading.start() > 0:
        text = text[first_heading.start():]
    lines = text.split("\\n")
    index = 0
    emitted_title = False'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(filepath, 'w') as f:
        f.write(content)
    print("OK: markdown preprocessing added to markdown_to_docx.py")
else:
    print("ERROR: target block not found")
    sys.exit(1)
