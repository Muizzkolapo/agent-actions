  Your Current Setup:

  loop:
    param: stage
    range: [1, 3]

  - Same input data goes to all 3 iterations
  - Each iteration generates a different distractor (distractor_1, distractor_2, distractor_3)
  - No dependencies between iterations - they don't need to wait for each other
  - All 3 can run simultaneously

  Execution Pattern:

  Input Record → generate_distractors_1 (parallel) → distractor_1
              → generate_distractors_2 (parallel) → distractor_2
              → generate_distractors_3 (parallel) → distractor_3
                                                 ↓
                           reconstruct_options ← [all 3 distractors]

  Why It's Parallel:

  - Independent processing: Each iteration doesn't need results from others
  - Same source data: All read from the same input
  - Different outputs: Each produces a unique field
  - Barrier synchronization: reconstruct_options waits for ALL to complete

  This is a classic parallel map operation followed by a reduce/collect step.