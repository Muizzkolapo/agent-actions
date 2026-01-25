import json
import uuid
import re
from collections import defaultdict
def process_code_segments(data):
    # Generate a common code_segment_id
    code_segment_id = str(uuid.uuid4())

    # List to hold individual JSON objects
    individual_segments = []

    # Iterate through each code segment, add code_segment_id, and append to the result list
    for segment in data.get("code_segments", []):
        segment["code_segment_id"] = code_segment_id
        individual_segments.append(segment)

    return json.dumps(individual_segments, indent=2)





def combine_blanks_one_per_occurrence_old(blocks):
    """
    Stitch blocks that share the same code_segment_id into a single quiz object.

    • Each blank *occurrence* gets a fresh placeholder (__BLANK_1__, __BLANK_2__, …)
      in reading order.
    • Returns learner-facing `blanked_code`, fully populated `completed_code`,
      a detailed `blanks` answer key (with explanations), **and** a bare
      `answers` list holding just the replacement words in order.

    Returns
    -------
    list[dict] – one dict per code_segment_id
    """
    grouped = defaultdict(list)
    for b in blocks:
        grouped[b["content"]["code_segment_id"]].append(b)

    out = []

    for seg_id, seg_blocks in grouped.items():
        seg_blocks.sort(key=lambda b: int(re.search(r"\d+", b["content"]["block_id"]).group()))

        parts, blanks, next_no = [], [], 1

        for blk in seg_blocks:
            frag = blk["content"]["blanked_code"]

            for blank in blk["content"]["blanks"]:
                new_ph   = f"__BLANK_{next_no}__"
                next_no += 1

                frag = frag.replace(blank["placeholder_id"], new_ph)

                blanks.append({
                    "placeholder_id": new_ph,
                    "original_text" : blank["original_text"],
                    "explanation"   : blk["content"].get(blank["placeholder_id"], "")
                })

            parts.append(frag)

        blanked_code = "\n\n".join(parts)

        completed_code = blanked_code
        for entry in blanks:
            completed_code = completed_code.replace(entry["placeholder_id"],
                                                    entry["original_text"])

        # ✨ NEW – bare answers list in placeholder order
        answers = [b["original_text"] for b in blanks]

        out.append({
            "code_segment_id": seg_id,
            "blanked_code"  : blanked_code,
            "completed_code": completed_code,
            "blanks"        : blanks,
            "answers"       : answers          # ← just the words, ordered
        })

    return  json.dumps(out, indent=2) 

import json
import re
from collections import defaultdict

def combine_blanks_one_per_occurrence(blocks):
    """
    Stitch blocks that share the same code_segment_id into a single quiz object.

    • Each blank *occurrence* gets a fresh placeholder (__BLANK_1__, __BLANK_2__, …)
      in reading order.
    • Returns learner-facing `blanked_code`, fully populated `completed_code`,
      aggregated `hints` (remapped to new placeholders), a detailed `blanks` answer key
      (with explanations), a bare `answers` list holding just the replacement words in order,
      and the shared `CodeExplanation` for that code_segment_id.
    """
    grouped = defaultdict(list)
    for b in blocks:
        grouped[b["content"]["code_segment_id"]].append(b)

    out = []

    for seg_id, seg_blocks in grouped.items():
        # Sort blocks by block_id numeric value
        seg_blocks.sort(key=lambda b: int(re.search(r"\d+", b["content"]["block_id"]).group()))

        parts, blanks, hints, next_no = [], [], [], 1

        # Get the shared explanation (assume all blocks in the group have the same one)
        explanation = seg_blocks[0]["content"].get("CodeExplanation", "")
        url = seg_blocks[0]["content"].get("url", "")
        id_ = seg_blocks[0]["content"].get("id", "")

        for blk in seg_blocks:
            frag = blk["content"]["blanked_code"]

            # Index this block's hints by original placeholder for quick lookup
            block_hints = {}
            for h in blk["content"].get("hints", []) or []:
                # Expecting shape: {"placeholder_id": "__BLANK_1__", "hint": "..."}
                pid = h.get("placeholder_id")
                if pid:
                    block_hints[pid] = h.get("hint", "")

            for blank in blk["content"]["blanks"]:
                old_ph = blank["placeholder_id"]
                new_ph = f"__BLANK_{next_no}__"
                next_no += 1

                # Swap placeholder in fragment
                frag = frag.replace(old_ph, new_ph)

                # Collect blanks answer key (keep explanation if present on block content under old placeholder id)
                blanks.append({
                    "placeholder_id": new_ph,
                    "original_text": blank["original_text"],
                    "explanation": blk["content"].get(old_ph, "")
                })

                # If there was a hint for the old placeholder, remap it to the new placeholder id
                if old_ph in block_hints:
                    hints.append({
                        "placeholder_id": new_ph,
                        "hint": block_hints[old_ph]
                    })

            parts.append(frag)

        blanked_code = "\n\n".join(parts)

        # Build completed_code by substituting back original texts
        completed_code = blanked_code
        for entry in blanks:
            completed_code = completed_code.replace(entry["placeholder_id"], entry["original_text"])

        answers = [b["original_text"] for b in blanks]

        out.append({
            "code_segment_id": seg_id,
            "blanked_code": blanked_code,
            "completed_code": completed_code,
            "hints": hints,                      # ✅ aggregated & remapped hints
            "blanks": blanks,
            "answers": answers,
            "CodeExplanation": explanation,      # ✅ included here per segment
            "url": url,                          # ✅ included here per segment
            "id": id_,                           # ✅ included here per segment
        })

    return json.dumps(out, indent=2)







#-------------------------------------------------------------------------------------------------------------------------------------------------
# MOCKUP HTML GENERATION FOR VS CODE
# This code generates HTML mockups of VS Code editor windows with syntax highlighting.
#-------------------------------------------------------------------------------------------------------------------------------------------------
import json
import re

def generate_vscode_mockup_html(filename, code, is_completed=True):
    """
    Generate VS Code mockup HTML for given code
    """
    
    # Determine file extension and language
    file_ext = filename.split('.')[-1] if '.' in filename else 'txt'
    language_map = {
        'py': 'Python',
        'yml': 'YAML',
        'yaml': 'YAML',
        'js': 'JavaScript',
        'html': 'HTML',
        'css': 'CSS',
        'json': 'JSON'
    }
    language = language_map.get(file_ext, 'Text')
    
    # Icon mapping
    icon_map = {
        'py': '<i class="fab fa-python" style="margin-right: 6px; color: #3776ab;"></i>',
        'yml': '<i class="fas fa-file-code" style="margin-right: 6px; color: #cb171e;"></i>',
        'yaml': '<i class="fas fa-file-code" style="margin-right: 6px; color: #cb171e;"></i>',
        'js': '<i class="fab fa-js-square" style="margin-right: 6px; color: #f7df1e;"></i>',
        'html': '<i class="fab fa-html5" style="margin-right: 6px; color: #e34f26;"></i>',
        'css': '<i class="fab fa-css3-alt" style="margin-right: 6px; color: #1572b6;"></i>',
        'json': '<i class="fas fa-file-code" style="margin-right: 6px; color: #25d366;"></i>'
    }
    icon = icon_map.get(file_ext, '<i class="fas fa-file" style="margin-right: 6px; color: #888;"></i>')
    
    def highlight_python_code(code):
        """Apply syntax highlighting for Python code"""
        if not code:
            return ''
        
        # Escape HTML characters first
        code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Handle blank placeholders first (before other highlighting)
        code = re.sub(r'(__BLANK_\d+__)', r'<span class="blank-placeholder">\1</span>', code)
        
        # Comments
        code = re.sub(r'(#.*$)', r'<span class="comment">\1</span>', code, flags=re.MULTILINE)
        
        # Strings (single and double quotes)
        code = re.sub(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", r'<span class="string">\1</span>', code)
        
        # Keywords
        keywords = ['from', 'import', 'def', 'class', 'if', 'else', 'elif', 'for', 'while', 'try', 'except', 'with', 'as', 'return', 'yield', 'break', 'continue', 'pass', 'and', 'or', 'not', 'in', 'is', 'lambda', 'async', 'await']
        for keyword in keywords:
            code = re.sub(rf'\b({keyword})\b', r'<span class="keyword">\1</span>', code)
        
        # Module names (after from/import, but not in blank placeholders)
        code = re.sub(r'(\bfrom\s+)([a-zA-Z_][a-zA-Z0-9_.]*?)(\s+import)', r'\1<span class="module">\2</span>\3', code)
        code = re.sub(r'(\bimport\s+)([a-zA-Z_][a-zA-Z0-9_.]*)', r'\1<span class="module">\2</span>', code)
        
        # Class names (PascalCase, not in blank placeholders)
        code = re.sub(r'(?<!blank-placeholder">)(?<!__)\b([A-Z][a-zA-Z0-9]*)\b(?!\s*:)(?!__)', r'<span class="class-name">\1</span>', code)
        
        # Variables and parameters
        code = re.sub(r'\b([a-z_][a-zA-Z0-9_]*)\s*=', r'<span class="parameter">\1</span> =', code)
        
        # Properties (after dot notation)
        code = re.sub(r'\.([a-zA-Z_][a-zA-Z0-9_]*)', r'.<span class="property">\1</span>', code)
        
        # Function calls
        code = re.sub(r'(?<!property">)([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', r'<span class="function">\1</span>(', code)
        
        return code
    
    def highlight_yaml_code(code):
        """Apply syntax highlighting for YAML code"""
        if not code:
            return ''
        
        # Escape HTML characters first
        code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Handle blank placeholders first
        code = re.sub(r'(__BLANK_\d+__)', r'<span class="blank-placeholder">\1</span>', code)
        
        # Comments
        code = re.sub(r'(#.*$)', r'<span class="comment">\1</span>', code, flags=re.MULTILINE)
        
        # Keys (before colon)
        code = re.sub(r'^(\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1<span class="yaml-key">\2</span>:', code, flags=re.MULTILINE)
        
        # Strings (quoted values)
        code = re.sub(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", r'<span class="string">\1</span>', code)
        
        # Values (after colon, not quoted)
        code = re.sub(r':\s*([a-zA-Z_][a-zA-Z0-9_:]*?)(?=\s|$|#)', r': <span class="yaml-value">\1</span>', code)
        
        return code
    
    # Apply appropriate syntax highlighting
    if file_ext == 'py':
        highlighted_code = highlight_python_code(code)
    elif file_ext in ['yml', 'yaml']:
        highlighted_code = highlight_yaml_code(code)
    else:
        highlighted_code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        highlighted_code = re.sub(r'(__BLANK_\d+__)', r'<span class="blank-placeholder">\1</span>', highlighted_code)
    
    # Determine tab status
    tab_status = "completed" if is_completed else "blank"
    title_suffix = f" - {language} ({'Completed' if is_completed else 'Fill in the blanks Quiz'})"
    
    html_template = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VS Code Mockup - {filename}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        body {{
            font-family: 'Inter', sans-serif;
            background-color: #1a1d21;
            color: #d4d4d4;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
            box-sizing: border-box;
        }}
        .vscode-container {{
            width: 100%;
            max-width: 1000px;
            background-color: #1f2428;
            border-radius: 10px;
            box-shadow: 0 15px 40px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.05);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }}
        .vscode-title-bar {{
            background-color: #32383e;
            padding: 10px 15px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #2a2f33;
        }}
        .vscode-title-bar .controls {{ display: flex; gap: 8px; }}
        .vscode-title-bar .control-dot {{ width: 12px; height: 12px; border-radius: 50%; }}
        .vscode-title-bar .dot-red {{ background-color: #fc605c; }}
        .vscode-title-bar .dot-yellow {{ background-color: #fdbc40; }}
        .vscode-title-bar .dot-green {{ background-color: #34c749; }}
        .vscode-title-bar .title-text {{ font-size: 13px; color: #c5c8c6; }}

        .vscode-tab-bar {{
            background-color: #252a2e;
            padding: 0;
            display: flex;
            border-bottom: 1px solid #1e2226;
        }}
        .vscode-tab {{
            background-color: #1f2428;
            color: #e0e0e0;
            padding: 12px 18px;
            font-size: 13px;
            border-right: 1px solid #1e2226;
            position: relative;
            cursor: default;
        }}
        .vscode-tab::after {{
            content: '';
            position: absolute;
            bottom: 0; left: 0; right: 0;
            height: 2px;
            background-color: #007fd4;
        }}

        .vscode-editor-area {{
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}

        .vscode-editor {{
            padding: 20px;
            font-family: 'SF Mono', 'Consolas', 'Liberation Mono', Menlo, Courier, monospace;
            font-size: 14px;
            line-height: 1.7;
            overflow: auto;
            flex-grow: 1;
            background-color: #1f2428;
            color: #d4d4d4;
        }}
        .vscode-editor pre {{ margin: 0; white-space: pre-wrap; word-wrap: break-word; }}
        .vscode-editor code {{ display: block; }}

        /* Syntax Highlighting */
        .keyword {{ color: #c586c0; font-weight: 500; }}
        .comment {{ color: #7f848e; font-style: italic; }}
        .string {{ color: #d19a66; }}
        .function {{ color: #dcdcaa; }}
        .class-name {{ color: #4ec9b0; }}
        .parameter {{ color: #9cdcfe; }}
        .operator {{ color: #d4d4d4; }}
        .punctuation {{ color: #d4d4d4; }}
        .number {{ color: #b5cea8; }}
        .method {{ color: #dcdcaa; }}
        .property {{ color: #9cdcfe; }}
        .module {{ color: #4ec9b0; }}
        .yaml-key {{ color: #9cdcfe; }}
        .yaml-value {{ color: #ce9178; }}

        .blank-placeholder {{
            background-color: #2a2f33;
            color: #a0a0a0;
            padding: 3px 8px;
            border-radius: 4px;
            border: 1px dashed #4a4f53;
            display: inline-block;
            min-width: 110px;
            text-align: center;
            font-style: italic;
            font-family: 'Inter', sans-serif;
        }}

        .vscode-status-bar {{
            background-color: #007acc;
            color: white;
            padding: 6px 15px;
            font-size: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .vscode-status-bar .status-item {{ margin-right: 15px; display: inline-flex; align-items: center; }}
        .vscode-status-bar .status-item i {{ margin-right: 5px; }}
    </style>
</head>
<body>
    <div class="vscode-container rounded-lg">
        <div class="vscode-title-bar">
            <div class="controls">
                <span class="control-dot dot-red"></span>
                <span class="control-dot dot-yellow"></span>
                <span class="control-dot dot-green"></span>
            </div>
            <div class="title-text">{filename}{title_suffix}</div>
            <div></div>
        </div>

        <div class="vscode-tab-bar">
            <div class="vscode-tab">
                {icon}{filename}
            </div>
        </div>

        <div class="vscode-editor-area">
            <div class="vscode-editor">
                <pre><code>{highlighted_code}</code></pre>
            </div>
        </div>

        <div class="vscode-status-bar">
            <div class="status-left">
                <span class="status-item"><i class="fas fa-code-branch"></i>main*</span>
                <span class="status-item"><i class="fas fa-exclamation-circle"></i>0 <i class="fas fa-exclamation-triangle"></i>0</span>
            </div>
            <div class="status-right">
                <span class="status-item">Ln 1, Col 1</span>
                <span class="status-item">Spaces: 4</span>
                <span class="status-item">UTF-8</span>
                <span class="status-item">{language}</span>
                <span class="status-item"><i class="fas fa-bell"></i></span>
            </div>
        </div>
    </div>
</body>
</html>'''
    
    return html_template

def append_vscode_mockup_fields(data):
    """
    Append VS Code mockup fields to the data structure
    """
    
    for item in data:
        content = item.get('content', {})
        filename = content.get('filename', 'untitled.txt')
        
        # Generate VS Code mockup for blanked code
        blanked_code = content.get('blanked_code', '')
        vscode_mockup_blank = generate_vscode_mockup_html(filename, blanked_code, is_completed=False)
        
        # Generate VS Code mockup for completed code
        completed_code = content.get('completed_code', '')
        vscode_mockup_completed = generate_vscode_mockup_html(filename, completed_code, is_completed=True)
        
        # Add new fields to content
        content['vscode_mockup'] = vscode_mockup_blank
        content['completed'] = vscode_mockup_completed
    
    return json.dumps(data, indent=2)


#-------------------------------------------------------------------------------------------------------------------------------------------------
# CODE ENDING
#-------------------------------------------------------------------------------------------------------------------------------------------------








import re
import json

import re
import textwrap

import re
import textwrap

def extract_code_blocks1(data):
    content = data["page_content"]

    # Match ```<optional language>\n<code>```
    pattern = r"```(?:[A-Za-z0-9_+\-\.#]+)?\s*\n(.*?)```"
    matches = re.findall(pattern, content, flags=re.DOTALL)

    code_blocks = []
    for code in matches:
        cleaned_code = textwrap.dedent(code).strip("\n\r ")
        code_blocks.append({"code_sample": cleaned_code})

    data["code_blocks"] = code_blocks
    return data

def extract_code_blocks(data):
    content = data["code_sample"]

    # Match ```<optional language>\n<code>```
    pattern = r"```(?:[A-Za-z0-9_+\-\.#]+)?\s*\n(.*?)```"
    matches = re.findall(pattern, content, flags=re.DOTALL)

    code_blocks = []
    for code in matches:
        cleaned_code = textwrap.dedent(code).strip("\n\r ")
        code_blocks.append({"code_sample": cleaned_code})

    data["code_blocks"] = code_blocks
    return data


import re
import json

def flatten_code_samples(record):
    """
    Turn a single input record with `code_blocks` into a list of records,
    one per code sample, duplicating the metadata fields.
    """
    META_FIELDS = ["id","topic","doc_name","bloom_details","url","title","page_content"]

    base = {k: record.get(k) for k in META_FIELDS}
    blocks = record.get("code_blocks") or []

    # normalize to list of strings
    def get_code(block):
        if isinstance(block, dict):
            return block.get("code_sample", "")
        return str(block) if block is not None else ""

    rows = []
    for idx, block in enumerate(blocks, start=1):
        code = (get_code(block) or "").strip()
        row = dict(base)
        row["code_sample"] = code
        row["code_index"] = idx

        # carry through detected language if available
        if isinstance(block, dict) and "code_language" in block and block["code_language"]:
            row["code_language"] = block["code_language"]

        rows.append(row)

    return rows






def should_keep(snippet: dict) -> bool:
    """
    Returns True if the snippet's 'keep' field is True, otherwise False.
    """
    return bool(snippet.get("keep", True))


def filter_keep_records(data):
    """
    Removes any record from the input list where content['keep'] is False.
    
    Args:
        data (list): List of dictionaries containing a 'content' key.
        
    Returns:
        list: Filtered list containing only records with keep=True.
    """
    return [record for record in data if record.get("content", {}).get("keep", False) is True]








def append_code_segments(data):
    """
    Takes a dict with 'code_sample' and appends a 'code_segments'
    field containing a single block with that code.
    """
    code_sample = data.get("code_sample", "").strip()
    data["code_segments"] = [
        {
            "block_id": "block_1",
            "code_text": code_sample
        }
    ]
    return data









#----------------------------------------------------filter_objects_with_code_blocks

def filter_objects_with_code_blocks(objects_list):
    """
    Filter objects to return only those that have non-empty code_blocks.
    
    Args:
        objects_list (list): List of objects with 'content' containing 'code_blocks'
        
    Returns:
        list: Filtered list containing only objects with non-empty code_blocks
    """
    filtered_objects = []
    
    for obj in objects_list:
        # Check if the object has the expected structure
        if (isinstance(obj, dict) and 
            'content' in obj and 
            isinstance(obj['content'], dict) and 
            'code_blocks' in obj['content']):
            
            code_blocks = obj['content']['code_blocks']
            
            # Keep objects that have non-empty code_blocks
            if code_blocks and len(code_blocks) > 0:
                filtered_objects.append(obj)
    
    return filtered_objects


def filter_objects_without_code_blocks(objects_list):
    """
    Alternative function: Filter objects to return only those WITHOUT code blocks
    (in case you meant the opposite - objects with empty code_blocks)
    
    Args:
        objects_list (list): List of objects with 'content' containing 'code_blocks'
        
    Returns:
        list: Filtered list containing only objects with empty code_blocks
    """
    filtered_objects = []
    
    for obj in objects_list:
        # Check if the object has the expected structure
        if (isinstance(obj, dict) and 
            'content' in obj and 
            isinstance(obj['content'], dict) and 
            'code_blocks' in obj['content']):
            
            code_blocks = obj['content']['code_blocks']
            
            # Keep objects that have empty code_blocks
            if not code_blocks or len(code_blocks) == 0:
                filtered_objects.append(obj)
    
    return filtered_objects


# -----------------------------------------------------------filter_objects_with_code_blocks