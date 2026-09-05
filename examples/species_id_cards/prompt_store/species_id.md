{prompt Summarize_Entry}
Summarise this field-guide entry, then judge how much usable identification
detail it carries.

**Entry**: {{ source.entry_text }}

**Guide**: {{ source.guide }}

`detail_level` is `high` when the entry names several marks a reader could use
in the field, `medium` when it names one or two, `low` when it is mostly range
or status.

```json
{
  "summary": "One sentence on what the entry covers",
  "detail_level": "high",
  "detail_reason": "Why that level"
}
```

{end_prompt}

{prompt Extract_Field_Marks}
Extract the field marks this entry describes. A field mark is something a reader
could actually see or hear.

**Entry**: {{ source.entry_text }}

Prefer marks that would separate the species from a look-alike over marks that
merely describe it.

```json
{
  "marks": [
    {"mark_text": "Pale straw legs", "mark_kind": "structure", "species": "Willow Warbler"}
  ],
  "pass_notes": "What this pass prioritised"
}
```

{end_prompt}

{prompt Canonicalize_Marks}
Three independent passes extracted marks from the same entry. Reconcile them.

**Pass 1**: {{ extract_field_marks_1.marks }}

**Pass 2**: {{ extract_field_marks_2.marks }}

**Pass 3**: {{ extract_field_marks_3.marks }}

Merge marks that say the same thing in different words, keeping the clearest
wording. Set `merged_count` to how many passes contributed each mark.

```json
{
  "canonical_marks": [
    {"mark_text": "Pale straw legs", "mark_kind": "structure", "species": "Willow Warbler", "merged_count": 3}
  ],
  "reconcile_notes": "What was merged and why"
}
```

{end_prompt}

{prompt Rank_Diagnostic_Value}
Judge whether this mark actually separates the species from its look-alikes.

**Mark**: {{ dedupe_across_guides.mark_text }}

**Kind**: {{ dedupe_across_guides.mark_kind }}

**Species**: {{ dedupe_across_guides.species }}

A mark shared with every similar species is not diagnostic however striking it
is.

```json
{
  "verdict": "keep",
  "diagnostic_score": 0.8,
  "reason": "Why"
}
```

{end_prompt}

{prompt Draft_Id_Note}
Write a short note telling a reader how to use this mark in the field, and quote
the sentence from the entry that supports it.

**Mark**: {{ select_approved_marks.mark_text }}

**Species**: {{ select_approved_marks.species }}

**Entry**: {{ source.entry_text }}

The quote must appear in the entry verbatim. Do not paraphrase it.

```json
{
  "note_text": "How to use the mark",
  "supporting_quote": "A sentence copied from the entry",
  "confidence": 0.9
}
```

{end_prompt}

{prompt Consolidate_Id_Note}
Two drafters wrote a note for the same mark. Reconcile them into one.

**Draft 1**: {{ draft_id_note_1.note_text }} — quoting: {{ draft_id_note_1.supporting_quote }}

**Draft 2**: {{ draft_id_note_2.note_text }} — quoting: {{ draft_id_note_2.supporting_quote }}

**Entry**: {{ source.entry_text }}

Choose the quote that best supports the agreed note, verbatim from the entry.

```json
{
  "note_text": "The agreed note",
  "supporting_quote": "A sentence copied from the entry",
  "drafts_agreed": true
}
```

{end_prompt}

{prompt Describe_Confusion_Risk}
Name the species this mark is most often confused with, and what separates them.

**Note**: {{ consolidate_id_note.note_text }}

**Quote**: {{ consolidate_id_note.supporting_quote }}

**Passage**: {{ locate_supporting_passage.passage }}

**Species**: {{ dedupe_across_guides.species }}

```json
{
  "confusable_with": "The look-alike",
  "why_confusable": "What they share",
  "separating_detail": "What tells them apart"
}
```

{end_prompt}

{prompt Auto_Review_Note}
Screen this note before a reviewer sees it.

**Mark**: {{ dedupe_across_guides.mark_text }}

**Note**: {{ consolidate_id_note.note_text }}

**Passage**: {{ locate_supporting_passage.passage }}

Score how well the passage supports the note. Set `in_hand_only` when the mark
could only be used on a bird in the hand — wing formula, skull ossification —
since a field-guide reader cannot apply it. Recommend `review` when either is a
problem, `pass` otherwise.

```json
{
  "grounding_score": 0.9,
  "in_hand_only": false,
  "review_recommendation": "pass",
  "review_reason": "Why"
}
```
{end_prompt}
