def add_asterisk_to_correct_answer(data: dict) -> dict:
    """
    Adds asterisk as the very first character to correct answer options.
    Simple and direct - just prepends * to whatever is in the field.
    
    Args:
        data: Dictionary with 'answer_indices' and 'options'
    
    Returns:
        List containing the updated dictionary with asterisks added.
    """
    answer_indices = data.get("answer_indices", [])
    options = data.get("options", [])
    
    if not options or not answer_indices:
        print("Warning: Missing options or answer_indices")
        return [data]

    # Add asterisk to each correct answer option
    for index in answer_indices:
        if 0 <= index < len(options):
            # Simply prepend asterisk as the very first character
            if not options[index].startswith("*"):
                options[index] = "*" + options[index]
                letter = chr(ord('A') + index)
                print(f"Added asterisk to option {letter}")

    return [data]

# Test with your exact data
def test_asterisk():
    test_data = {
        "answer_indices": [0, 2, 3],
        "options": [
            '<html><body><div>Option A</div></body></html>',
            '<html><body><div>Option B</div></body></html>',
            '<html><body><div>Option C</div></body></html>',
            '<html><body><div>Option D</div></body></html>'
        ]
    }
    
    print("Before:")
    for i, opt in enumerate(test_data["options"]):
        print(f"{chr(ord('A')+i)}: {opt[:30]}...")
    
    result = add_asterisk_to_correct_answer(test_data)
    
    print("\nAfter:")
    for i, opt in enumerate(result[0]["options"]):
        letter = chr(ord('A')+i)
        has_asterisk = "✓" if opt.startswith("*") else "❌"
        print(f"{letter}: {has_asterisk} {opt[:30]}...")

if __name__ == "__main__":
    test_asterisk()