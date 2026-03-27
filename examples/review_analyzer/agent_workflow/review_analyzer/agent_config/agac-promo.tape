# Agent Actions — Promo Video
# Run with: vhs agac-promo.tape  (from agent_config/)

Output agac-promo.mp4

Set Framerate 60
Set Width 2200
Set Height 800
Set FontSize 28
Set Padding 0
Set Theme "Catppuccin Mocha"

Set Margin 80
Set MarginFill "#674EFF"
Set WindowBar Colorful
Set WindowBarSize 40
Set BorderRadius 8

Set CursorBlink true

Require bat
Require agac

# Scene 1: Intro slides (4 × 2.5s = 10s)
Hide
Type "bash intro.sh" Enter
Show

Sleep 14s

# Scene 2: Scroll through the YAML
Hide
Type "clear" Enter
Show

Sleep 1s

Type 'bat --color=always --plain --paging=never review_analyzer.yml | while read line; do echo "$line"; sleep 0.03; done'
Enter
Sleep 9s

# Scene 3: Run the pipeline
Hide
Type "clear" Enter
Show

Sleep 500ms

Type "agac run -a review_analyzer"
Enter

Sleep 20s

Sleep 4s
